"""Tests for Tier 2: the planner, its refusals, and the tool answers.

No Ollama. The planner takes its generator as an argument, so a scripted model
drives every path — including the ones a live model reaches rarely and a test
must reach every time: a name that does not exist, arguments that will not
validate, an id smuggled into a call, and a timeout.

The properties under test, in order of how much they would cost to get wrong:

* a planned call can never widen scope
* an unusable plan refuses rather than answering something adjacent
* Tier 1 keeps every question it already answers, at Tier 1 speed
"""

from __future__ import annotations

import json
import os
import sys
import unittest
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import httpx

from app.main import app  # noqa: F401 - imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import (
    OrderCancellationReason,
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.insights.chat import resolve_route
from app.services.insights.periods import local_today
from app.services.insights.scope import InsightsScope
from app.services.insights.skills import SKILL_NAMES, SkillParams, run_skill
from app.services.insights.tool_chat import (
    CHAT_TOOLS,
    TOOL_FORMATTERS,
    build_planner_prompt,
    clean_arguments,
    plan_question,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()

TEST_DB_NAME = os.environ.get("CHAT_TOOLS_TEST_DB", "restaurant_rag_chat_tools_test")
TZ = ZoneInfo(settings.business_timezone)
ROUTABLE_SKILLS = tuple(name for name in SKILL_NAMES if name != "tool_answer")


class ScriptedModel:
    """Replays fixed replies; anything past the end repeats the last."""

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str, timeout_seconds: float, max_tokens: int) -> str:
        self.prompts.append(prompt)
        reply = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


def plan_with(reply, question: str = "was anything out of stock?"):
    """Plan once, with the cache off.

    These tests are about what the planner does with a reply, and a cache hit
    would serve an earlier test's plan instead of running this one's.
    """

    model = ScriptedModel(reply)
    return (
        plan_question(question, skills=ROUTABLE_SKILLS, generate=model, use_cache=False),
        model,
    )


# --- the planner -----------------------------------------------------------


class PlannerTests(unittest.TestCase):
    def test_a_valid_tool_plan_is_accepted(self) -> None:
        plan, _ = plan_with(json.dumps({"tool": "get_stockouts", "args": {"window_days": 30}}))
        self.assertTrue(plan.ok)
        self.assertEqual(plan.tool, "get_stockouts")
        self.assertEqual(plan.args, {"window_days": 30})

    def test_a_skill_plan_is_accepted(self) -> None:
        plan, _ = plan_with(json.dumps({"skill": "revenue_diagnosis"}))
        self.assertTrue(plan.ok)
        self.assertEqual(plan.skill, "revenue_diagnosis")
        self.assertIsNone(plan.tool)

    def test_every_registry_tool_is_now_reachable(self) -> None:
        # 2A.2 added the remaining formatters, so the chat set and the registry
        # are the same twenty tools. A tool with no formatter would reach an
        # owner as an empty reply, which is why the two must not drift.
        from app.services.insights.analyst.registry import TOOLS

        self.assertEqual(sorted(CHAT_TOOLS), sorted(TOOLS))

    def test_a_tool_that_does_not_exist_is_refused(self) -> None:
        plan, _ = plan_with(json.dumps({"tool": "get_owner_password", "args": {}}))
        self.assertFalse(plan.ok)
        self.assertEqual(plan.error, "unknown_tool")

    def test_an_invented_tool_is_refused(self) -> None:
        plan, _ = plan_with(json.dumps({"tool": "drop_all_orders", "args": {}}))
        self.assertFalse(plan.ok)
        self.assertEqual(plan.error, "unknown_tool")

    def test_an_invented_skill_is_refused(self) -> None:
        plan, _ = plan_with(json.dumps({"skill": "read_the_owners_email"}))
        self.assertFalse(plan.ok)

    def test_malformed_json_is_refused(self) -> None:
        plan, _ = plan_with("I think you should check the stock levels")
        self.assertFalse(plan.ok)
        self.assertEqual(plan.error, "planner_unusable")

    def test_a_timeout_is_refused_not_raised(self) -> None:
        plan, _ = plan_with(httpx.TimeoutException("read timed out"))
        self.assertFalse(plan.ok)
        self.assertEqual(plan.error, "planner_unavailable")

    def test_the_prompt_carries_each_tool_s_real_arguments(self) -> None:
        # A generic example made the planner pass window_days to a tool that
        # takes none, which strict validation then rejected.
        prompt = build_planner_prompt("anything", ROUTABLE_SKILLS)
        self.assertIn("get_branch_status(no arguments)", prompt)
        self.assertIn("get_stockouts(window_days)", prompt)

    def test_the_prompt_never_contains_an_identifier_field(self) -> None:
        prompt = build_planner_prompt("anything", ROUTABLE_SKILLS)
        self.assertNotIn("restaurant_id", prompt.replace("restaurant, branch", ""))


class ArgumentTests(unittest.TestCase):
    def test_an_argument_the_tool_does_not_declare_is_dropped(self) -> None:
        # Harmless over-supply costs the owner nothing, so it is removed rather
        # than turned into a refusal.
        args, error = clean_arguments("get_branch_status", {"window_days": 30})
        self.assertIsNone(error)
        self.assertEqual(args, {})

    def test_a_declared_argument_survives(self) -> None:
        args, error = clean_arguments("get_stockouts", {"window_days": 7})
        self.assertIsNone(error)
        self.assertEqual(args, {"window_days": 7})

    def test_a_smuggled_scope_identifier_fails_the_call(self) -> None:
        # The one thing a question may never choose. Stripping it silently would
        # be worse than refusing: it would mean the attempt left no trace.
        for name in ("restaurant_id", "restaurant_location_id", "user_id", "sql"):
            with self.subTest(argument=name):
                args, error = clean_arguments("get_stockouts", {name: "x", "window_days": 7})
                self.assertIsNotNone(error)
                self.assertEqual(args, {})

    def test_a_smuggled_identifier_refuses_the_whole_plan(self) -> None:
        plan, _ = plan_with(
            json.dumps(
                {"tool": "get_stockouts", "args": {"restaurant_id": str(uuid.uuid4())}}
            )
        )
        self.assertFalse(plan.ok)
        self.assertEqual(plan.error, "invalid_arguments")

    def test_non_object_arguments_are_refused(self) -> None:
        args, error = clean_arguments("get_stockouts", ["window_days"])
        self.assertIsNotNone(error)
        self.assertEqual(args, {})


