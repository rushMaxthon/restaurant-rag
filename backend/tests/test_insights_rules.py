"""Tests for the deterministic insight rules.

No database and no model: rules take a diagnostics snapshot and return findings,
so every threshold, gate, and ranking decision is checked in isolation.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401  (imported first to settle import order)
from app.config import get_settings
from app.models.enums import OwnerInsightSeverity, OwnerInsightType
from app.schemas.insights import (
    AnomalyReportResponse,
    ContributionBreakdownResponse,
    ContributionResponse,
    DiagnosticsSnapshotResponse,
    InsightsDataQuality,
    InsightsPeriod,
    InsightsScopeResponse,
    MetricDeltaResponse,
)
from app.services.insights.rules import collect_facts, evaluate_rules

settings = get_settings()

RESTAURANT_ID = "11111111-1111-1111-1111-111111111111"


class SettingsOverride:
    def __init__(self, **overrides: object) -> None:
        self._overrides = overrides
        self._previous: dict[str, object] = {}

    def __enter__(self) -> None:
        for key, value in self._overrides.items():
            self._previous[key] = getattr(settings, key)
            setattr(settings, key, value)

    def __exit__(self, *_exc: object) -> None:
        for key, value in self._previous.items():
            setattr(settings, key, value)


def delta(
    metric: str,
    current: float,
    previous: float,
) -> MetricDeltaResponse:
    change = current - previous
    percent = ((current - previous) / abs(previous) * 100.0) if previous else None
    direction = "up" if change > 1e-9 else "down" if change < -1e-9 else "flat"
    return MetricDeltaResponse(
        metric=metric,
        current=current,
        previous=previous,
        absolute_change=change,
        percent_change=percent,
        direction=direction,
        sufficient_data=True,
    )


def contribution(
    key: str,
    label: str,
    current: float,
    previous: float,
    *,
    share: float | None = None,
    current_orders: int = 10,
    previous_orders: int = 10,
) -> ContributionResponse:
    change = current - previous
    percent = ((current - previous) / abs(previous) * 100.0) if previous else None
    return ContributionResponse(
        key=key,
        label=label,
        current=current,
        previous=previous,
        absolute_change=change,
        percent_change=percent,
        contribution_share=share,
        direction="up" if change > 0 else "down" if change < 0 else "flat",
        current_orders=current_orders,
        previous_orders=previous_orders,
        current_quantity=current_orders,
        previous_quantity=previous_orders,
    )


def breakdown(
    dimension: str,
    parent_change: float,
    rows: list[ContributionResponse],
    *,
    basis: str = "gross_revenue",
) -> ContributionBreakdownResponse:
    return ContributionBreakdownResponse(
        dimension=dimension,
        basis=basis,
        parent_change=parent_change,
        sufficient_data=True,
        contributions=rows,
    )


def snapshot(
    *,
    headline: list[MetricDeltaResponse] | None = None,
    breakdowns: list[ContributionBreakdownResponse] | None = None,
    anomalies: AnomalyReportResponse | None = None,
    sufficient_volume: bool = True,
    weekday_aligned: bool = True,
) -> DiagnosticsSnapshotResponse:
    return DiagnosticsSnapshotResponse(
        scope=InsightsScopeResponse(
            restaurant_id=RESTAURANT_ID,
            restaurant_location_id=None,
            timezone="Asia/Kolkata",
        ),
        current_period=InsightsPeriod(
            start_date=date(2026, 3, 9),
            end_date=date(2026, 3, 15),
            day_count=7,
            label="09 Mar - 15 Mar 2026",
        ),
        previous_period=InsightsPeriod(
            start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 8),
            day_count=7,
            label="02 Mar - 08 Mar 2026",
        ),
        generated_at="2026-03-16T00:00:00+00:00",
        data_quality=InsightsDataQuality(
            sufficient_volume=sufficient_volume,
            weekday_aligned=weekday_aligned,
            includes_partial_day=False,
            counted_order_statuses=["DELIVERED"],
            notes=[],
        ),
        headline=headline or [],
        breakdowns=breakdowns or [],
        anomalies=anomalies
        or AnomalyReportResponse(
            evaluated=False, baseline_days=0, baseline_median_orders=0.0, points=[]
        ),
    )


def types_of(candidates) -> set[OwnerInsightType]:
    return {candidate.insight_type for candidate in candidates}


class VolumeGateTests(unittest.TestCase):
    def test_nothing_fires_without_sufficient_volume(self) -> None:
        # The same collapse that would be a HIGH finding at scale must stay
        # silent for a restaurant doing a handful of orders.
        result = evaluate_rules(
            snapshot(
                headline=[delta("gross_revenue", 4000.0, 10000.0)],
                sufficient_volume=False,
            )
        )
        self.assertEqual(result, [])


class RevenueRuleTests(unittest.TestCase):
    def test_drop_beyond_both_thresholds_fires(self) -> None:
        with SettingsOverride(
            insight_revenue_change_percent=8.0, insight_revenue_change_minimum=1000.0
        ):
            result = evaluate_rules(
                snapshot(headline=[delta("gross_revenue", 8800.0, 10000.0)])
            )
        self.assertIn(OwnerInsightType.REVENUE_DROP, types_of(result))
        found = next(row for row in result if row.insight_type == OwnerInsightType.REVENUE_DROP)
        self.assertIn("12.0%", found.title)
        self.assertEqual(found.facts["absolute_change"], -1200.0)

    def test_percentage_alone_is_not_enough(self) -> None:
        # 20% of a small base is not a headline.
        with SettingsOverride(
            insight_revenue_change_percent=8.0, insight_revenue_change_minimum=1000.0
        ):
            result = evaluate_rules(
                snapshot(headline=[delta("gross_revenue", 400.0, 500.0)])
            )
        self.assertNotIn(OwnerInsightType.REVENUE_DROP, types_of(result))

    def test_absolute_alone_is_not_enough(self) -> None:
        # A large business moving 1% is normal trading.
        with SettingsOverride(
            insight_revenue_change_percent=8.0, insight_revenue_change_minimum=1000.0
        ):
            result = evaluate_rules(
                snapshot(headline=[delta("gross_revenue", 495000.0, 500000.0)])
            )
        self.assertNotIn(OwnerInsightType.REVENUE_DROP, types_of(result))

    def test_growth_is_reported_as_information(self) -> None:
        with SettingsOverride(
            insight_revenue_change_percent=8.0, insight_revenue_change_minimum=1000.0
        ):
            result = evaluate_rules(
                snapshot(headline=[delta("gross_revenue", 12000.0, 10000.0)])
            )
        found = next(row for row in result if row.insight_type == OwnerInsightType.REVENUE_SPIKE)
        self.assertEqual(found.severity, OwnerInsightSeverity.INFO)

    def test_severity_scales_with_magnitude(self) -> None:
        with SettingsOverride(
            insight_revenue_change_percent=8.0, insight_revenue_change_minimum=1000.0
        ):
            severe = evaluate_rules(
                snapshot(headline=[delta("gross_revenue", 5000.0, 20000.0)])
            )
        found = next(row for row in severe if row.insight_type == OwnerInsightType.REVENUE_DROP)
        self.assertEqual(found.severity, OwnerInsightSeverity.HIGH)


class ItemRuleTests(unittest.TestCase):
    def test_top_decliner_by_share_fires(self) -> None:
        rows = [
            contribution("pizza", "Margherita Pizza", 2500.0, 3500.0, share=90.0),
            contribution("pasta", "Pasta Alfredo", 2100.0, 2200.0, share=10.0),
        ]
        with SettingsOverride(
            insight_item_contribution_percent=25.0, insight_revenue_change_minimum=1000.0
        ):
            result = evaluate_rules(
                snapshot(breakdowns=[breakdown("item", -1100.0, rows, basis="item_revenue")])
            )
        declines = [row for row in result if row.insight_type == OwnerInsightType.ITEM_DECLINE]
        self.assertEqual(declines[0].subject, "Margherita Pizza")

    def test_large_decline_fires_even_when_the_total_is_flat(self) -> None:
        # One dish collapsing while another masks it in the total is exactly the
        # finding a share-only test would miss.
        rows = [
            contribution("pizza", "Margherita Pizza", 1000.0, 4000.0, share=None),
            contribution("pasta", "Pasta Alfredo", 5000.0, 2000.0, share=None),
        ]
        with SettingsOverride(
            insight_item_contribution_percent=25.0, insight_revenue_change_minimum=1000.0
        ):
            result = evaluate_rules(
                snapshot(breakdowns=[breakdown("item", 0.0, rows, basis="item_revenue")])
            )
        declines = [row for row in result if row.insight_type == OwnerInsightType.ITEM_DECLINE]
        self.assertEqual(len(declines), 1)
        self.assertEqual(declines[0].subject, "Margherita Pizza")

    def test_immaterial_movement_is_ignored(self) -> None:
        rows = [contribution("side", "Garlic Bread", 480.0, 500.0, share=4.0)]
        with SettingsOverride(
            insight_item_contribution_percent=25.0, insight_revenue_change_minimum=1000.0
        ):
            result = evaluate_rules(
                snapshot(breakdowns=[breakdown("item", -500.0, rows, basis="item_revenue")])
            )
        self.assertNotIn(OwnerInsightType.ITEM_DECLINE, types_of(result))


class WeekdayRuleTests(unittest.TestCase):
    def _snapshot(self, *, aligned: bool):
        rows = [contribution("2", "Tuesday", 1000.0, 3000.0, share=80.0)]
        return snapshot(
            breakdowns=[breakdown("weekday", -2500.0, rows)],
            weekday_aligned=aligned,
        )

    def test_fires_when_windows_cover_the_same_weekdays(self) -> None:
        with SettingsOverride(insight_weekday_contribution_percent=30.0):
            result = evaluate_rules(self._snapshot(aligned=True))
        self.assertIn(OwnerInsightType.WEEKDAY_WEAKNESS, types_of(result))

    def test_suppressed_when_the_comparison_is_not_like_for_like(self) -> None:
        # Comparing a Tuesday against a Saturday is not a finding.
        with SettingsOverride(insight_weekday_contribution_percent=30.0):
            result = evaluate_rules(self._snapshot(aligned=False))
        self.assertNotIn(OwnerInsightType.WEEKDAY_WEAKNESS, types_of(result))


class CohortRuleTests(unittest.TestCase):
    def test_returning_customer_decline_fires(self) -> None:
        rows = [
            contribution("returning", "Returning customers", 3000.0, 6000.0),
            contribution("new", "New customers", 2000.0, 2100.0),
        ]
        with SettingsOverride(insight_cohort_change_percent=15.0):
            result = evaluate_rules(
                snapshot(breakdowns=[breakdown("customer_cohort", -3100.0, rows)])
            )
        self.assertIn(OwnerInsightType.RETURNING_CUSTOMER_DECLINE, types_of(result))
        self.assertNotIn(OwnerInsightType.NEW_CUSTOMER_DECLINE, types_of(result))

    def test_new_customer_decline_fires_separately(self) -> None:
        rows = [contribution("new", "New customers", 500.0, 2000.0)]
        with SettingsOverride(insight_cohort_change_percent=15.0):
            result = evaluate_rules(
                snapshot(breakdowns=[breakdown("customer_cohort", -1500.0, rows)])
            )
        self.assertIn(OwnerInsightType.NEW_CUSTOMER_DECLINE, types_of(result))


class CancellationRuleTests(unittest.TestCase):
    def test_rate_above_threshold_fires(self) -> None:
        headline = [
            delta("orders", 90.0, 100.0),
            delta("cancelled_orders", 10.0, 2.0),
            delta("cancelled_value", 5000.0, 900.0),
        ]
        with SettingsOverride(
            insight_cancellation_rate_percent=8.0, insight_cancellation_minimum_orders=3
        ):
            result = evaluate_rules(snapshot(headline=headline))
        found = next(
            row for row in result if row.insight_type == OwnerInsightType.CANCELLATION_SPIKE
        )
        self.assertEqual(found.facts["cancelled_orders"], 10)
        self.assertEqual(found.facts["attempted_orders"], 100)
        self.assertAlmostEqual(found.facts["cancellation_rate"], 10.0)

    def test_a_couple_of_cancellations_do_not_fire(self) -> None:
        headline = [
            delta("orders", 12.0, 14.0),
            delta("cancelled_orders", 2.0, 1.0),
            delta("cancelled_value", 800.0, 400.0),
        ]
        with SettingsOverride(
            insight_cancellation_rate_percent=8.0, insight_cancellation_minimum_orders=3
        ):
            result = evaluate_rules(snapshot(headline=headline))
        self.assertNotIn(OwnerInsightType.CANCELLATION_SPIKE, types_of(result))


class AnomalyRuleTests(unittest.TestCase):
    def test_evaluated_anomalies_become_insights(self) -> None:
        report = AnomalyReportResponse(
            evaluated=True,
            baseline_days=28,
            baseline_median_orders=20.0,
            points=[
                {
                    "day": date(2026, 3, 11),
                    "metric": "revenue",
                    "value": 2000.0,
                    "baseline_median": 10000.0,
                    "robust_z": -6.2,
                    "direction": "down",
                    "severity": "high",
                }
            ],
        )
        result = evaluate_rules(snapshot(anomalies=report))
        found = next(row for row in result if row.insight_type == OwnerInsightType.ANOMALY_DAY)
        self.assertEqual(found.severity, OwnerInsightSeverity.HIGH)
        self.assertEqual(found.dedupe_key, "ANOMALY_DAY:2026-03-11")

    def test_unevaluated_report_produces_nothing(self) -> None:
        report = AnomalyReportResponse(
            evaluated=False, baseline_days=3, baseline_median_orders=1.0, points=[]
        )
        result = evaluate_rules(snapshot(anomalies=report))
        self.assertNotIn(OwnerInsightType.ANOMALY_DAY, types_of(result))


class RankingAndDedupeTests(unittest.TestCase):
    def _mixed_snapshot(self):
        return snapshot(
            headline=[
                delta("gross_revenue", 8000.0, 10000.0),
                delta("average_order_value", 400.0, 500.0),
            ],
            breakdowns=[
                breakdown(
                    "item",
                    -2000.0,
                    [contribution("pizza", "Margherita Pizza", 2000.0, 4000.0, share=100.0)],
                    basis="item_revenue",
                )
            ],
        )

    def test_actionable_findings_outrank_informational_ones(self) -> None:
        result = evaluate_rules(
            snapshot(
                headline=[delta("gross_revenue", 20000.0, 10000.0)],
                breakdowns=[
                    breakdown(
                        "item",
                        10000.0,
                        [
                            contribution("pizza", "Margherita Pizza", 1000.0, 3000.0, share=-20.0),
                            contribution("pasta", "Pasta Alfredo", 14000.0, 2000.0, share=120.0),
                        ],
                        basis="item_revenue",
                    )
                ],
            )
        )
        # The revenue spike moved more money, but the dish that collapsed is the
        # one an owner can act on.
        self.assertEqual(result[0].insight_type, OwnerInsightType.ITEM_DECLINE)

    def test_dedupe_keys_are_unique_within_a_run(self) -> None:
        result = evaluate_rules(self._mixed_snapshot())
        keys = [row.dedupe_key for row in result]
        self.assertEqual(len(keys), len(set(keys)))

    def test_limit_truncates_after_ranking(self) -> None:
        result = evaluate_rules(self._mixed_snapshot(), limit=1)
        self.assertEqual(len(result), 1)

    def test_dedupe_keys_are_stable_across_runs(self) -> None:
        # Stability is what lets a continuing slump be suppressed rather than
        # regenerated every night.
        first = evaluate_rules(self._mixed_snapshot())
        second = evaluate_rules(self._mixed_snapshot())
        self.assertEqual(
            [row.dedupe_key for row in first], [row.dedupe_key for row in second]
        )

    def test_collect_facts_namespaces_every_number(self) -> None:
        result = evaluate_rules(self._mixed_snapshot())
        facts = collect_facts(result)
        self.assertTrue(facts)
        self.assertTrue(all("." in key for key in facts))


if __name__ == "__main__":
    unittest.main()
