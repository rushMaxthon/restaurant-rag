"""Pure-logic tests for the insights diagnostics layer.

No database and no Redis: everything here is deterministic Python over metric
result sets, which is exactly the part that must not be allowed to drift.
"""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401  (imported first to settle import order)
from app.config import get_settings
from app.services.insights.diagnostics import (
    build_contributions,
    build_delta,
    detect_anomalies,
    direction_of,
    fill_daily_series,
    has_sufficient_volume,
    percent_change_of,
)
from app.services.insights.metrics import DailyPoint, ItemMetrics, rollup_dayparts, HourMetrics
from app.services.insights.periods import (
    build_period,
    previous_period,
    resolve_period_comparison,
)
from fastapi import HTTPException

settings = get_settings()


def item(name: str, revenue: float, orders: int = 5, quantity: int = 5) -> ItemMetrics:
    return ItemMetrics(
        dish_key=name.lower(),
        name=name,
        category="Pizza",
        menu_item_id=None,
        quantity=quantity,
        revenue=revenue,
        orders=orders,
    )


class SettingsOverride:
    """Temporarily override cached settings shared by the insights modules."""

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


class PercentChangeTests(unittest.TestCase):
    def test_normal_change(self) -> None:
        self.assertAlmostEqual(percent_change_of(88.0, 100.0), -12.0)
        self.assertAlmostEqual(percent_change_of(150.0, 100.0), 50.0)

    def test_zero_baseline_returns_none_not_infinity(self) -> None:
        # "Grew from nothing" and "did not change" are different findings, so a
        # missing baseline must not collapse into 0% or an infinity.
        self.assertIsNone(percent_change_of(500.0, 0.0))
        self.assertIsNone(percent_change_of(0.0, 0.0))

    def test_negative_baseline_uses_magnitude(self) -> None:
        self.assertAlmostEqual(percent_change_of(-50.0, -100.0), 50.0)

    def test_direction_ignores_floating_point_residue(self) -> None:
        self.assertEqual(direction_of(1e-12), "flat")
        self.assertEqual(direction_of(-0.5), "down")
        self.assertEqual(direction_of(0.5), "up")


class BuildDeltaTests(unittest.TestCase):
    def test_reports_absolute_and_percent(self) -> None:
        delta = build_delta("gross_revenue", 8800.0, 10000.0)
        self.assertAlmostEqual(delta.absolute_change, -1200.0)
        self.assertAlmostEqual(delta.percent_change, -12.0)
        self.assertEqual(delta.direction, "down")
        self.assertIsNone(delta.note)

    def test_missing_baseline_is_annotated(self) -> None:
        delta = build_delta("orders", 12.0, 0.0)
        self.assertIsNone(delta.percent_change)
        self.assertIsNotNone(delta.note)


class SufficientVolumeTests(unittest.TestCase):
    def test_low_volume_is_rejected(self) -> None:
        with SettingsOverride(insights_min_orders_for_delta=10):
            self.assertFalse(has_sufficient_volume(4, 6))
            self.assertTrue(has_sufficient_volume(10, 0))
            # The higher of the two windows decides, so a collapse from a busy
            # week to a quiet one still reports.
            self.assertTrue(has_sufficient_volume(1, 40))


