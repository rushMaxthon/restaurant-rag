"""Multi-part owner questions: decomposition, composition, and coverage.

A question asking for four things must not be answered with the first one that
matched a pattern. These tests cover the decomposition (which parts a question
asks for), the guard against over-triggering on single-intent questions, and the
rule that an unanswerable part is named rather than silently dropped.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import unittest

from app.services.insights.multipart import PARTS_BY_KEY, decompose
from app.services.insights.router import STRUCTURALLY_ROUTED_SKILLS, route_with_rules
from app.services.insights.skills import SKILLS


class DecompositionTests(unittest.TestCase):
    def keys(self, question: str) -> tuple[str, ...]:
        return tuple(part.key for part in decompose(question))

    def test_the_reported_question_finds_all_four_parts(self) -> None:
        # The question that exposed this: it was answered with customer-group
        # data alone, which is a quarter of what was asked.
        keys = self.keys(
            "Give me an analysis of last month's sales. How much revenue did I "
            "make, how many orders did I receive, which item was ordered the "
            "most, and how many new customers did I get?"
        )

        self.assertEqual(keys, ("revenue", "orders", "top_item", "new_customers"))

    def test_the_same_request_phrased_as_a_list(self) -> None:
        # Nothing is keyed to the wording of one question.
        keys = self.keys(
            "How did last month perform? Give me revenue, orders, "
            "best-selling item, and new customers."
        )

        self.assertEqual(keys, ("revenue", "orders", "top_item", "new_customers"))

    def test_other_combinations_compose_too(self) -> None:
        cases = {
            "show me revenue and cancellations for last week": ("revenue", "cancellations"),
            "what is my average order value, and when am I busiest?": (
                "average_order_value",
                "busiest_time",
            ),
            "give me orders and my best selling dish": ("orders", "top_item"),
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(self.keys(question), expected)

    # -- the guard against over-triggering ---------------------------------

    def test_single_intent_questions_are_left_alone(self) -> None:
        # These mention one thing, or mention two without asking for both. A
        # decomposition here would replace a good single answer with a worse
        # compound one.
        for question in (
            "why are my sales down",
            "which dish sells best",
            "how many orders did I get",
            "when am I busiest",
            "why are orders being cancelled",
            "what is my average order value",
        ):
            with self.subTest(question=question):
                self.assertEqual(decompose(question), ())

    def test_a_list_of_one_thing_is_not_multi_part(self) -> None:
        # Enumeration alone is not enough — there has to be more than one part.
        self.assertEqual(decompose("give me revenue, please, for last month"), ())

    def test_ordered_the_most_is_not_an_order_count(self) -> None:
        # "ordered" must not register as "orders": the word-boundary match is
        # what keeps the best-seller question from also requesting a count.
        self.assertEqual(
            self.keys("which item was ordered the most, and what is my revenue"),
            ("revenue", "top_item"),
        )

    def test_parts_are_capped(self) -> None:
        from app.services.insights.multipart import MAX_PARTS

        keys = self.keys(
            "give me revenue, orders, best selling item, new customers, "
            "average order value, cancellations, and when I am busiest"
        )

        self.assertLessEqual(len(keys), MAX_PARTS)

    # -- routing -----------------------------------------------------------

    def test_a_multi_part_question_routes_to_the_composer(self) -> None:
        routed = route_with_rules(
            "How much revenue did I make, how many orders did I receive, and "
            "which item was ordered the most?"
        )

        self.assertIsNotNone(routed)
        self.assertEqual(routed.skill, "multi_part")
        self.assertEqual(routed.params.parts, ("revenue", "orders", "top_item"))

    def test_a_refusal_still_wins_over_composition(self) -> None:
        # An unsupported topic must be refused, not composed around. Profit is
        # not recorded anywhere, so this is a refusal however it is phrased.
        routed = route_with_rules("what was my profit, and my revenue, last month?")

        self.assertIsNotNone(routed)
        self.assertEqual(routed.skill, "unsupported")

    def test_the_period_is_parsed_for_the_whole_question(self) -> None:
        routed = route_with_rules("last month, give me revenue and orders")

        self.assertEqual(routed.params.window_days, 30)

    def test_the_planner_can_never_choose_the_composer(self) -> None:
        # Its parts come from the question text, so a planner naming it would
        # produce a composition of nothing.
        self.assertIn("multi_part", STRUCTURALLY_ROUTED_SKILLS)

    def test_every_part_names_a_real_skill(self) -> None:
        for key, part in PARTS_BY_KEY.items():
            with self.subTest(part=key):
                self.assertIn(part.skill, SKILLS)


if __name__ == "__main__":
    unittest.main()
