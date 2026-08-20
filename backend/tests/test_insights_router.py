"""Tests for question routing.

No database and no model: routing is a pure function from a question to a skill
and its parameters, which is the part that decides whether an owner gets the
answer they asked for.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, timedelta
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import httpx

from app.main import app  # noqa: F401  (imported first to settle import order)
from app.services.insights import router as router_module
from app.services.insights.periods import local_today
from app.services.insights.router import (
    detect_metric,
    detect_unsupported_topic,
    parse_period,
    route_question,
    route_with_model,
    route_with_rules,
)
from app.services.insights.router import STRUCTURALLY_ROUTED_SKILLS
from app.services.insights.skills import SKILL_NAMES


def skill_for(question: str) -> str:
    return route_question(question, allow_model=False).skill


class RuleRoutingTests(unittest.TestCase):
    def test_diagnosis_questions(self) -> None:
        for question in (
            "why are my sales down this week?",
            "what happened to revenue?",
            "sales dropped, explain",
            "why is revenue falling",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "revenue_diagnosis")

    def test_metric_lookup_questions(self) -> None:
        for question in (
            "how much revenue did I make last week?",
            "what was my total revenue",
            "how many orders did I get",
            "what is my average order value",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "metric_lookup")

    def test_item_questions(self) -> None:
        for question in (
            "what is my best selling dish?",
            "which item sells the most",
            "show me my worst sellers",
            "what's most popular",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "item_performance")

    def test_time_questions(self) -> None:
        for question in (
            "when am I busiest?",
            "what time do I get the most orders",
            "which day is quietest",
            "how is dinner trade performing",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "time_patterns")

    def test_retention_questions(self) -> None:
        for question in (
            "am I losing customers?",
            "how many repeat customers do I have",
            "what about new customers",
            "is my churn getting worse",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "customer_retention")

    def test_offer_questions(self) -> None:
        for question in (
            "did my offers work?",
            "are my discounts worth it",
            "how are my promotions doing",
            "show me offer performance",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "offer_performance")

    def test_recommendation_questions(self) -> None:
        for question in (
            "how can I increase sales?",
            "what should I do",
            "give me some recommendations",
            "any suggestions",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "recommendations")

    def test_summary_questions(self) -> None:
        for question in (
            "give me a summary",
            "how is business going",
            "recap this week for me",
        ):
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), "briefing_recall")

    def test_metric_is_extracted_for_lookups(self) -> None:
        routed = route_question("how many orders last week", allow_model=False)
        self.assertEqual(routed.params.metric, "orders")

        routed = route_question("what was my average order value", allow_model=False)
        self.assertEqual(routed.params.metric, "average_order_value")


class UnsupportedTopicTests(unittest.TestCase):
    """Questions the platform holds no data for must be refused, not guessed."""

    def test_topics_without_data_are_refused(self) -> None:
        for question, topic in (
            ("what do my reviews say?", "reviews"),
            ("how are my ratings", "reviews"),
            ("what is my profit margin", "profit"),
            ("what is my food cost", "profit"),
            ("how do I compare to competitors", "competitors"),
            ("how is my staff performing", "staff"),
            ("how much stock did I waste", "stock"),
        ):
            with self.subTest(question=question):
                routed = route_question(question, allow_model=False)
                self.assertEqual(routed.skill, "unsupported")
                self.assertEqual(routed.params.topic, topic)

    def test_cancellation_reasons_are_now_answered(self) -> None:
        # Refused until Phase 6A began recording a reason for every
        # cancellation. It must also not fall through to the generic "why"
        # diagnosis, which would answer a different question.
        for question in (
            "why were orders cancelled?",
            "what were the cancellation reasons",
            "reasons for cancelled orders",
        ):
            with self.subTest(question=question):
                self.assertEqual(
                    route_question(question, allow_model=False).skill,
                    "cancellation_reasons",
                )

    def test_stock_stays_refused(self) -> None:
        # Availability events say when a dish was switched off. That is not the
        # same as knowing stock levels or wastage, and conflating them would be
        # exactly the overreach these refusals exist to prevent.
        for question in (
            "how much stock did I waste",
            "what is my inventory looking like",
            "how much food went to waste",
        ):
            with self.subTest(question=question):
                routed = route_question(question, allow_model=False)
                self.assertEqual(routed.skill, "unsupported")
                self.assertEqual(routed.params.topic, "stock")

    def test_cancellation_counts_are_still_answerable(self) -> None:
        routed = route_question("how many orders were cancelled", allow_model=False)
        self.assertEqual(routed.skill, "metric_lookup")
        self.assertEqual(routed.params.metric, "cancelled_orders")

    def test_detect_helpers(self) -> None:
        self.assertEqual(detect_unsupported_topic("show me reviews"), "reviews")
        self.assertIsNone(detect_unsupported_topic("show me revenue"))
        self.assertEqual(detect_metric("what were my sales"), "gross_revenue")


class PeriodParsingTests(unittest.TestCase):
    """Ranges are parsed in code, never taken from the model."""

    def test_yesterday(self) -> None:
        params = parse_period("how did I do yesterday")
        expected = local_today() - timedelta(days=1)
        self.assertEqual(params.date_from, expected)
        self.assertEqual(params.date_to, expected)

    def test_today(self) -> None:
        params = parse_period("how are sales today")
        self.assertEqual(params.date_from, local_today())

    def test_relative_windows(self) -> None:
        self.assertEqual(parse_period("revenue last month").window_days, 30)
        self.assertEqual(parse_period("orders in the last fortnight").window_days, 14)
        self.assertEqual(parse_period("sales over the past week").window_days, 7)

    def test_explicit_day_counts(self) -> None:
        self.assertEqual(parse_period("revenue for the last 21 days").window_days, 21)

    def test_absurd_day_counts_are_clamped(self) -> None:
        # An unbounded window would let one question scan years of orders.
        params = parse_period("revenue for the last 999 days")
        self.assertLessEqual(params.window_days, 180)

    # -- the default period, and the periods that override it ---------------

    def test_no_period_named_means_the_last_three_months(self) -> None:
        """The commonest case, and the one that was wrong.

        "Which item sells the most?" is a question about the menu, not about
        this week. Answering it from seven days ranked a whole menu on a handful
        of orders, and never said which seven days it meant.
        """

        for question in (
            "which item sells the most",
            "which dish is performing best",
            "how are my customers doing",
            "why are sales down",
        ):
            with self.subTest(question=question):
                params = parse_period(question)
                self.assertEqual(params.window_days, 90)
                self.assertIsNone(params.date_from)

    def test_this_week_means_this_calendar_week(self) -> None:
        params = parse_period("how are sales this week")
        today = local_today()
        monday = today - timedelta(days=today.weekday())

        self.assertEqual(params.date_from, monday)
        self.assertLessEqual(params.date_to, today)
        self.assertIsNone(params.window_days)

    def test_last_week_means_the_week_before_this_one(self) -> None:
        # These two used to resolve to the same trailing seven days, so an owner
        # asking how last week went was shown a window covering most of this one.
        params = parse_period("how did we do last week")
        today = local_today()
        monday = today - timedelta(days=today.weekday())

        self.assertEqual(params.date_to, monday - timedelta(days=1))
        self.assertEqual(params.date_from, monday - timedelta(days=7))
        self.assertNotEqual(params.date_from, parse_period("this week").date_from)

    def test_an_explicit_range_is_used_exactly(self) -> None:
        # Measuring three months because the phrasing was unfamiliar would be
        # the silent substitution this layer exists to prevent.
        cases = (
            ("revenue between 1 june and 15 june", date(2026, 6, 1), date(2026, 6, 15)),
            ("orders from 2026-06-01 to 2026-06-15", date(2026, 6, 1), date(2026, 6, 15)),
            ("sales between june 1 and june 15", date(2026, 6, 1), date(2026, 6, 15)),
        )
        for question, start, end in cases:
            with self.subTest(question=question):
                params = parse_period(question)
                self.assertEqual((params.date_from, params.date_to), (start, end))
                self.assertIsNone(params.window_days)

    def test_a_reversed_range_is_read_the_right_way_round(self) -> None:
        params = parse_period("revenue between 15 june and 1 june")

        self.assertLess(params.date_from, params.date_to)

    def test_the_default_is_withheld_when_a_caller_asks_what_was_stated(self) -> None:
        # How the follow-up layer tells "they named a period" from "a default
        # applies". Without it every follow-up looked like it named a new one.
        self.assertIsNone(parse_period("why are sales down", apply_default=False).window_days)
        self.assertEqual(parse_period("last month", apply_default=False).window_days, 30)


class ModelFallbackTests(unittest.TestCase):
    def test_rules_miss_returns_none(self) -> None:
        self.assertIsNone(route_with_rules("wibble wobble flimflam"))

    def test_model_result_is_used_when_rules_miss(self) -> None:
        reply = json.dumps({"skill": "time_patterns", "metric": None, "subject": None})
        with patch.object(router_module, "_call_router_model", return_value=reply):
            routed = route_question("wibble wobble flimflam", allow_model=True)
        self.assertEqual(routed.skill, "time_patterns")
        self.assertEqual(routed.source, "llm")

    def test_invented_skill_is_rejected(self) -> None:
        # Executing an analysis that does not exist would be guesswork.
        reply = json.dumps({"skill": "predict_the_future", "metric": None, "subject": None})
        with patch.object(router_module, "_call_router_model", return_value=reply):
            self.assertIsNone(route_with_model("wibble wobble"))

    def test_malformed_model_output_is_rejected(self) -> None:
        with patch.object(router_module, "_call_router_model", return_value="not json"):
            self.assertIsNone(route_with_model("wibble wobble"))

    def test_model_timeout_is_handled(self) -> None:
        with patch.object(
            router_module, "_call_router_model", side_effect=httpx.ReadTimeout("slow")
        ):
            self.assertIsNone(route_with_model("wibble wobble"))

    def test_unroutable_question_falls_back_with_low_confidence(self) -> None:
        with patch.object(router_module, "_call_router_model", return_value="not json"):
            routed = route_question("wibble wobble flimflam", allow_model=True)
        self.assertEqual(routed.skill, "revenue_diagnosis")
        self.assertEqual(routed.confidence, "low")

    def test_model_is_not_called_when_rules_match(self) -> None:
        # Every avoided call is ~20 seconds saved on a CPU-only host.
        with patch.object(router_module, "_call_router_model") as call:
            route_question("why are sales down", allow_model=True)
        call.assert_not_called()

    def test_period_still_parsed_in_code_on_the_model_path(self) -> None:
        reply = json.dumps({"skill": "time_patterns", "metric": None, "subject": None})
        with patch.object(router_module, "_call_router_model", return_value=reply):
            routed = route_question("wibble wobble last month", allow_model=True)
        self.assertEqual(routed.params.window_days, 30)


class RouterContractTests(unittest.TestCase):
    def test_every_registered_skill_is_reachable_or_deliberate(self) -> None:
        # Guards against adding a skill and forgetting to route to it.
        routed = {skill_for(q) for q in (
            "why are sales down",
            "how much revenue last week",
            "best selling dish",
            "when am I busiest",
            "am I losing repeat customers",
            "did my offers work",
            "how can I increase sales",
            "give me a summary",
            "what do my reviews say",
            "why were orders cancelled",
            "how long do orders take to be accepted",
            "did my offer work",
            "which items are declining and what promotion should I run",
        )}
        # Branch comparison is reached structurally, after the database has
        # resolved a real branch name, so it is not text-routable by design.
        self.assertEqual(routed, set(SKILL_NAMES) - STRUCTURALLY_ROUTED_SKILLS)

    def test_the_commonest_phrasings_route_deterministically(self) -> None:
        """Questions an owner actually types, that used to match no rule at all.

        Each of these fell through to the planner: slow, and often answered by a
        skill that addressed a different question. "How did this week compare to
        last week" came back describing dayparts.
        """

        cases = {
            "Are customers coming back?": "customer_retention",
            "are customers returning": "customer_retention",
            "do customers order again": "customer_retention",
            "How did this week compare to last week?": "revenue_diagnosis",
            "how did last month compare with the month before": "revenue_diagnosis",
            "How is the restaurant doing?": "revenue_diagnosis",
            "how's business": "revenue_diagnosis",
            "how are we doing": "revenue_diagnosis",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(skill_for(question), expected)

    def test_a_greeting_is_not_claimed_by_the_trading_patterns(self) -> None:
        # "how's it going" is a greeting. The comparison patterns must not claim
        # it, or the small-talk detector never sees it.
        from app.services.insights.router import detect_small_talk

        self.assertEqual(detect_small_talk("how's it going"), "how_are_you")
        self.assertIsNone(detect_small_talk("how is the restaurant doing"))

    def test_a_follow_up_period_is_understood(self) -> None:
        # "and the month before?" parsed as no period at all, so the follow-up
        # had nothing to resolve and fell through to the model.
        self.assertEqual(parse_period("What about the month before?").window_days, 30)
        self.assertEqual(parse_period("and the previous month").window_days, 30)

    def test_prompt_lists_only_real_skills(self) -> None:
        prompt = router_module.build_router_prompt("test")
        for name in SKILL_NAMES:
            self.assertIn(name, prompt)


if __name__ == "__main__":
    unittest.main()