class FormatterCoverageTests(unittest.TestCase):
    def test_every_chat_tool_has_a_formatter(self) -> None:
        # A tool the planner may choose with nothing to render it would reach an
        # owner as an empty reply.
        self.assertEqual(sorted(TOOL_FORMATTERS), sorted(CHAT_TOOLS))

    def test_formatters_handle_an_empty_result(self) -> None:
        for tool, formatter in TOOL_FORMATTERS.items():
            with self.subTest(tool=tool):
                # Must not raise; saying nothing is allowed, crashing is not.
                formatter({})


class DeterministicToolRoutingTests(unittest.TestCase):
    """Tool questions recognised in code, with no model and no wait."""

    def setUp(self) -> None:
        self._flag = settings.enable_ai_manager_chat_tools
        settings.enable_ai_manager_chat_tools = True

    def tearDown(self) -> None:
        settings.enable_ai_manager_chat_tools = self._flag

    def route(self, question: str):
        from app.services.insights.router import route_with_rules

        return route_with_rules(question)

    def test_payment_failure_questions_never_become_an_order_count(self) -> None:
        # This is the wrong answer that live testing found: "how many orders
        # failed at payment" matched the word "orders" and was reported as total
        # orders, up 1900%.
        for question in (
            "how many orders failed at payment?",
            "how many payments failed",
            "how many checkouts were abandoned",
            "how much did we lose at checkout",
        ):
            with self.subTest(question=question):
                routed = self.route(question)
                self.assertIsNotNone(routed)
                self.assertEqual(routed.skill, "tool_answer")
                self.assertEqual(routed.params.tool, "get_payment_failures")

    def test_availability_questions_reach_the_stockout_tool(self) -> None:
        for question in (
            "was anything out of stock last month",
            "did anything sell out",
            "which items were switched off",
            "was any dish unavailable",
        ):
            with self.subTest(question=question):
                routed = self.route(question)
                self.assertEqual(routed.params.tool, "get_stockouts")

    def test_wastage_is_still_refused(self) -> None:
        # Availability is recorded; stock levels and wastage are not. The tool
        # patterns must not blur that, or an honest limit becomes a wrong claim.
        for question in (
            "how much stock did I waste",
            "what is my inventory looking like",
            "how much food went to waste",
        ):
            with self.subTest(question=question):
                routed = self.route(question)
                self.assertEqual(routed.skill, "unsupported")
                self.assertEqual(routed.params.topic, "stock")

    def test_phase_a_questions_route_without_a_model(self) -> None:
        """The seven new tools, reached deterministically.

        Each of these is data that existed in the database the whole time and
        had no way to reach an owner.
        """

        for question, tool in (
            ("do more people order delivery or pickup?", "get_fulfillment_mix"),
            ("how many orders were collection?", "get_fulfillment_mix"),
            ("how do customers pay?", "get_payment_mix"),
            ("what payment methods do people use?", "get_payment_mix"),
            ("how much did I pay in delivery fees?", "get_order_economics"),
            ("how much tax did we collect?", "get_order_economics"),
            ("are card payments failing?", "get_payment_health"),
            ("is stripe having problems?", "get_payment_health"),
            ("what offers are currently live and when do they expire?", "get_offer_catalogue"),
            ("how many offers do I have?", "get_offer_catalogue"),
            ("what combos do you suggest?", "get_combos"),
            ("which items are ordered together?", "get_combos"),
            ("what are my opening hours?", "get_schedule"),
            ("what are my delivery slots?", "get_schedule"),
            ("how did my push notifications perform?", "get_notification_campaigns"),
        ):
            with self.subTest(question=question):
                routed = self.route(question)
                self.assertIsNotNone(routed, question)
                self.assertEqual(routed.skill, "tool_answer")
                self.assertEqual(routed.params.tool, tool)

    def test_the_new_tools_do_not_steal_existing_questions(self) -> None:
        # Seven new pattern sets are seven new chances to claim a question that
        # already had a better answer.
        for question, expected_tool in (
            ("did my offers work?", None),
            ("what promotion should I run?", None),
            ("why are my sales down?", None),
            ("how many orders failed at payment?", "get_payment_failures"),
            ("which branch is closed right now?", "get_branch_status"),
            ("was anything out of stock?", "get_stockouts"),
        ):
            with self.subTest(question=question):
                from app.services.insights.router import detect_tool

                self.assertEqual(detect_tool(question), expected_tool)

    def test_offer_liveness_comes_from_the_date_not_the_state(self) -> None:
        """An offer marked ACTIVE whose expiry has passed is not live.

        Real data has ten offers marked ACTIVE of which nine expired two months
        ago. Reporting the state column would tell an owner ten offers are
        running when a customer can use none of them.
        """

        answer = TOOL_FORMATTERS["get_offer_catalogue"](
            {
                "total": 2,
                "live_now": 0,
                "active_but_expired": 2,
                "by_state": {"ACTIVE": 2},
                "offers": [
                    {"name": "Stale", "state": "ACTIVE", "is_live": False,
                     "discount_type": "PERCENTAGE", "discount_value": 10.0,
                     "expires_at": "2026-06-23T00:00:00+00:00"},
                    {"name": "Also stale", "state": "ACTIVE", "is_live": False,
                     "discount_type": "PERCENTAGE", "discount_value": 20.0,
                     "expires_at": "2026-06-23T00:00:00+00:00"},
                ],
            }
        )
        self.assertIn("None of the", answer)
        self.assertIn("expiry date has passed", answer)
        self.assertNotIn("(live)", answer)

    def test_offer_expiry_is_answered_rather_than_refused(self) -> None:
        """The Q1 refusal from the original review, now a real answer.

        `expires_at` was in the database the whole time; nothing read it.
        """

        routed = self.route("what offers are currently live, and when does each expire?")
        self.assertEqual(routed.skill, "tool_answer")
        self.assertEqual(routed.params.tool, "get_offer_catalogue")

    # The golden set. Each entry is a phrasing an owner could plausibly type,
    # fixed here so a pattern change that breaks one is visible immediately.
    GOLDEN_ROUTES: tuple[tuple[str, str], ...] = (
        # fulfilment — behaviour, not settings
        ("do more people order delivery or pickup", "tool:get_fulfillment_mix"),
        ("what's my delivery vs collection split", "tool:get_fulfillment_mix"),
        ("how many orders are takeaway", "tool:get_fulfillment_mix"),
        ("do customers schedule orders in advance", "tool:get_fulfillment_mix"),
        ("what percentage of orders are pickup", "tool:get_fulfillment_mix"),
        # payment mix
        ("how do customers pay", "tool:get_payment_mix"),
        ("what payment methods do people use", "tool:get_payment_mix"),
        ("how many people pay cash", "tool:get_payment_mix"),
        ("is anyone paying by card", "tool:get_payment_mix"),
        ("what's my payment split", "tool:get_payment_mix"),
        # economics
        ("how much did I pay in delivery fees", "tool:get_order_economics"),
        ("how much tax did we collect", "tool:get_order_economics"),
        ("how much have I given away in discounts", "tool:get_order_economics"),
        ("what makes up my order totals", "tool:get_order_economics"),
        # provider health
        ("are card payments failing", "tool:get_payment_health"),
        ("is stripe having problems", "tool:get_payment_health"),
        ("any payment gateway issues", "tool:get_payment_health"),
        ("are online payments working", "tool:get_payment_health"),
        # offers
        ("what offers are live", "tool:get_offer_catalogue"),
        ("when do my offers expire", "tool:get_offer_catalogue"),
        ("how many offers do I have", "tool:get_offer_catalogue"),
        ("do I have any active promotions", "tool:get_offer_catalogue"),
        # combos
        ("what combos do you suggest", "tool:get_combos"),
        ("which items are ordered together", "tool:get_combos"),
        ("what bundles could I offer", "tool:get_combos"),
        # schedule — settings, not behaviour
        ("what are my opening hours", "tool:get_schedule"),
        ("what time do we close", "tool:get_schedule"),
        ("what are my delivery slots", "tool:get_schedule"),
        ("how far ahead can people order", "tool:get_schedule"),
        # notifications
        ("how did my push notifications perform", "tool:get_notification_campaigns"),
        ("how many notifications did we send", "tool:get_notification_campaigns"),
        # availability, branch state, menu, coverage, anomalies
        ("was anything out of stock", "tool:get_stockouts"),
        ("did anything sell out", "tool:get_stockouts"),
        ("which branch is closed", "tool:get_branch_status"),
        ("is any location shut", "tool:get_branch_status"),
        ("what's on my menu", "tool:get_menu_health"),
        ("how many menu items do I have", "tool:get_menu_health"),
        ("how many days did we trade", "tool:get_data_coverage"),
        ("was any day unusually bad", "tool:get_anomalies"),
        # payment loss
        ("how many orders failed at payment", "tool:get_payment_failures"),
        ("how much did we lose at checkout", "tool:get_payment_failures"),
        # tools added deterministic routing in Phase B
        ("show me revenue day by day", "tool:get_daily_series"),
        ("what were my daily sales", "tool:get_daily_series"),
        ("how did each branch do", "tool:get_location_performance"),
        ("revenue by branch please", "tool:get_location_performance"),
        ("what findings have been raised", "tool:get_insight_history"),
        ("what have you flagged recently", "tool:get_insight_history"),
        ("how does this week compare to last week", "tool:get_metric_deltas"),
        ("give me the numbers", "tool:get_period_metrics"),
        # Tier 1 keeps these, and must keep them faster
        ("why are my sales down", "skill:revenue_diagnosis"),
        ("how much revenue did I make", "skill:metric_lookup"),
        ("what is my best selling dish", "skill:item_performance"),
        ("which items get the fewest orders", "skill:item_performance"),
        ("when am I busiest", "skill:time_patterns"),
        ("how can I increase sales", "skill:recommendations"),
        ("am I losing repeat customers", "skill:customer_retention"),
        ("did my offers work", "skill:offer_performance"),
        ("why were orders cancelled", "skill:cancellation_reasons"),
        ("give me a summary", "skill:briefing_recall"),
        ("how long do orders take to prepare", "skill:order_operations"),
        # Tier 3 refusals for data that genuinely does not exist
        ("what do my reviews say", "refuse"),
        ("what is my profit margin", "refuse"),
        ("how much stock did I waste", "refuse"),
        ("how many registered users", "refuse"),
        ("how do I compare to competitors", "refuse"),
        ("how many staff do I have", "refuse"),
        ("how much did I spend on marketing", "refuse"),
    )

    def classify(self, question: str) -> str:
        routed = self.route(question)
        if routed is None:
            return "planner"
        if routed.skill == "tool_answer":
            return f"tool:{routed.params.tool}"
        if routed.skill == "unsupported":
            return "refuse"
        return f"skill:{routed.skill}"

    def test_the_golden_set_routes_deterministically(self) -> None:
        """Every phrasing lands where it should, with no model involved."""

        for question, expected in self.GOLDEN_ROUTES:
            with self.subTest(question=question):
                self.assertEqual(self.classify(question), expected)

    def test_ambiguous_pairs_stay_apart(self) -> None:
        """Wordings close enough that one rule could swallow the other.

        Each pair shares vocabulary and means different things — a setting
        against a behaviour, provider health against lost orders, availability
        against wastage.
        """

        for first, second in (
            ("how far ahead can people order", "do customers schedule orders in advance"),
            ("are card payments failing", "how many orders failed at payment"),
            ("what offers are live", "did my offers work"),
            ("was anything out of stock", "how much stock did I waste"),
            ("which branch is closed", "how did each branch do"),
            ("show me revenue day by day", "was any day unusually bad"),
            ("how many menu items do I have", "what is my best selling dish"),
            ("what findings have been raised", "what should I do next"),
            ("how did my push notifications perform", "how much did I spend on marketing"),
        ):
            with self.subTest(pair=(first, second)):
                self.assertNotEqual(self.classify(first), self.classify(second))

    def test_marketing_spend_is_refused_while_campaigns_are_answered(self) -> None:
        # Campaigns exist and carry open rates; spend does not exist at all.
        # Conflating them would either invent a cost or hide real data.
        self.assertEqual(
            self.route("how did my push notifications perform").params.tool,
            "get_notification_campaigns",
        )
        refused = self.route("how much did I spend on marketing")
        self.assertEqual(refused.skill, "unsupported")
        self.assertEqual(refused.params.entity, "marketing_spend")

    def test_branch_questions_stay_with_the_chat_layer(self) -> None:
        """Named-branch questions are resolved against real branch names.

        No pattern here should claim them: a regex cannot know what this
        restaurant's branches are called, and `apply_branch_scope` can.
        """

        from app.services.insights.router import detect_tool

        for question in (
            "how is Bodakdev doing on its own",
            "compare Bodakdev and Ellisbridge",
            "how were sales at Ellisbridge",
        ):
            with self.subTest(question=question):
                self.assertNotIn(
                    detect_tool(question), ("get_branch_metrics", "compare_locations")
                )

    def test_deterministic_arguments_validate_for_every_routed_tool(self) -> None:
        """Arguments come from each tool's own schema, not from an assumption.

        Every routed tool was handed `window_days`, so `get_insight_history` —
        which takes a limit — failed validation and answered "I could not look
        that up" to a question that had routed correctly.
        """

        from pydantic import ValidationError

        from app.services.insights.analyst.registry import TOOLS
        from app.services.insights.router import TOOL_PATTERNS, _tool_arguments

        for tool, _patterns in TOOL_PATTERNS:
            with self.subTest(tool=tool):
                args = _tool_arguments(tool, "in the last 30 days")
                try:
                    TOOLS[tool].args_model.model_validate(args)
                except ValidationError as error:  # pragma: no cover - failure path
                    self.fail(f"{tool} got {args}: {error}")

    def test_a_routed_tool_question_actually_answers(self) -> None:
        # Routing correctly and then failing validation is indistinguishable to
        # an owner from not being supported at all.
        routed = self.route("what findings have been raised")
        self.assertEqual(routed.params.tool, "get_insight_history")
        self.assertNotIn("window_days", routed.params.tool_args)

    def test_every_chat_tool_is_in_the_planner_catalogue(self) -> None:
        """A tool absent from the prompt is unreachable for any phrasing the
        deterministic patterns miss, which is the whole point of Tier 2."""

        prompt = build_planner_prompt("anything", ROUTABLE_SKILLS)
        for tool in CHAT_TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(f"- {tool}(", prompt)

    def test_branch_status_and_coverage_questions(self) -> None:
        self.assertEqual(
            self.route("which branch is closed right now").params.tool, "get_branch_status"
        )
        self.assertEqual(
            self.route("how many days did we trade last month").params.tool,
            "get_data_coverage",
        )

    def test_the_window_is_snapped_to_one_the_tool_accepts(self) -> None:
        # A tool refuses an unlisted window, and refusing an owner for saying
        # "last 45 days" is a worse answer than measuring the nearest one.
        from app.services.insights.analyst.schemas import ALLOWED_WINDOW_DAYS

        routed = self.route("was anything out of stock in the last 45 days")
        self.assertIn(routed.params.tool_args["window_days"], ALLOWED_WINDOW_DAYS)

    def test_a_tool_taking_no_arguments_is_given_none(self) -> None:
        routed = self.route("which branch is closed right now")
        self.assertEqual(routed.params.tool_args, {})

    def test_a_tool_only_question_refuses_when_disabled(self) -> None:
        """No skill covers these, so with the flag off they must refuse.

        Live testing found "do more people order delivery or pickup" answered
        as "Orders was 0" for a restaurant outside the rollout — the looser
        metric rule claimed it once the tool rule stood down.
        """

        settings.enable_ai_manager_chat_tools = False
        for question in (
            "do more people order delivery or pickup?",
            "how do customers pay?",
            "what are my opening hours?",
            "what combos do you suggest?",
        ):
            with self.subTest(question=question):
                routed = self.route(question)
                self.assertEqual(routed.skill, "unsupported")
                self.assertEqual(routed.params.entity, "not_enabled_yet")
                self.assertNotEqual(routed.params.metric, "orders")

    def test_the_flag_off_still_does_not_give_a_wrong_answer(self) -> None:
        """A wrong answer must not sit behind a feature flag.

        With tool answers off, a payment-failure question goes to the
        cancellations skill, which genuinely reports payments that never
        completed. What it must never do is become a total order count.
        """

        settings.enable_ai_manager_chat_tools = False
        routed = self.route("how many orders failed at payment?")
        self.assertIsNotNone(routed)
        self.assertNotEqual(routed.skill, "tool_answer")
        self.assertEqual(routed.skill, "cancellation_reasons")
        self.assertNotEqual(routed.params.metric, "orders")


