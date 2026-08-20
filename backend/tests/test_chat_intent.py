"""Golden set for question intent, and the guarantees that stop wrong answers.

Every case here comes from a question that was answered incorrectly in review.
The four that prompted this work are named individually, because a regression in
any of them is a regression in the thing owners noticed.

The tests are deliberately about *parameters* rather than prose: what broke was
never the wording, it was that the question's direction, ranking basis and
metric were parsed and then ignored, or never parsed at all.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.insights.router import (
    detect_direction,
    detect_limit,
    detect_metric,
    detect_rank_basis,
    detect_unanswerable_entity,
    route_question,
)


def routed(question: str):
    return route_question(question, allow_model=False)


class TheFourFailedQuestions(unittest.TestCase):
    """The exact questions from the review, asserted by name."""

    def test_fewest_orders_asks_for_the_bottom_by_order_count(self) -> None:
        # Answered with the biggest earner before.
        params = routed("Which menu items are getting the fewest orders right now?")
        self.assertEqual(params.skill, "item_performance")
        self.assertEqual(params.params.direction, "bottom")
        self.assertEqual(params.params.rank_by, "orders")

    def test_biggest_drop_asks_for_falling_by_order_count(self) -> None:
        # Answered with the biggest *rise* before, from the same template.
        params = routed(
            "Which menu items have the biggest drop in orders compared with the "
            "previous period?"
        )
        self.assertEqual(params.skill, "item_performance")
        self.assertEqual(params.params.direction, "falling")
        self.assertEqual(params.params.rank_by, "orders")

    def test_the_two_opposite_questions_do_not_resolve_identically(self) -> None:
        # The clearest symptom: opposite questions produced byte-identical
        # answers, because only the skill was carried and nothing else.
        fewest = routed("Which menu items are getting the fewest orders right now?")
        dropped = routed("Which menu items have the biggest drop in orders?")
        self.assertEqual(fewest.skill, dropped.skill)
        self.assertNotEqual(fewest.params.direction, dropped.params.direction)

    def test_user_counts_are_refused_not_answered_with_revenue(self) -> None:
        # Answered with revenue before, because the metric silently defaulted.
        params = routed(
            "How many total users do we currently have, and how many are active users?"
        )
        self.assertEqual(params.skill, "unsupported")
        self.assertEqual(params.params.entity, "registered_users")

    def test_offer_expiry_is_never_reported_as_a_question_about_reviews(self) -> None:
        # The refusal named customer reviews for a question about offers, because
        # an undetected topic fell back to the first key in the topic table.
        params = routed("What offers are currently live, and when does each offer expire?")
        self.assertNotEqual(params.params.topic, "reviews")


class DirectionTests(unittest.TestCase):
    def test_bottom_phrasings(self) -> None:
        for question in (
            "which dishes sell the least",
            "what are my worst performing items",
            "which items are slowest",
            "what isn't selling",
            "show me the lowest earning dishes",
        ):
            with self.subTest(question=question):
                self.assertEqual(detect_direction(question), "bottom")

    def test_top_phrasings(self) -> None:
        for question in (
            "what is my best selling dish",
            "which items are most popular",
            "show me my top dishes",
            "what earns the highest",
        ):
            with self.subTest(question=question):
                self.assertEqual(detect_direction(question), "top")

    def test_falling_phrasings(self) -> None:
        for question in (
            "which dishes dropped the most",
            "what fell this month",
            "which items are declining",
            "what has gone down",
        ):
            with self.subTest(question=question):
                self.assertEqual(detect_direction(question), "falling")

    def test_a_change_word_beats_a_magnitude_word(self) -> None:
        # "Biggest drop" holds both. The movement is the specific request; the
        # magnitude only orders the results within it.
        self.assertEqual(detect_direction("which items had the biggest drop"), "falling")
        self.assertEqual(detect_direction("what grew the most"), "rising")

    def test_a_question_with_no_direction_has_none(self) -> None:
        self.assertIsNone(detect_direction("how did my dishes do"))


class RankBasisTests(unittest.TestCase):
    def test_order_count_phrasings(self) -> None:
        for question in (
            "which items get the fewest orders",
            "what is ordered most often",
            "which dish has the highest order count",
        ):
            with self.subTest(question=question):
                self.assertEqual(detect_rank_basis(question), "orders")

    def test_quantity_phrasings(self) -> None:
        self.assertEqual(detect_rank_basis("which dish sold the most units"), "quantity")
        self.assertEqual(detect_rank_basis("how many portions went out"), "quantity")

    def test_revenue_phrasings(self) -> None:
        self.assertEqual(detect_rank_basis("which dish earns the most revenue"), "revenue")

    def test_no_basis_is_left_unset_rather_than_guessed(self) -> None:
        # The skill then picks its own default and says which it used.
        self.assertIsNone(detect_rank_basis("what is my best dish"))


class LimitTests(unittest.TestCase):
    def test_explicit_counts(self) -> None:
        self.assertEqual(detect_limit("show me my top 5 dishes"), 5)
        self.assertEqual(detect_limit("3 worst items please"), 3)

    def test_absent_and_absurd_limits(self) -> None:
        self.assertIsNone(detect_limit("show me my dishes"))
        # Capped, so a question cannot ask for an unbounded list.
        self.assertEqual(detect_limit("top 99 dishes"), 10)


class NoSilentDefaultTests(unittest.TestCase):
    """The rule that turns a wrong answer into an honest one."""

    def test_an_unrecognised_metric_is_not_quietly_revenue(self) -> None:
        params = routed("how many total users do we have")
        self.assertNotEqual(params.params.metric, "gross_revenue")

    def test_a_recognised_metric_still_resolves(self) -> None:
        self.assertEqual(routed("how much revenue last week").params.metric, "gross_revenue")
        self.assertEqual(routed("how many orders yesterday").params.metric, "orders")
        self.assertEqual(detect_metric("what is my average order value"), "average_order_value")

    def test_a_metric_question_with_no_metric_carries_none(self) -> None:
        # metric_lookup then refuses and lists what it can answer, rather than
        # reporting revenue as though revenue had been asked for.
        params = routed("how many of those do we have")
        if params.skill == "metric_lookup":
            self.assertIsNone(params.params.metric)


class UnanswerableEntityTests(unittest.TestCase):
    def test_entities_the_platform_does_not_model(self) -> None:
        for question, entity in (
            ("how many registered users are there", "registered_users"),
            ("how many app users do we have", "registered_users"),
            ("do we have any table bookings today", "reservations"),
            ("how many refunds did we issue", "refunds"),
            ("how are our delivery riders performing", "delivery_partners"),
        ):
            with self.subTest(question=question):
                self.assertEqual(detect_unanswerable_entity(question), entity)

    def test_ordinary_questions_name_no_unanswerable_entity(self) -> None:
        # A false positive here would refuse a question the system can answer,
        # which is its own kind of wrong.
        for question in (
            "how many orders did I get",
            "how many customers ordered last week",
            "why are my sales down",
            "which dishes are selling",
        ):
            with self.subTest(question=question):
                self.assertIsNone(detect_unanswerable_entity(question))


class RoutingStillWorksTests(unittest.TestCase):
    """The questions that were already right must stay right."""

    def test_previously_working_questions_are_unchanged(self) -> None:
        for question, skill in (
            ("why are my sales down?", "revenue_diagnosis"),
            ("how much revenue did I make?", "metric_lookup"),
            ("how can I increase sales?", "recommendations"),
            ("when am I busiest?", "time_patterns"),
            ("did my offers work?", "offer_performance"),
            ("am I losing repeat customers?", "customer_retention"),
            ("why were orders cancelled?", "cancellation_reasons"),
            ("give me a summary", "briefing_recall"),
            ("what do my reviews say?", "unsupported"),
        ):
            with self.subTest(question=question):
                self.assertEqual(routed(question).skill, skill)

    def test_unsupported_topics_keep_their_own_wording(self) -> None:
        self.assertEqual(routed("what is my profit margin").params.topic, "profit")
        self.assertEqual(routed("what do my reviews say").params.topic, "reviews")


if __name__ == "__main__":
    unittest.main()