class ContributionTests(unittest.TestCase):
    def test_shares_sum_to_one_hundred_percent(self) -> None:
        current = [item("Pizza", 820.0), item("Pasta", 400.0)]
        previous = [item("Pizza", 1000.0), item("Pasta", 420.0)]
        parent_change = sum(row.revenue for row in current) - sum(row.revenue for row in previous)

        breakdown = build_contributions(
            "item",
            basis="item_revenue",
            current_rows=current,
            previous_rows=previous,
            key_fn=lambda row: row.dish_key,
            label_fn=lambda row: row.name,
            value_fn=lambda row: row.revenue,
            orders_fn=lambda row: row.orders,
            parent_change=parent_change,
        )

        self.assertAlmostEqual(breakdown.parent_change, -200.0)
        total_share = sum(row.contribution_share or 0.0 for row in breakdown.contributions)
        self.assertAlmostEqual(total_share, 100.0)

        pizza = next(row for row in breakdown.contributions if row.label == "Pizza")
        self.assertAlmostEqual(pizza.absolute_change, -180.0)
        self.assertAlmostEqual(pizza.contribution_share, 90.0)
        self.assertAlmostEqual(pizza.percent_change, -18.0)

    def test_ranked_by_absolute_impact_not_percentage(self) -> None:
        # A tiny item halving is a bigger percentage but a smaller business
        # problem than the flagship sliding a little.
        current = [item("Flagship", 5000.0, orders=200), item("Side", 50.0, orders=10)]
        previous = [item("Flagship", 5600.0, orders=220), item("Side", 100.0, orders=20)]

        breakdown = build_contributions(
            "item",
            basis="item_revenue",
            current_rows=current,
            previous_rows=previous,
            key_fn=lambda row: row.dish_key,
            label_fn=lambda row: row.name,
            value_fn=lambda row: row.revenue,
            orders_fn=lambda row: row.orders,
        )
        self.assertEqual(breakdown.contributions[0].label, "Flagship")

    def test_offsetting_movements_may_exceed_full_share(self) -> None:
        # Pizza fell 300 while Pasta rose 100, netting -200. Pizza is therefore
        # 150% of the net change, and clamping that would misstate what happened.
        current = [item("Pizza", 700.0), item("Pasta", 500.0)]
        previous = [item("Pizza", 1000.0), item("Pasta", 400.0)]

        breakdown = build_contributions(
            "item",
            basis="item_revenue",
            current_rows=current,
            previous_rows=previous,
            key_fn=lambda row: row.dish_key,
            label_fn=lambda row: row.name,
            value_fn=lambda row: row.revenue,
            orders_fn=lambda row: row.orders,
        )
        pizza = next(row for row in breakdown.contributions if row.label == "Pizza")
        self.assertAlmostEqual(pizza.contribution_share, 150.0)
        self.assertEqual(len(breakdown.top_decliners), 1)
        self.assertEqual(len(breakdown.top_growers), 1)

    def test_items_present_in_only_one_window(self) -> None:
        current = [item("Newly launched", 300.0, orders=8)]
        previous = [item("Discontinued", 500.0, orders=9)]

        breakdown = build_contributions(
            "item",
            basis="item_revenue",
            current_rows=current,
            previous_rows=previous,
            key_fn=lambda row: row.dish_key,
            label_fn=lambda row: row.name,
            value_fn=lambda row: row.revenue,
            orders_fn=lambda row: row.orders,
        )
        by_label = {row.label: row for row in breakdown.contributions}
        self.assertAlmostEqual(by_label["Newly launched"].previous, 0.0)
        self.assertAlmostEqual(by_label["Discontinued"].current, 0.0)
        self.assertAlmostEqual(by_label["Discontinued"].absolute_change, -500.0)

    def test_low_volume_children_are_dropped(self) -> None:
        with SettingsOverride(insights_min_orders_for_contribution=3):
            current = [item("Real mover", 800.0, orders=40), item("One-off", 900.0, orders=1)]
            previous = [item("Real mover", 1000.0, orders=50)]

            breakdown = build_contributions(
                "item",
                basis="item_revenue",
                current_rows=current,
                previous_rows=previous,
                key_fn=lambda row: row.dish_key,
                label_fn=lambda row: row.name,
                value_fn=lambda row: row.revenue,
                orders_fn=lambda row: row.orders,
            )
            labels = {row.label for row in breakdown.contributions}
            self.assertIn("Real mover", labels)
            self.assertNotIn("One-off", labels)

    def test_limit_truncates_after_ranking(self) -> None:
        current = [item(f"Item {index}", float(index) * 10, orders=10) for index in range(1, 11)]
        previous = [item(f"Item {index}", 0.0, orders=10) for index in range(1, 11)]
        breakdown = build_contributions(
            "item",
            basis="item_revenue",
            current_rows=current,
            previous_rows=previous,
            key_fn=lambda row: row.dish_key,
            label_fn=lambda row: row.name,
            value_fn=lambda row: row.revenue,
            orders_fn=lambda row: row.orders,
            limit=3,
        )
        self.assertEqual(len(breakdown.contributions), 3)
        self.assertEqual(breakdown.contributions[0].label, "Item 10")


class DaypartRollupTests(unittest.TestCase):
    def test_hours_fold_into_named_dayparts(self) -> None:
        hours = [
            HourMetrics(hour=9, orders=2, revenue=200.0),
            HourMetrics(hour=13, orders=5, revenue=900.0),
            HourMetrics(hour=20, orders=8, revenue=1600.0),
            HourMetrics(hour=23, orders=1, revenue=150.0),
        ]
        by_name = {row.daypart: row for row in rollup_dayparts(hours)}
        self.assertEqual(by_name["Breakfast"].orders, 2)
        self.assertEqual(by_name["Lunch"].orders, 5)
        self.assertEqual(by_name["Dinner"].orders, 8)
        # 23:00 belongs to the late-night bucket, which wraps midnight.
        self.assertEqual(by_name["Late night"].orders, 1)
        self.assertAlmostEqual(sum(row.revenue for row in rollup_dayparts(hours)), 2850.0)


