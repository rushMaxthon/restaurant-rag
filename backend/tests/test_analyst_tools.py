"""Tests for the Phase 8A analyst tool layer.

Two tiers, matching the rest of the insights suite:

* Registry guards need no database. They assert the properties that make the
  layer safe to hand to a caller that generates its own arguments: no tool may
  accept a tenant identifier, nothing may be callable outside the registry, and
  the module must contain no write path.
* Integration tests run every tool against a throwaway Postgres seeded with two
  restaurants, one of which has a closed branch and a payment-failure cluster —
  the shape that made a branch closure read as a declining dish. They are
  skipped automatically when no database is reachable.
"""

from __future__ import annotations

import inspect
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
from app.services.insights.analyst import registry as analyst_registry
from app.services.insights.analyst import tools as analyst_tools
from app.services.insights.analyst.registry import (
    FORBIDDEN_ARGUMENT_NAMES,
    TOOL_LIST,
    TOOLS,
    call_tool,
    describe_tools,
    tool_names,
)
from app.services.insights.analyst.schemas import ALLOWED_WINDOW_DAYS, ToolArgs
from app.services.insights.periods import local_today
from app.services.insights.scope import InsightsScope
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()

TEST_DB_NAME = os.environ.get("ANALYST_TEST_DB", "restaurant_rag_analyst_test")
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
    except Exception:  # noqa: BLE001 - any connection failure means "skip"
        return False
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001
                pass


def local_datetime(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour, 0), tzinfo=TZ)


# --- registry guards -------------------------------------------------------


class RegistryGuardTests(unittest.TestCase):
    """The properties that make this layer safe to expose to a generated caller."""

    def test_no_tool_accepts_a_tenant_identifier(self) -> None:
        # The whole safety story is that scope is injected, never requested. A
        # tool that took a restaurant id would quietly undo it.
        for spec in TOOL_LIST:
            with self.subTest(tool=spec.name):
                offending = set(spec.args_model.model_fields) & FORBIDDEN_ARGUMENT_NAMES
                self.assertEqual(offending, set())

    def test_every_argument_model_forbids_unknown_keys(self) -> None:
        # Rejecting an unexpected key means a smuggled `restaurant_id` fails the
        # call visibly rather than being silently ignored.
        for spec in TOOL_LIST:
            with self.subTest(tool=spec.name):
                self.assertTrue(issubclass(spec.args_model, ToolArgs))
                self.assertEqual(spec.args_model.model_config.get("extra"), "forbid")

    def test_tool_names_are_unique_and_registered(self) -> None:
        self.assertEqual(len(TOOL_LIST), len(TOOLS))
        self.assertEqual(len(set(tool_names())), len(TOOL_LIST))

    def test_handlers_take_scope_positionally(self) -> None:
        for spec in TOOL_LIST:
            with self.subTest(tool=spec.name):
                parameters = list(inspect.signature(spec.handler).parameters)
                self.assertEqual(parameters[:3], ["db", "scope", "args"])

    def test_tools_module_contains_no_write_path(self) -> None:
        # A read-only layer that imports a write helper is one refactor away from
        # not being read-only, so this is asserted against the source itself.
        source = Path(analyst_tools.__file__).read_text()
        for forbidden in (
            "db.add",
            "db.commit",
            "db.delete",
            "db.flush",
            "session.add",
            "create_restaurant_offer",
            "approve_proposal",
            "session.execute(text",
        ):
            with self.subTest(pattern=forbidden):
                self.assertNotIn(forbidden, source)

    def test_registry_rejects_a_scope_bearing_tool(self) -> None:
        from pydantic import ConfigDict

        class LeakyArgs(ToolArgs):
            model_config = ConfigDict(extra="forbid")
            restaurant_id: str

        leaky = analyst_registry._spec("leaky", "", LeakyArgs, lambda db, scope, args: {})
        with self.assertRaises(RuntimeError):
            analyst_registry._validate_registry((leaky,))

    def test_describe_tools_exposes_a_schema_for_every_tool(self) -> None:
        described = describe_tools()
        self.assertEqual(len(described), len(TOOL_LIST))
        for entry in described:
            with self.subTest(tool=entry["name"]):
                self.assertIn("description", entry)
                self.assertIn("properties", entry["arguments"])

    def test_unknown_tool_is_reported_not_raised(self) -> None:
        result = call_tool(None, InsightsScope(restaurant_id=uuid.uuid4()), "drop_tables")
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "unknown_tool")


