"""Tests for the Phase 8C bounded loop.

No Ollama. Every test drives the loop with a scripted `generate` function, which
is the only way to test a timeout, a malformed reply, or an infinite loop
deterministically — and the reason the runner takes the generator as an argument
rather than reaching for a module-level client.

The properties under test are all about what happens when the model misbehaves,
because that is the normal case on a CPU host: it will time out, it will emit
prose where JSON was asked for, and it will repeat itself. None of those may
lose data, hang, or reach an owner.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
import uuid
from datetime import date, datetime, time, timedelta
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
    AnalysisRunStatus,
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
from app.models.owner_action import OwnerActionProposal
from app.models.owner_analysis_run import OwnerAnalysisRun
from app.models.owner_insight import OwnerInsight
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.insights.analyst import runner as runner_module
from app.services.insights.analyst.output import AIFinding
from app.services.insights.analyst.prompts import truncate_result
from app.services.insights.analyst.runner import (
    SEEDED_CALLS,
    _extract_json,
    _repair_truncated_json,
    run_analysis,
)
from app.services.insights.analyst.validation import check_causal_language
from app.services.insights.periods import local_today, resolve_period_comparison
from app.services.insights.scope import InsightsScope
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()

TEST_DB_NAME = os.environ.get("ANALYST_RUNNER_TEST_DB", "restaurant_rag_analyst_runner_test")
TZ = ZoneInfo(settings.business_timezone)


def _admin_url() -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/postgres"
    )


def _test_url() -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/{TEST_DB_NAME}"
    )


def postgres_available() -> bool:
    engine = None
    try:
        engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
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


class ScriptedModel:
    """A generator that replays a fixed list of replies.

    Anything past the end of the script repeats the last reply, so a test that
    means "and then it keeps doing this" does not have to spell out twelve
    identical entries.
    """

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str, timeout_seconds: float, max_tokens: int) -> str:
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self.replies) - 1)
        reply = self.replies[index]
        if isinstance(reply, Exception):
            raise reply
        return reply


# Two calls are executed before the model is asked anything, so every expected
# tool-call count is that many higher than the number of calls the model chose.
SEEDED = len(SEEDED_CALLS)


def explore(tool: str, **args) -> str:
    return json.dumps({"tool": tool, "args": args, "reason": "looking"})


DONE = json.dumps({"done": True, "reason": "enough"})


def conclude(findings: list[dict] | None = None, **extra) -> str:
    payload = {"insufficient_data": False, "summary": "s", "findings": findings or []}
    payload.update(extra)
    return json.dumps(payload)


# --- causal overreach (no database) ----------------------------------------


class CausalLanguageTests(unittest.TestCase):
    """An explanation may be offered. It may not be presented as measured."""

    def _finding(self, **overrides) -> AIFinding:
        base = {
            "category": "branches",
            "title": "Riverside stopped trading",
            "body": "Riverside took 0 orders this period, against 19 before.",
            "evidence": ["call_1"],
        }
        base.update(overrides)
        return AIFinding(**base)

    def test_a_measured_observation_passes(self) -> None:
        self.assertIsNone(check_causal_language(self._finding()))

    def test_a_cause_in_the_body_is_rejected(self) -> None:
        # Nothing in this platform measures why an order happened, so a cause
        # stated as observation is a measurement that was never made.
        for phrasing in (
            "Revenue fell because the branch closed.",
            "The drop was caused by the payment failures.",
            "Orders fell due to the lunch closure.",
            "The refit led to a fall in revenue.",
        ):
            with self.subTest(body=phrasing):
                error = check_causal_language(self._finding(body=phrasing))
                self.assertIsNotNone(error)
                self.assertIn("cause", error)

    def test_a_hedged_interpretation_is_allowed(self) -> None:
        self.assertIsNone(
            check_causal_language(
                self._finding(
                    interpretation="This may be because the branch is closed; worth checking."
                )
            )
        )

    def test_an_unhedged_interpretation_is_rejected(self) -> None:
        error = check_causal_language(
            self._finding(interpretation="Revenue fell because the branch closed.")
        )
        self.assertIsNotNone(error)
        self.assertIn("possibility", error)

    def test_an_interpretation_without_a_cause_needs_no_hedge(self) -> None:
        self.assertIsNone(
            check_causal_language(
                self._finding(interpretation="The branch is marked closed.")
            )
        )


class TruncatedReplyTests(unittest.TestCase):
    """Recovering a reply that ran out of tokens, without recovering its errors."""

    def test_a_complete_reply_is_untouched(self) -> None:
        payload = '{"insufficient_data": false, "findings": []}'
        self.assertEqual(_extract_json(payload)["findings"], [])

    def test_a_reply_cut_mid_finding_keeps_the_complete_ones(self) -> None:
        # The exact shape of the 8C run that was lost: two findings written, the
        # second half-finished when the token budget ran out.
        truncated = (
            '{"insufficient_data": false, "summary": "Trade moved.", "findings": ['
            '{"category":"branches","title":"Ellisbridge stopped","body":"0 orders.",'
            '"evidence":["call_1"]},'
            '{"category":"payments","title":"Failures","body":"Some orders never p'
        )
        recovered = _extract_json(truncated)
        self.assertEqual(len(recovered["findings"]), 1)
        self.assertEqual(recovered["findings"][0]["title"], "Ellisbridge stopped")
        self.assertEqual(recovered["summary"], "Trade moved.")

    def test_a_reply_cut_inside_a_string_is_still_closed(self) -> None:
        repaired = _repair_truncated_json('{"summary": "half a sen')
        self.assertEqual(json.loads(repaired)["summary"], "half a sen")

    def test_prose_is_still_refused(self) -> None:
        # Repair closes structure; it does not invent one.
        with self.assertRaises(ValueError):
            _extract_json("the analysis is that things are fine")

    def test_repair_recovers_form_not_correctness(self) -> None:
        # A truncated reply carrying an invented figure is recovered as JSON and
        # then rejected by the same gates as any other reply. Repair must never
        # become a way in.
        truncated = (
            '{"findings": [{"category":"revenue","title":"Collapse",'
            '"body":"Revenue fell by 987654.","evidence":["call_1"]},'
            '{"category":"x","title":"cut'
        )
        recovered = _extract_json(truncated)
        self.assertEqual(len(recovered["findings"]), 1)
        self.assertIn("987654", recovered["findings"][0]["body"])


class ResultTruncationTests(unittest.TestCase):
    def test_a_large_result_is_truncated_for_the_prompt(self) -> None:
        payload = {"rows": [{"value": index} for index in range(5000)]}
        rendered = truncate_result(payload, limit=200)
        self.assertLessEqual(len(rendered), 260)
        self.assertIn("truncated", rendered)

    def test_a_small_result_is_untouched(self) -> None:
        self.assertEqual(truncate_result({"a": 1}, limit=200), '{"a":1}')


# --- the loop --------------------------------------------------------------


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class RunnerTests(unittest.TestCase):
    engine = None
    session_factory = None

    @classmethod
    def setUpClass(cls) -> None:
        admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin_engine.dispose()

        cls.engine = create_engine(_test_url())
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
        admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin_engine.dispose()

    @classmethod
    def _seed(cls, session: Session) -> None:
        today = local_today(settings.business_timezone)
        owner = User(
            id=uuid.uuid4(),
            app_client_id=None,
            full_name="Owner",
            email="runner-owner@example.com",
            hashed_password="x",
            role=UserRole.OWNER,
        )
        customer = User(
            id=uuid.uuid4(),
            app_client_id=None,
            full_name="Cust",
            email="runner-cust@example.com",
            hashed_password="x",
            role=UserRole.CUSTOMER,
        )
        session.add_all([owner, customer])
        session.flush()

        restaurant = Restaurant(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name="Runner Diner",
            slug="runner-diner",
            cuisine_type="Thai",
            address_line_1="1 Test Street",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            is_approved=True,
            is_active=True,
        )
        session.add(restaurant)
        session.flush()

        location = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            branch_name="Runner Diner Main",
            address_line_1="1 Test Street",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
        )
        session.add(location)
        session.flush()

        dish = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            name="Pad Thai",
            category="Noodles",
            price=Decimal("100.00"),
        )
        session.add(dish)
        session.flush()

        # Enough trade in both windows that coverage is not the thing under test.
        for offset in list(range(2, 8)) + list(range(9, 15)):
            for _ in range(3):
                placed_at = datetime.combine(
                    today - timedelta(days=offset), time(13, 0), tzinfo=TZ
                )
                order = Order(
                    id=uuid.uuid4(),
                    customer_id=customer.id,
                    restaurant_id=restaurant.id,
                    restaurant_location_id=location.id,
                    status=OrderStatus.DELIVERED,
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
                )
                session.add(order)
                session.add(
                    OrderItem(
                        id=uuid.uuid4(),
                        order_id=order.id,
                        menu_item_id=dish.id,
                        item_name_snapshot=dish.name,
                        unit_price=Decimal("100.00"),
                        quantity=1,
                        total_price=Decimal("100.00"),
                    )
                )
        session.commit()
        cls.restaurant_id = restaurant.id

    def setUp(self) -> None:
        self._shadow = settings.ai_manager_analyst_shadow_mode
        self._max_calls = settings.analyst_max_tool_calls
        self._budget = settings.analyst_time_budget_seconds
        settings.ai_manager_analyst_shadow_mode = True

    def tearDown(self) -> None:
        settings.ai_manager_analyst_shadow_mode = self._shadow
        settings.analyst_max_tool_calls = self._max_calls
        settings.analyst_time_budget_seconds = self._budget
        with self.session_factory() as session:
            session.query(OwnerActionProposal).delete()
            session.query(OwnerInsight).delete()
            session.query(OwnerAnalysisRun).delete()
            session.commit()

    def scope(self) -> InsightsScope:
        return InsightsScope(restaurant_id=self.restaurant_id)

    def run_with(self, model: ScriptedModel):
        with self.session_factory() as session:
            result = run_analysis(
                session,
                scope=self.scope(),
                comparison=resolve_period_comparison(window_days=7),
                generate=model,
                enabled=True,
            )
            run = session.get(OwnerAnalysisRun, result.run_id) if result.run_id else None
            return result, run

    # -- the happy path ---------------------------------------------------

    def test_a_clean_run_completes_and_is_audited(self) -> None:
        model = ScriptedModel(
            explore("get_period_metrics", window_days=7),
            DONE,
            conclude(),
        )
        result, run = self.run_with(model)

        self.assertEqual(result.status, AnalysisRunStatus.COMPLETED)
        self.assertEqual(result.tool_calls, SEEDED + 1)
        self.assertIsNotNone(run)
        self.assertEqual(run.tool_call_count, SEEDED + 1)
        # The seeded opening comes first, then what the model chose.
        self.assertEqual(run.transcript["calls"][0]["tool"], "get_data_coverage")
        self.assertEqual(run.transcript["calls"][-1]["tool"], "get_period_metrics")
        self.assertTrue(run.shadow_mode)

    def test_shadow_mode_writes_nothing_visible(self) -> None:
        # The whole point of 8C: a completed run that produced a valid finding
        # still puts nothing in front of an owner.
        model = ScriptedModel(
            explore("get_data_coverage", window_days=7),
            DONE,
            conclude(
                [
                    {
                        "category": "volume",
                        "title": "Trade is steady",
                        "body": "There were 18 counted orders in the window.",
                        "evidence": ["call_1"],
                    }
                ]
            ),
        )
        result, _run = self.run_with(model)

        self.assertEqual(result.status, AnalysisRunStatus.COMPLETED)
        self.assertEqual(result.insights_written, 0)
        self.assertEqual(result.proposals_written, 0)
        with self.session_factory() as session:
            self.assertEqual(session.scalar(select(func.count(OwnerInsight.id))), 0)
            self.assertEqual(session.scalar(select(func.count(OwnerActionProposal.id))), 0)

    # -- failure modes ----------------------------------------------------

    def test_a_timeout_while_exploring_still_concludes(self) -> None:
        # Whatever was gathered before the timeout is still worth concluding
        # from; the alternative throws away real work.
        model = ScriptedModel(
            explore("get_period_metrics", window_days=7),
            httpx.TimeoutException("read timed out"),
        )
        result, run = self.run_with(model)

        self.assertEqual(result.tool_calls, SEEDED + 1)
        self.assertIsNotNone(run)
        self.assertIn("timed out", (run.failure_reason or "").lower())

    def test_a_timeout_before_any_call_fails_the_run(self) -> None:
        model = ScriptedModel(httpx.TimeoutException("read timed out"))
        result, run = self.run_with(model)

        self.assertEqual(result.status, AnalysisRunStatus.FAILED)
        # The seeded calls still ran; the model contributed nothing.
        self.assertEqual(result.tool_calls, SEEDED)
        self.assertTrue(result.fell_back)
        self.assertIsNotNone(run)

    def test_malformed_json_twice_ends_exploration(self) -> None:
        model = ScriptedModel("this is not json", "still not json")
        result, run = self.run_with(model)

        self.assertEqual(result.status, AnalysisRunStatus.FAILED)
        self.assertEqual(result.tool_calls, SEEDED)
        self.assertIsNotNone(run)

    def test_a_malformed_conclusion_fails_without_losing_the_audit(self) -> None:
        model = ScriptedModel(
            explore("get_period_metrics", window_days=7),
            DONE,
            "the analysis is that things are fine",
        )
        result, run = self.run_with(model)

        self.assertEqual(result.status, AnalysisRunStatus.FAILED)
        self.assertTrue(result.fell_back)
        self.assertEqual(run.tool_call_count, SEEDED + 1)
        self.assertIn("unusable", run.failure_reason)

    def test_an_unknown_tool_is_fed_back_then_ends_exploration(self) -> None:
        model = ScriptedModel(explore("drop_all_tables"))
        result, run = self.run_with(model)

        self.assertEqual(result.tool_calls, SEEDED)
        self.assertIn("unknown tool", (run.failure_reason or ""))

    def test_an_unknown_tool_can_be_corrected(self) -> None:
        model = ScriptedModel(
            explore("get_everything"),
            explore("get_period_metrics", window_days=7),
            DONE,
            conclude(),
        )
        result, _run = self.run_with(model)

        self.assertEqual(result.status, AnalysisRunStatus.COMPLETED)
        self.assertEqual(result.tool_calls, SEEDED + 1)

    def test_repeating_one_call_forever_terminates(self) -> None:
        # The infinite-loop case. Without the guard this runs until the call
        # budget empties, wasting a minute of CPU per repeat.
        model = ScriptedModel(explore("get_period_metrics", window_days=7))
        result, run = self.run_with(model)

        self.assertEqual(result.tool_calls, SEEDED + 1)
        self.assertIn("repeated", (run.failure_reason or ""))

    def test_the_call_budget_is_enforced(self) -> None:
        settings.analyst_max_tool_calls = 3
        model = ScriptedModel(
            explore("get_period_metrics", window_days=7),
            explore("get_data_coverage", window_days=7),
            explore("get_branch_status"),
            explore("get_menu_health"),
            conclude(),
        )
        result, run = self.run_with(model)

        # The budget counts seeded calls too, so the model gets what is left.
        self.assertEqual(result.tool_calls, 3)
        self.assertEqual(run.tool_call_count, 3)

    def test_the_time_budget_is_enforced(self) -> None:
        settings.analyst_time_budget_seconds = 0.0
        model = ScriptedModel(explore("get_period_metrics", window_days=7))
        result, run = self.run_with(model)

        self.assertEqual(result.tool_calls, 0)
        self.assertEqual(result.status, AnalysisRunStatus.FAILED)
        self.assertIn("budget", (run.failure_reason or ""))

    def test_a_failing_tool_does_not_end_the_run(self) -> None:
        # A rejected argument is a normal outcome the model can correct, not a
        # reason to abandon an analysis.
        model = ScriptedModel(
            explore("get_period_metrics", window_days=83),
            explore("get_period_metrics", window_days=7),
            DONE,
            conclude(),
        )
        result, run = self.run_with(model)

        self.assertEqual(result.status, AnalysisRunStatus.COMPLETED)
        self.assertEqual(result.tool_calls, SEEDED + 2)
        # The rejected window is the model's first choice, after the seeded pair.
        self.assertFalse(run.transcript["calls"][SEEDED]["ok"])

    # -- validation in the loop -------------------------------------------

    def test_an_invented_figure_is_rejected_end_to_end(self) -> None:
        model = ScriptedModel(
            explore("get_period_metrics", window_days=7),
            DONE,
            conclude(
                [
                    {
                        "category": "revenue",
                        "title": "Revenue collapsed",
                        "body": "Revenue fell by 987654 this period.",
                        "evidence": ["call_1"],
                    }
                ]
            ),
        )
        result, run = self.run_with(model)

        self.assertEqual(result.status, AnalysisRunStatus.REJECTED)
        self.assertEqual(len(result.outcome.findings), 0)
        self.assertEqual(run.rejection_reasons[0]["gate"], "numbers")

    def test_a_causal_claim_is_rejected_end_to_end(self) -> None:
        model = ScriptedModel(
            explore("get_period_metrics", window_days=7),
            DONE,
            conclude(
                [
                    {
                        "category": "revenue",
                        "title": "Steady trade",
                        "body": "There were 18 orders because customers came back.",
                        "evidence": ["call_1"],
                    }
                ]
            ),
        )
        result, run = self.run_with(model)

        self.assertEqual(result.status, AnalysisRunStatus.REJECTED)
        self.assertEqual(run.rejection_reasons[0]["gate"], "causality")

    def test_a_fabricated_citation_is_rejected_end_to_end(self) -> None:
        model = ScriptedModel(
            explore("get_period_metrics", window_days=7),
            DONE,
            conclude(
                [
                    {
                        "category": "revenue",
                        "title": "Steady trade",
                        "body": "There were 18 orders.",
                        "evidence": ["call_42"],
                    }
                ]
            ),
        )
        result, run = self.run_with(model)

        self.assertEqual(result.status, AnalysisRunStatus.REJECTED)
        self.assertEqual(run.rejection_reasons[0]["gate"], "evidence")

    # -- scope isolation ---------------------------------------------------

    def test_a_branch_scoped_run_never_sees_another_branch(self) -> None:
        """The whole-restaurant and branch-level runs must not blend.

        Checked at the only place it can leak: the transcript the model reads.
        A branch-scoped run whose prompt mentioned a second branch would be one
        generation away from attributing that branch's trade to this one.
        """

        with self.session_factory() as session:
            other = RestaurantLocation(
                id=uuid.uuid4(),
                restaurant_id=self.restaurant_id,
                branch_name="Runner Diner Second",
                address_line_1="2 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
            )
            session.add(other)
            session.commit()
            main_id = session.scalars(
                select(RestaurantLocation.id).where(
                    RestaurantLocation.restaurant_id == self.restaurant_id,
                    RestaurantLocation.branch_name == "Runner Diner Main",
                )
            ).one()

            branch_scope = InsightsScope(
                restaurant_id=self.restaurant_id, restaurant_location_id=main_id
            )
            model = ScriptedModel(
                explore("get_branch_status"),
                explore("get_menu_health"),
                DONE,
                conclude(),
            )
            result = run_analysis(
                session,
                scope=branch_scope,
                comparison=resolve_period_comparison(window_days=7),
                generate=model,
                enabled=True,
            )
            run = session.get(OwnerAnalysisRun, result.run_id)

        self.assertEqual(result.status, AnalysisRunStatus.COMPLETED)
        # The run is recorded against the branch, not the restaurant as a whole.
        self.assertEqual(run.restaurant_location_id, main_id)
        for prompt in model.prompts:
            self.assertNotIn("Runner Diner Second", prompt)

    def test_a_branch_scoped_run_cannot_ask_across_branches(self) -> None:
        with self.session_factory() as session:
            main_id = session.scalars(
                select(RestaurantLocation.id).where(
                    RestaurantLocation.restaurant_id == self.restaurant_id,
                    RestaurantLocation.branch_name == "Runner Diner Main",
                )
            ).one()
            branch_scope = InsightsScope(
                restaurant_id=self.restaurant_id, restaurant_location_id=main_id
            )
            model = ScriptedModel(
                explore("get_breakdown", dimension="location", window_days=7),
                explore("get_period_metrics", window_days=7),
                DONE,
                conclude(),
            )
            result = run_analysis(
                session,
                scope=branch_scope,
                comparison=resolve_period_comparison(window_days=7),
                generate=model,
                enabled=True,
            )
            run = session.get(OwnerAnalysisRun, result.run_id)

        # Refused rather than answered restaurant-wide, and the refusal is what
        # the model was shown.
        cross_branch = [
            call for call in run.transcript["calls"] if call["tool"] == "get_breakdown"
        ]
        self.assertEqual(len(cross_branch), 1)
        self.assertFalse(cross_branch[0]["ok"])

    def test_a_whole_restaurant_run_is_recorded_without_a_branch(self) -> None:
        model = ScriptedModel(explore("get_period_metrics", window_days=7), DONE, conclude())
        _result, run = self.run_with(model)
        self.assertIsNone(run.restaurant_location_id)

    # -- the flag ---------------------------------------------------------

    def test_the_run_is_skipped_when_the_flag_is_off(self) -> None:
        model = ScriptedModel(explore("get_period_metrics", window_days=7))
        with self.session_factory() as session:
            result = run_analysis(
                session, scope=self.scope(), generate=model, enabled=False
            )
            self.assertEqual(result.status, AnalysisRunStatus.SKIPPED)
            self.assertTrue(result.fell_back)
            # Nothing ran, so nothing was generated and nothing was recorded.
            self.assertEqual(model.prompts, [])
            self.assertEqual(session.scalar(select(func.count(OwnerAnalysisRun.id))), 0)

    def test_the_model_never_sees_an_identifier(self) -> None:
        # Scope is injected, and the prompts carry no id a model could echo back
        # into an argument.
        model = ScriptedModel(
            explore("get_period_metrics", window_days=7), DONE, conclude()
        )
        self.run_with(model)
        for prompt in model.prompts:
            self.assertNotIn(str(self.restaurant_id), prompt)
            self.assertNotIn("restaurant_id", prompt)


if __name__ == "__main__":
    unittest.main()