class FillDailySeriesTests(unittest.TestCase):
    def test_missing_days_become_zeros(self) -> None:
        points = [
            DailyPoint(day=date(2026, 1, 1), orders=10, revenue=1000.0),
            DailyPoint(day=date(2026, 1, 4), orders=5, revenue=500.0),
        ]
        filled = fill_daily_series(points, date(2026, 1, 1), date(2026, 1, 5))
        self.assertEqual(len(filled), 5)
        self.assertEqual([point.orders for point in filled], [10, 0, 0, 5, 0])


class AnomalyDetectionTests(unittest.TestCase):
    def _series(
        self,
        baseline_value: float,
        baseline_days: int,
        evaluation_values: list[float],
        *,
        orders_per_day: int = 20,
        start: date = date(2026, 1, 1),
    ) -> tuple[list[DailyPoint], date]:
        points: list[DailyPoint] = []
        cursor = start
        for index in range(baseline_days):
            # A little variation keeps the MAD non-zero, as real data would.
            wobble = 1.0 if index % 2 else -1.0
            points.append(
                DailyPoint(day=cursor, orders=orders_per_day, revenue=baseline_value + wobble * 50)
            )
            cursor += timedelta(days=1)
        evaluation_start = cursor
        for value in evaluation_values:
            points.append(DailyPoint(day=cursor, orders=orders_per_day, revenue=value))
            cursor += timedelta(days=1)
        return points, evaluation_start

    def test_flags_a_genuine_collapse(self) -> None:
        series, evaluation_start = self._series(10000.0, 28, [10050.0, 2000.0, 9950.0])
        report = detect_anomalies(series, evaluation_start=evaluation_start, z_threshold=3.0)

        self.assertTrue(report.evaluated)
        self.assertEqual(len(report.points), 1)
        self.assertAlmostEqual(report.points[0].value, 2000.0)
        self.assertEqual(report.points[0].direction, "down")

    def test_stable_series_produces_no_anomalies(self) -> None:
        series, evaluation_start = self._series(10000.0, 28, [10020.0, 9980.0, 10010.0])
        report = detect_anomalies(series, evaluation_start=evaluation_start, z_threshold=3.0)
        self.assertTrue(report.evaluated)
        self.assertEqual(report.points, [])

    def test_short_history_is_not_evaluated(self) -> None:
        series, evaluation_start = self._series(10000.0, 5, [1000.0])
        report = detect_anomalies(
            series, evaluation_start=evaluation_start, min_baseline_days=14
        )
        self.assertFalse(report.evaluated)
        self.assertEqual(report.points, [])
        self.assertIn("history", (report.note or "").lower())

    def test_low_volume_restaurant_is_not_alerted(self) -> None:
        # Two orders a day swings wildly by nature. Alerting here would train an
        # owner to ignore the feature entirely.
        series, evaluation_start = self._series(
            400.0, 28, [50.0], orders_per_day=2
        )
        report = detect_anomalies(
            series, evaluation_start=evaluation_start, min_daily_orders=3
        )
        self.assertFalse(report.evaluated)
        self.assertIn("volume", (report.note or "").lower())

    def test_perfectly_flat_baseline_falls_back_to_stdev(self) -> None:
        # A zero MAD would divide by zero; the fallback must stay finite.
        points = [
            DailyPoint(day=date(2026, 1, 1) + timedelta(days=index), orders=20, revenue=1000.0)
            for index in range(20)
        ]
        points.append(DailyPoint(day=date(2026, 1, 21), orders=20, revenue=10.0))
        report = detect_anomalies(points, evaluation_start=date(2026, 1, 21))
        self.assertTrue(report.evaluated)
        # Baseline has no dispersion at all, so no statistically sound call can
        # be made and the layer stays silent rather than guessing.
        self.assertEqual(report.points, [])

    def test_spike_is_flagged_as_up(self) -> None:
        series, evaluation_start = self._series(5000.0, 28, [25000.0])
        report = detect_anomalies(series, evaluation_start=evaluation_start, z_threshold=3.0)
        self.assertTrue(report.evaluated)
        self.assertEqual(report.points[0].direction, "up")
        self.assertEqual(report.points[0].severity, "high")