# --- integration -----------------------------------------------------------


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class AnalystToolIntegrationTests(unittest.TestCase):
    """Every tool, against a seeded two-tenant database."""

    engine = None
    session_factory = None
    restaurant_a: uuid.UUID
    restaurant_b: uuid.UUID
    main_branch: uuid.UUID
    riverside_branch: uuid.UUID

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

    # -- seeding ----------------------------------------------------------

    @classmethod
    def _user(cls, session: Session, name: str, email: str, role: UserRole) -> User:
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

    @classmethod
    def _restaurant(cls, session: Session, owner: User, name: str, slug: str) -> Restaurant:
        restaurant = Restaurant(
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
        session.add(restaurant)
        return restaurant

    @classmethod
    def _location(
        cls,
        session: Session,
        restaurant: Restaurant,
        branch_name: str,
        *,
        is_open: bool = True,
        closed_reason: str | None = None,
    ) -> RestaurantLocation:
        location = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            branch_name=branch_name,
            address_line_1="1 Test Street",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            is_open=is_open,
            temporary_closed_reason=closed_reason,
        )
        session.add(location)
        return location

    @classmethod
    def _menu_item(
        cls,
        session: Session,
        restaurant: Restaurant,
        location: RestaurantLocation,
        name: str,
        category: str,
        price: str,
        *,
        is_available: bool = True,
    ) -> MenuItem:
        item = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            name=name,
            category=category,
            price=Decimal(price),
            is_available=is_available,
        )
        session.add(item)
        return item

    @classmethod
    def _order(
        cls,
        session: Session,
        *,
        customer: User,
        restaurant: Restaurant,
        location: RestaurantLocation,
        placed_at: datetime,
        status: OrderStatus,
        menu_item: MenuItem | None = None,
        unit_price: str = "100.00",
        quantity: int = 1,
        cancellation_reason: OrderCancellationReason | None = None,
    ) -> Order:
        line_total = Decimal(unit_price) * quantity
        order = Order(
            id=uuid.uuid4(),
            customer_id=customer.id,
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            status=status,
            payment_status=PaymentStatus.PAID,
            payment_method=PaymentMethod.CARD,
            payment_provider="test",
            fulfillment_type=OrderFulfillmentType.DELIVERY,
            schedule_type=OrderScheduleType.ASAP,
            scheduled_at=placed_at,
            subtotal=line_total,
            delivery_fee=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=line_total,
            currency="INR",
            delivery_address="1 Test Street",
            placed_at=placed_at,
            cancellation_reason=cancellation_reason,
        )
        session.add(order)
        if menu_item is not None:
            session.add(
                OrderItem(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    menu_item_id=menu_item.id,
                    item_name_snapshot=menu_item.name,
                    unit_price=Decimal(unit_price),
                    quantity=quantity,
                    total_price=line_total,
                )
            )
        return order

    @classmethod
    def _seed(cls, session: Session) -> None:
        today = local_today(settings.business_timezone)
        # Current window is the last 7 complete days; the previous window is the
        # 7 before that.
        current_day = today - timedelta(days=2)
        previous_day = today - timedelta(days=9)

        owner_a = cls._user(session, "Owner A", "owner-a@example.com", UserRole.OWNER)
        owner_b = cls._user(session, "Owner B", "owner-b@example.com", UserRole.OWNER)
        customer_a = cls._user(session, "Cust A", "cust-a@example.com", UserRole.CUSTOMER)
        customer_b = cls._user(session, "Cust B", "cust-b@example.com", UserRole.CUSTOMER)
        session.flush()

        restaurant_a = cls._restaurant(session, owner_a, "Bowl House", "bowl-house")
        restaurant_b = cls._restaurant(session, owner_b, "Rival Kitchen", "rival-kitchen")
        session.flush()

        main = cls._location(session, restaurant_a, "Bowl House Main")
        riverside = cls._location(
            session,
            restaurant_a,
            "Bowl House Riverside",
            is_open=False,
            closed_reason="Refit",
        )
        rival_branch = cls._location(session, restaurant_b, "Rival Kitchen Central")
        session.flush()

        noodles = cls._menu_item(session, restaurant_a, main, "Pad Thai", "Noodles", "100.00")
        soup = cls._menu_item(
            session, restaurant_a, main, "Tom Yum", "Soup", "80.00", is_available=False
        )
        salad = cls._menu_item(
            session, restaurant_a, riverside, "Mango Salad", "Salads", "90.00"
        )
        rival_item = cls._menu_item(
            session, restaurant_b, rival_branch, "Rival Roll", "Rolls", "70.00"
        )
        session.flush()

        # Previous window: Riverside carried the whole business.
        for _ in range(4):
            cls._order(
                session,
                customer=customer_a,
                restaurant=restaurant_a,
                location=riverside,
                placed_at=local_datetime(previous_day, 13),
                status=OrderStatus.DELIVERED,
                menu_item=salad,
                unit_price="90.00",
            )

        # Current window: Riverside is shut and Main carries everything.
        for _ in range(3):
            cls._order(
                session,
                customer=customer_a,
                restaurant=restaurant_a,
                location=main,
                placed_at=local_datetime(current_day, 17),
                status=OrderStatus.DELIVERED,
                menu_item=noodles,
                unit_price="100.00",
            )

        # Money lost at the payment step, not to a competitor.
        cls._order(
            session,
            customer=customer_a,
            restaurant=restaurant_a,
            location=main,
            placed_at=local_datetime(current_day, 18),
            status=OrderStatus.CANCELLED,
            unit_price="150.00",
            cancellation_reason=OrderCancellationReason.PAYMENT_NOT_COMPLETED,
        )
        cls._order(
            session,
            customer=customer_a,
            restaurant=restaurant_a,
            location=main,
            placed_at=local_datetime(current_day, 19),
            status=OrderStatus.PAYMENT_PENDING,
            unit_price="120.00",
        )

        # The other tenant trades in both windows and must never be visible.
        for day in (previous_day, current_day):
            cls._order(
                session,
                customer=customer_b,
                restaurant=restaurant_b,
                location=rival_branch,
                placed_at=local_datetime(day, 12),
                status=OrderStatus.DELIVERED,
                menu_item=rival_item,
                unit_price="70.00",
            )

        session.commit()

        cls.restaurant_a = restaurant_a.id
        cls.restaurant_b = restaurant_b.id
        cls.main_branch = main.id
        cls.riverside_branch = riverside.id
        cls.soup_id = soup.id

    # -- helpers ----------------------------------------------------------

    def scope_a(self) -> InsightsScope:
        return InsightsScope(restaurant_id=self.restaurant_a)

    def scope_main(self) -> InsightsScope:
        return InsightsScope(
            restaurant_id=self.restaurant_a, restaurant_location_id=self.main_branch
        )

    def call(self, name: str, args: dict | None = None, scope: InsightsScope | None = None):
        with self.session_factory() as session:
            return call_tool(session, scope or self.scope_a(), name, args)

    def _default_args(self, spec) -> dict:
        args: dict = {}
        fields = spec.args_model.model_fields
        if "branch_name" in fields:
            args["branch_name"] = "Bowl House Main"
        if "branch_a" in fields:
            args["branch_a"] = "Bowl House Main"
            args["branch_b"] = "Bowl House Riverside"
        if "dimension" in fields:
            args["dimension"] = "location"
        return args

    # -- isolation --------------------------------------------------------

    def test_every_tool_runs_and_leaks_nothing_from_the_other_tenant(self) -> None:
        for spec in TOOL_LIST:
            with self.subTest(tool=spec.name):
                result = self.call(spec.name, self._default_args(spec))
                self.assertTrue(result.ok, msg=f"{spec.name}: {result.error} {result.detail}")
                rendered = repr(result.to_payload())
                self.assertNotIn("Rival", rendered)
                self.assertNotIn(str(self.restaurant_b), rendered)

    def test_branch_of_another_restaurant_does_not_resolve(self) -> None:
        # A 'not found' rather than a permission error: confirming the branch
        # exists but belongs to someone else is itself a disclosure.
        result = self.call("get_branch_metrics", {"branch_name": "Rival Kitchen Central"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "branch_not_found")
        self.assertNotIn("Rival", result.detail or "")

    def test_branch_scoped_analysis_cannot_read_another_branch(self) -> None:
        result = self.call(
            "get_branch_metrics",
            {"branch_name": "Bowl House Riverside"},
            scope=self.scope_main(),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "outside_current_scope")

    def test_branch_scope_narrows_branch_status_and_menu(self) -> None:
        status = self.call("get_branch_status", scope=self.scope_main())
        self.assertEqual([row["branch_name"] for row in status.data["branches"]], ["Bowl House Main"])

        menu = self.call("get_menu_health", scope=self.scope_main())
        self.assertEqual(
            {row["branch_name"] for row in menu.data["items"]}, {"Bowl House Main"}
        )

    # -- the branch-closure scenario --------------------------------------

    def test_location_performance_surfaces_a_branch_that_stopped_trading(self) -> None:
        result = self.call("get_location_performance", {"window_days": 7})
        stopped = [row for row in result.data["branches"] if row.get("stopped_trading")]
        self.assertEqual(len(stopped), 1)
        self.assertEqual(stopped[0]["branch_name"], "Bowl House Riverside")
        self.assertEqual(stopped[0]["previous"]["orders"], 4)
        self.assertEqual(stopped[0]["current"]["revenue"], 0.0)

    def test_location_breakdown_attributes_the_change_to_branches(self) -> None:
        result = self.call("get_breakdown", {"dimension": "location", "window_days": 7})
        labels = {row["label"] for row in result.data["breakdown"]["contributions"]}
        self.assertIn("Bowl House Riverside", labels)
        self.assertIn("Bowl House Main", labels)

    def test_location_dimension_is_absent_when_pinned_to_one_branch(self) -> None:
        result = self.call(
            "get_breakdown", {"dimension": "location"}, scope=self.scope_main()
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "dimension_unavailable")

    def test_branch_status_reports_the_closure(self) -> None:
        result = self.call("get_branch_status")
        riverside = next(
            row for row in result.data["branches"] if row["branch_name"] == "Bowl House Riverside"
        )
        self.assertFalse(riverside["is_open"])
        self.assertEqual(riverside["temporary_closed_reason"], "Refit")

    def test_compare_locations_returns_both_branches(self) -> None:
        result = self.call(
            "compare_locations",
            {"branch_a": "Main", "branch_b": "Riverside", "window_days": 7},
        )
        self.assertTrue(result.ok)
        names = [row["branch_name"] for row in result.data["branches"]]
        self.assertEqual(names, ["Bowl House Main", "Bowl House Riverside"])
        self.assertEqual(result.data["branches"][1]["current"]["orders"], 0)

    # -- payment failures and coverage ------------------------------------

    def test_payment_failures_are_separated_from_lost_demand(self) -> None:
        result = self.call("get_payment_failures", {"window_days": 7})
        self.assertEqual(result.data["lost_orders"], 2)
        self.assertEqual(result.data["lost_value"], 270.0)
        reasons = {row["reason"] for row in result.data["current"]}
        self.assertEqual(reasons, {"PAYMENT_NOT_COMPLETED", "PAYMENT_PENDING"})

    def test_payment_failures_are_excluded_from_counted_revenue(self) -> None:
        # The same orders must not appear in revenue, or the leak would be
        # counted as trade it never became.
        metrics = self.call("get_period_metrics", {"window_days": 7})
        self.assertEqual(metrics.data["current"]["orders"], 3)
        self.assertEqual(metrics.data["current"]["gross_revenue"], 300.0)

    def test_coverage_reports_how_thin_the_window_is(self) -> None:
        result = self.call("get_data_coverage", {"window_days": 7})
        self.assertEqual(result.data["current"]["days_in_window"], 7)
        self.assertEqual(result.data["current"]["trading_days"], 1)
        self.assertEqual(result.data["current"]["orders"], 3)

    def test_menu_health_reports_switched_off_items_and_gaps(self) -> None:
        result = self.call("get_menu_health")
        self.assertEqual(result.data["unavailable_count"], 1)
        gaps = {row["branch_name"]: row["missing_categories"] for row in result.data["category_gaps_by_branch"]}
        self.assertIn("Salads", gaps["Bowl House Main"])
        self.assertIn("Noodles", gaps["Bowl House Riverside"])

    # -- argument handling -------------------------------------------------

    def test_unlisted_window_is_rejected(self) -> None:
        result = self.call("get_period_metrics", {"window_days": 83})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "window_not_allowed")
        self.assertNotIn(83, ALLOWED_WINDOW_DAYS)

    def test_smuggled_scope_argument_fails_the_call(self) -> None:
        result = self.call(
            "get_period_metrics",
            {"window_days": 7, "restaurant_id": str(self.restaurant_b)},
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "invalid_arguments")

    def test_unknown_dimension_is_rejected_by_the_schema(self) -> None:
        result = self.call("get_breakdown", {"dimension": "supplier"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "invalid_arguments")

    # -- read-only ---------------------------------------------------------

    def test_running_every_tool_writes_nothing(self) -> None:
        def counts(session: Session) -> tuple[int, int, int]:
            return (
                session.scalar(select(text("count(*)")).select_from(Order)),
                session.scalar(select(text("count(*)")).select_from(MenuItem)),
                session.scalar(select(text("count(*)")).select_from(RestaurantLocation)),
            )

        with self.session_factory() as session:
            before = counts(session)
            for spec in TOOL_LIST:
                call_tool(session, self.scope_a(), spec.name, self._default_args(spec))
            # IdentitySet does not compare equal to a plain set, so these are
            # emptiness checks rather than equality against one.
            self.assertEqual(list(session.new), [])
            self.assertEqual(list(session.dirty), [])
            self.assertEqual(list(session.deleted), [])
            after = counts(session)

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