class PlanCacheTests(unittest.TestCase):
    """Caching the mapping, not the data."""

    def setUp(self) -> None:
        from app.services.insights import tool_chat

        self.store: dict[str, object] = {}
        self._get = tool_chat.cache_get_json
        self._set = tool_chat.cache_set_json
        tool_chat.cache_get_json = lambda key: self.store.get(key)
        tool_chat.cache_set_json = lambda key, value, ttl_seconds=None: self.store.__setitem__(
            key, value
        ) or True

    def tearDown(self) -> None:
        from app.services.insights import tool_chat

        tool_chat.cache_get_json = self._get
        tool_chat.cache_set_json = self._set

    def plan(self, reply, question):
        model = ScriptedModel(reply)
        return plan_question(question, skills=ROUTABLE_SKILLS, generate=model), model

    def test_a_repeated_question_skips_the_model(self) -> None:
        reply = json.dumps({"tool": "get_stockouts", "args": {"window_days": 30}})
        first, first_model = self.plan(reply, "was anything out of stock last month")
        second, second_model = self.plan(reply, "was anything out of stock last month")

        self.assertTrue(first.ok and second.ok)
        self.assertEqual(second.tool, "get_stockouts")
        self.assertEqual(len(first_model.prompts), 1)
        # The whole point: six to eight seconds becomes none.
        self.assertEqual(second_model.prompts, [])

    def test_wording_differences_that_do_not_matter_share_an_entry(self) -> None:
        reply = json.dumps({"tool": "get_branch_status", "args": {}})
        self.plan(reply, "Which branch is closed?")
        _, model = self.plan(reply, "  which BRANCH   is closed? ")
        self.assertEqual(model.prompts, [])

    def test_a_different_question_does_not_reuse_the_entry(self) -> None:
        self.plan(json.dumps({"tool": "get_stockouts", "args": {}}), "was anything out of stock")
        plan, model = self.plan(
            json.dumps({"tool": "get_branch_status", "args": {}}), "which branch is closed"
        )
        self.assertEqual(plan.tool, "get_branch_status")
        self.assertEqual(len(model.prompts), 1)

    def test_no_tenant_data_is_written_to_the_cache(self) -> None:
        """The property that makes sharing entries between restaurants safe.

        A plan is a mapping from wording to a tool. The scope is applied when
        the tool runs, long after this is read back, so nothing here belongs to
        a restaurant and the key does not need to name one.
        """

        self.plan(
            json.dumps({"tool": "get_stockouts", "args": {"window_days": 30}}),
            "was anything out of stock",
        )
        stored = json.dumps(self.store, default=str)
        self.assertNotIn("restaurant", stored)
        self.assertEqual(list(self.store.values())[0].keys(), {"tool", "args", "skill"})

    def test_a_failed_plan_is_not_cached(self) -> None:
        # Caching a refusal would make a one-off model failure permanent.
        self.plan("not json at all", "some unusual question")
        self.assertEqual(self.store, {})

    def test_a_cached_tool_no_longer_offered_is_ignored(self) -> None:
        # The tool set can shrink between writing an entry and reading it, so a
        # hit is re-validated rather than trusted because it was stored.
        from app.services.insights.tool_chat import plan_cache_key

        question = "a question about something withdrawn"
        self.store[plan_cache_key(question)] = {"tool": "get_withdrawn", "args": {}}
        plan, model = self.plan(json.dumps({"tool": "get_stockouts", "args": {}}), question)
        self.assertEqual(plan.tool, "get_stockouts")
        self.assertEqual(len(model.prompts), 1)

    def test_a_cached_plan_with_a_smuggled_identifier_is_ignored(self) -> None:
        from app.services.insights.tool_chat import plan_cache_key

        question = "a poisoned entry"
        self.store[plan_cache_key(question)] = {
            "tool": "get_stockouts",
            "args": {"restaurant_id": "someone-else"},
        }
        plan, model = self.plan(
            json.dumps({"tool": "get_stockouts", "args": {"window_days": 7}}), question
        )
        self.assertEqual(plan.args, {"window_days": 7})
        self.assertEqual(len(model.prompts), 1)

    def test_the_version_is_part_of_the_key(self) -> None:
        # A prompt or tool-set change must not be answered from entries written
        # against the old one.
        from app.services.insights.tool_chat import PLAN_CACHE_VERSION, plan_cache_key

        self.assertIn(PLAN_CACHE_VERSION, plan_cache_key("anything"))