class PeriodResolutionTests(unittest.TestCase):
    def test_previous_period_is_contiguous_and_equal_length(self) -> None:
        current = build_period(date(2026, 3, 9), date(2026, 3, 15))
        previous = previous_period(current)
        self.assertEqual(previous.end_date, date(2026, 3, 8))
        self.assertEqual(previous.start_date, date(2026, 3, 2))
        self.assertEqual(previous.day_count, current.day_count)

    def test_business_timezone_bounds_are_offset_from_utc(self) -> None:
        # Asia/Kolkata is +05:30, so local midnight on 9 Mar is 18:30 UTC on 8 Mar.
        period = build_period(date(2026, 3, 9), date(2026, 3, 9), timezone_name="Asia/Kolkata")
        self.assertEqual(period.start_at, datetime(2026, 3, 8, 18, 30, tzinfo=UTC))
        self.assertEqual(period.end_at, datetime(2026, 3, 9, 18, 30, tzinfo=UTC))

    def test_explicit_range_is_respected(self) -> None:
        comparison = resolve_period_comparison(
            date_from=date(2026, 3, 9), date_to=date(2026, 3, 15)
        )
        self.assertEqual(comparison.current.start_date, date(2026, 3, 9))
        self.assertEqual(comparison.previous.start_date, date(2026, 3, 2))
        self.assertTrue(comparison.weekday_aligned)

    def test_reversed_dates_are_swapped(self) -> None:
        comparison = resolve_period_comparison(
            date_from=date(2026, 3, 15), date_to=date(2026, 3, 9)
        )
        self.assertEqual(comparison.current.start_date, date(2026, 3, 9))
        self.assertEqual(comparison.current.end_date, date(2026, 3, 15))

    def test_partial_weeks_are_flagged_as_not_weekday_aligned(self) -> None:
        comparison = resolve_period_comparison(
            date_from=date(2026, 3, 9), date_to=date(2026, 3, 13)
        )
        self.assertFalse(comparison.weekday_aligned)

    def test_default_window_ends_today(self) -> None:
        """The window an owner means when they say "the last 7 days".

        It used to end on the last complete day, so on the 19th a 7-day window
        answered for the 12th to the 18th — a week the owner had not asked
        about, and one that left out the day they opened the page to look at.
        """

        from app.services.insights.periods import local_today

        today = local_today()
        with SettingsOverride(insights_default_window_days=7):
            comparison = resolve_period_comparison()

        self.assertEqual(comparison.current.end_date, today)
        self.assertEqual(comparison.current.start_date, today - timedelta(days=6))
        self.assertEqual(comparison.current.day_count, 7)
        # Today is in progress, and every caller is told so rather than having
        # the day quietly dropped.
        self.assertTrue(comparison.includes_partial_day)

    def test_the_previous_window_ends_the_day_before_this_one(self) -> None:
        # On 19 Aug: 13-19 Aug against 6-12 Aug. Equal lengths, no gap, no
        # overlap — otherwise the comparison is not like-for-like.
        from app.services.insights.periods import local_today

        today = local_today()
        with SettingsOverride(insights_default_window_days=7):
            comparison = resolve_period_comparison()

        self.assertEqual(
            comparison.previous.end_date, comparison.current.start_date - timedelta(days=1)
        )
        self.assertEqual(comparison.previous.start_date, today - timedelta(days=13))
        self.assertEqual(comparison.previous.day_count, comparison.current.day_count)

    def test_longer_windows_follow_the_same_rule(self) -> None:
        from app.services.insights.periods import local_today

        today = local_today()
        for days in (30, 90):
            with self.subTest(days=days):
                comparison = resolve_period_comparison(window_days=days)

                self.assertEqual(comparison.current.end_date, today)
                self.assertEqual(
                    comparison.current.start_date, today - timedelta(days=days - 1)
                )
                self.assertEqual(comparison.current.day_count, days)
                self.assertEqual(
                    comparison.previous.end_date, today - timedelta(days=days)
                )
                self.assertEqual(comparison.previous.day_count, days)

    def test_window_running_into_today_is_flagged(self) -> None:
        from app.services.insights.periods import local_today

        today = local_today()
        comparison = resolve_period_comparison(
            date_from=today - timedelta(days=6), date_to=today
        )
        self.assertTrue(comparison.includes_partial_day)

    def test_oversized_window_is_rejected(self) -> None:
        with SettingsOverride(insights_max_window_days=90):
            with self.assertRaises(HTTPException) as raised:
                resolve_period_comparison(
                    date_from=date(2025, 1, 1), date_to=date(2026, 1, 1)
                )
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
