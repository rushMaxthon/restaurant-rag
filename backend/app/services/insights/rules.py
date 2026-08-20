"""Deterministic rules that turn a diagnostics snapshot into ranked insights.

No LLM. Each rule states a finding in a fixed template and attaches the exact
numbers behind it, so the feature is fully usable with narration switched off —
and so narration has something to be checked against when it is switched on.

Two guards apply throughout:

* Nothing fires unless the snapshot reports sufficient volume. A restaurant
  doing a handful of orders a week would otherwise generate a headline every
  night from ordinary noise.
* A movement must clear both a percentage and an absolute floor, so a large
  swing on a tiny base does not outrank a real one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from app.config import get_settings
from app.models.enums import OwnerInsightSeverity, OwnerInsightType
from app.schemas.insights import (
    ContributionBreakdownResponse,
    ContributionResponse,
    DiagnosticsSnapshotResponse,
    MetricDeltaResponse,
)

settings = get_settings()

# Lowest to highest, so a cap can be applied with `min`.
SEVERITY_ORDER = {
    OwnerInsightSeverity.INFO: 0,
    OwnerInsightSeverity.LOW: 1,
    OwnerInsightSeverity.MEDIUM: 2,
    OwnerInsightSeverity.HIGH: 3,
}

CURRENCY_SYMBOLS = {"inr": "₹", "usd": "$", "eur": "€", "gbp": "£"}


@dataclass(slots=True)
class CandidateInsight:
    insight_type: OwnerInsightType
    severity: OwnerInsightSeverity
    score: Decimal
    title: str
    body: str
    dedupe_key: str
    dimension: str | None = None
    subject: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    # Filled in later by the root-cause layer, which needs database access the
    # rules deliberately do not have. None is the common, honest case.
    root_cause: str | None = None


def money(value: float) -> str:
    symbol = CURRENCY_SYMBOLS.get(settings.payment_currency.lower())
    rounded = round(abs(value))
    formatted = f"{rounded:,}"
    if symbol is None:
        return f"{settings.payment_currency.upper()} {formatted}"
    return f"{symbol}{formatted}"


def percent(value: float | None) -> str:
    """Magnitude only. Use where the direction is already carried by wording."""

    if value is None:
        return "n/a"
    return f"{abs(value):.1f}%"


def percent_is_misleading(previous: float | None, percent_value: float | None) -> bool:
    """Whether a percentage change would mislead more than it informs.

    True when there was effectively nothing to grow from, or when the growth is
    so large that the figure describes the quiet period rather than the busy
    one. Callers quote the money instead, which is the part an owner can act on.
    """

    if percent_value is None:
        return False
    if previous is not None and abs(previous) < 1e-9:
        return True
    return abs(percent_value) >= settings.insights_misleading_percent_change


def share_phrase(share: float | None) -> str:
    """A contribution share in words an owner can read.

    Signed shares are legitimate arithmetic and can exceed 100% — one line item
    falling further than the total, offset by others rising. "+249.5% of the
    overall change" is exactly right and completely unreadable, so the size is
    described instead of printed.
    """

    if share is None:
        return ""
    # Direction first. A negative share means this line moved *against* the
    # overall change, and describing its size without saying so reads as if it
    # had driven the very movement it worked against.
    if share < 0:
        return "moving against the overall change"

    magnitude = abs(share)
    if magnitude >= 100.0:
        return "which accounts for the whole of the change"
    if magnitude >= 50.0:
        return "which accounts for most of the change"
    if magnitude >= 20.0:
        return "a large part of the change"
    return "a small part of the change"


def change_phrase(previous: float | None, change: float, percent_value: float | None) -> str:
    """"₹1,260 (48.0%)" — or just the money where the percentage would mislead."""

    if percent_is_misleading(previous, percent_value):
        return money(change)
    return f"{money(change)} ({percent(percent_value)})"


def movement_label(previous: float | None, percent_value: float | None, change: float) -> str:
    """The size of a movement, for a title. Money when a percentage would lie."""

    if percent_is_misleading(previous, percent_value):
        return money(change)
    return percent(percent_value)


def plain_percent(value: float | None) -> str:
    """A rate as a person writes it: "10%", not "10.0%".

    `percent` keeps a decimal because it describes measured change, where the
    tenth carries information. A discount is a round number somebody chose, and
    the trailing zero only makes it read like machine output.
    """

    if value is None:
        return "n/a"
    if float(value).is_integer():
        return f"{int(value)}%"
    return f"{value:.1f}%"


def signed_percent(value: float | None) -> str:
    """Percentage with its sign kept.

    Contribution shares must never lose their direction: an item that moved
    against the overall change would otherwise read as if it had driven it.
    """

    if value is None:
        return "n/a"
    return f"{value:+.1f}%"


def is_material_change(
    absolute_change: float | None,
    percent_change: float | None,
) -> bool:
    """One definition of "big enough to mention", used everywhere.

    Both gates must clear: a large percentage on a tiny base is not a headline,
    and a tiny percentage on a large base is normal trading. The briefing
    narrative uses this too, so it cannot announce a movement the rules had
    already judged immaterial.
    """

    if absolute_change is None or percent_change is None:
        return False
    return (
        abs(percent_change) >= settings.insight_revenue_change_percent
        and abs(absolute_change) >= settings.insight_revenue_change_minimum
    )


def _period_revenue(snapshot: DiagnosticsSnapshotResponse) -> float | None:
    delta = _delta(snapshot, "gross_revenue")
    if delta is None:
        return None
    return max(abs(delta.current), abs(delta.previous)) or None


def _severity_floors(period_revenue: float | None) -> tuple[float, float]:
    """The money a movement must involve to be MEDIUM, then HIGH.

    Two floors, and the lower of each pair wins: a flat rupee amount, and a
    share of what this restaurant actually takes. The flat floor alone made
    severity meaningless for anyone small — a restaurant turning over ₹2,700 a
    quarter could never clear ₹2,000, so every finding it ever produced was LOW
    and the column stopped carrying information.
    """

    medium = float(settings.insight_severity_medium_floor)
    high = float(settings.insight_severity_high_floor)
    if period_revenue:
        medium = min(medium, period_revenue * settings.insight_severity_medium_revenue_share)
        high = min(high, period_revenue * settings.insight_severity_high_revenue_share)
    return medium, high


def _severity_for(
    magnitude: float,
    threshold: float,
    *,
    money_amount: float | None = None,
    period_revenue: float | None = None,
) -> OwnerInsightSeverity:
    """How loud a finding should be.

    The share of a movement sets the ceiling, but the money involved sets the
    floor. A dish can be 90% of a change and still be trivial if the change was
    a few hundred rupees, and marking that HIGH is how a feed becomes noise.

    The floor is relative to the restaurant's own trade — see `_severity_floors`.
    """

    if threshold <= 0:
        severity = OwnerInsightSeverity.LOW
    else:
        ratio = magnitude / threshold
        if ratio >= 3:
            severity = OwnerInsightSeverity.HIGH
        elif ratio >= 2:
            severity = OwnerInsightSeverity.MEDIUM
        else:
            severity = OwnerInsightSeverity.LOW

    if money_amount is None:
        return severity

    money = abs(money_amount)
    medium_floor, high_floor = _severity_floors(period_revenue)
    if money < medium_floor:
        return min(severity, OwnerInsightSeverity.LOW, key=SEVERITY_ORDER.get)
    if money < high_floor:
        return min(severity, OwnerInsightSeverity.MEDIUM, key=SEVERITY_ORDER.get)
    return severity


def _normalize_subject(value: str) -> str:
    return "-".join(value.strip().lower().split())


def _delta(snapshot: DiagnosticsSnapshotResponse, metric: str) -> MetricDeltaResponse | None:
    for row in snapshot.headline:
        if row.metric == metric:
            return row
    return None


def _breakdown(
    snapshot: DiagnosticsSnapshotResponse, dimension: str
) -> ContributionBreakdownResponse | None:
    for row in snapshot.breakdowns:
        if row.dimension == dimension:
            return row
    return None


def _decliners(breakdown: ContributionBreakdownResponse | None) -> list[ContributionResponse]:
    if breakdown is None:
        return []
    rows = [row for row in breakdown.contributions if row.absolute_change < 0]
    rows.sort(key=lambda row: row.absolute_change)
    return rows


def _growers(breakdown: ContributionBreakdownResponse | None) -> list[ContributionResponse]:
    if breakdown is None:
        return []
    rows = [row for row in breakdown.contributions if row.absolute_change > 0]
    rows.sort(key=lambda row: -row.absolute_change)
    return rows


def _is_material(row: ContributionResponse, share_threshold: float) -> bool:
    """Whether a child's movement is worth raising on its own.

    Either it explains a meaningful share of the overall change, or it moved
    enough money to matter regardless — the second test is what catches a dish
    collapsing while another masks it in the total.
    """

    share = abs(row.contribution_share) if row.contribution_share is not None else 0.0
    return (
        share >= share_threshold
        or abs(row.absolute_change) >= settings.insight_revenue_change_minimum
    )


def _contribution_facts(row: ContributionResponse) -> dict[str, Any]:
    return {
        "current": round(row.current, 2),
        "previous": round(row.previous, 2),
        "absolute_change": round(row.absolute_change, 2),
        "percent_change": round(row.percent_change, 1) if row.percent_change is not None else None,
        "contribution_share": (
            round(row.contribution_share, 1) if row.contribution_share is not None else None
        ),
        "current_orders": row.current_orders,
        "previous_orders": row.previous_orders,
    }


# --- individual rules ------------------------------------------------------


def _revenue_rules(snapshot: DiagnosticsSnapshotResponse) -> list[CandidateInsight]:
    delta = _delta(snapshot, "gross_revenue")
    if delta is None or delta.percent_change is None:
        return []
    if not is_material_change(delta.absolute_change, delta.percent_change):
        return []

    facts = {
        "current_revenue": round(delta.current, 2),
        "previous_revenue": round(delta.previous, 2),
        "absolute_change": round(delta.absolute_change, 2),
        "percent_change": round(delta.percent_change, 1),
    }

    if delta.direction == "down":
        severity = _severity_for(
            abs(delta.percent_change),
            settings.insight_revenue_change_percent,
            money_amount=delta.absolute_change,
            period_revenue=_period_revenue(snapshot),
        )
        return [
            CandidateInsight(
                insight_type=OwnerInsightType.REVENUE_DROP,
                severity=severity,
                score=Decimal(str(abs(delta.absolute_change))),
                title=(
                    "Revenue is down "
                    f"{movement_label(delta.previous, delta.percent_change, delta.absolute_change)}"
                ),
                body=(
                    f"Revenue fell from {money(delta.previous)} to {money(delta.current)}, "
                    "a drop of "
                    f"{change_phrase(delta.previous, delta.absolute_change, delta.percent_change)}"
                    " versus the previous period."
                ),
                dedupe_key="REVENUE_DROP:total",
                dimension="total",
                subject="Revenue",
                facts=facts,
            )
        ]

    if delta.direction == "up":
        return [
            CandidateInsight(
                insight_type=OwnerInsightType.REVENUE_SPIKE,
                severity=OwnerInsightSeverity.INFO,
                score=Decimal(str(abs(delta.absolute_change))),
                title=(
                    "Revenue is up "
                    f"{movement_label(delta.previous, delta.percent_change, delta.absolute_change)}"
                ),
                body=(
                    f"Revenue rose from {money(delta.previous)} to {money(delta.current)}, "
                    "a gain of "
                    f"{change_phrase(delta.previous, delta.absolute_change, delta.percent_change)}"
                    " versus the previous period."
                ),
                dedupe_key="REVENUE_SPIKE:total",
                dimension="total",
                subject="Revenue",
                facts=facts,
            )
        ]
    return []


def _item_rules(snapshot: DiagnosticsSnapshotResponse) -> list[CandidateInsight]:
    breakdown = _breakdown(snapshot, "item")
    insights: list[CandidateInsight] = []

    for row in _decliners(breakdown)[:2]:
        if not _is_material(row, settings.insight_item_contribution_percent):
            continue
        share = abs(row.contribution_share) if row.contribution_share is not None else 0.0
        insights.append(
            CandidateInsight(
                insight_type=OwnerInsightType.ITEM_DECLINE,
                severity=_severity_for(
                    share,
                    settings.insight_item_contribution_percent,
                    money_amount=row.absolute_change,
                    period_revenue=_period_revenue(snapshot),
                ),
                score=Decimal(str(abs(row.absolute_change))),
                title=f"{row.label} sales are falling",
                body=(
                    f"{row.label} brought in {money(row.current)}, down "
                    f"{money(row.absolute_change)} from {money(row.previous)}"
                    + (
                        f", {share_phrase(row.contribution_share)}."
                        if row.contribution_share is not None
                        else "."
                    )
                ),
                dedupe_key=f"ITEM_DECLINE:{_normalize_subject(row.label)}",
                dimension="item",
                subject=row.label,
                facts=_contribution_facts(row),
            )
        )

    for row in _growers(breakdown)[:1]:
        if not _is_material(row, settings.insight_item_contribution_percent):
            continue
        insights.append(
            CandidateInsight(
                insight_type=OwnerInsightType.ITEM_SURGE,
                severity=OwnerInsightSeverity.INFO,
                score=Decimal(str(abs(row.absolute_change))),
                title=f"{row.label} is growing",
                body=(
                    f"{row.label} brought in {money(row.current)}, up "
                    f"{money(row.absolute_change)} from {money(row.previous)}."
                ),
                dedupe_key=f"ITEM_SURGE:{_normalize_subject(row.label)}",
                dimension="item",
                subject=row.label,
                facts=_contribution_facts(row),
            )
        )

    return insights


def _location_rules(snapshot: DiagnosticsSnapshotResponse) -> list[CandidateInsight]:
    """Branch-level movements, which outrank anything inside a branch.

    A whole branch is the largest unit this platform can move: opening or
    closing one changes every dish, daypart, and cohort it carried, all at once.
    Without this rule those child movements are the only thing the feed can see,
    and a shut branch reads as a list of declining dishes — which is exactly what
    the first real controlled run produced.

    A branch that has stopped trading entirely is treated as material regardless
    of the configured share threshold. Zero is not a small number here, and the
    ordinary contribution test can miss it when another branch's growth masks the
    loss in the total.
    """

    breakdown = _breakdown(snapshot, "location")
    insights: list[CandidateInsight] = []

    for row in _decliners(breakdown)[:2]:
        stopped = row.current == 0 and row.previous_orders > 0
        if not stopped and not _is_material(row, settings.insight_location_contribution_percent):
            continue

        share = abs(row.contribution_share) if row.contribution_share is not None else 0.0
        if stopped:
            title = f"{row.label} has stopped taking orders"
            body = (
                f"{row.label} took {row.previous_orders} orders worth "
                f"{money(row.previous)} in the previous period and none at all "
                "this period. Anything that branch used to sell will look like a "
                "falling dish until it trades again."
            )
            severity = _severity_for(
                # A full stop is reported at the ceiling its money allows, rather
                # than at whatever share the arithmetic happened to produce.
                max(share, settings.insight_location_contribution_percent * 3),
                settings.insight_location_contribution_percent,
                money_amount=row.absolute_change,
                period_revenue=_period_revenue(snapshot),
            )
        else:
            title = f"{row.label} revenue is down"
            body = (
                f"{row.label} brought in {money(row.current)}, down "
                f"{money(row.absolute_change)} from {money(row.previous)}"
                + (
                    f", {share_phrase(row.contribution_share)}."
                    if row.contribution_share is not None
                    else "."
                )
            )
            severity = _severity_for(
                share,
                settings.insight_location_contribution_percent,
                money_amount=row.absolute_change,
                period_revenue=_period_revenue(snapshot),
            )

        insights.append(
            CandidateInsight(
                insight_type=OwnerInsightType.LOCATION_DECLINE,
                severity=severity,
                # Scored above a same-sized child movement so the branch leads
                # the feed rather than tying with a dish it contained.
                score=Decimal(str(abs(row.absolute_change) * 1.5)),
                title=title,
                body=body,
                dedupe_key=f"LOCATION_DECLINE:{_normalize_subject(row.label)}",
                dimension="location",
                subject=row.label,
                facts={**_contribution_facts(row), "stopped_trading": stopped},
            )
        )

    return insights


def _category_rules(snapshot: DiagnosticsSnapshotResponse) -> list[CandidateInsight]:
    breakdown = _breakdown(snapshot, "category")
    insights: list[CandidateInsight] = []
    for row in _decliners(breakdown)[:1]:
        if not _is_material(row, settings.insight_category_contribution_percent):
            continue
        share = abs(row.contribution_share) if row.contribution_share is not None else 0.0
        insights.append(
            CandidateInsight(
                insight_type=OwnerInsightType.CATEGORY_DECLINE,
                severity=_severity_for(
                    share,
                    settings.insight_category_contribution_percent,
                    money_amount=row.absolute_change,
                    period_revenue=_period_revenue(snapshot),
                ),
                score=Decimal(str(abs(row.absolute_change))),
                title=f"The {row.label} category is down",
                body=(
                    f"{row.label} fell from {money(row.previous)} to {money(row.current)}, "
                    f"a drop of {money(row.absolute_change)}."
                ),
                dedupe_key=f"CATEGORY_DECLINE:{_normalize_subject(row.label)}",
                dimension="category",
                subject=row.label,
                facts=_contribution_facts(row),
            )
        )
    return insights


def _daypart_rules(snapshot: DiagnosticsSnapshotResponse) -> list[CandidateInsight]:
    breakdown = _breakdown(snapshot, "daypart")
    insights: list[CandidateInsight] = []
    for row in _decliners(breakdown)[:1]:
        if not _is_material(row, settings.insight_daypart_contribution_percent):
            continue
        share = abs(row.contribution_share) if row.contribution_share is not None else 0.0
        insights.append(
            CandidateInsight(
                insight_type=OwnerInsightType.DAYPART_WEAKNESS,
                severity=_severity_for(
                    share,
                    settings.insight_daypart_contribution_percent,
                    money_amount=row.absolute_change,
                    period_revenue=_period_revenue(snapshot),
                ),
                score=Decimal(str(abs(row.absolute_change))),
                title=f"{row.label} trade has weakened",
                body=(
                    f"{row.label} revenue fell from {money(row.previous)} to "
                    f"{money(row.current)}, with orders down from {row.previous_orders} "
                    f"to {row.current_orders}."
                ),
                dedupe_key=f"DAYPART_WEAKNESS:{_normalize_subject(row.label)}",
                dimension="daypart",
                subject=row.label,
                facts=_contribution_facts(row),
            )
        )
    return insights


def _weekday_rules(snapshot: DiagnosticsSnapshotResponse) -> list[CandidateInsight]:
    # Comparing a Tuesday against a Saturday is not a finding, so this rule only
    # runs when both windows cover the same weekday mix.
    if not snapshot.data_quality.weekday_aligned:
        return []

    breakdown = _breakdown(snapshot, "weekday")
    insights: list[CandidateInsight] = []
    for row in _decliners(breakdown)[:1]:
        if not _is_material(row, settings.insight_weekday_contribution_percent):
            continue
        share = abs(row.contribution_share) if row.contribution_share is not None else 0.0
        insights.append(
            CandidateInsight(
                insight_type=OwnerInsightType.WEEKDAY_WEAKNESS,
                severity=_severity_for(
                    share,
                    settings.insight_weekday_contribution_percent,
                    money_amount=row.absolute_change,
                    period_revenue=_period_revenue(snapshot),
                ),
                score=Decimal(str(abs(row.absolute_change))),
                title=f"{row.label} is the weakest day",
                body=(
                    f"{row.label} revenue fell from {money(row.previous)} to "
                    f"{money(row.current)}, a drop of {money(row.absolute_change)}."
                ),
                dedupe_key=f"WEEKDAY_WEAKNESS:{_normalize_subject(row.label)}",
                dimension="weekday",
                subject=row.label,
                facts=_contribution_facts(row),
            )
        )
    return insights


def _cohort_rules(snapshot: DiagnosticsSnapshotResponse) -> list[CandidateInsight]:
    breakdown = _breakdown(snapshot, "customer_cohort")
    if breakdown is None:
        return []

    insights: list[CandidateInsight] = []
    for row in breakdown.contributions:
        if row.percent_change is None or row.percent_change > -settings.insight_cohort_change_percent:
            continue

        is_returning = row.key == "returning"
        insight_type = (
            OwnerInsightType.RETURNING_CUSTOMER_DECLINE
            if is_returning
            else OwnerInsightType.NEW_CUSTOMER_DECLINE
        )
        explanation = (
            "Fewer regulars came back this period, which usually shows up before revenue does."
            if is_returning
            else "Fewer first-time customers ordered this period."
        )
        insights.append(
            CandidateInsight(
                insight_type=insight_type,
                severity=_severity_for(
                    abs(row.percent_change),
                    settings.insight_cohort_change_percent,
                    money_amount=row.absolute_change,
                    period_revenue=_period_revenue(snapshot),
                ),
                score=Decimal(str(abs(row.absolute_change))),
                title=f"{row.label} spend is down {percent(row.percent_change)}",
                body=(
                    f"{row.label} spent {money(row.current)}, down from "
                    f"{money(row.previous)}. Orders moved from {row.previous_orders} to "
                    f"{row.current_orders}. {explanation}"
                ),
                dedupe_key=f"{insight_type.value}:{row.key}",
                dimension="customer_cohort",
                subject=row.label,
                facts=_contribution_facts(row),
            )
        )
    return insights


def _cancellation_rules(snapshot: DiagnosticsSnapshotResponse) -> list[CandidateInsight]:
    cancelled = _delta(snapshot, "cancelled_orders")
    orders = _delta(snapshot, "orders")
    if cancelled is None or orders is None:
        return []
    if cancelled.current < settings.insight_cancellation_minimum_orders:
        return []

    attempted = orders.current + cancelled.current
    if attempted <= 0:
        return []
    rate = (cancelled.current / attempted) * 100.0
    if rate < settings.insight_cancellation_rate_percent:
        return []

    value = _delta(snapshot, "cancelled_value")
    lost_value = value.current if value is not None else 0.0
    return [
        CandidateInsight(
            insight_type=OwnerInsightType.CANCELLATION_SPIKE,
            severity=_severity_for(
                rate,
                settings.insight_cancellation_rate_percent,
                money_amount=lost_value,
            ),
            score=Decimal(str(abs(lost_value))),
            title=f"{percent(rate)} of orders were cancelled",
            body=(
                f"{int(cancelled.current)} of {int(attempted)} orders were cancelled "
                f"({percent(rate)}), worth {money(lost_value)}."
            ),
            dedupe_key="CANCELLATION_SPIKE:total",
            dimension="total",
            subject="Cancellations",
            facts={
                "cancelled_orders": int(cancelled.current),
                "previous_cancelled_orders": int(cancelled.previous),
                "attempted_orders": int(attempted),
                "cancellation_rate": round(rate, 1),
                "cancelled_value": round(lost_value, 2),
            },
        )
    ]


def _aov_rules(snapshot: DiagnosticsSnapshotResponse) -> list[CandidateInsight]:
    delta = _delta(snapshot, "average_order_value")
    if delta is None or delta.percent_change is None:
        return []
    if delta.percent_change > -settings.insight_aov_change_percent:
        return []

    return [
        CandidateInsight(
            insight_type=OwnerInsightType.AOV_DROP,
            severity=_severity_for(
                abs(delta.percent_change),
                settings.insight_aov_change_percent,
                money_amount=delta.absolute_change,
                period_revenue=_period_revenue(snapshot),
            ),
            score=Decimal(str(abs(delta.absolute_change))),
            title=f"Average order value is down {percent(delta.percent_change)}",
            body=(
                f"The average order fell from {money(delta.previous)} to "
                f"{money(delta.current)}, a drop of {money(delta.absolute_change)}."
            ),
            dedupe_key="AOV_DROP:total",
            dimension="total",
            subject="Average order value",
            facts={
                "current_aov": round(delta.current, 2),
                "previous_aov": round(delta.previous, 2),
                "absolute_change": round(delta.absolute_change, 2),
                "percent_change": round(delta.percent_change, 1),
            },
        )
    ]


def _anomaly_rules(snapshot: DiagnosticsSnapshotResponse) -> list[CandidateInsight]:
    report = snapshot.anomalies
    if not report.evaluated:
        return []

    severity_map = {
        "high": OwnerInsightSeverity.HIGH,
        "medium": OwnerInsightSeverity.MEDIUM,
        "low": OwnerInsightSeverity.LOW,
    }
    insights: list[CandidateInsight] = []
    for point in report.points[:2]:
        gap = point.value - point.baseline_median
        wording = "well below" if point.direction == "down" else "well above"
        insights.append(
            CandidateInsight(
                insight_type=OwnerInsightType.ANOMALY_DAY,
                severity=severity_map.get(point.severity, OwnerInsightSeverity.LOW),
                score=Decimal(str(abs(gap))),
                title=f"{point.day.strftime('%d %b')} was an unusual day",
                body=(
                    f"{point.day.strftime('%d %b')} took {money(point.value)}, "
                    f"{wording} the usual {money(point.baseline_median)} for a day "
                    f"in this period."
                ),
                dedupe_key=f"ANOMALY_DAY:{point.day.isoformat()}",
                dimension="daily",
                subject=point.day.isoformat(),
                facts={
                    "day": point.day.isoformat(),
                    "value": round(point.value, 2),
                    "baseline_median": round(point.baseline_median, 2),
                    "difference": round(gap, 2),
                },
            )
        )
    return insights


RULES: tuple = (
    _revenue_rules,
    # Before the child dimensions: a branch movement explains them, not the
    # other way round.
    _location_rules,
    _item_rules,
    _category_rules,
    _daypart_rules,
    _weekday_rules,
    _cohort_rules,
    _cancellation_rules,
    _aov_rules,
    _anomaly_rules,
)

# Ordering tiebreaker when two findings carry a similar money impact. A drop an
# owner can act on outranks a spike that only confirms good news.
SEVERITY_WEIGHT = {
    OwnerInsightSeverity.HIGH: 4,
    OwnerInsightSeverity.MEDIUM: 3,
    OwnerInsightSeverity.LOW: 2,
    OwnerInsightSeverity.INFO: 1,
}



def _drop_duplicate_category_findings(
    candidates: list[CandidateInsight],
) -> list[CandidateInsight]:
    """Remove a category finding that one item already explains.

    A category containing a single moving dish produces two cards describing the
    same event — "Salads is down ₹144" and "Thai Mango Salad is down ₹144" — which
    reads as two problems when there is one. The item is kept, because it names
    the thing the owner can actually act on.
    """

    item_changes = [
        float(candidate.facts.get("absolute_change") or 0.0)
        for candidate in candidates
        if candidate.insight_type == OwnerInsightType.ITEM_DECLINE
    ]
    if not item_changes:
        return candidates

    threshold = settings.insight_duplicate_share_threshold
    kept: list[CandidateInsight] = []
    for candidate in candidates:
        if candidate.insight_type == OwnerInsightType.CATEGORY_DECLINE:
            category_change = abs(float(candidate.facts.get("absolute_change") or 0.0))
            explained = any(
                category_change > 0
                and abs(item_change) >= category_change * threshold
                and abs(item_change) <= category_change / max(threshold, 0.01)
                for item_change in item_changes
            )
            if explained:
                continue
        kept.append(candidate)
    return kept


def evaluate_rules(
    snapshot: DiagnosticsSnapshotResponse,
    *,
    limit: int | None = None,
) -> list[CandidateInsight]:
    """Run every rule against a snapshot and return the ranked findings."""

    if not snapshot.data_quality.sufficient_volume:
        return []

    candidates: list[CandidateInsight] = []
    for rule in RULES:
        candidates.extend(rule(snapshot))

    candidates = _drop_duplicate_category_findings(candidates)

    # A rule set can produce two cards for the same subject. The first one wins,
    # since rules run in order of decreasing generality.
    seen: set[str] = set()
    deduped: list[CandidateInsight] = []
    for candidate in candidates:
        if candidate.dedupe_key in seen:
            continue
        seen.add(candidate.dedupe_key)
        deduped.append(candidate)

    deduped.sort(
        key=lambda row: (
            -SEVERITY_WEIGHT.get(row.severity, 0),
            -float(row.score),
            row.title.lower(),
        )
    )

    resolved_limit = limit if limit is not None else settings.insight_max_per_briefing
    return deduped[:resolved_limit]


def collect_facts(candidates: Iterable[CandidateInsight]) -> dict[str, Any]:
    """Merge every candidate's numbers into one namespaced fact map."""

    facts: dict[str, Any] = {}
    for index, candidate in enumerate(candidates):
        prefix = f"{candidate.insight_type.value.lower()}_{index}"
        for key, value in candidate.facts.items():
            facts[f"{prefix}.{key}"] = value
    return facts


__all__ = [
    "CandidateInsight",
    "RULES",
    "collect_facts",
    "evaluate_rules",
    "money",
    "percent",
]
