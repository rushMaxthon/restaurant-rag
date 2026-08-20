"""Period comparison, contribution attribution, and anomaly detection.

Pure Python over metric result sets — nothing here touches the database, so all
of it is unit-testable without Postgres.

The central idea is contribution attribution: a headline delta ("revenue is down
12%") is only actionable once it is decomposed into which children moved it and
by how much. For every dimension the layer reports each child's signed change
and its share of the parent change, so a narrator can say "Pizza accounts for
62% of the drop" from a computed number rather than an impression.

Contribution shares are deliberately not clamped to 0-100%. When some children
grow while others shrink, a decliner's share of a smaller net change legitimately
exceeds 100%, and hiding that would misrepresent what happened.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Iterable, Sequence, TypeVar

from app.config import get_settings
from app.services.insights.metrics import DailyPoint

settings = get_settings()

T = TypeVar("T")

# Money and counts below this are treated as zero when deciding direction, so
# floating point residue never renders as a "change".
EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class MetricDelta:
    """A single metric compared across two windows."""

    metric: str
    current: float
    previous: float
    absolute_change: float
    percent_change: float | None
    direction: str
    sufficient_data: bool
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Contribution:
    key: str
    label: str
    current: float
    previous: float
    absolute_change: float
    percent_change: float | None
    contribution_share: float | None
    direction: str
    current_orders: int = 0
    previous_orders: int = 0
    current_quantity: int = 0
    previous_quantity: int = 0


@dataclass(frozen=True, slots=True)
class ContributionBreakdown:
    dimension: str
    # Which revenue basis the parent change is measured on. Item and category
    # breakdowns sum to the item-revenue delta; order-partitioned dimensions sum
    # to the gross-revenue delta. Mixing the two produces shares that do not add
    # up, so the basis travels with the data.
    basis: str
    parent_change: float
    contributions: list[Contribution] = field(default_factory=list)
    sufficient_data: bool = True
    note: str | None = None
    # Movement that is real but not shown: children dropped for low volume, and
    # children beyond the display limit. Without these, the listed percentages
    # cannot be reconciled against the parent change and an owner is left doing
    # arithmetic that will not add up.
    excluded_change: float = 0.0
    excluded_children: int = 0

    @property
    def top_decliners(self) -> list[Contribution]:
        return [row for row in self.contributions if row.absolute_change < -EPSILON]

    @property
    def top_growers(self) -> list[Contribution]:
        return [row for row in self.contributions if row.absolute_change > EPSILON]


@dataclass(frozen=True, slots=True)
class AnomalyPoint:
    day: date
    metric: str
    value: float
    baseline_median: float
    robust_z: float
    direction: str
    severity: str


@dataclass(frozen=True, slots=True)
class AnomalyReport:
    evaluated: bool
    points: list[AnomalyPoint] = field(default_factory=list)
    baseline_days: int = 0
    baseline_median_orders: float = 0.0
    note: str | None = None


def direction_of(change: float) -> str:
    if change > EPSILON:
        return "up"
    if change < -EPSILON:
        return "down"
    return "flat"


def percent_change_of(current: float, previous: float) -> float | None:
    """Percent change, or None when there is no baseline to divide by.

    Returning None rather than 0 or infinity keeps "grew from nothing" distinct
    from "did not change", which are very different findings for an owner.
    """

    if abs(previous) < EPSILON:
        return None
    return ((current - previous) / abs(previous)) * 100.0


def build_delta(
    metric: str,
    current: float,
    previous: float,
    *,
    sufficient_data: bool = True,
    note: str | None = None,
) -> MetricDelta:
    change = current - previous
    percent = percent_change_of(current, previous)
    resolved_note = note
    if resolved_note is None and percent is None and abs(current) > EPSILON:
        resolved_note = "No activity in the previous period, so no percentage baseline exists."
    return MetricDelta(
        metric=metric,
        current=current,
        previous=previous,
        absolute_change=change,
        percent_change=percent,
        direction=direction_of(change),
        sufficient_data=sufficient_data,
        note=resolved_note,
    )


def has_sufficient_volume(current_orders: int, previous_orders: int) -> bool:
    """Whether a period comparison carries enough volume to be worth reporting.

    A restaurant doing four orders a week can swing 50% on one cancelled party
    booking. Below the configured floor the layer reports the raw numbers but
    marks the comparison as insufficient rather than handing over a percentage
    someone might act on.
    """

    threshold = settings.insights_min_orders_for_delta
    return max(current_orders, previous_orders) >= threshold


def build_contributions(
    dimension: str,
    *,
    basis: str,
    current_rows: Iterable[T],
    previous_rows: Iterable[T],
    key_fn: Callable[[T], str],
    label_fn: Callable[[T], str],
    value_fn: Callable[[T], float],
    orders_fn: Callable[[T], int] | None = None,
    quantity_fn: Callable[[T], int] | None = None,
    parent_change: float | None = None,
    limit: int | None = None,
    sufficient_data: bool = True,
    note: str | None = None,
) -> ContributionBreakdown:
    """Rank a dimension's children by their signed contribution to the parent change."""

    current_map = {key_fn(row): row for row in current_rows}
    previous_map = {key_fn(row): row for row in previous_rows}

    resolved_parent_change = parent_change
    if resolved_parent_change is None:
        resolved_parent_change = sum(value_fn(row) for row in current_map.values()) - sum(
            value_fn(row) for row in previous_map.values()
        )

    min_orders = settings.insights_min_orders_for_contribution
    contributions: list[Contribution] = []
    kept_change = 0.0
    dropped_change = 0.0
    dropped_children = 0
    for key in current_map.keys() | previous_map.keys():
        current_row = current_map.get(key)
        previous_row = previous_map.get(key)
        current_value = value_fn(current_row) if current_row is not None else 0.0
        previous_value = value_fn(previous_row) if previous_row is not None else 0.0
        change = current_value - previous_value

        current_orders = (
            orders_fn(current_row) if orders_fn is not None and current_row is not None else 0
        )
        previous_orders = (
            orders_fn(previous_row) if orders_fn is not None and previous_row is not None else 0
        )
        # Drop children too small to matter in either window, so a single
        # one-off order does not outrank a genuine category-wide movement.
        if orders_fn is not None and max(current_orders, previous_orders) < min_orders:
            dropped_change += change
            dropped_children += 1
            continue

        share: float | None = None
        if abs(resolved_parent_change) > EPSILON:
            share = (change / resolved_parent_change) * 100.0

        kept_change += change
        contributions.append(
            Contribution(
                key=key,
                label=label_fn(current_row if current_row is not None else previous_row),
                current=current_value,
                previous=previous_value,
                absolute_change=change,
                percent_change=percent_change_of(current_value, previous_value),
                contribution_share=share,
                direction=direction_of(change),
                current_orders=current_orders,
                previous_orders=previous_orders,
                current_quantity=(
                    quantity_fn(current_row)
                    if quantity_fn is not None and current_row is not None
                    else 0
                ),
                previous_quantity=(
                    quantity_fn(previous_row)
                    if quantity_fn is not None and previous_row is not None
                    else 0
                ),
            )
        )

    contributions.sort(key=lambda row: (-abs(row.absolute_change), row.label.lower()))
    if limit is not None and len(contributions) > limit:
        for row in contributions[limit:]:
            dropped_change += row.absolute_change
            dropped_children += 1
        contributions = contributions[:limit]

    resolved_note = note
    if dropped_children and abs(dropped_change) > EPSILON:
        excluded = (
            f"{dropped_children} smaller contributor"
            f"{'s' if dropped_children != 1 else ''} account for the remaining "
            f"{dropped_change:+.2f} and are not listed."
        )
        resolved_note = f"{note} {excluded}".strip() if note else excluded

    return ContributionBreakdown(
        dimension=dimension,
        basis=basis,
        parent_change=resolved_parent_change,
        contributions=contributions,
        sufficient_data=sufficient_data,
        note=resolved_note,
        excluded_change=round(dropped_change, 2),
        excluded_children=dropped_children,
    )


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _median_absolute_deviation(values: Sequence[float], median_value: float) -> float:
    if not values:
        return 0.0
    return _median([abs(value - median_value) for value in values])


