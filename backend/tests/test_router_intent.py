"""Routing regressions for intent that was previously mis-classified.

The bug these exist for: asking *"which items are declining and what promotion
should I run for them?"* returned an offer ROI report. The word "promotion"
matched a bare noun pattern on `offer_performance`, which sat above both
`item_performance` and `recommendations` in the ordered list — so a request for
advice was answered with a performance report about an unrelated offer.

Two lessons are encoded here:

* A pattern must carry *intent*, not just a topic noun. "Promotion" appears in
  both "how are my promotions doing" and "what promotion should I run", and
  those are opposite questions.
* A compound question must not be silently answered by half of itself.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401  (imported first to settle import order)
from app.services.insights.router import route_question
from app.services.insights.router import STRUCTURALLY_ROUTED_SKILLS
from app.services.insights.skills import SKILL_NAMES


def skill_for(question: str) -> str:
    return route_question(question, allow_model=False).skill


class ReportedBugTests(unittest.TestCase):
    """The exact question that misrouted, and its close variants."""

    def test_the_reported_question_no_longer_returns_offer_roi(self) -> None:
        question = (
            "Which items are declining in sales and what promotion should I run for them?"
        )
        routed = skill_for(question)
        self.assertEqual(routed, "item_promotion_advice")
        self.assertNotEqual(routed, "offer_performance")

    def test_compound_variants_all_reach_the_combined_answer(self) -> None:
        for question in (
            "which declining dishes should I offer a discount on",
            "what promotion should I run for my falling dishes",
            "which items are dropping and what offer would help",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "item_promotion_advice")

    def test_plural_dishes_is_matched(self) -> None:
        # `dishs?` does not match "dishes", which sent a compound question to a
        # half-answer until the plural was handled.
        self.assertEqual(
            skill_for("which declining dishes should I discount"), "item_promotion_advice"
        )


class RequestedVerificationTests(unittest.TestCase):
    """The three cases named in the bug report."""

    def test_which_items_are_declining_is_item_performance(self) -> None:
        for question in (
            "Which items are declining?",
            "which dishes are falling",
            "show me my worst sellers",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "item_performance")

    def test_which_items_should_i_promote_is_recommendations(self) -> None:
        # No decline mentioned, so this is purely a request for advice.
        for question in (
            "Which items should I promote?",
            "what offer should I run",
            "what promotion should I run",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "recommendations")

    def test_did_my_offer_work_is_action_outcomes(self) -> None:
        for question in ("Did my offer work?", "did it work", "was it worth it"):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "action_outcomes")


class IntentSeparationTests(unittest.TestCase):
    """Topic nouns alone must not decide the analysis."""

    def test_promotion_performance_still_reaches_offer_performance(self) -> None:
        # The fix must not overcorrect: genuine performance questions about
        # promotions still belong to the ROI report.
        for question in (
            "How are my promotions doing?",
            "did my offers work",
            "are my discounts worth it",
            "show me offer performance",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "offer_performance")

    def test_advice_and_performance_are_not_confused(self) -> None:
        advice = skill_for("what promotion should I run")
        performance = skill_for("how are my promotions performing")
        self.assertNotEqual(advice, performance)
        self.assertEqual(advice, "recommendations")
        self.assertEqual(performance, "offer_performance")


class NoRegressionTests(unittest.TestCase):
    """Everything that routed correctly before must still route correctly."""

    def test_unrelated_intents_are_unaffected(self) -> None:
        for question, expected in (
            ("what is my best selling dish", "item_performance"),
            ("why are sales down", "revenue_diagnosis"),
            ("how much revenue last week", "metric_lookup"),
            ("when am I busiest", "time_patterns"),
            ("am I losing repeat customers", "customer_retention"),
            ("how can I increase sales", "recommendations"),
            ("give me a summary", "briefing_recall"),
            ("why were orders cancelled", "cancellation_reasons"),
            ("how long do orders take to be accepted", "order_operations"),
            ("what do my reviews say", "unsupported"),
            ("how much stock did I waste", "unsupported"),
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), expected)

    def test_every_skill_is_still_reachable(self) -> None:
        reached = {
            skill_for(question)
            for question in (
                "why are sales down",
                "how much revenue last week",
                "best selling dish",
                "when am I busiest",
                "am I losing repeat customers",
                "did my offers work",
                "how can I increase sales",
                "give me a summary",
                "why were orders cancelled",
                "how long do orders take to be accepted",
                "did my offer work",
                "which items are declining and what promotion should I run",
                "what do my reviews say",
            )
        }
        self.assertEqual(reached, set(SKILL_NAMES) - STRUCTURALLY_ROUTED_SKILLS)


if __name__ == "__main__":
    unittest.main()