class ToolPathAvailabilityTests(unittest.TestCase):
    """Who reaches the tool path. The answer is now: everyone, or no one."""

    def setUp(self) -> None:
        self._flag = settings.enable_ai_manager_chat_tools
        settings.enable_ai_manager_chat_tools = True

    def tearDown(self) -> None:
        settings.enable_ai_manager_chat_tools = self._flag

    def route(self, restaurant_id):
        return resolve_route(
            "which branch is closed right now?",
            scope=InsightsScope(restaurant_id=restaurant_id),
        )

    def test_every_restaurant_reaches_the_tool_path(self) -> None:
        """The allowlist these tests used to police is gone.

        It was meant as a rollout dial and became a permanent split: one
        restaurant got the data tools and every other owner got a thinner
        assistant, with nothing on screen to explain the difference.
        """

        for _ in range(3):
            self.assertEqual(self.route(uuid.uuid4()).skill, "tool_answer")

    def test_the_build_switch_applies_to_everyone_equally(self) -> None:
        settings.enable_ai_manager_chat_tools = False
        for _ in range(3):
            self.assertNotEqual(self.route(uuid.uuid4()).skill, "tool_answer")

    def test_no_setting_can_gate_the_tool_path_by_restaurant(self) -> None:
        # The leak live testing once found here was a restaurant slipping *into*
        # the rollout by a longer route. The fix now is structural: there is no
        # per-restaurant setting left to slip past.
        from app.config.settings import Settings

        self.assertEqual(
            [name for name in Settings.model_fields if name.endswith("_restaurant_ids")],
            [],
        )

