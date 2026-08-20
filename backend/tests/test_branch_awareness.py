"""Regression tests for branch awareness in the rules engine and in chat.

Both halves guard the same failure: a whole branch moving and the system
describing it as something else. The rules half asserts the finding exists and
outranks the dishes it contains; the chat half asserts a branch named in a
question actually scopes the answer, and that a branch it may not read is
refused rather than quietly answered at a wider scope.
"""

from __future__ import annotations

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

from app.main import app  # noqa: F401 - imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import (
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    OwnerInsightSeverity,
    OwnerInsightType,
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
from app.services.insights.branch_scope import resolve_branch_mentions
from app.services.insights.chat import answer_question, apply_branch_scope
from app.services.insights.periods import local_today
from app.services.insights.router import route_question
from app.services.insights.rules import evaluate_rules
from app.services.insights.scope import InsightsScope
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()

TEST_DB_NAME = os.environ.get("BRANCH_TEST_DB", "restaurant_rag_branch_test")
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


# --- rules engine ----------------------------------------------------------


def _contribution(
    key: str,
    label: str,
    current: float,
    previous: float,
    share: float,
    *,
    current_orders: int = 0,
    previous_orders: int = 0,
) -> ContributionResponse:
    change = current - previous
    return ContributionResponse(
        key=key,
        label=label,
        current=current,
        previous=previous,
        absolute_change=change,
        percent_change=(change / previous * 100) if previous else None,
        contribution_share=share,
        direction="down" if change < 0 else "up",
        current_orders=current_orders,
        previous_orders=previous_orders,
        current_quantity=0,
        previous_quantity=0,
    )


def _snapshot_with_branch_swap() -> DiagnosticsSnapshotResponse:
    """The Phase 7 scenario: one branch stops, another starts, dishes follow."""

    period = InsightsPeriod(
        start_date=date(2026, 7, 15),
        end_date=date(2026, 8, 13),
        day_count=30,
        label="15 Jul - 13 Aug 2026",
    )
    previous = InsightsPeriod(
        start_date=date(2026, 6, 15),
        end_date=date(2026, 7, 14),
        day_count=30,
        label="15 Jun - 14 Jul 2026",
    )

    def delta(metric: str, current: float, prior: float) -> MetricDeltaResponse:
        change = current - prior
        return MetricDeltaResponse(
            metric=metric,
            current=current,
            previous=prior,
            absolute_change=change,
            percent_change=(change / prior * 100) if prior else None,
            direction="down" if change < 0 else "up",
            sufficient_data=True,
        )

    return DiagnosticsSnapshotResponse(
        scope=InsightsScopeResponse(
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=None,
            timezone="Asia/Kolkata",
        ),
        current_period=period,
        previous_period=previous,
        generated_at="2026-08-14T00:00:00+00:00",
        data_quality=InsightsDataQuality(
            sufficient_volume=True,
            weekday_aligned=True,
            includes_partial_day=False,
            counted_order_statuses=["DELIVERED"],
            notes=[],
            trading_days=4,
            days_in_window=30,
        ),
        headline=[
            delta("gross_revenue", 8000.0, 12000.0),
            delta("orders", 9.0, 19.0),
        ],
        breakdowns=[
            ContributionBreakdownResponse(
                dimension="location",
                basis="gross_revenue",
                parent_change=-4000.0,
                sufficient_data=True,
                note=None,
                excluded_change=0.0,
                excluded_children=0,
                contributions=[
                    _contribution(
                        "riverside",
                        "Riverside",
                        0.0,
                        9000.0,
                        -225.0,
                        previous_orders=19,
                    ),
                    _contribution("main", "Main", 8000.0, 3000.0, 125.0, current_orders=9),
                ],
            ),
            ContributionBreakdownResponse(
                dimension="item",
                basis="item_revenue",
                parent_change=-4000.0,
                sufficient_data=True,
                note=None,
                excluded_change=0.0,
                excluded_children=0,
                contributions=[
                    _contribution(
                        "mango salad",
                        "Mango Salad",
                        0.0,
                        3000.0,
                        -75.0,
                        previous_orders=6,
                    ),
                ],
            ),
        ],
        anomalies=AnomalyReportResponse(
            evaluated=False,
            baseline_days=0,
            baseline_median_orders=0.0,
            note=None,
            points=[],
        ),
    )


class LocationRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = _snapshot_with_branch_swap()
        self.findings = evaluate_rules(self.snapshot)

    def test_a_branch_that_stopped_trading_is_flagged(self) -> None:
        located = [
            row
            for row in self.findings
            if row.insight_type == OwnerInsightType.LOCATION_DECLINE
        ]
        self.assertEqual(len(located), 1)
        self.assertEqual(located[0].subject, "Riverside")
        self.assertTrue(located[0].facts["stopped_trading"])

    def test_the_branch_finding_outranks_the_dish_it_contained(self) -> None:
        # The regression this whole change exists for: an owner whose branch shut
        # was shown "Mango Salad sales are falling" at the top of the feed.
        titles = [row.title for row in self.findings]
        branch_index = next(
            index
            for index, row in enumerate(self.findings)
            if row.insight_type == OwnerInsightType.LOCATION_DECLINE
        )
        item_index = next(
            index
            for index, row in enumerate(self.findings)
            if row.insight_type == OwnerInsightType.ITEM_DECLINE
        )
        self.assertLess(branch_index, item_index, msg=f"order was {titles}")

    def test_a_full_stop_is_not_reported_as_a_mild_finding(self) -> None:
        located = next(
            row
            for row in self.findings
            if row.insight_type == OwnerInsightType.LOCATION_DECLINE
        )
        self.assertIn(
            located.severity,
            {OwnerInsightSeverity.MEDIUM, OwnerInsightSeverity.HIGH},
        )

    def test_no_location_finding_without_a_location_breakdown(self) -> None:
        # Branch-scoped snapshots omit the dimension entirely; the rule must not
        # invent a finding from its absence.
        snapshot = _snapshot_with_branch_swap()
        snapshot.breakdowns = [
            row for row in snapshot.breakdowns if row.dimension != "location"
        ]
        types = {row.insight_type for row in evaluate_rules(snapshot)}
        self.assertNotIn(OwnerInsightType.LOCATION_DECLINE, types)

    def test_a_small_branch_wobble_is_not_flagged(self) -> None:
        # Thresholds must still apply, or every branch becomes a finding.
        snapshot = _snapshot_with_branch_swap()
        location = next(
            row for row in snapshot.breakdowns if row.dimension == "location"
        )
        location.contributions = [
            _contribution("riverside", "Riverside", 940.0, 1000.0, -1.5, current_orders=4)
        ]
        types = {row.insight_type for row in evaluate_rules(snapshot)}
        self.assertNotIn(OwnerInsightType.LOCATION_DECLINE, types)


