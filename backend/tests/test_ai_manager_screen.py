"""The AI Manager screen: one period, honest percentages, useful severity.

These cover the things the screen got wrong rather than the things the maths
got wrong — the arithmetic was already exact. What was broken was a stale
briefing presented as today's headline, four different windows on one screen,
percentages measured against near-empty periods, and a severity column where
every row said LOW.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.services.insights.rules import (
    change_phrase,
    movement_label,
    percent_is_misleading,
    plain_percent,
    share_phrase,
    _severity_floors,
)

settings = get_settings()


class MisleadingPercentageTests(unittest.TestCase):
    """A percentage off a near-empty period describes the quiet week."""

    def test_a_zero_baseline_is_always_misleading(self) -> None:
        # There is nothing to have grown from, so any percentage is invented.
        self.assertTrue(percent_is_misleading(0.0, 100.0))

    def test_a_huge_swing_off_a_tiny_base_is_misleading(self) -> None:
        # The real case: ₹44 one week, ₹1,304 the next, reported as +2859.6%.
        self.assertTrue(percent_is_misleading(44.07, 2859.6))

    def test_an_ordinary_movement_keeps_its_percentage(self) -> None:
        self.assertFalse(percent_is_misleading(1368.0, 95.2))
        self.assertFalse(percent_is_misleading(1000.0, -28.6))

    def test_no_percentage_at_all_is_not_misleading(self) -> None:
        self.assertFalse(percent_is_misleading(100.0, None))

    def test_the_money_is_quoted_where_the_percentage_would_lie(self) -> None:
        self.assertEqual(movement_label(44.07, 2859.6, 1260.23), "₹1,260")
        self.assertIn("%", movement_label(1368.0, 95.2, 1302.0))

    def test_the_body_and_the_title_agree(self) -> None:
        # Both go through the same rule, so a headline cannot drop a percentage
        # that the sentence below it still prints.
        self.assertNotIn("%", change_phrase(44.07, 1260.23, 2859.6))
        self.assertIn("%", change_phrase(1368.0, 1302.0, 95.2))


class ContributionShareTests(unittest.TestCase):
    """Signed shares are correct arithmetic and unreadable prose."""

    def test_a_share_above_one_hundred_is_described_not_printed(self) -> None:
        # "+249.5% contribution to the overall change" is exactly right and
        # reads to an owner like a broken number.
        phrase = share_phrase(249.5)
        self.assertNotIn("%", phrase)
        self.assertIn("whole", phrase)

    def test_direction_survives(self) -> None:
        # A line moving against the change must never read as having driven it.
        self.assertEqual(share_phrase(-68.2), "moving against the overall change")

    def test_sizes_are_distinguished(self) -> None:
        self.assertIn("most", share_phrase(60.0))
        self.assertIn("large", share_phrase(30.0))
        self.assertIn("small", share_phrase(5.0))


class SeverityScaleTests(unittest.TestCase):
    """Severity has to mean something for a small restaurant too."""

    def test_a_small_restaurant_can_exceed_low(self) -> None:
        # A quarter's revenue of ₹2,670 could never clear a flat ₹2,000 floor,
        # so every finding it ever produced was LOW and the column carried no
        # information at all.
        medium, high = _severity_floors(2670.0)

        self.assertLess(medium, float(settings.insight_severity_medium_floor))
        self.assertLess(high, float(settings.insight_severity_high_floor))
        self.assertLess(medium, high)

    def test_a_large_restaurant_still_needs_real_money(self) -> None:
        # The flat floor wins where it is the lower of the two, so scale cannot
        # make a trivial movement loud.
        medium, high = _severity_floors(10_000_000.0)

        self.assertEqual(medium, float(settings.insight_severity_medium_floor))
        self.assertEqual(high, float(settings.insight_severity_high_floor))

    def test_no_revenue_leaves_the_flat_floors(self) -> None:
        medium, high = _severity_floors(None)

        self.assertEqual(medium, float(settings.insight_severity_medium_floor))
        self.assertEqual(high, float(settings.insight_severity_high_floor))


class DiscountFormattingTests(unittest.TestCase):
    def test_a_discount_reads_as_a_person_writes_it(self) -> None:
        # "Promote Pad Thai Veg at 10.0% off" reads like machine output.
        self.assertEqual(plain_percent(10.0), "10%")
        self.assertEqual(plain_percent(20.0), "20%")

    def test_a_real_fraction_is_kept(self) -> None:
        self.assertEqual(plain_percent(12.5), "12.5%")


if __name__ == "__main__":
    unittest.main()


class TodayInclusiveWindowTests(unittest.TestCase):
    """Windows run up to and including today.

    A window ending on the last complete day answered for a period the owner
    had not asked about — most visibly first thing in the morning, when today's
    trade is the thing they opened the page to look at.
    """

    def _frozen(self, day: date):
        """Resolve windows as if today were `day`, so the maths is checkable."""

        from unittest.mock import patch
        import app.services.insights.periods as periods

        return patch.object(periods, "local_today", return_value=day)

    def test_the_reported_example(self) -> None:
        # 7 days selected on 19 Aug 2026 must be 13-19 Aug, against 6-12 Aug.
        from app.services.insights.periods import resolve_period_comparison

        with self._frozen(date(2026, 8, 19)):
            comparison = resolve_period_comparison(window_days=7)

        self.assertEqual(comparison.current.start_date, date(2026, 8, 13))
        self.assertEqual(comparison.current.end_date, date(2026, 8, 19))
        self.assertEqual(comparison.previous.start_date, date(2026, 8, 6))
        self.assertEqual(comparison.previous.end_date, date(2026, 8, 12))

    def test_thirty_and_ninety_follow_the_same_rule(self) -> None:
        from app.services.insights.periods import resolve_period_comparison

        with self._frozen(date(2026, 8, 19)):
            month = resolve_period_comparison(window_days=30)
            quarter = resolve_period_comparison(window_days=90)

        self.assertEqual(month.current.start_date, date(2026, 7, 21))
        self.assertEqual(month.current.end_date, date(2026, 8, 19))
        self.assertEqual(month.previous.start_date, date(2026, 6, 21))
        self.assertEqual(month.previous.end_date, date(2026, 7, 20))

        self.assertEqual(quarter.current.start_date, date(2026, 5, 22))
        self.assertEqual(quarter.current.end_date, date(2026, 8, 19))
        self.assertEqual(quarter.previous.end_date, date(2026, 5, 21))

    def test_the_two_windows_abut_without_gap_or_overlap(self) -> None:
        # A gap loses a day of trade from the comparison; an overlap counts one
        # twice. Either makes the delta wrong in a way nothing else reveals.
        from app.services.insights.periods import resolve_period_comparison

        for days in (7, 30, 90):
            with self.subTest(days=days):
                with self._frozen(date(2026, 8, 19)):
                    comparison = resolve_period_comparison(window_days=days)

                self.assertEqual(
                    comparison.previous.end_date + timedelta(days=1),
                    comparison.current.start_date,
                )
                self.assertEqual(
                    comparison.current.day_count, comparison.previous.day_count
                )

    def test_a_window_ending_today_is_flagged_as_partial(self) -> None:
        # Today counts, but it is a day in progress. Including it silently would
        # read as a collapse in trade every morning.
        from app.services.insights.periods import resolve_period_comparison

        with self._frozen(date(2026, 8, 19)):
            comparison = resolve_period_comparison(window_days=7)

        self.assertTrue(comparison.includes_partial_day)

    def test_an_explicit_past_range_is_left_exactly_as_asked(self) -> None:
        # Today-inclusive is a default, not a rewrite: a named range stays put
        # and is not flagged as partial.
        from app.services.insights.periods import resolve_period_comparison

        with self._frozen(date(2026, 8, 19)):
            comparison = resolve_period_comparison(
                date_from=date(2026, 6, 1), date_to=date(2026, 6, 15)
            )

        self.assertEqual(comparison.current.start_date, date(2026, 6, 1))
        self.assertEqual(comparison.current.end_date, date(2026, 6, 15))
        self.assertEqual(comparison.previous.end_date, date(2026, 5, 31))
        self.assertFalse(comparison.includes_partial_day)

    def test_a_leap_day_does_not_shift_the_boundary(self) -> None:
        # Dates are calculated, never assembled from month lengths.
        from app.services.insights.periods import resolve_period_comparison

        with self._frozen(date(2028, 3, 1)):
            comparison = resolve_period_comparison(window_days=7)

        self.assertEqual(comparison.current.start_date, date(2028, 2, 24))
        self.assertEqual(comparison.current.end_date, date(2028, 3, 1))
        self.assertEqual(comparison.previous.end_date, date(2028, 2, 23))


class TodayInclusiveChatTests(unittest.TestCase):
    """The same rule where the chat resolves a period from the question."""

    def _frozen(self, day: date):
        from unittest.mock import patch
        import app.services.insights.router as router

        return patch.object(router, "local_today", return_value=day)

    def test_this_week_runs_to_today(self) -> None:
        # Wednesday 19 Aug 2026: Monday the 17th through today.
        from app.services.insights.router import parse_period

        with self._frozen(date(2026, 8, 19)):
            params = parse_period("how are sales this week")

        self.assertEqual(params.date_from, date(2026, 8, 17))
        self.assertEqual(params.date_to, date(2026, 8, 19))

    def test_this_week_on_a_monday_is_that_monday(self) -> None:
        # It used to resolve to an empty or backwards range here.
        from app.services.insights.router import parse_period

        with self._frozen(date(2026, 8, 17)):
            params = parse_period("this week")

        self.assertEqual(params.date_from, date(2026, 8, 17))
        self.assertEqual(params.date_to, date(2026, 8, 17))

    def test_last_week_is_still_the_previous_calendar_week(self) -> None:
        from app.services.insights.router import parse_period

        with self._frozen(date(2026, 8, 19)):
            params = parse_period("how did we do last week")

        self.assertEqual(params.date_from, date(2026, 8, 10))
        self.assertEqual(params.date_to, date(2026, 8, 16))

    def test_an_unspecified_period_is_ninety_days_ending_today(self) -> None:
        from app.services.insights.periods import resolve_period_comparison
        from app.services.insights.router import parse_period

        with self._frozen(date(2026, 8, 19)):
            params = parse_period("which dish sells best")

        self.assertEqual(params.window_days, 90)

        import app.services.insights.periods as periods
        from unittest.mock import patch

        with patch.object(periods, "local_today", return_value=date(2026, 8, 19)):
            comparison = resolve_period_comparison(window_days=params.window_days)

        self.assertEqual(comparison.current.end_date, date(2026, 8, 19))