class FormatterGoldenTests(unittest.TestCase):
    """Every formatter, against a payload shaped like its tool's output."""

    PAYLOADS: dict[str, dict] = {
        "get_period_metrics": {
            "period": {"label": "1 Aug - 7 Aug"},
            "current": {"gross_revenue": 100.0, "orders": 4, "average_order_value": 25.0, "customers": 3},
            "previous": {"gross_revenue": 80.0, "orders": 3, "average_order_value": 26.6, "customers": 2},
        },
        "get_metric_deltas": {
            "period": {"label": "1 Aug - 7 Aug"},
            "headline": [
                {"metric": "gross_revenue", "current": 100.0, "previous": 80.0,
                 "percent_change": 25.0, "direction": "up"},
            ],
        },
        "get_breakdown": {
            "period": {"label": "1 Aug - 7 Aug"},
            "breakdown": {"dimension": "daypart", "note": None, "contributions": [
                {"label": "Lunch", "current": 40.0, "previous": 90.0, "absolute_change": -50.0}
            ]},
        },
        "get_daily_series": {
            "period": {"label": "1 Aug - 7 Aug"},
            "days_in_window": 7,
            "days_with_orders": [{"day": "2026-08-02", "orders": 3, "revenue": 60.0}],
        },
        "get_location_performance": {
            "period": {"label": "1 Aug - 7 Aug"},
            "branches": [
                {"branch_name": "Main", "current": {"orders": 5, "revenue": 100.0},
                 "previous": {"orders": 2, "revenue": 40.0}},
                {"branch_name": "Riverside", "current": {"orders": 0, "revenue": 0.0},
                 "previous": {"orders": 9, "revenue": 200.0}, "stopped_trading": True},
            ],
        },
        "get_branch_metrics": {
            "branch_name": "Main", "is_open": True,
            "period": {"label": "1 Aug - 7 Aug"},
            "current": {"gross_revenue": 100.0, "orders": 5},
            "previous": {"gross_revenue": 60.0, "orders": 3},
            "coverage": {"trading_days": 4},
        },
        "compare_locations": {
            "period": {"label": "1 Aug - 7 Aug"},
            "branches": [
                {"branch_name": "Main", "is_open": True, "trading_days": 4,
                 "current": {"orders": 5, "gross_revenue": 100.0}},
                {"branch_name": "Riverside", "is_open": False, "trading_days": 0,
                 "current": {"orders": 0, "gross_revenue": 0.0}},
            ],
        },
        "get_cancellations": {
            "period": {"label": "1 Aug - 7 Aug"},
            "current": {"cancelled_orders": 2, "cancelled_value": 50.0},
            "by_reason": [{"reason": "PAYMENT_NOT_COMPLETED", "orders": 2, "value": 50.0}],
        },
        "get_order_operations": {
            "period": {"label": "1 Aug - 7 Aug"},
            "acceptance_latency": {"median_minutes": 4.0, "sample_size": 10},
            "preparation_time": {"median_minutes": 17.0, "sample_size": 9},
        },
        "get_offer_performance": {
            "period": {"label": "1 Aug - 7 Aug"},
            "offers": [{"offer_name": "Welcome", "orders": 1, "gross_revenue": 100.0, "discount_cost": 10.0}],
            "caveat": "Observational only.",
        },
        "get_customer_cohorts": {
            "period": {"label": "1 Aug - 7 Aug"},
            "current": [{"cohort": "new", "customers": 3, "orders": 4, "revenue": 90.0}],
        },
        "get_recent_briefing": {
            "briefing": {"headline": "Orders are down", "narrative": "They fell.",
                         "period_start": "2026-08-01", "period_end": "2026-08-07"},
        },
        "get_insight_history": {
            "insights": [{"title": "Lunch weakened", "body": "Lunch fell to zero."}],
        },
        "get_open_recommendations": {
            "recommendations": [
                {"title": "Promote Pad Thai", "rationale": "It fell.", "expected_impact_amount": 664.26}
            ],
        },
        "get_stockouts": {
            "period": {"label": "1 Aug - 7 Aug"},
            "items": [{"item_name": "Tom Yum", "hours_unavailable": 12.0, "switch_offs": 2}],
        },
        "get_payment_failures": {
            "period": {"label": "1 Aug - 7 Aug"}, "lost_orders": 2, "lost_value": 50.0,
            "lost_value_share_of_revenue_percent": 16.7,
            "current": [{"reason": "PAYMENT_NOT_COMPLETED", "orders": 2, "value": 50.0}],
        },
        "get_branch_status": {
            "branches": [{"branch_name": "Main", "is_open": True, "is_active": True,
                          "opening_time": "10:00:00", "closing_time": "23:30:00"}],
        },
        "get_menu_health": {
            "items": [{"branch_name": "Main", "name": "Pad Thai", "category": "Noodles", "is_available": True}],
            "unavailable_count": 0, "category_gaps_by_branch": [],
        },
        "get_data_coverage": {
            "period": {"label": "1 Aug - 7 Aug"},
            "current": {"days_in_window": 7, "trading_days": 4, "orders": 20, "customers": 6},
            "minimum_orders_for_reliable_percentages": 10,
        },
        "get_anomalies": {
            "period": {"label": "1 Aug - 7 Aug"},
            "anomalies": {"evaluated": True, "points": [{"day": "2026-08-03", "value": 5.0, "baseline": 40.0}]},
        },
        "get_fulfillment_mix": {
            "period": {"label": "1 Aug - 7 Aug"}, "total_orders": 10,
            "splits": [
                {"fulfillment_type": "DELIVERY", "schedule_type": "ASAP", "orders": 7,
                 "revenue": 700.0, "share_percent": 70.0},
                {"fulfillment_type": "PICKUP", "schedule_type": "ASAP", "orders": 3,
                 "revenue": 300.0, "share_percent": 30.0},
            ],
        },
        "get_payment_mix": {
            "period": {"label": "1 Aug - 7 Aug"}, "total_orders": 10,
            "methods": [
                {"payment_method": "COD", "orders": 8, "revenue": 800.0, "share_percent": 80.0},
                {"payment_method": "GOOGLE_PAY", "orders": 2, "revenue": 200.0, "share_percent": 20.0},
            ],
        },
        "get_order_economics": {
            "period": {"label": "1 Aug - 7 Aug"}, "orders": 10,
            "subtotal": 900.0, "delivery_fee": 60.0, "tax_amount": 45.0,
            "discount_amount": 15.0, "total_amount": 990.0,
            "note": "Food and operating costs are not held anywhere, so none of this is profit.",
        },
        "get_payment_health": {
            "period": {"label": "1 Aug - 7 Aug"},
            "transactions": [
                {"provider": "stripe", "status": "PAID", "failure_code": None,
                 "count": 2, "amount": 200.0},
                {"provider": "stripe", "status": "FAILED", "failure_code": "card_declined",
                 "count": 1, "amount": 100.0},
            ],
        },
        "get_offer_catalogue": {
            "total": 2, "by_state": {"ACTIVE": 1, "EXPIRED": 1},
            "live_now": 1, "active_but_expired": 0,
            "offers": [
                {"source": "template", "name": "Welcome offer", "state": "ACTIVE",
                 "discount_type": "PERCENTAGE", "discount_value": 20.0,
                 "minimum_order_amount": 199.0, "starts_at": None,
                 "expires_at": "2026-09-01T00:00:00+00:00", "is_live": True},
                {"source": "generated", "name": "Try Pad Thai", "state": "EXPIRED",
                 "discount_type": "PERCENTAGE", "discount_value": 10.0,
                 "minimum_order_amount": 99.0, "starts_at": None,
                 "expires_at": "2026-08-01T00:00:00+00:00",
                 "is_live": False, "views": 75, "clicks": 2, "conversions": 1},
            ],
        },
        "get_combos": {
            "combos": [
                {"combo_name": "Pad Thai + Iced Tea", "orders_seen": 7, "customers_seen": 5,
                 "original_total_price": 17.0, "suggested_combo_price": 16.0,
                 "status": "ACTIVE", "is_active": True, "customer_visible": True},
            ],
        },
        "get_notification_campaigns": {
            "total": 1,
            "campaigns": [
                {"title": "Weekend deal", "status": "SENT", "audience": "ALL_USERS",
                 "scheduled_for": None, "dispatched_at": "2026-08-10T10:00:00+00:00",
                 "sent": 120, "delivered": 110, "opened": 30, "failed": 10},
            ],
        },
        "get_schedule": {
            "branches": [
                {"branch_name": "Main", "opening_time": "10:00:00", "closing_time": "23:30:00",
                 "is_open": True, "future_order_enabled": True, "max_future_days": 7,
                 "slot_interval_minutes": 30,
                 "slots": [{"day": "MONDAY", "fulfillment_type": "DELIVERY",
                            "start_time": "10:00:00", "end_time": "14:00:00", "is_active": True}]},
            ],
        },
    }

    def test_every_tool_has_a_golden_payload(self) -> None:
        # A formatter with no example is a formatter nobody has read the output
        # of, and it will reach an owner before it reaches a reviewer.
        self.assertEqual(sorted(self.PAYLOADS), sorted(CHAT_TOOLS))

    def test_every_formatter_produces_something_readable(self) -> None:
        for tool, payload in self.PAYLOADS.items():
            with self.subTest(tool=tool):
                answer = TOOL_FORMATTERS[tool](payload)
                self.assertTrue(answer, f"{tool} produced nothing")
                self.assertNotIn("None", answer)
                self.assertNotIn("{", answer)

    def test_no_formatter_invents_a_figure(self) -> None:
        """Every number printed must appear in the payload it came from.

        The formatters are deterministic, so this is defence against a mistake
        rather than against a model — but a formatter that computes its own
        figure would slip past every other check in the system.
        """

        # Uses the production helpers, so the test allows exactly what the real
        # guardrail allows — including the rounded forms `money()` writes, which
        # is why "₹664" is legitimate for 664.26.
        from app.services.insights.facts import (
            _expand_allowed,
            extract_numbers,
            unsupported_numbers,
        )

        for tool, payload in self.PAYLOADS.items():
            with self.subTest(tool=tool):
                answer = TOOL_FORMATTERS[tool](payload) or ""
                allowed: set[float] = set()
                for value in extract_numbers(json.dumps(payload, default=str)):
                    allowed |= _expand_allowed(value)
                # List positions the formatter numbers itself with.
                allowed |= {float(n) for n in range(0, 21)}
                self.assertEqual(
                    unsupported_numbers(answer, allowed), [], f"{tool} invented a figure"
                )