def _stdev(values: Sequence[float], mean_value: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _robust_z(value: float, baseline: Sequence[float]) -> tuple[float, float]:
    """Robust z-score of `value` against `baseline`, plus the baseline median.

    Median/MAD rather than mean/stdev because a single festival day would
    otherwise inflate the standard deviation enough to mask a real slump for
    the rest of the month. Falls back to mean/stdev only when the MAD is zero,
    which happens on very flat series.
    """

    median_value = _median(baseline)
    mad = _median_absolute_deviation(baseline, median_value)
    if mad > EPSILON:
        # 0.6745 rescales MAD to be consistent with a normal distribution's sigma.
        return 0.6745 * (value - median_value) / mad, median_value

    mean_value = sum(baseline) / len(baseline) if baseline else 0.0
    stdev = _stdev(baseline, mean_value)
    if stdev > EPSILON:
        return (value - mean_value) / stdev, median_value
    return 0.0, median_value


def _severity_for(abs_z: float, threshold: float) -> str:
    if abs_z >= threshold * 2:
        return "high"
    if abs_z >= threshold * 1.5:
        return "medium"
    return "low"


def fill_daily_series(
    points: Sequence[DailyPoint],
    start_date: date,
    end_date: date,
) -> list[DailyPoint]:
    """Densify a daily series so days with no orders read as zero, not as gaps.

    A closed Monday must count as a zero in the baseline; skipping it would make
    the restaurant look busier on average than it is.
    """

    by_day = {point.day: point for point in points}
    filled: list[DailyPoint] = []
    cursor = start_date
    while cursor <= end_date:
        existing = by_day.get(cursor)
        filled.append(existing or DailyPoint(day=cursor, orders=0, revenue=0.0))
        cursor = cursor + timedelta(days=1)
    return filled


def detect_anomalies(
    series: Sequence[DailyPoint],
    *,
    evaluation_start: date,
    metric: str = "revenue",
    z_threshold: float | None = None,
    min_daily_orders: int | None = None,
    min_baseline_days: int | None = None,
) -> AnomalyReport:
    """Flag days in the evaluation window that deviate from the trailing baseline.

    `series` must be dense and cover both the baseline (before
    `evaluation_start`) and the evaluation window.
    """

    threshold = z_threshold if z_threshold is not None else settings.insights_anomaly_z_threshold
    min_orders = (
        min_daily_orders
        if min_daily_orders is not None
        else settings.insights_min_daily_orders_for_anomaly
    )
    min_days = (
        min_baseline_days
        if min_baseline_days is not None
        else settings.insights_anomaly_min_baseline_days
    )

    baseline_points = [point for point in series if point.day < evaluation_start]
    evaluation_points = [point for point in series if point.day >= evaluation_start]

    if len(baseline_points) < min_days:
        return AnomalyReport(
            evaluated=False,
            baseline_days=len(baseline_points),
            note=(
                f"Needs at least {min_days} days of history to detect anomalies; "
                f"only {len(baseline_points)} available."
            ),
        )

    baseline_orders = [float(point.orders) for point in baseline_points]
    median_orders = _median(baseline_orders)
    if median_orders < min_orders:
        return AnomalyReport(
            evaluated=False,
            baseline_days=len(baseline_points),
            baseline_median_orders=median_orders,
            note=(
                "Daily order volume is too low for anomaly detection "
                f"(median {median_orders:.1f}/day, needs {min_orders})."
            ),
        )

    value_of: Callable[[DailyPoint], float] = (
        (lambda point: point.revenue) if metric == "revenue" else (lambda point: float(point.orders))
    )
    baseline_values = [value_of(point) for point in baseline_points]

    points: list[AnomalyPoint] = []
    for point in evaluation_points:
        value = value_of(point)
        robust_z, baseline_median = _robust_z(value, baseline_values)
        if abs(robust_z) < threshold:
            continue
        points.append(
            AnomalyPoint(
                day=point.day,
                metric=metric,
                value=value,
                baseline_median=baseline_median,
                robust_z=robust_z,
                direction="up" if robust_z > 0 else "down",
                severity=_severity_for(abs(robust_z), threshold),
            )
        )

    points.sort(key=lambda row: (-abs(row.robust_z), row.day))
    return AnomalyReport(
        evaluated=True,
        points=points,
        baseline_days=len(baseline_points),
        baseline_median_orders=median_orders,
    )


__all__ = [
    "AnomalyPoint",
    "AnomalyReport",
    "Contribution",
    "ContributionBreakdown",
    "EPSILON",
    "MetricDelta",
    "build_contributions",
    "build_delta",
    "detect_anomalies",
    "direction_of",
    "fill_daily_series",
    "has_sufficient_volume",
    "percent_change_of",
]
