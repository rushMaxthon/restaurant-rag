"""SQL-layer tests for the insights metrics.

Two tiers:

* Query-shape guards compile every metric query and assert the tenancy
  predicate and business-timezone conversion are present. They need no
  database, so a cross-restaurant isolation regression is caught even in an
  environment where Postgres is unavailable.
* Integration tests run the real aggregates against a throwaway Postgres
  database seeded with two restaurants. They are skipped automatically when no
  database is reachable.
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

from app.main import app  # imported first to settle import order
from app.config import get_settings
from app.config.database import get_db
from app.models.base import Base
from app.models.enums import (
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
from app.services.auth import get_current_user
from app.services.insights import metrics as metrics_layer
from app.services.insights.periods import build_period
from app.services.insights.scope import InsightsScope, resolve_insights_scope
from app.services.insights.service import build_diagnostics_snapshot
from app.services.insights.periods import PeriodComparison
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()

TEST_DB_NAME = os.environ.get("INSIGHTS_TEST_DB", "restaurant_rag_insights_test")
IST = ZoneInfo("Asia/Kolkata")

# The scenario windows. Both are whole weeks so weekday comparisons are
# like-for-like.
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
    try:
        engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with engine.connect():
            return True
    except Exception:  # noqa: BLE001 - any connection failure means "skip"
        return False
    finally:
        try:
            engine.dispose()
        except Exception:  # noqa: BLE001
            pass


def ist(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=IST)


# --- query-shape guards ----------------------------------------------------


class QueryShapeTests(unittest.TestCase):
    """Every metric query must be tenant-scoped and timezone-correct."""

    def setUp(self) -> None:
        self.scope = InsightsScope(restaurant_id=uuid.uuid4())
        self.scoped_to_branch = InsightsScope(
            restaurant_id=uuid.uuid4(), restaurant_location_id=uuid.uuid4()
        )
        self.period = build_period(CURRENT_START, CURRENT_END, timezone_name="Asia/Kolkata")

    def _compiled(self, query) -> str:
        # SQLAlchemy renders a literal-bound uuid without dashes, so comparisons
        # below use the hex form.
        return str(query.compile(compile_kwargs={"literal_binds": True}))

    def _all_queries(self, scope: InsightsScope) -> dict[str, object]:
        return {
            "totals": metrics_layer.totals_query(scope, self.period),
            "cancellations": metrics_layer.cancellations_query(scope, self.period),
            "daily_series": metrics_layer.daily_series_query(scope, self.period),
            "items": metrics_layer.item_metrics_query(scope, self.period),
            "categories": metrics_layer.category_metrics_query(scope, self.period),
            "hours": metrics_layer.hour_metrics_query(scope, self.period),
            "weekdays": metrics_layer.weekday_metrics_query(scope, self.period),
            "cohorts": metrics_layer.customer_cohort_query(scope, self.period),
            "series_range": metrics_layer.daily_series_range_query(
                scope, self.period, self.period
            ),
            "locations": metrics_layer.location_metrics_query(scope, self.period),
            "coverage": metrics_layer.coverage_query(scope, self.period),
            "payment_failures": metrics_layer.payment_failure_query(scope, self.period),
        }

    def test_every_query_filters_by_restaurant(self) -> None:
        for name, query in self._all_queries(self.scope).items():
            with self.subTest(query=name):
                sql = self._compiled(query)
                self.assertIn("orders.restaurant_id", sql)
                self.assertIn(self.scope.restaurant_id.hex, sql)

    def test_branch_scope_adds_location_filter(self) -> None:
        for name, query in self._all_queries(self.scoped_to_branch).items():
            with self.subTest(query=name):
                sql = self._compiled(query)
                self.assertIn("orders.restaurant_location_id", sql)
                self.assertIn(self.scoped_to_branch.restaurant_location_id.hex, sql)

    def test_cohort_lookback_subquery_is_also_scoped(self) -> None:
        # The first-order subquery scans all history, so an unscoped version
        # would leak another restaurant's customers into the new/returning split.
        sql = self._compiled(metrics_layer.customer_cohort_query(self.scope, self.period))
        self.assertEqual(sql.count(self.scope.restaurant_id.hex), 2)

    def test_location_query_filters_orders_not_just_groups_by_branch(self) -> None:
        # Grouping by `orders.restaurant_location_id` puts the column in the SQL
        # whether or not it is filtered on, so the branch-scoped assertion above
        # would pass even with the predicate missing. This checks the WHERE.
        sql = self._compiled(
            metrics_layer.location_metrics_query(self.scoped_to_branch, self.period)
        )
        where_clause = sql.split("WHERE", 1)[1]
        self.assertIn(self.scoped_to_branch.restaurant_location_id.hex, where_clause)
        self.assertIn(self.scoped_to_branch.restaurant_id.hex, where_clause)

    def test_payment_failure_query_excludes_operational_cancellations(self) -> None:
        # Only the payment reasons, so a kitchen cancellation is not presented
        # as recoverable money.
        sql = self._compiled(metrics_layer.payment_failure_query(self.scope, self.period))
        self.assertIn("PAYMENT_NOT_COMPLETED", sql)
        self.assertIn("PAYMENT_ABANDONED", sql)
        self.assertIn("PAYMENT_FAILED", sql)
        self.assertIn("PAYMENT_PENDING", sql)

    def test_time_buckets_use_the_business_timezone(self) -> None:
        for name in ("daily_series", "hours", "weekdays", "series_range", "coverage"):
            with self.subTest(query=name):
                sql = self._compiled(self._all_queries(self.scope)[name])
                self.assertIn("timezone", sql)
                self.assertIn("Asia/Kolkata", sql)

    def test_revenue_queries_exclude_cancelled_and_pending(self) -> None:
        for name in ("totals", "daily_series", "items", "categories", "hours", "weekdays"):
            with self.subTest(query=name):
                sql = self._compiled(self._all_queries(self.scope)[name])
                self.assertNotIn("CANCELLED", sql)
                self.assertNotIn("PAYMENT_PENDING", sql)

    def test_counted_statuses_ignore_unknown_configuration(self) -> None:
        previous = settings.insights_counted_order_statuses
        try:
            settings.insights_counted_order_statuses = "DELIVERED,CANCELLED,NOT_A_STATUS"
            counted = metrics_layer.counted_order_statuses()
            self.assertEqual(counted, (OrderStatus.DELIVERED,))
        finally:
            settings.insights_counted_order_statuses = previous


# --- integration -----------------------------------------------------------


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class MetricsIntegrationTests(unittest.TestCase):
    engine = None
    session_factory = None
    restaurant_a: uuid.UUID
    restaurant_b: uuid.UUID
    location_a1: uuid.UUID
    location_a2: uuid.UUID
    owner_a_id: uuid.UUID
    owner_b_id: uuid.UUID

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
    def _make_user(cls, session: Session, name: str, email: str, role: UserRole) -> User:
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
    def _make_restaurant(cls, session: Session, owner: User, name: str, slug: str) -> Restaurant:
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

    @classmethod
    def _make_location(
        cls, session: Session, restaurant: Restaurant, branch_name: str
    ) -> RestaurantLocation:
        location = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            branch_name=branch_name,
            address_line_1="1 Test Street",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
        )
        session.add(location)
        return location

    @classmethod
    def _make_menu_item(
        cls,
        session: Session,
        restaurant: Restaurant,
        location: RestaurantLocation,
        name: str,
        category: str,
        price: str,
    ) -> MenuItem:
        menu_item = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            name=name,
            category=category,
            price=Decimal(price),
        )
        session.add(menu_item)
        return menu_item

    @classmethod
    def _make_order(
        cls,
        session: Session,
        *,
        customer: User,
        restaurant: Restaurant,
        location: RestaurantLocation,
        placed_at: datetime,
        status: OrderStatus,
        menu_item: MenuItem | None = None,
        quantity: int = 1,
        unit_price: str = "0.00",
        total_amount: str | None = None,
    ) -> Order:
        line_total = Decimal(unit_price) * quantity
        resolved_total = Decimal(total_amount) if total_amount is not None else line_total
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
            total_amount=resolved_total,
            currency="INR",
            delivery_address="1 Test Street",
            placed_at=placed_at,
        )
        session.add(order)
        session.flush()
        if menu_item is not None:
            session.add(
                OrderItem(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    menu_item_id=menu_item.id,
                    item_name_snapshot=menu_item.name,
                    quantity=quantity,
                    base_unit_price=Decimal(unit_price),
                    customization_total_price=Decimal("0.00"),
                    unit_price=Decimal(unit_price),
                    total_price=line_total,
                    selected_options_snapshot=[],
                )
            )
        return order

    @classmethod
    def _seed(cls, session: Session) -> None:
        owner_a = cls._make_user(session, "Owner A", "owner-a@test.local", UserRole.OWNER)
        owner_b = cls._make_user(session, "Owner B", "owner-b@test.local", UserRole.OWNER)
        customer_1 = cls._make_user(session, "Regular", "c1@test.local", UserRole.CUSTOMER)
        customer_2 = cls._make_user(session, "Newcomer", "c2@test.local", UserRole.CUSTOMER)
        customer_b = cls._make_user(session, "B Customer", "cb@test.local", UserRole.CUSTOMER)
        session.flush()

        restaurant_a = cls._make_restaurant(session, owner_a, "Restaurant A", "restaurant-a")
        restaurant_b = cls._make_restaurant(session, owner_b, "Restaurant B", "restaurant-b")
        session.flush()

        location_a1 = cls._make_location(session, restaurant_a, "A - Indiranagar")
        location_a2 = cls._make_location(session, restaurant_a, "A - Koramangala")
        location_b1 = cls._make_location(session, restaurant_b, "B - Main")
        session.flush()

        # The same dish exists at both branches as separate rows, which is what
        # the dish-key collapse in `item_metrics_query` has to survive.
        pizza_a1 = cls._make_menu_item(
            session, restaurant_a, location_a1, "Margherita Pizza", "Pizza", "500.00"
        )
        pizza_a2 = cls._make_menu_item(
            session, restaurant_a, location_a2, "Margherita Pizza", "Pizza", "500.00"
        )
        pasta_a2 = cls._make_menu_item(
            session, restaurant_a, location_a2, "Pasta Alfredo", "Pasta", "300.00"
        )
        burger_b = cls._make_menu_item(
            session, restaurant_b, location_b1, "Cheeseburger", "Burgers", "1000.00"
        )
        session.flush()

        # Previous week: pizza every evening, pasta every lunchtime, all from the
        # one regular customer.
        for offset in range(7):
            day = PREVIOUS_START + timedelta(days=offset)
            cls._make_order(
                session,
                customer=customer_1,
                restaurant=restaurant_a,
                location=location_a1,
                placed_at=ist(day, 20),
                status=OrderStatus.DELIVERED,
                menu_item=pizza_a1,
                unit_price="500.00",
            )
            cls._make_order(
                session,
                customer=customer_1,
                restaurant=restaurant_a,
                location=location_a2,
                placed_at=ist(day, 13),
                status=OrderStatus.DELIVERED,
                menu_item=pasta_a2,
                unit_price="300.00",
            )

        # Current week: pizza drops from 7 evenings to 5, pasta holds steady.
        for day_number in (9, 10, 13, 14):
            cls._make_order(
                session,
                customer=customer_2,
                restaurant=restaurant_a,
                location=location_a1,
                placed_at=ist(date(2026, 3, day_number), 20),
                status=OrderStatus.DELIVERED,
                menu_item=pizza_a1,
                unit_price="500.00",
            )
        cls._make_order(
            session,
            customer=customer_2,
            restaurant=restaurant_a,
            location=location_a2,
            placed_at=ist(date(2026, 3, 15), 20),
            status=OrderStatus.DELIVERED,
            menu_item=pizza_a2,
            unit_price="500.00",
        )
        for day_number in (9, 10, 11, 13, 14, 15):
            cls._make_order(
                session,
                customer=customer_1,
                restaurant=restaurant_a,
                location=location_a2,
                placed_at=ist(date(2026, 3, day_number), 13),
                status=OrderStatus.DELIVERED,
                menu_item=pasta_a2,
                unit_price="300.00",
            )
        # 01:30 IST on 12 March is 20:00 UTC on 11 March. Under UTC bucketing it
        # would land on the wrong day and in the evening hour bucket.
        cls._make_order(
            session,
            customer=customer_1,
            restaurant=restaurant_a,
            location=location_a2,
            placed_at=ist(date(2026, 3, 12), 1, 30),
            status=OrderStatus.DELIVERED,
            menu_item=pasta_a2,
            unit_price="300.00",
        )

        # Noise that must never reach revenue.
        cls._make_order(
            session,
            customer=customer_2,
            restaurant=restaurant_a,
            location=location_a1,
            placed_at=ist(date(2026, 3, 11), 21),
            status=OrderStatus.CANCELLED,
            menu_item=pizza_a1,
            quantity=10,
            unit_price="500.00",
            total_amount="5000.00",
        )
        cls._make_order(
            session,
            customer=customer_2,
            restaurant=restaurant_a,
            location=location_a1,
            placed_at=ist(date(2026, 3, 12), 19),
            status=OrderStatus.PAYMENT_PENDING,
            menu_item=pizza_a1,
            quantity=6,
            unit_price="500.00",
            total_amount="3000.00",
        )

        # A busier neighbour that must never show up in Restaurant A's numbers.
        for offset in range(7):
            for _ in range(3):
                cls._make_order(
                    session,
                    customer=customer_b,
                    restaurant=restaurant_b,
                    location=location_b1,
                    placed_at=ist(CURRENT_START + timedelta(days=offset), 12),
                    status=OrderStatus.DELIVERED,
                    menu_item=burger_b,
                    unit_price="1000.00",
                )

        session.commit()

        cls.restaurant_a = restaurant_a.id
        cls.restaurant_b = restaurant_b.id
        cls.location_a1 = location_a1.id
        cls.location_a2 = location_a2.id
        cls.owner_a_id = owner_a.id
        cls.owner_b_id = owner_b.id

    # -- helpers ----------------------------------------------------------

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)
        self.scope_a = InsightsScope(restaurant_id=self.restaurant_a)
        self.scope_b = InsightsScope(restaurant_id=self.restaurant_b)
        self.current = build_period(CURRENT_START, CURRENT_END, timezone_name="Asia/Kolkata")
        self.previous = build_period(PREVIOUS_START, PREVIOUS_END, timezone_name="Asia/Kolkata")

    # -- totals and status filtering --------------------------------------

    def test_totals_exclude_cancelled_and_payment_pending(self) -> None:
        totals = metrics_layer.fetch_totals(self.session, self.scope_a, self.current)
        # 5 pizzas at 500 plus 7 pastas at 300. The 5,000 cancelled order and the
        # 3,000 unpaid checkout are both absent.
        self.assertEqual(totals.orders, 12)
        self.assertAlmostEqual(totals.gross_revenue, 4600.0)
        self.assertAlmostEqual(totals.item_revenue, 4600.0)
        self.assertEqual(totals.items_sold, 12)
        self.assertEqual(totals.customers, 2)

    def test_previous_period_totals(self) -> None:
        totals = metrics_layer.fetch_totals(self.session, self.scope_a, self.previous)
        self.assertEqual(totals.orders, 14)
        self.assertAlmostEqual(totals.gross_revenue, 5600.0)
        self.assertEqual(totals.customers, 1)

    def test_cancellations_are_reported_separately(self) -> None:
        cancellations = metrics_layer.fetch_cancellations(self.session, self.scope_a, self.current)
        self.assertEqual(cancellations.cancelled_orders, 1)
        self.assertAlmostEqual(cancellations.cancelled_value, 5000.0)

    # -- isolation --------------------------------------------------------

    def test_restaurant_totals_are_isolated(self) -> None:
        totals_a = metrics_layer.fetch_totals(self.session, self.scope_a, self.current)
        totals_b = metrics_layer.fetch_totals(self.session, self.scope_b, self.current)
        self.assertAlmostEqual(totals_a.gross_revenue, 4600.0)
        self.assertAlmostEqual(totals_b.gross_revenue, 21000.0)
        self.assertEqual(totals_b.orders, 21)

    def test_no_cross_restaurant_items_leak(self) -> None:
        items_a = metrics_layer.fetch_item_metrics(self.session, self.scope_a, self.current)
        names = {row.name for row in items_a}
        self.assertNotIn("Cheeseburger", names)

    def test_owner_cannot_scope_to_another_restaurant(self) -> None:
        owner_a = self.session.get(User, self.owner_a_id)
        with self.assertRaises(HTTPException) as raised:
            resolve_insights_scope(
                self.session, current_user=owner_a, restaurant_id=self.restaurant_b
            )
        self.assertEqual(raised.exception.status_code, 403)

    def test_owner_scope_resolves_to_own_restaurant(self) -> None:
        owner_a = self.session.get(User, self.owner_a_id)
        scope = resolve_insights_scope(self.session, current_user=owner_a)
        self.assertEqual(scope.restaurant_id, self.restaurant_a)

    def test_branch_from_another_restaurant_is_rejected(self) -> None:
        owner_b = self.session.get(User, self.owner_b_id)
        with self.assertRaises(HTTPException) as raised:
            resolve_insights_scope(
                self.session,
                current_user=owner_b,
                restaurant_location_id=self.location_a1,
            )
        self.assertEqual(raised.exception.status_code, 404)

    # -- location scoping --------------------------------------------------

    def test_location_filter_narrows_to_one_branch(self) -> None:
        branch_scope = InsightsScope(
            restaurant_id=self.restaurant_a, restaurant_location_id=self.location_a1
        )
        totals = metrics_layer.fetch_totals(self.session, branch_scope, self.current)
        self.assertEqual(totals.orders, 4)
        self.assertAlmostEqual(totals.gross_revenue, 2000.0)

    # -- timezone correctness ---------------------------------------------

    def test_after_midnight_order_buckets_to_the_local_day(self) -> None:
        series = metrics_layer.fetch_daily_series(self.session, self.scope_a, self.current)
        by_day = {point.day: point for point in series}
        # 01:30 IST on 12 March is 20:00 UTC on 11 March. UTC bucketing would put
        # this order on the 11th and leave the 12th empty.
        self.assertIn(date(2026, 3, 12), by_day)
        self.assertEqual(by_day[date(2026, 3, 12)].orders, 1)
        self.assertEqual(by_day[date(2026, 3, 11)].orders, 1)

    def test_hour_buckets_use_local_time(self) -> None:
        hours = metrics_layer.fetch_hour_metrics(self.session, self.scope_a, self.current)
        by_hour = {row.hour: row.orders for row in hours}
        self.assertEqual(by_hour.get(20), 5)
        self.assertEqual(by_hour.get(13), 6)
        self.assertEqual(by_hour.get(1), 1)
        # The 01:30 IST order sits at 20:00 UTC; if that hour held 2 orders the
        # conversion silently did not happen.
        self.assertNotEqual(by_hour.get(20), 6)

    def test_dayparts_reflect_local_hours(self) -> None:
        hours = metrics_layer.fetch_hour_metrics(self.session, self.scope_a, self.current)
        by_daypart = {row.daypart: row for row in metrics_layer.rollup_dayparts(hours)}
        self.assertEqual(by_daypart["Dinner"].orders, 5)
        self.assertEqual(by_daypart["Lunch"].orders, 6)
        self.assertEqual(by_daypart["Late night"].orders, 1)

    def test_weekday_buckets_match_local_calendar(self) -> None:
        weekdays = metrics_layer.fetch_weekday_metrics(self.session, self.scope_a, self.current)
        by_weekday = {row.iso_weekday: row for row in weekdays}
        # 12 March 2026 is a Thursday, and its only order is the 01:30 one.
        self.assertEqual(date(2026, 3, 12).isoweekday(), 4)
        self.assertEqual(by_weekday[4].orders, 1)
        self.assertEqual(by_weekday[4].weekday_name, "Thursday")

    # -- item and category grain ------------------------------------------

    def test_branch_duplicates_collapse_to_one_dish(self) -> None:
        items = metrics_layer.fetch_item_metrics(self.session, self.scope_a, self.current)
        names = [row.name for row in items]
        self.assertEqual(sorted(names), ["Margherita Pizza", "Pasta Alfredo"])
        pizza = next(row for row in items if row.name == "Margherita Pizza")
        # Four orders from one branch and one from the other, counted once.
        self.assertEqual(pizza.orders, 5)
        self.assertAlmostEqual(pizza.revenue, 2500.0)

    def test_category_revenue(self) -> None:
        categories = metrics_layer.fetch_category_metrics(self.session, self.scope_a, self.current)
        by_category = {row.category: row for row in categories}
        self.assertAlmostEqual(by_category["Pizza"].revenue, 2500.0)
        self.assertAlmostEqual(by_category["Pasta"].revenue, 2100.0)

    # -- customer cohorts --------------------------------------------------

    def test_new_versus_returning_split(self) -> None:
        cohorts = metrics_layer.fetch_customer_cohorts(self.session, self.scope_a, self.current)
        by_cohort = {row.cohort: row for row in cohorts}
        # The newcomer's first ever order at this restaurant is inside the window.
        self.assertEqual(by_cohort["new"].customers, 1)
        self.assertEqual(by_cohort["new"].orders, 5)
        self.assertAlmostEqual(by_cohort["new"].revenue, 2500.0)
        # The regular first ordered in the previous week, so they are returning.
        self.assertEqual(by_cohort["returning"].orders, 7)
        self.assertAlmostEqual(by_cohort["returning"].revenue, 2100.0)

    def test_cohort_revenue_sums_to_gross(self) -> None:
        cohorts = metrics_layer.fetch_customer_cohorts(self.session, self.scope_a, self.current)
        totals = metrics_layer.fetch_totals(self.session, self.scope_a, self.current)
        self.assertAlmostEqual(sum(row.revenue for row in cohorts), totals.gross_revenue)

    # -- full snapshot -----------------------------------------------------

    def _snapshot(self, scope: InsightsScope):
        comparison = PeriodComparison(
            current=self.current,
            previous=self.previous,
            timezone_name="Asia/Kolkata",
            weekday_aligned=True,
            includes_partial_day=False,
        )
        return build_diagnostics_snapshot(self.session, scope=scope, comparison=comparison)

    def test_snapshot_headline_deltas(self) -> None:
        snapshot = self._snapshot(self.scope_a)
        by_metric = {row.metric: row for row in snapshot.headline}

        revenue = by_metric["gross_revenue"]
        self.assertAlmostEqual(revenue.current, 4600.0)
        self.assertAlmostEqual(revenue.previous, 5600.0)
        self.assertAlmostEqual(revenue.absolute_change, -1000.0)
        self.assertAlmostEqual(revenue.percent_change, -17.857142857, places=6)
        self.assertEqual(revenue.direction, "down")
        self.assertTrue(revenue.sufficient_data)

        orders = by_metric["orders"]
        self.assertAlmostEqual(orders.absolute_change, -2.0)

        cancelled = by_metric["cancelled_orders"]
        self.assertAlmostEqual(cancelled.current, 1.0)
        self.assertAlmostEqual(cancelled.previous, 0.0)

    def test_snapshot_attributes_the_drop_to_pizza(self) -> None:
        snapshot = self._snapshot(self.scope_a)
        items = next(row for row in snapshot.breakdowns if row.dimension == "item")

        self.assertAlmostEqual(items.parent_change, -1000.0)
        top = items.contributions[0]
        self.assertEqual(top.label, "Margherita Pizza")
        self.assertAlmostEqual(top.absolute_change, -1000.0)
        # Pasta held steady, so pizza explains the entire decline.
        self.assertAlmostEqual(top.contribution_share, 100.0)
        self.assertAlmostEqual(top.percent_change, -28.571428571, places=6)

    def test_snapshot_category_and_cohort_breakdowns(self) -> None:
        snapshot = self._snapshot(self.scope_a)
        by_dimension = {row.dimension: row for row in snapshot.breakdowns}

        categories = {row.label: row for row in by_dimension["category"].contributions}
        self.assertAlmostEqual(categories["Pizza"].absolute_change, -1000.0)
        self.assertAlmostEqual(categories["Pasta"].absolute_change, 0.0)

        cohorts = {row.label: row for row in by_dimension["customer_cohort"].contributions}
        self.assertAlmostEqual(cohorts["Returning customers"].absolute_change, 2100.0)
        self.assertAlmostEqual(cohorts["New customers"].absolute_change, -3100.0)
        # Offsetting cohort movements must still net to the gross change.
        self.assertAlmostEqual(
            sum(row.absolute_change for row in by_dimension["customer_cohort"].contributions),
            -1000.0,
        )

    def test_snapshot_dinner_daypart_carries_the_decline(self) -> None:
        snapshot = self._snapshot(self.scope_a)
        dayparts = {
            row.label: row
            for row in next(
                item for item in snapshot.breakdowns if item.dimension == "daypart"
            ).contributions
        }
        self.assertAlmostEqual(dayparts["Dinner"].absolute_change, -1000.0)

    def test_snapshot_is_isolated_between_restaurants(self) -> None:
        snapshot_a = self._snapshot(self.scope_a)
        snapshot_b = self._snapshot(self.scope_b)

        revenue_a = next(row for row in snapshot_a.headline if row.metric == "gross_revenue")
        revenue_b = next(row for row in snapshot_b.headline if row.metric == "gross_revenue")
        self.assertAlmostEqual(revenue_a.current, 4600.0)
        self.assertAlmostEqual(revenue_b.current, 21000.0)

        labels_a = {
            row.label
            for breakdown in snapshot_a.breakdowns
            for row in breakdown.contributions
        }
        self.assertNotIn("Cheeseburger", labels_a)
        self.assertEqual(snapshot_a.scope.restaurant_id, self.restaurant_a)

    def test_snapshot_reports_no_history_for_anomaly_detection(self) -> None:
        # Nothing was seeded before the comparison windows, so the baseline is
        # all zeros and the layer must decline to call anomalies rather than
        # flagging every day as a collapse.
        snapshot = self._snapshot(self.scope_a)
        self.assertFalse(snapshot.anomalies.evaluated)
        self.assertIsNotNone(snapshot.anomalies.note)

    def test_snapshot_declares_the_counted_statuses(self) -> None:
        snapshot = self._snapshot(self.scope_a)
        self.assertNotIn("CANCELLED", snapshot.data_quality.counted_order_statuses)
        self.assertNotIn("PAYMENT_PENDING", snapshot.data_quality.counted_order_statuses)

    # -- route wiring ------------------------------------------------------

    def _client_as(self, user_id: uuid.UUID) -> TestClient:
        """A test client authenticated as one user, backed by the seeded database."""

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

    def test_endpoint_returns_a_snapshot_for_the_owner(self) -> None:
        client = self._client_as(self.owner_a_id)
        response = client.get(
            "/api/owner/insights/diagnostics",
            params={
                "date_from": CURRENT_START.isoformat(),
                "date_to": CURRENT_END.isoformat(),
                "refresh": "true",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["scope"]["restaurant_id"], str(self.restaurant_a))
        revenue = next(row for row in body["headline"] if row["metric"] == "gross_revenue")
        self.assertAlmostEqual(revenue["current"], 4600.0)
        self.assertAlmostEqual(revenue["previous"], 5600.0)

    def test_endpoint_refuses_another_restaurant(self) -> None:
        client = self._client_as(self.owner_a_id)
        response = client.get(
            "/api/owner/insights/diagnostics",
            params={
                "restaurant_id": str(self.restaurant_b),
                "date_from": CURRENT_START.isoformat(),
                "date_to": CURRENT_END.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_endpoint_accepts_a_branch_filter(self) -> None:
        client = self._client_as(self.owner_a_id)
        response = client.get(
            "/api/owner/insights/diagnostics",
            params={
                "restaurant_location_id": str(self.location_a1),
                "date_from": CURRENT_START.isoformat(),
                "date_to": CURRENT_END.isoformat(),
                "refresh": "true",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        orders = next(row for row in body["headline"] if row["metric"] == "orders")
        self.assertAlmostEqual(orders["current"], 4.0)


if __name__ == "__main__":
    unittest.main()