# --- chat scope ------------------------------------------------------------


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class ChatBranchScopeTests(unittest.TestCase):
    engine = None
    session_factory = None
    _router_llm: bool = True

    def setUp(self) -> None:
        # Branch scoping is what is under test, not the model router. Leaving it
        # on would send every question to Ollama and make these tests both slow
        # and dependent on a host that may not be running.
        type(self)._router_llm = settings.enable_ai_manager_chat_llm_router
        settings.enable_ai_manager_chat_llm_router = False
        # Same reasoning for answer generation, which is now on for every
        # restaurant rather than an allowlisted one.
        type(self)._answers = settings.enable_ai_manager_chat_answers
        settings.enable_ai_manager_chat_answers = False

    def tearDown(self) -> None:
        settings.enable_ai_manager_chat_llm_router = type(self)._router_llm
        settings.enable_ai_manager_chat_answers = type(self)._answers

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
        current_day = today - timedelta(days=2)
        previous_day = today - timedelta(days=9)

        owner = User(
            id=uuid.uuid4(),
            app_client_id=None,
            full_name="Owner",
            email="branch-owner@example.com",
            hashed_password="x",
            role=UserRole.OWNER,
        )
        customer = User(
            id=uuid.uuid4(),
            app_client_id=None,
            full_name="Cust",
            email="branch-cust@example.com",
            hashed_password="x",
            role=UserRole.CUSTOMER,
        )
        session.add_all([owner, customer])
        session.flush()

        restaurant = Restaurant(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name="Bangkok Bowl",
            slug="bangkok-bowl",
            cuisine_type="Thai",
            address_line_1="1 Test Street",
            city="Ahmedabad",
            state="Gujarat",
            postal_code="380054",
            is_approved=True,
            is_active=True,
        )
        session.add(restaurant)
        session.flush()

        def location(name: str, is_open: bool) -> RestaurantLocation:
            row = RestaurantLocation(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                branch_name=name,
                address_line_1="1 Test Street",
                city="Ahmedabad",
                state="Gujarat",
                postal_code="380054",
                is_open=is_open,
            )
            session.add(row)
            return row

        bodakdev = location("Bangkok Bowl Bodakdev", True)
        ellisbridge = location("Bangkok Bowl Ellisbridge", False)
        session.flush()

        dish = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            restaurant_location_id=bodakdev.id,
            name="Pad Thai",
            category="Noodles",
            price=Decimal("100.00"),
        )
        session.add(dish)
        session.flush()

        def order(location_row: RestaurantLocation, day: date, amount: str) -> None:
            placed_at = datetime.combine(day, time(13, 0), tzinfo=TZ)
            total = Decimal(amount)
            row = Order(
                id=uuid.uuid4(),
                customer_id=customer.id,
                restaurant_id=restaurant.id,
                restaurant_location_id=location_row.id,
                status=OrderStatus.DELIVERED,
                payment_status=PaymentStatus.PAID,
                payment_method=PaymentMethod.CARD,
                payment_provider="test",
                fulfillment_type=OrderFulfillmentType.DELIVERY,
                schedule_type=OrderScheduleType.ASAP,
                scheduled_at=placed_at,
                subtotal=total,
                delivery_fee=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                discount_amount=Decimal("0.00"),
                total_amount=total,
                currency="INR",
                delivery_address="1 Test Street",
                placed_at=placed_at,
            )
            session.add(row)
            session.add(
                OrderItem(
                    id=uuid.uuid4(),
                    order_id=row.id,
                    menu_item_id=dish.id,
                    item_name_snapshot=dish.name,
                    unit_price=total,
                    quantity=1,
                    total_price=total,
                )
            )

        for _ in range(3):
            order(bodakdev, current_day, "100.00")
        for _ in range(4):
            order(ellisbridge, previous_day, "90.00")
        session.commit()

        cls.restaurant_id = restaurant.id
        cls.owner_id = owner.id
        cls.bodakdev_id = bodakdev.id
        cls.ellisbridge_id = ellisbridge.id

    def scope(self) -> InsightsScope:
        return InsightsScope(restaurant_id=self.restaurant_id)

    def branch_scope(self) -> InsightsScope:
        return InsightsScope(
            restaurant_id=self.restaurant_id, restaurant_location_id=self.bodakdev_id
        )

    # -- mention resolution ----------------------------------------------

    def test_a_distinctive_branch_token_resolves(self) -> None:
        with self.session_factory() as session:
            mention = resolve_branch_mentions(
                session, self.scope(), "how can I increase sales at Ellisbridge?"
            )
        self.assertEqual(
            [match.branch_name for match in mention.matches], ["Bangkok Bowl Ellisbridge"]
        )

    def test_a_token_shared_by_every_branch_resolves_nothing(self) -> None:
        # "Bangkok" is in both branch names and in the restaurant name, so it
        # cannot identify either one.
        with self.session_factory() as session:
            mention = resolve_branch_mentions(
                session, self.scope(), "how is Bangkok Bowl doing?"
            )
        self.assertEqual(mention.matches, ())

    def test_ordinary_questions_name_no_branch(self) -> None:
        # The reason matching runs against real branch names rather than parsing
        # "at X": every one of these would otherwise yield a phantom branch.
        questions = (
            "how were sales at lunch?",
            "what happened at the weekend?",
            "why are my sales down?",
            "what is my best selling dish?",
        )
        with self.session_factory() as session:
            for question in questions:
                with self.subTest(question=question):
                    mention = resolve_branch_mentions(session, self.scope(), question)
                    self.assertEqual(mention.matches, ())

    def test_two_branches_are_recognised_as_a_comparison(self) -> None:
        with self.session_factory() as session:
            mention = resolve_branch_mentions(
                session,
                self.scope(),
                "how is Ellisbridge performing compared to Bodakdev?",
            )
        self.assertTrue(mention.is_comparison)

    # -- routing ----------------------------------------------------------

    def test_a_named_branch_narrows_the_scope_and_is_stated(self) -> None:
        with self.session_factory() as session:
            routed, skill_scope, prefix, refusal = apply_branch_scope(
                session,
                scope=self.scope(),
                question="how can I increase sales at Ellisbridge?",
                routed=route_question(
                    "how can I increase sales at Ellisbridge?", allow_model=False
                ),
            )
        self.assertIsNone(refusal)
        self.assertEqual(skill_scope.restaurant_location_id, self.ellisbridge_id)
        self.assertIn("Ellisbridge", prefix)
        self.assertEqual(routed.params.branches, ("Bangkok Bowl Ellisbridge",))

    def test_a_comparison_routes_to_the_comparison_skill(self) -> None:
        question = "how is Ellisbridge performing compared to Bodakdev?"
        with self.session_factory() as session:
            routed, skill_scope, _prefix, refusal = apply_branch_scope(
                session,
                scope=self.scope(),
                question=question,
                routed=route_question(question, allow_model=False),
            )
        self.assertIsNone(refusal)
        self.assertEqual(routed.skill, "branch_comparison")
        # A comparison needs both branches, so the scope must stay restaurant-wide.
        self.assertIsNone(skill_scope.restaurant_location_id)
        self.assertEqual(len(routed.params.branches), 2)

    def test_a_question_with_no_branch_is_left_alone(self) -> None:
        with self.session_factory() as session:
            routed, skill_scope, prefix, refusal = apply_branch_scope(
                session,
                scope=self.scope(),
                question="why are my sales down?",
                routed=route_question("why are my sales down?", allow_model=False),
            )
        self.assertIsNone(refusal)
        self.assertIsNone(skill_scope.restaurant_location_id)
        self.assertEqual(prefix, "")
        self.assertEqual(routed.skill, "revenue_diagnosis")

    def test_a_branch_outside_the_scope_is_refused(self) -> None:
        with self.session_factory() as session:
            _routed, _scope, _prefix, refusal = apply_branch_scope(
                session,
                scope=self.branch_scope(),
                question="how is Ellisbridge doing?",
                routed=route_question("how is Ellisbridge doing?", allow_model=False),
            )
        self.assertIsNotNone(refusal)
        self.assertIn("Ellisbridge", refusal)

    # -- end to end -------------------------------------------------------

    def test_branch_answer_uses_that_branch_s_numbers(self) -> None:
        with self.session_factory() as session:
            branch_turn = answer_question(
                session,
                scope=self.scope(),
                user_id=self.owner_id,
                question="how were sales at Ellisbridge?",
                persist=False,
            )
            whole_turn = answer_question(
                session,
                scope=self.scope(),
                user_id=self.owner_id,
                question="how were sales?",
                persist=False,
            )

        self.assertTrue(branch_turn.answer.startswith("For Bangkok Bowl Ellisbridge:"))
        # The bug being guarded: these two used to be the same sentence.
        self.assertNotEqual(
            branch_turn.answer.replace("For Bangkok Bowl Ellisbridge: ", ""),
            whole_turn.answer,
        )
        self.assertEqual(
            branch_turn.skill_params["branches"], ["Bangkok Bowl Ellisbridge"]
        )

    def test_comparison_answer_names_both_branches(self) -> None:
        with self.session_factory() as session:
            turn = answer_question(
                session,
                scope=self.scope(),
                user_id=self.owner_id,
                question="how is Ellisbridge performing compared to Bodakdev?",
                persist=False,
            )
        self.assertEqual(turn.skill, "branch_comparison")
        self.assertIn("Bangkok Bowl Ellisbridge", turn.answer)
        self.assertIn("Bangkok Bowl Bodakdev", turn.answer)
        self.assertIn("closed", turn.answer)

    def test_refused_branch_question_answers_nothing(self) -> None:
        with self.session_factory() as session:
            turn = answer_question(
                session,
                scope=self.branch_scope(),
                user_id=self.owner_id,
                question="how is Ellisbridge doing?",
                persist=False,
            )
        self.assertEqual(turn.skill, "unsupported")
        self.assertIn("cannot answer", turn.answer)


if __name__ == "__main__":
    unittest.main()