# --- integration -----------------------------------------------------------


def postgres_available() -> bool:
    engine = None
    try:
        engine = create_engine(
            f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_server}:{settings.postgres_port}/postgres",
            isolation_level="AUTOCOMMIT",
        )
        with engine.connect():
            return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001
                pass


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class ToolAnswerIntegrationTests(unittest.TestCase):
    engine = None
    session_factory = None

    @classmethod
    def setUpClass(cls) -> None:
        admin_url = (
            f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_server}:{settings.postgres_port}/postgres"
        )
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin_engine.dispose()

        cls.engine = create_engine(
            f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_server}:{settings.postgres_port}/{TEST_DB_NAME}"
        )
        with cls.engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
        Base.metadata.create_all(cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, expire_on_commit=False)
        with cls.session_factory() as session:
            cls._seed(session)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.engine is not None:
            cls.engine.dispose()
        admin_engine = create_engine(
            f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_server}:{settings.postgres_port}/postgres",
            isolation_level="AUTOCOMMIT",
        )
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin_engine.dispose()

    @classmethod
    def _seed(cls, session: Session) -> None:
        today = local_today(settings.business_timezone)

        def user(name: str, email: str, role: UserRole) -> User:
            row = User(
                id=uuid.uuid4(),
                app_client_id=None,
                full_name=name,
                email=email,
                hashed_password="x",
                role=role,
            )
            session.add(row)
            return row

        owner_a = user("Owner A", "tools-a@example.com", UserRole.OWNER)
        owner_b = user("Owner B", "tools-b@example.com", UserRole.OWNER)
        customer = user("Cust", "tools-c@example.com", UserRole.CUSTOMER)
        session.flush()

        def restaurant(owner: User, name: str, slug: str) -> Restaurant:
            row = Restaurant(
                id=uuid.uuid4(),
                owner_id=owner.id,
                name=name,
                slug=slug,
                cuisine_type="Thai",
                address_line_1="1 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                is_approved=True,
                is_active=True,
            )
            session.add(row)
            return row

        ours = restaurant(owner_a, "Ours", "ours")
        theirs = restaurant(owner_b, "Rival Kitchen", "rival-kitchen")
        session.flush()

        def location(rest: Restaurant, name: str, is_open: bool) -> RestaurantLocation:
            row = RestaurantLocation(
                id=uuid.uuid4(),
                restaurant_id=rest.id,
                branch_name=name,
                address_line_1="1 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                is_open=is_open,
                temporary_closed_reason="Refit" if not is_open else None,
            )
            session.add(row)
            return row

        ours_main = location(ours, "Ours Main", True)
        location(ours, "Ours Riverside", False)
        theirs_main = location(theirs, "Rival Central", True)
        session.flush()

        dish = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=ours.id,
            restaurant_location_id=ours_main.id,
            name="Pad Thai",
            category="Noodles",
            price=Decimal("100.00"),
        )
        rival_dish = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=theirs.id,
            restaurant_location_id=theirs_main.id,
            name="Rival Roll",
            category="Rolls",
            price=Decimal("70.00"),
        )
        session.add_all([dish, rival_dish])
        session.flush()

        def order(rest, loc, item, day_offset: int, status: OrderStatus, reason=None):
            placed_at = datetime.combine(
                today - timedelta(days=day_offset), time(13, 0), tzinfo=TZ
            )
            row = Order(
                id=uuid.uuid4(),
                customer_id=customer.id,
                restaurant_id=rest.id,
                restaurant_location_id=loc.id,
                status=status,
                payment_status=PaymentStatus.PAID,
                payment_method=PaymentMethod.CARD,
                payment_provider="test",
                fulfillment_type=OrderFulfillmentType.DELIVERY,
                schedule_type=OrderScheduleType.ASAP,
                scheduled_at=placed_at,
                subtotal=Decimal("100.00"),
                delivery_fee=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                discount_amount=Decimal("0.00"),
                total_amount=Decimal("100.00"),
                currency="INR",
                delivery_address="1 Test Street",
                placed_at=placed_at,
                cancellation_reason=reason,
            )
            session.add(row)
            session.add(
                OrderItem(
                    id=uuid.uuid4(),
                    order_id=row.id,
                    menu_item_id=item.id,
                    item_name_snapshot=item.name,
                    unit_price=Decimal("100.00"),
                    quantity=1,
                    total_price=Decimal("100.00"),
                )
            )

        for offset in range(2, 8):
            order(ours, ours_main, dish, offset, OrderStatus.DELIVERED)
        order(
            ours,
            ours_main,
            dish,
            2,
            OrderStatus.CANCELLED,
            OrderCancellationReason.PAYMENT_NOT_COMPLETED,
        )
        for offset in range(2, 6):
            order(theirs, theirs_main, rival_dish, offset, OrderStatus.DELIVERED)
        session.commit()

        cls.ours = ours.id
        cls.theirs = theirs.id

    def scope(self) -> InsightsScope:
        return InsightsScope(restaurant_id=self.ours)

    def run_tool(self, tool: str, args: dict | None = None):
        with self.session_factory() as session:
            return run_skill(
                session,
                scope=self.scope(),
                skill="tool_answer",
                params=SkillParams(tool=tool, tool_args=args or {}),
            )

    # -- answers ----------------------------------------------------------

    def test_branch_status_reports_the_closed_branch(self) -> None:
        result = self.run_tool("get_branch_status")
        self.assertIn("Ours Riverside", result.answer)
        self.assertIn("closed", result.answer)
        self.assertFalse(result.unsupported)

    def test_payment_failures_are_reported(self) -> None:
        result = self.run_tool("get_payment_failures", {"window_days": 30})
        self.assertIn("payment step", result.answer)

    def test_menu_health_lists_the_menu(self) -> None:
        result = self.run_tool("get_menu_health")
        self.assertIn("Pad Thai", result.answer)

    def test_data_coverage_states_trading_days(self) -> None:
        result = self.run_tool("get_data_coverage", {"window_days": 30})
        self.assertIn("traded on", result.answer)

    def test_stockouts_with_no_events_says_so(self) -> None:
        result = self.run_tool("get_stockouts", {"window_days": 30})
        self.assertIn("No dishes were switched off", result.answer)

    # -- isolation and refusal --------------------------------------------

    def test_no_tool_answer_leaks_the_other_restaurant(self) -> None:
        """Every tool, including the seven added in Phase A.

        Three of the new ones read tables that carry no restaurant id of their
        own — payment transactions, fulfilment slots — and are scoped through a
        join, which is exactly where a tenancy predicate gets forgotten.
        """

        from app.services.insights.analyst.registry import TOOLS

        for tool in CHAT_TOOLS:
            with self.subTest(tool=tool):
                fields = TOOLS[tool].args_model.model_fields
                args: dict = {}
                if "window_days" in fields:
                    args["window_days"] = 30
                if "branch_name" in fields:
                    args["branch_name"] = "Ours Main"
                if "branch_a" in fields:
                    args["branch_a"], args["branch_b"] = "Ours Main", "Ours Riverside"
                if "dimension" in fields:
                    args["dimension"] = "item"
                result = self.run_tool(tool, args)
                self.assertNotIn("Rival", result.answer)
                self.assertNotIn(str(self.theirs), result.answer)

    def test_a_tool_that_does_not_exist_refuses(self) -> None:
        result = self.run_tool("get_owner_password", {})
        self.assertTrue(result.unsupported)
        self.assertIn("could not find data", result.answer)

    def test_a_rejected_argument_refuses_rather_than_answering(self) -> None:
        # 83 is not an allowed window. The tool refuses it, and the answer says
        # so rather than quietly using a different period.
        result = self.run_tool("get_stockouts", {"window_days": 83})
        self.assertTrue(result.unsupported)
        self.assertIn("could not look that up", result.answer.lower())

    # -- tier ordering ----------------------------------------------------

    def test_tier_one_questions_never_reach_the_planner(self) -> None:
        # A planner call costs six to eight seconds. Any question the rules
        # already answer must not pay it.
        model = ScriptedModel(json.dumps({"tool": "get_stockouts", "args": {}}))
        previous = settings.enable_ai_manager_chat_tools
        settings.enable_ai_manager_chat_tools = True
        try:
            for question in (
                "why are my sales down?",
                "what is my best selling dish?",
                "how can I increase sales?",
                "when am I busiest?",
            ):
                with self.subTest(question=question):
                    routed = resolve_route(question, generate=model)
                    self.assertNotEqual(routed.skill, "tool_answer")
            self.assertEqual(model.prompts, [])
        finally:
            settings.enable_ai_manager_chat_tools = previous

    def test_the_flag_off_means_no_planner_call(self) -> None:
        model = ScriptedModel(json.dumps({"tool": "get_stockouts", "args": {}}))
        previous = settings.enable_ai_manager_chat_tools
        settings.enable_ai_manager_chat_tools = False
        try:
            resolve_route("was anything out of stock last week", generate=model)
            self.assertEqual(model.prompts, [])
        finally:
            settings.enable_ai_manager_chat_tools = previous

    def test_a_tool_question_routes_to_the_tool_when_enabled(self) -> None:
        model = ScriptedModel(
            json.dumps({"tool": "get_stockouts", "args": {"window_days": 30}})
        )
        previous = settings.enable_ai_manager_chat_tools
        settings.enable_ai_manager_chat_tools = True
        try:
            routed = resolve_route("was anything switched off last month", generate=model)
        finally:
            settings.enable_ai_manager_chat_tools = previous

        self.assertEqual(routed.skill, "tool_answer")
        self.assertEqual(routed.params.tool, "get_stockouts")
        self.assertEqual(routed.params.tool_args, {"window_days": 30})


if __name__ == "__main__":
    unittest.main()
