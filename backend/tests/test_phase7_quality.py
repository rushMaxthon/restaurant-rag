"""Regressions for the nine issues found in the first real controlled run.

Every test here exists because the system produced something misleading on real
data — not because a function threw. They are grouped by the issue number from
that run so a future change that reintroduces one is obvious.

The common thread: a number that is *arithmetically correct* can still tell an
owner something false. These lock down the wording and the gating as much as the
maths.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401  (imported first to settle import order)
from app.config import get_settings
from app.models.enums import OwnerInsightSeverity, OwnerInsightType
from app.services.insights.diagnostics import build_contributions
from app.services.insights.facts import FactPack
from app.services.insights.narrator import _revenue_headline, _template_narration
from app.services.insights.rules import (
    CandidateInsight,
    _drop_duplicate_category_findings,
    _severity_for,
    evaluate_rules,
    is_material_change,
    signed_percent,
)
from tests.test_insights_rules import (
    SettingsOverride,
    breakdown,
    contribution,
    delta,
    snapshot,
)

settings = get_settings()


def headline_pack(
    *,
    revenue_current: float,
    revenue_previous: float,
    orders_current: int,
    orders_previous: int,
    aov_current: float = 0.0,
) -> FactPack:
    def metric(current: float, previous: float) -> dict:
        change = current - previous
        percent_change = (change / abs(previous) * 100.0) if previous else None
        return {
            "current": current,
            "previous": previous,
            "change": change,
            "percent_change": percent_change,
            "direction": "up" if change > 0 else "down" if change < 0 else "flat",
        }

    return FactPack(
        period_label="15 Jul - 13 Aug 2026",
        previous_period_label="15 Jun - 14 Jul 2026",
        timezone="Asia/Kolkata",
        headline={
            "gross_revenue": metric(revenue_current, revenue_previous),
            "orders": metric(orders_current, orders_previous),
            "average_order_value": metric(aov_current, 0.0),
        },
    )


class Issue1RevenueHeadlineTests(unittest.TestCase):
    """Revenue rising while orders fall is not growth, and must not read as it."""

    def test_the_exact_case_from_the_real_run(self) -> None:
        # Bangkok Bowl: revenue +35.9% while orders halved. The old headline
        # said "Revenue is up 35.9%" and nothing else.
        headline, opening = _revenue_headline(
            headline_pack(
                revenue_current=739.49,
                revenue_previous=544.15,
                orders_current=9,
                orders_previous=19,
                aov_current=82.17,
            )
        )
        self.assertIn("Orders are down", headline)
        self.assertNotEqual(headline, "Revenue is up 35.9%")
        self.assertIn("fewer customers", opening)

    def test_material_revenue_rise_with_falling_orders_states_both(self) -> None:
        headline, opening = _revenue_headline(
            headline_pack(
                revenue_current=20000,
                revenue_previous=10000,
                orders_current=80,
                orders_previous=200,
                aov_current=250,
            )
        )
        self.assertIn("Revenue is up", headline)
        self.assertIn("orders are down", headline)
        self.assertIn("fewer customers", opening)

    def test_genuine_growth_still_reads_as_growth(self) -> None:
        # The fix must not make every positive period sound like a problem.
        headline, _ = _revenue_headline(
            headline_pack(
                revenue_current=20000,
                revenue_previous=10000,
                orders_current=200,
                orders_previous=120,
                aov_current=100,
            )
        )
        self.assertEqual(headline, "Revenue is up 100.0%")

    def test_falling_orders_are_never_hidden_by_flat_revenue(self) -> None:
        # The failure mode introduced by fixing issue 3 in isolation: an
        # immaterial revenue move must not bury a halving of order count.
        headline, _ = _revenue_headline(
            headline_pack(
                revenue_current=560,
                revenue_previous=544,
                orders_current=9,
                orders_previous=19,
                aov_current=62,
            )
        )
        self.assertIn("Orders are down", headline)


class Issue2ContributionSignTests(unittest.TestCase):
    """A negative contributor must never be shown as a positive contribution."""

    def test_signed_percent_keeps_direction(self) -> None:
        self.assertEqual(signed_percent(-68.2), "-68.2%")
        self.assertEqual(signed_percent(92.9), "+92.9%")

    def test_item_body_says_when_a_line_moved_against_the_change(self) -> None:
        # The real run rendered a -68.2% share as "68.2% of the overall change",
        # making a dish that dragged revenue down read as if it drove it up.
        rows = [contribution("salad", "Thai Mango Salad", 0.0, 143.84, share=-68.2)]
        result = evaluate_rules(
            snapshot(breakdowns=[breakdown("item", 210.86, rows, basis="item_revenue")])
        )
        declines = [row for row in result if row.insight_type == OwnerInsightType.ITEM_DECLINE]
        self.assertTrue(declines)
        # The share is described rather than printed — "+249.5% contribution to
        # the overall change" is correct arithmetic and unreadable — but the
        # direction still has to survive, or a line that moved against the
        # change reads as though it caused it.
        self.assertIn("moving against the overall change", declines[0].body)
        self.assertNotIn("accounts for", declines[0].body)


class Issue3MaterialityTests(unittest.TestCase):
    """One definition of "big enough", shared by the rules and the briefing."""

    def test_small_absolute_move_is_immaterial(self) -> None:
        with SettingsOverride(
            insight_revenue_change_percent=8.0, insight_revenue_change_minimum=1000.0
        ):
            self.assertFalse(is_material_change(195.0, 35.9))

    def test_small_percentage_move_is_immaterial(self) -> None:
        with SettingsOverride(
            insight_revenue_change_percent=8.0, insight_revenue_change_minimum=1000.0
        ):
            self.assertFalse(is_material_change(5000.0, 1.0))

    def test_headline_makes_no_claim_the_rules_would_reject(self) -> None:
        # ₹195 on ₹544 fails the money gate, so no rule fires — and the
        # briefing must not announce it either.
        with SettingsOverride(
            insight_revenue_change_percent=8.0, insight_revenue_change_minimum=1000.0
        ):
            headline, _ = _revenue_headline(
                headline_pack(
                    revenue_current=739.49,
                    revenue_previous=544.15,
                    orders_current=19,
                    orders_previous=19,
                )
            )
        self.assertIn("No major change", headline)
        self.assertNotIn("35.9%", headline)

    def test_rules_and_headline_agree_on_the_same_movement(self) -> None:
        with SettingsOverride(
            insight_revenue_change_percent=8.0, insight_revenue_change_minimum=1000.0
        ):
            fired = evaluate_rules(
                snapshot(headline=[delta("gross_revenue", 739.49, 544.15)])
            )
            headline, _ = _revenue_headline(
                headline_pack(
                    revenue_current=739.49,
                    revenue_previous=544.15,
                    orders_current=19,
                    orders_previous=19,
                )
            )
        revenue_rules = [
            row
            for row in fired
            if row.insight_type
            in {OwnerInsightType.REVENUE_DROP, OwnerInsightType.REVENUE_SPIKE}
        ]
        self.assertEqual(revenue_rules, [])
        self.assertIn("No major change", headline)


class Issue4ReconciliationTests(unittest.TestCase):
    """Listed shares must reconcile against the parent change."""

    def test_filtered_children_are_counted_and_labelled(self) -> None:
        with SettingsOverride(insights_min_orders_for_contribution=3):
            rows_current = [
                contribution("big", "Big Seller", 1000.0, 500.0, current_orders=40),
                # Two orders is below the contribution floor, so this real ₹300
                # of movement is dropped from the listed shares.
                contribution("tiny", "Rare Dish", 300.0, 0.0, current_orders=2, previous_orders=2),
            ]
            result = build_contributions(
                "item",
                basis="item_revenue",
                current_rows=rows_current,
                previous_rows=[],
                key_fn=lambda row: row.key,
                label_fn=lambda row: row.label,
                value_fn=lambda row: row.current,
                orders_fn=lambda row: row.current_orders,
                parent_change=500.0,
            )
        self.assertEqual(result.excluded_children, 1)
        self.assertNotEqual(result.excluded_change, 0.0)
        self.assertIn("not listed", result.note or "")

    def test_children_beyond_the_display_limit_are_counted(self) -> None:
        rows = [
            contribution(f"i{index}", f"Item {index}", float(index) * 100, 0.0, current_orders=10)
            for index in range(1, 8)
        ]
        result = build_contributions(
            "item",
            basis="item_revenue",
            current_rows=rows,
            previous_rows=[],
            key_fn=lambda row: row.key,
            label_fn=lambda row: row.label,
            value_fn=lambda row: row.current,
            orders_fn=lambda row: row.current_orders,
            limit=3,
        )
        self.assertEqual(len(result.contributions), 3)
        self.assertEqual(result.excluded_children, 4)

    def test_nothing_excluded_means_no_note(self) -> None:
        rows = [contribution("a", "A", 100.0, 0.0, current_orders=10)]
        result = build_contributions(
            "item",
            basis="item_revenue",
            current_rows=rows,
            previous_rows=[],
            key_fn=lambda row: row.key,
            label_fn=lambda row: row.label,
            value_fn=lambda row: row.current,
            orders_fn=lambda row: row.current_orders,
        )
        self.assertEqual(result.excluded_children, 0)
        self.assertIsNone(result.note)


class Issue5DuplicateInsightTests(unittest.TestCase):
    """A category explained entirely by one dish is one finding, not two."""

    def _candidate(self, insight_type, change, subject):
        return CandidateInsight(
            insight_type=insight_type,
            severity=OwnerInsightSeverity.MEDIUM,
            score=Decimal("1"),
            title=subject,
            body="",
            dedupe_key=f"{insight_type.value}:{subject}",
            subject=subject,
            facts={"absolute_change": change},
        )

    def test_category_matching_one_item_is_dropped(self) -> None:
        # The real run produced "Salads is down ₹144" beside "Thai Mango Salad
        # is down ₹144" — the same event twice.
        kept = _drop_duplicate_category_findings(
            [
                self._candidate(OwnerInsightType.ITEM_DECLINE, -143.84, "Thai Mango Salad"),
                self._candidate(OwnerInsightType.CATEGORY_DECLINE, -143.84, "Salads"),
            ]
        )
        self.assertEqual([row.insight_type for row in kept], [OwnerInsightType.ITEM_DECLINE])

    def test_category_larger_than_its_biggest_item_survives(self) -> None:
        # A broad category decline is a different finding and must be kept.
        kept = _drop_duplicate_category_findings(
            [
                self._candidate(OwnerInsightType.ITEM_DECLINE, -143.84, "Thai Mango Salad"),
                self._candidate(OwnerInsightType.CATEGORY_DECLINE, -900.0, "Mains"),
            ]
        )
        self.assertEqual(len(kept), 2)

    def test_category_alone_is_untouched(self) -> None:
        kept = _drop_duplicate_category_findings(
            [self._candidate(OwnerInsightType.CATEGORY_DECLINE, -500.0, "Salads")]
        )
        self.assertEqual(len(kept), 1)


class Issue6SeverityTests(unittest.TestCase):
    """Severity is capped by the money involved, not just the share."""

    def test_the_exact_case_from_the_real_run(self) -> None:
        # "Lunch trade has weakened" was HIGH on a ₹377 move.
        with SettingsOverride(
            insight_severity_medium_floor=Decimal("2000.00"),
            insight_severity_high_floor=Decimal("5000.00"),
        ):
            severity = _severity_for(100.0, 25.0, money_amount=377.0)
        self.assertEqual(severity, OwnerInsightSeverity.LOW)

    def test_large_movements_still_reach_high(self) -> None:
        with SettingsOverride(
            insight_severity_medium_floor=Decimal("2000.00"),
            insight_severity_high_floor=Decimal("5000.00"),
        ):
            self.assertEqual(
                _severity_for(100.0, 25.0, money_amount=9000.0), OwnerInsightSeverity.HIGH
            )

    def test_mid_sized_movements_cap_at_medium(self) -> None:
        with SettingsOverride(
            insight_severity_medium_floor=Decimal("2000.00"),
            insight_severity_high_floor=Decimal("5000.00"),
        ):
            self.assertEqual(
                _severity_for(100.0, 25.0, money_amount=3000.0), OwnerInsightSeverity.MEDIUM
            )

    def test_the_money_floor_never_raises_severity(self) -> None:
        # A large sum with a small share stays low: the cap is a ceiling only.
        self.assertEqual(
            _severity_for(10.0, 25.0, money_amount=50000.0), OwnerInsightSeverity.LOW
        )

    def test_daypart_severity_respects_the_floor_end_to_end(self) -> None:
        rows = [contribution("lunch", "Lunch", 0.0, 377.0, share=100.0, current_orders=0,
                             previous_orders=14)]
        with SettingsOverride(
            insight_daypart_contribution_percent=30.0,
            insight_severity_medium_floor=Decimal("2000.00"),
        ):
            result = evaluate_rules(snapshot(breakdowns=[breakdown("daypart", -377.0, rows)]))
        dayparts = [
            row for row in result if row.insight_type == OwnerInsightType.DAYPART_WEAKNESS
        ]
        self.assertTrue(dayparts)
        self.assertEqual(dayparts[0].severity, OwnerInsightSeverity.LOW)


class Issue7AdaptiveWindowTests(unittest.TestCase):
    """A sparse restaurant must not silently produce nothing forever."""

    def test_ladder_is_parsed_and_ordered(self) -> None:
        with SettingsOverride(insights_adaptive_window_days="30,7,14"):
            self.assertEqual(settings.insights_adaptive_window_days_list, [7, 14, 30])

    def test_absurd_windows_are_dropped(self) -> None:
        with SettingsOverride(
            insights_adaptive_window_days="7,0,-3,99999,abc", insights_max_window_days=180
        ):
            self.assertEqual(settings.insights_adaptive_window_days_list, [7])

    def test_empty_configuration_falls_back_to_the_default(self) -> None:
        with SettingsOverride(
            insights_adaptive_window_days="", insights_default_window_days=7
        ):
            self.assertEqual(settings.insights_adaptive_window_days_list, [7])

    def test_widening_does_not_weaken_the_materiality_gates(self) -> None:
        # The fallback may look at more days. It must never lower the bar for
        # what counts as worth reporting.
        with SettingsOverride(
            insight_revenue_change_percent=8.0, insight_revenue_change_minimum=1000.0
        ):
            self.assertFalse(is_material_change(195.0, 35.9))


class Issue9RootCauseHonestyTests(unittest.TestCase):
    """No events means no explanation — never an invented one."""

    def test_absent_history_yields_no_cause(self) -> None:
        from app.services.insights.root_cause import explain_item_decline

        self.assertIsNone(explain_item_decline(subject="Thai Mango Salad", stockouts={}))

    def test_a_dish_without_its_own_stockout_is_not_explained(self) -> None:
        from app.services.insights.root_cause import StockoutWindow, explain_item_decline

        stockouts = {
            "margherita pizza": StockoutWindow(
                dish_key="margherita pizza",
                item_name="Margherita Pizza",
                hours_unavailable=6.0,
                switch_offs=1,
            )
        }
        self.assertIsNone(explain_item_decline(subject="Pasta Alfredo", stockouts=stockouts))

    def test_candidates_default_to_no_root_cause(self) -> None:
        result = evaluate_rules(
            snapshot(headline=[delta("gross_revenue", 5000.0, 20000.0)])
        )
        self.assertTrue(result)
        self.assertTrue(all(row.root_cause is None for row in result))


class NarrativeIntegrationTests(unittest.TestCase):
    """The whole template narrative, on the shape of data that misled before."""

    def test_briefing_does_not_claim_growth_when_orders_collapsed(self) -> None:
        pack = headline_pack(
            revenue_current=739.49,
            revenue_previous=544.15,
            orders_current=9,
            orders_previous=19,
            aov_current=82.17,
        )
        narration = _template_narration(pack, [], reason=None)
        lowered = narration.narrative.lower()

        self.assertIn("orders", narration.headline.lower())
        self.assertNotIn("revenue is up 35.9%", narration.headline.lower())
        self.assertIn("fewer customers", lowered)


if __name__ == "__main__":
    unittest.main()
