"""Assembles one diagnostics snapshot from the metric and diagnostic layers.

This is the only module that talks to both Postgres and Redis. Everything it
returns is deterministic: no LLM is involved at this step, and the same window
over the same data always produces the same snapshot.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas.insights import (
    AnomalyPointResponse,
    AnomalyReportResponse,
    ContributionBreakdownResponse,
    ContributionResponse,
    DiagnosticsSnapshotResponse,
    InsightsDataQuality,
    InsightsPeriod,
    InsightsScopeResponse,
    MetricDeltaResponse,
)
from app.services.cache import cache_delete_pattern, cache_get_json, cache_set_json
from app.services.insights import metrics as metrics_layer
from app.services.insights.diagnostics import (
    AnomalyReport,
    ContributionBreakdown,
    MetricDelta,
    build_contributions,
    build_delta,
    detect_anomalies,
    fill_daily_series,
    has_sufficient_volume,
)
from app.services.insights.periods import (
    AnalysisPeriod,
    local_today,
    PeriodComparison,
    baseline_period,
    resolve_period_comparison,
)
from app.services.insights.scope import InsightsScope

settings = get_settings()
logger = logging.getLogger(__name__)

INSIGHTS_CACHE_PREFIX = "insights:diagnostics"


def _cache_key(scope: InsightsScope, comparison: PeriodComparison) -> str:
    return (
        f"{INSIGHTS_CACHE_PREFIX}:{scope.cache_fragment()}"
        f":{comparison.current.start_date}:{comparison.current.end_date}"
    )


def invalidate_insights_caches(restaurant_id: object | None = None) -> int:
    """Drop cached snapshots, for one restaurant or all of them."""

    if restaurant_id is None:
        return cache_delete_pattern(f"{INSIGHTS_CACHE_PREFIX}:*")
    return cache_delete_pattern(f"{INSIGHTS_CACHE_PREFIX}:{restaurant_id}:*")


def _period_payload(period: AnalysisPeriod) -> InsightsPeriod:
    return InsightsPeriod(
        start_date=period.start_date,
        end_date=period.end_date,
        day_count=period.day_count,
        label=period.label(),
    )


def _delta_payload(delta: MetricDelta) -> MetricDeltaResponse:
    # The diagnostic dataclasses use slots, so they carry no __dict__.
    return MetricDeltaResponse(**asdict(delta))


def _breakdown_payload(breakdown: ContributionBreakdown) -> ContributionBreakdownResponse:
    return ContributionBreakdownResponse(
        dimension=breakdown.dimension,
        basis=breakdown.basis,
        parent_change=breakdown.parent_change,
        sufficient_data=breakdown.sufficient_data,
        note=breakdown.note,
        excluded_change=breakdown.excluded_change,
        excluded_children=breakdown.excluded_children,
        contributions=[ContributionResponse(**asdict(row)) for row in breakdown.contributions],
    )


def _anomaly_payload(report: AnomalyReport) -> AnomalyReportResponse:
    return AnomalyReportResponse(
        evaluated=report.evaluated,
        baseline_days=report.baseline_days,
        baseline_median_orders=report.baseline_median_orders,
        note=report.note,
        points=[AnomalyPointResponse(**asdict(point)) for point in report.points],
    )


def build_diagnostics_snapshot(
    db: Session,
    *,
    scope: InsightsScope,
    comparison: PeriodComparison,
) -> DiagnosticsSnapshotResponse:
    current = comparison.current
    previous = comparison.previous

    current_totals = metrics_layer.fetch_totals(db, scope, current)
    previous_totals = metrics_layer.fetch_totals(db, scope, previous)
    current_cancellations = metrics_layer.fetch_cancellations(db, scope, current)
    previous_cancellations = metrics_layer.fetch_cancellations(db, scope, previous)

    sufficient = has_sufficient_volume(current_totals.orders, previous_totals.orders)

    headline = [
        build_delta(
            "gross_revenue",
            current_totals.gross_revenue,
            previous_totals.gross_revenue,
            sufficient_data=sufficient,
        ),
        build_delta("orders", current_totals.orders, previous_totals.orders, sufficient_data=sufficient),
        build_delta(
            "average_order_value",
            current_totals.average_order_value,
            previous_totals.average_order_value,
            sufficient_data=sufficient,
        ),
        build_delta(
            "customers",
            current_totals.customers,
            previous_totals.customers,
            sufficient_data=sufficient,
        ),
        build_delta(
            "items_sold",
            current_totals.items_sold,
            previous_totals.items_sold,
            sufficient_data=sufficient,
        ),
        build_delta(
            "item_revenue",
            current_totals.item_revenue,
            previous_totals.item_revenue,
            sufficient_data=sufficient,
        ),
        build_delta(
            "discount_total",
            current_totals.discount_total,
            previous_totals.discount_total,
            sufficient_data=sufficient,
        ),
        build_delta(
            "cancelled_orders",
            current_cancellations.cancelled_orders,
            previous_cancellations.cancelled_orders,
            sufficient_data=sufficient,
        ),
        build_delta(
            "cancelled_value",
            current_cancellations.cancelled_value,
            previous_cancellations.cancelled_value,
            sufficient_data=sufficient,
        ),
    ]

    gross_change = current_totals.gross_revenue - previous_totals.gross_revenue
    item_change = current_totals.item_revenue - previous_totals.item_revenue

    current_items = metrics_layer.fetch_item_metrics(db, scope, current)
    previous_items = metrics_layer.fetch_item_metrics(db, scope, previous)
    current_categories = metrics_layer.fetch_category_metrics(db, scope, current)
    previous_categories = metrics_layer.fetch_category_metrics(db, scope, previous)
    current_hours = metrics_layer.fetch_hour_metrics(db, scope, current)
    previous_hours = metrics_layer.fetch_hour_metrics(db, scope, previous)
    current_weekdays = metrics_layer.fetch_weekday_metrics(db, scope, current)
    previous_weekdays = metrics_layer.fetch_weekday_metrics(db, scope, previous)
    current_cohorts = metrics_layer.fetch_customer_cohorts(db, scope, current)
    previous_cohorts = metrics_layer.fetch_customer_cohorts(db, scope, previous)

    limit = settings.insights_top_contributor_limit

    breakdowns = [
        build_contributions(
            "item",
            basis="item_revenue",
            current_rows=current_items,
            previous_rows=previous_items,
            key_fn=lambda row: row.dish_key,
            label_fn=lambda row: row.name,
            value_fn=lambda row: row.revenue,
            orders_fn=lambda row: row.orders,
            quantity_fn=lambda row: row.quantity,
            parent_change=item_change,
            limit=limit,
            sufficient_data=sufficient,
        ),
        build_contributions(
            "category",
            basis="item_revenue",
            current_rows=current_categories,
            previous_rows=previous_categories,
            key_fn=lambda row: row.category,
            label_fn=lambda row: row.category,
            value_fn=lambda row: row.revenue,
            orders_fn=lambda row: row.orders,
            quantity_fn=lambda row: row.quantity,
            parent_change=item_change,
            limit=limit,
            sufficient_data=sufficient,
        ),
        build_contributions(
            "hour_of_day",
            basis="gross_revenue",
            current_rows=current_hours,
            previous_rows=previous_hours,
            key_fn=lambda row: str(row.hour),
            label_fn=lambda row: f"{row.hour:02d}:00",
            value_fn=lambda row: row.revenue,
            orders_fn=lambda row: row.orders,
            parent_change=gross_change,
            limit=24,
            sufficient_data=sufficient,
        ),
        build_contributions(
            "daypart",
            basis="gross_revenue",
            current_rows=metrics_layer.rollup_dayparts(current_hours),
            previous_rows=metrics_layer.rollup_dayparts(previous_hours),
            key_fn=lambda row: row.daypart,
            label_fn=lambda row: row.daypart,
            value_fn=lambda row: row.revenue,
            orders_fn=lambda row: row.orders,
            parent_change=gross_change,
            sufficient_data=sufficient,
        ),
        build_contributions(
            "weekday",
            basis="gross_revenue",
            current_rows=current_weekdays,
            previous_rows=previous_weekdays,
            key_fn=lambda row: str(row.iso_weekday),
            label_fn=lambda row: row.weekday_name,
            value_fn=lambda row: row.revenue,
            orders_fn=lambda row: row.orders,
            parent_change=gross_change,
            limit=7,
            sufficient_data=sufficient,
            note=(
                None
                if comparison.weekday_aligned
                else (
                    "The two windows do not cover the same weekday mix, so weekday "
                    "contributions are not like-for-like."
                )
            ),
        ),
        build_contributions(
            "customer_cohort",
            basis="gross_revenue",
            current_rows=current_cohorts,
            previous_rows=previous_cohorts,
            key_fn=lambda row: row.cohort,
            label_fn=lambda row: "New customers" if row.cohort == "new" else "Returning customers",
            value_fn=lambda row: row.revenue,
            orders_fn=lambda row: row.orders,
            parent_change=gross_change,
            sufficient_data=sufficient,
        ),
    ]

    # Only meaningful across branches. Scoped to one, every contribution would
    # be a single 100% row that says nothing.
    if scope.restaurant_location_id is None:
        current_locations = metrics_layer.fetch_location_metrics(db, scope, current)
        previous_locations = metrics_layer.fetch_location_metrics(db, scope, previous)
        breakdowns.append(
            build_contributions(
                "location",
                basis="gross_revenue",
                current_rows=current_locations,
                previous_rows=previous_locations,
                key_fn=lambda row: str(row.restaurant_location_id),
                label_fn=lambda row: row.branch_name,
                value_fn=lambda row: row.revenue,
                orders_fn=lambda row: row.orders,
                parent_change=gross_change,
                limit=limit,
                sufficient_data=sufficient,
            )
        )

    baseline = baseline_period(current)
    series = metrics_layer.fetch_daily_series_range(db, scope, baseline, current)
    dense_series = fill_daily_series(series, baseline.start_date, current.end_date)
    anomalies = detect_anomalies(
        dense_series,
        evaluation_start=current.start_date,
        metric="revenue",
    )

    coverage = metrics_layer.fetch_coverage(db, scope, current)

    notes: list[str] = []
    # Said before the volume note, because "4 of 30 days had any trade at all"
    # explains a thin window in a way an order count alone does not.
    if coverage.trading_days and coverage.trading_days < coverage.days_in_window:
        notes.append(
            f"Only {coverage.trading_days} of {coverage.days_in_window} days in "
            "this window had any orders, so daily and weekday patterns rest on "
            "very few days."
        )
    if not sufficient:
        notes.append(
            "Order volume is below the reporting threshold "
            f"({settings.insights_min_orders_for_delta}), so percentage changes are unreliable."
        )
    if not comparison.weekday_aligned:
        notes.append(
            "The comparison window is not a whole number of weeks, so the two "
            "periods cover different weekdays."
        )
    if comparison.includes_partial_day:
        # Windows run up to today, so this is the normal case. An owner
        # comparing the figure against their own till reading needs to know it
        # covers a day still in progress, and that the previous period it is
        # measured against is a whole one.
        notes.append(
            f"Today ({local_today(comparison.timezone_name).strftime('%d %b')}) is "
            "included and is still in progress, so it counts only the trade taken "
            "so far and will keep rising through the day."
        )
    else:
        # Only reached when a caller asked for a range that ends in the past.
        notes.append(
            f"This window ends on {current.end_date.strftime('%d %b')}, so it does "
            "not include today."
        )
    if current.day_count != settings.insights_default_window_days:
        notes.append(
            f"A {current.day_count}-day window was used because shorter periods "
            "did not have enough orders to compare."
        )
    if anomalies.note:
        notes.append(anomalies.note)

    return DiagnosticsSnapshotResponse(
        scope=InsightsScopeResponse(
            restaurant_id=scope.restaurant_id,
            restaurant_location_id=scope.restaurant_location_id,
            timezone=comparison.timezone_name,
        ),
        current_period=_period_payload(current),
        previous_period=_period_payload(previous),
        generated_at=datetime.now(UTC).isoformat(),
        data_quality=InsightsDataQuality(
            sufficient_volume=sufficient,
            weekday_aligned=comparison.weekday_aligned,
            includes_partial_day=comparison.includes_partial_day,
            counted_order_statuses=[
                order_status.value for order_status in metrics_layer.counted_order_statuses()
            ],
            notes=notes,
            trading_days=coverage.trading_days,
            days_in_window=coverage.days_in_window,
        ),
        headline=[_delta_payload(delta) for delta in headline],
        breakdowns=[_breakdown_payload(breakdown) for breakdown in breakdowns],
        anomalies=_anomaly_payload(anomalies),
    )


def get_diagnostics_snapshot(
    db: Session,
    *,
    scope: InsightsScope,
    date_from=None,
    date_to=None,
    window_days: int | None = None,
    use_cache: bool = True,
) -> DiagnosticsSnapshotResponse:
    comparison = resolve_period_comparison(
        date_from=date_from,
        date_to=date_to,
        window_days=window_days,
    )

    cache_key = _cache_key(scope, comparison)
    # Every window now ends today, so refusing to cache a partial day would
    # have retired this cache entirely and put a fresh eighteen-query snapshot
    # behind every page load. A window running into today does keep moving, so
    # it gets a short life instead of none: fresh enough that an order placed a
    # minute ago shows up promptly, cheap enough that a reload is free.
    ttl = (
        settings.insights_partial_day_cache_ttl_seconds
        if comparison.includes_partial_day
        else settings.insights_cache_ttl_seconds
    )

    if use_cache:
        cached = cache_get_json(cache_key)
        if cached is not None:
            try:
                return DiagnosticsSnapshotResponse.model_validate(cached)
            except ValueError:
                logger.warning("Discarding malformed insights cache entry key=%s", cache_key)

    snapshot = build_diagnostics_snapshot(db, scope=scope, comparison=comparison)

    if use_cache:
        cache_set_json(cache_key, snapshot.model_dump(mode="json"), ttl_seconds=ttl)

    return snapshot


__all__ = [
    "INSIGHTS_CACHE_PREFIX",
    "build_diagnostics_snapshot",
    "get_diagnostics_snapshot",
    "invalidate_insights_caches",
]
