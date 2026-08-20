"""Integration tests for insight generation, dedupe, persistence, and endpoints.

Runs against a throwaway Postgres database and skips itself when none is
reachable, matching `test_insights_metrics_sql`.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # imported first to settle import order
from app.config import get_settings
from app.config.database import get_db
from app.models.base import Base
from app.models.enums import (
    InsightNarrationSource,
    OwnerActionStatus,
    OwnerActionType,
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    OwnerInsightStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.owner_action import OwnerActionProposal
from app.models.owner_insight import OwnerBriefing, OwnerInsight
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.auth import get_current_user
from app.services.insights.periods import resolve_period_comparison
from app.services.insights.generation import (
    generate_all_briefings,
    generate_for_restaurant,
)
from app.services.insights.periods import PeriodComparison, build_period
from app.services.insights.scope import InsightsScope
from tests.test_insights_rules import SettingsOverride
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()

TEST_DB_NAME = os.environ.get("INSIGHTS_GEN_TEST_DB", "restaurant_rag_insights_gen_test")
IST = ZoneInfo("Asia/Kolkata")

CURRENT_START = date(2026, 3, 9)
CURRENT_END = date(2026, 3, 15)
PREVIOUS_START = date(2026, 3, 2)
PREVIOUS_END = date(2026, 3, 8)


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
    except Exception:  # noqa: BLE001 - any connection failure means "skip"
        return False
    finally:
        if engine is not None:
            engine.dispose()


def ist(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=IST)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class InsightGenerationTests(unittest.TestCase):
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
        def make_user(name: str, email: str, role: UserRole) -> User:
            user = User(
                id=uuid.uuid4(),
                app_client_id=None,
                full_name=name,
                email=email,
                hashed_password="x",
                role=role,
            )
            session.add(user)
            return user

        owner_a = make_user("Owner A", "gen-owner-a@test.local", UserRole.OWNER)
        owner_b = make_user("Owner B", "gen-owner-b@test.local", UserRole.OWNER)
        customer = make_user("Customer", "gen-customer@test.local", UserRole.CUSTOMER)
        session.flush()

        def make_restaurant(owner: User, name: str, slug: str) -> Restaurant:
            restaurant = Restaurant(
                id=uuid.uuid4(),
                owner_id=owner.id,
                name=name,
                slug=slug,
                cuisine_type="Italian",
                address_line_1="1 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                is_approved=True,
                is_active=True,
            )
            session.add(restaurant)
            return restaurant

        restaurant_a = make_restaurant(owner_a, "Gen Restaurant A", "gen-restaurant-a")
        restaurant_b = make_restaurant(owner_b, "Gen Restaurant B", "gen-restaurant-b")
        session.flush()

        def make_location(restaurant: Restaurant, branch: str) -> RestaurantLocation:
            location = RestaurantLocation(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                branch_name=branch,
                address_line_1="1 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
            )
            session.add(location)
            return location

        location_a = make_location(restaurant_a, "A Main")
        location_b = make_location(restaurant_b, "B Main")
        session.flush()

        def make_menu_item(
            restaurant: Restaurant, location: RestaurantLocation, name: str, price: str
        ) -> MenuItem:
            menu_item = MenuItem(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                restaurant_location_id=location.id,
                name=name,
                category="Pizza",
                price=Decimal(price),
            )
            session.add(menu_item)
            return menu_item

        pizza_a = make_menu_item(restaurant_a, location_a, "Margherita Pizza", "500.00")
        pizza_b = make_menu_item(restaurant_b, location_b, "Pepperoni Pizza", "1000.00")
        session.flush()

        def make_order(
            restaurant: Restaurant,
            location: RestaurantLocation,
            menu_item: MenuItem,
            placed_at: datetime,
            unit_price: str,
        ) -> None:
            amount = Decimal(unit_price)
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
                subtotal=amount,
                delivery_fee=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                discount_amount=Decimal("0.00"),
                total_amount=amount,
                currency="INR",
                delivery_address="1 Test Street",
                placed_at=placed_at,
            )
            session.add(order)
            session.flush()
            session.add(
                OrderItem(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    menu_item_id=menu_item.id,
                    item_name_snapshot=menu_item.name,
                    quantity=1,
                    base_unit_price=amount,
                    customization_total_price=Decimal("0.00"),
                    unit_price=amount,
                    total_price=amount,
                    selected_options_snapshot=[],
                )
            )

        # Restaurant A: 14 orders last week, 10 this week — a clear, material drop.
        for offset in range(7):
            day = PREVIOUS_START + timedelta(days=offset)
            for hour in (13, 20):
                make_order(restaurant_a, location_a, pizza_a, ist(day, hour), "500.00")
        for offset in range(5):
            day = CURRENT_START + timedelta(days=offset)
            for hour in (13, 20):
                make_order(restaurant_a, location_a, pizza_a, ist(day, hour), "500.00")

        # Restaurant B moves independently, so a leak would be obvious.
        for offset in range(7):
            day = PREVIOUS_START + timedelta(days=offset)
            for hour in (12, 19, 21):
                make_order(restaurant_b, location_b, pizza_b, ist(day, hour), "1000.00")
        for offset in range(4):
            day = CURRENT_START + timedelta(days=offset)
            for hour in (12, 19, 21):
                make_order(restaurant_b, location_b, pizza_b, ist(day, hour), "1000.00")

        session.commit()

        cls.restaurant_a = restaurant_a.id
        cls.restaurant_b = restaurant_b.id
        cls.owner_a_id = owner_a.id
        cls.owner_b_id = owner_b.id

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)
        self.addCleanup(self._reset_generated_rows)
        self.scope_a = InsightsScope(restaurant_id=self.restaurant_a)
        self.scope_b = InsightsScope(restaurant_id=self.restaurant_b)
        self.comparison = PeriodComparison(
            current=build_period(CURRENT_START, CURRENT_END, timezone_name="Asia/Kolkata"),
            previous=build_period(PREVIOUS_START, PREVIOUS_END, timezone_name="Asia/Kolkata"),
            timezone_name="Asia/Kolkata",
            weekday_aligned=True,
            includes_partial_day=False,
        )
        self.now = datetime(2026, 3, 16, 4, 30, tzinfo=UTC)

    def _reset_generated_rows(self) -> None:
        with self.session_factory() as session:
            session.query(OwnerActionProposal).delete()
            session.query(OwnerInsight).delete()
            session.query(OwnerBriefing).delete()
            session.commit()

    def _generate(self, scope: InsightsScope, *, now: datetime | None = None):
        return generate_for_restaurant(
            self.session,
            scope=scope,
            comparison=self.comparison,
            now=now or self.now,
        )

    # -- generation --------------------------------------------------------

    def test_generation_persists_a_briefing_and_insights(self) -> None:
        result = self._generate(self.scope_a)

        self.assertIsNotNone(result.briefing_id)
        self.assertGreater(result.insights_created, 0)

        briefing = self.session.get(OwnerBriefing, result.briefing_id)
        self.assertEqual(briefing.restaurant_id, self.restaurant_a)
        self.assertEqual(briefing.period_start, CURRENT_START)
        self.assertTrue(briefing.narrative)
        # Narration is off by default, so the deterministic template is used.
        self.assertEqual(briefing.narration_source, InsightNarrationSource.TEMPLATE)
        self.assertIn("gross_revenue", briefing.facts["headline"])

    def test_revenue_drop_is_detected_and_attributed(self) -> None:
        self._generate(self.scope_a)
        rows = self.session.scalars(
            select(OwnerInsight).where(OwnerInsight.restaurant_id == self.restaurant_a)
        ).all()
        types = {row.insight_type.value for row in rows}
        self.assertIn("REVENUE_DROP", types)

        revenue = next(row for row in rows if row.insight_type.value == "REVENUE_DROP")
        # 14 orders at 500 fell to 10 at 500.
        self.assertAlmostEqual(float(revenue.facts["previous_revenue"]), 7000.0)
        self.assertAlmostEqual(float(revenue.facts["current_revenue"]), 5000.0)
        self.assertAlmostEqual(float(revenue.facts["absolute_change"]), -2000.0)

    def test_narrative_only_states_supported_numbers(self) -> None:
        from app.services.insights.facts import allowed_numbers, unsupported_numbers
        from app.services.insights.facts import FactPack

        result = self._generate(self.scope_a)
        briefing = self.session.get(OwnerBriefing, result.briefing_id)
        payload = briefing.facts
        pack = FactPack(
            period_label=payload["period"],
            previous_period_label=payload["previous_period"],
            timezone=payload["timezone"],
            headline=payload["headline"],
            insights=payload["findings"],
            notes=payload["caveats"],
        )
        allowed = allowed_numbers(
            pack,
            period_dates=(CURRENT_START, CURRENT_END, PREVIOUS_START, PREVIOUS_END),
        )
        text_out = f"{briefing.headline} {briefing.narrative}"
        self.assertEqual(unsupported_numbers(text_out, allowed), [])

    # -- dedupe ------------------------------------------------------------

    def test_rerunning_the_same_night_suppresses_repeats(self) -> None:
        first = self._generate(self.scope_a)
        second = self._generate(self.scope_a)

        self.assertGreater(first.insights_created, 0)
        # A continuing slump must not produce an identical card again.
        self.assertEqual(second.insights_created, 0)
        self.assertEqual(second.insights_suppressed, second.candidates_found)
        # The briefing itself is still written, so the owner has today's summary.
        self.assertIsNotNone(second.briefing_id)

    def test_findings_return_after_the_cooldown_lapses(self) -> None:
        self._generate(self.scope_a)
        later = self.now + timedelta(hours=settings.insight_dedupe_cooldown_hours + 1)
        revived = self._generate(self.scope_a, now=later)
        self.assertGreater(revived.insights_created, 0)

    def test_dismissed_findings_stay_suppressed(self) -> None:
        self._generate(self.scope_a)
        rows = self.session.scalars(
            select(OwnerInsight).where(OwnerInsight.restaurant_id == self.restaurant_a)
        ).all()
        for row in rows:
            row.status = OwnerInsightStatus.DISMISSED
        self.session.commit()

        # An owner who waved a finding away should not meet it again tomorrow.
        again = self._generate(self.scope_a)
        self.assertEqual(again.insights_created, 0)

    # -- isolation ---------------------------------------------------------

    def test_generation_is_isolated_between_restaurants(self) -> None:
        self._generate(self.scope_a)
        self._generate(self.scope_b)

        insights_a = self.session.scalars(
            select(OwnerInsight).where(OwnerInsight.restaurant_id == self.restaurant_a)
        ).all()
        insights_b = self.session.scalars(
            select(OwnerInsight).where(OwnerInsight.restaurant_id == self.restaurant_b)
        ).all()

        self.assertTrue(insights_a)
        self.assertTrue(insights_b)

        revenue_a = next(row for row in insights_a if row.insight_type.value == "REVENUE_DROP")
        revenue_b = next(row for row in insights_b if row.insight_type.value == "REVENUE_DROP")
        self.assertAlmostEqual(float(revenue_a.facts["previous_revenue"]), 7000.0)
        self.assertAlmostEqual(float(revenue_b.facts["previous_revenue"]), 21000.0)

    def test_batch_run_covers_every_active_restaurant(self) -> None:
        summary = generate_all_briefings(
            self.session, now=self.now, comparison=self.comparison
        )
        self.assertEqual(summary.restaurants_scanned, 2)
        self.assertEqual(summary.briefings_created, 2)
        self.assertEqual(summary.template_narrations, 2)
        self.assertEqual(summary.llm_narrations, 0)
        self.assertGreater(summary.insights_created, 0)

    def test_a_quiet_period_still_produces_a_briefing(self) -> None:
        """A quiet restaurant is not a failed one.

        These runs used to be skipped, so an owner with little trade opened the
        AI manager every day to an empty screen and no explanation — the
        feature looked broken rather than honest. A briefing is recorded now:
        it describes whatever trade there was, and the data-quality notes say
        the volume is below the threshold where trends mean anything.
        """

        summary = generate_all_briefings(self.session, now=self.now)

        self.assertEqual(summary.skipped, 0)
        self.assertEqual(summary.briefings_created, summary.restaurants_scanned)

    def test_thin_data_produces_no_findings_under_that_briefing(self) -> None:
        # The materiality gates are untouched. Including quiet restaurants means
        # publishing what is real, not lowering the bar for what counts. No
        # An explicitly empty window, so the assertion does not depend on where
        # today happens to fall relative to the seeded orders.
        empty = resolve_period_comparison(
            date_from=date(2025, 1, 1), date_to=date(2025, 1, 7)
        )
        result = generate_for_restaurant(
            self.session, scope=self.scope_a, comparison=empty, now=self.now
        )

        self.assertIsNotNone(result.briefing_id)
        self.assertTrue(result.low_confidence)
        self.assertEqual(result.insights_created, 0)

    # -- recommendations ---------------------------------------------------

    def test_no_proposals_are_written_while_the_flag_is_off(self) -> None:
        # The flag is set explicitly rather than inherited from the environment.
        # Reading ambient config made this test assert whatever .env happened to
        # say, so it passed for the wrong reason until actions were switched on
        # for real and it started failing on a change it has nothing to do with.
        with SettingsOverride(enable_ai_manager_actions=False):
            result = self._generate(self.scope_a)

        self.assertEqual(result.proposals_created, 0)
        self.assertEqual(self.session.query(OwnerActionProposal).count(), 0)

    def test_proposals_are_generated_from_fresh_findings(self) -> None:
        with SettingsOverride(enable_ai_manager_actions=True):
            result = self._generate(self.scope_a)

        self.assertGreater(result.proposals_created, 0)
        rows = self.session.scalars(
            select(OwnerActionProposal).where(
                OwnerActionProposal.restaurant_id == self.restaurant_a
            )
        ).all()
        self.assertEqual(len(rows), result.proposals_created)
        for row in rows:
            self.assertEqual(row.status, OwnerActionStatus.PROPOSED)
            self.assertIsNotNone(row.expires_at)

    def test_item_proposal_resolves_a_real_menu_item(self) -> None:
        with SettingsOverride(enable_ai_manager_actions=True):
            self._generate(self.scope_a)

        rows = self.session.scalars(
            select(OwnerActionProposal).where(
                OwnerActionProposal.restaurant_id == self.restaurant_a,
                OwnerActionProposal.action_type == OwnerActionType.PROMOTE_ITEM,
            )
        ).all()
        if not rows:
            self.skipTest("No item-level decline in this scenario")

        payload_item_id = uuid.UUID(rows[0].action_payload["applicable_item_id"])
        owning_restaurant = self.session.scalar(
            select(MenuItem.restaurant_id).where(MenuItem.id == payload_item_id)
        )
        # The offer must point at a dish this restaurant actually sells.
        self.assertEqual(owning_restaurant, self.restaurant_a)

    def test_proposals_link_back_to_the_finding_that_justified_them(self) -> None:
        with SettingsOverride(enable_ai_manager_actions=True):
            result = self._generate(self.scope_a)

        rows = self.session.scalars(
            select(OwnerActionProposal).where(
                OwnerActionProposal.restaurant_id == self.restaurant_a
            )
        ).all()
        linked = [row for row in rows if row.insight_id is not None]
        self.assertTrue(linked)
        for row in linked:
            insight = self.session.get(OwnerInsight, row.insight_id)
            self.assertEqual(insight.restaurant_id, self.restaurant_a)
            self.assertEqual(row.briefing_id, result.briefing_id)

    def test_an_open_proposal_is_not_raised_again(self) -> None:
        with SettingsOverride(enable_ai_manager_actions=True):
            first = self._generate(self.scope_a)
            # Far enough ahead that the insight cooldown has lapsed and the
            # findings are fresh again, but the proposals are still open.
            later = self.now + timedelta(hours=settings.insight_dedupe_cooldown_hours + 1)
            second = self._generate(self.scope_a, now=later)

        self.assertGreater(first.proposals_created, 0)
        self.assertEqual(second.proposals_created, 0)
        self.assertEqual(second.proposals_suppressed, first.proposals_created)

    def test_proposals_are_isolated_between_restaurants(self) -> None:
        with SettingsOverride(enable_ai_manager_actions=True):
            self._generate(self.scope_a)
            self._generate(self.scope_b)

        for restaurant_id in (self.restaurant_a, self.restaurant_b):
            rows = self.session.scalars(
                select(OwnerActionProposal).where(
                    OwnerActionProposal.restaurant_id == restaurant_id
                )
            ).all()
            self.assertTrue(rows)
            for row in rows:
                self.assertEqual(row.restaurant_id, restaurant_id)

    # -- endpoints ---------------------------------------------------------

    def _client_as(self, user_id: uuid.UUID) -> TestClient:
        session_factory = self.session_factory

        def override_db():
            with session_factory() as session:
                yield session

        def override_current_user() -> User:
            with session_factory() as session:
                return session.get(User, user_id)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def test_briefing_endpoint_returns_the_latest_briefing(self) -> None:
        self._generate(self.scope_a)
        response = self._client_as(self.owner_a_id).get("/api/owner/insights/briefing")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["restaurant_id"], str(self.restaurant_a))
        self.assertEqual(body["narration_source"], "TEMPLATE")
        self.assertTrue(body["insights"])

    def test_briefing_endpoint_404s_before_any_run(self) -> None:
        response = self._client_as(self.owner_a_id).get("/api/owner/insights/briefing")
        self.assertEqual(response.status_code, 404)

    def test_feed_shows_only_the_callers_restaurant(self) -> None:
        self._generate(self.scope_a)
        self._generate(self.scope_b)

        body_a = self._client_as(self.owner_a_id).get("/api/owner/insights/feed").json()
        subjects_a = {row["title"] for row in body_a}
        self.assertTrue(body_a)

        app.dependency_overrides.clear()
        body_b = self._client_as(self.owner_b_id).get("/api/owner/insights/feed").json()
        subjects_b = {row["title"] for row in body_b}
        self.assertTrue(body_b)

        for row in body_a:
            self.assertNotIn("Pepperoni", row["body"])
        for row in body_b:
            self.assertNotIn("Margherita", row["body"])
        self.assertNotEqual(subjects_a, subjects_b)

    def test_feed_filters_by_status(self) -> None:
        self._generate(self.scope_a)
        client = self._client_as(self.owner_a_id)
        response = client.get(
            "/api/owner/insights/feed", params={"insight_status": ["DISMISSED"]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_insight_status_can_be_updated(self) -> None:
        self._generate(self.scope_a)
        client = self._client_as(self.owner_a_id)
        feed = client.get("/api/owner/insights/feed").json()
        insight_id = feed[0]["id"]

        response = client.patch(
            f"/api/owner/insights/feed/{insight_id}", json={"status": "DISMISSED"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "DISMISSED")
        self.assertIsNotNone(body["acknowledged_at"])

    def test_cannot_update_another_restaurants_insight(self) -> None:
        self._generate(self.scope_b)
        with self.session_factory() as session:
            insight_b = session.scalars(
                select(OwnerInsight).where(OwnerInsight.restaurant_id == self.restaurant_b)
            ).first()

        client = self._client_as(self.owner_a_id)
        response = client.patch(
            f"/api/owner/insights/feed/{insight_b.id}", json={"status": "DISMISSED"}
        )
        # Scoped lookup, so it is indistinguishable from a missing row.
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
