"""What the admin's Platform watch says is wrong, and who may ask.

Each rule here was a problem found by somebody other than the admin first:
paid orders sitting in New, a branch open with nothing to order, the
scheduler silently stopped. The tests pin that each is noticed, that each
quiet case stays quiet, and that the page is the admin's alone.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import (  # noqa: E402
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.menu_item import MenuItem  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.restaurant import Restaurant  # noqa: E402
from app.models.restaurant_location import RestaurantLocation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import platform_watch  # noqa: E402
from app.services.auth import get_current_user  # noqa: E402

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_platform_watch_test"


def _url(database: str) -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/{database}"
    )


def postgres_available() -> bool:
    engine = None
    try:
        engine = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with engine.connect():
            return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if engine is not None:
            engine.dispose()


class WhoMayLookTests(unittest.TestCase):
    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _as(self, role: UserRole) -> int:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(), role=role, is_active=True, restaurant_id=None
        )
        return TestClient(app).get("/api/admin/platform-watch").status_code

    def test_an_owner_is_refused(self) -> None:
        self.assertEqual(self._as(UserRole.OWNER), 403)

    def test_a_customer_is_refused(self) -> None:
        self.assertEqual(self._as(UserRole.CUSTOMER), 403)


class TheSchedulerCheckTests(unittest.TestCase):
    """Beat stopping is invisible except through this."""

    def _with(self, raw):
        redis = mock.Mock()
        redis.get.return_value = raw
        with mock.patch.object(platform_watch, "_redis", return_value=redis):
            return platform_watch._check_scheduler(datetime.now(UTC))

    def test_never_seen_is_down_and_says_what_stops(self) -> None:
        check = self._with(None)
        self.assertEqual(check.status, platform_watch.DOWN)
        self.assertIn("stock refill", check.hint)

    def test_a_recent_heartbeat_is_ok(self) -> None:
        self.assertEqual(self._with(datetime.now(UTC).isoformat().encode()).status, platform_watch.OK)

    def test_a_stale_heartbeat_is_down(self) -> None:
        stale = (datetime.now(UTC) - timedelta(minutes=12)).isoformat().encode()
        check = self._with(stale)
        self.assertEqual(check.status, platform_watch.DOWN)
        self.assertIn("12 min", check.detail)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class WhatNeedsAttentionTests(unittest.TestCase):
    engine = None
    session_factory = None

    @classmethod
    def setUpClass(cls) -> None:
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin.dispose()
        cls.engine = create_engine(_url(TEST_DB_NAME))
        with cls.engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
        Base.metadata.create_all(cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.engine is not None:
            cls.engine.dispose()
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin.dispose()

    def setUp(self) -> None:
        with self.session_factory() as session:
            for table in reversed(Base.metadata.sorted_tables):
                session.execute(table.delete())
            session.commit()
        # Payment setup is its own subsystem with its own tests. Here a branch
        # can always take a card unless a test says otherwise.
        patcher = mock.patch(
            "app.services.payments.registry.available_payment_methods",
            return_value=[PaymentMethod.CARD],
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = datetime.now(UTC)

    def _restaurant(self, *, approved=True, dishes=1, located=True, fee="40", commission="10"):
        with self.session_factory() as session:
            owner = User(
                id=uuid.uuid4(), app_client_id=None, full_name="Owner",
                email=f"o-{uuid.uuid4().hex[:8]}@test.local", hashed_password="x", role=UserRole.OWNER,
            )
            session.add(owner)
            session.flush()
            restaurant = Restaurant(
                id=uuid.uuid4(), owner_id=owner.id, name=f"R {uuid.uuid4().hex[:4]}",
                slug=f"r-{uuid.uuid4().hex[:8]}", cuisine_type="Bakery", address_line_1="1 St",
                city="Surat", state="Gujarat", postal_code="395004", is_approved=approved, is_active=True,
            )
            session.add(restaurant)
            session.flush()
            location = RestaurantLocation(
                id=uuid.uuid4(), restaurant_id=restaurant.id, branch_name="Main",
                address_line_1="1 St", city="Surat", state="Gujarat", postal_code="395004",
                latitude=Decimal("21.2") if located else None, longitude=Decimal("72.8") if located else None,
                delivery_fee=Decimal(fee), commission_percent=Decimal(commission), is_open=True,
            )
            session.add(location)
            session.flush()
            for _ in range(dishes):
                session.add(MenuItem(
                    id=uuid.uuid4(), restaurant_id=restaurant.id, restaurant_location_id=location.id,
                    name=f"Dish {uuid.uuid4().hex[:4]}", category="Breads", price=Decimal("55"), is_available=True,
                ))
            customer = User(
                id=uuid.uuid4(), app_client_id=None, full_name="Customer",
                email=f"c-{uuid.uuid4().hex[:8]}@test.local", hashed_password="x", role=UserRole.ADMIN,
            )
            session.add(customer)
            session.commit()
            return restaurant.id, location.id, customer.id

    def _order(self, rid, lid, uid, *, status, payment=PaymentStatus.PAID, minutes_ago=0,
               schedule=OrderScheduleType.ASAP, scheduled_in=0):
        placed = self.now - timedelta(minutes=minutes_ago)
        with self.session_factory() as session:
            session.add(Order(
                id=uuid.uuid4(), customer_id=uid, restaurant_id=rid, restaurant_location_id=lid,
                status=status, payment_status=payment, payment_method=PaymentMethod.CARD,
                fulfillment_type=OrderFulfillmentType.PICKUP, schedule_type=schedule,
                scheduled_at=self.now + timedelta(minutes=scheduled_in), placed_at=placed,
                updated_at=placed, subtotal=Decimal("110"), delivery_fee=Decimal("0"),
                tax_amount=Decimal("0"), discount_amount=Decimal("0"), total_amount=Decimal("110"),
                delivery_address="Pickup",
            ))
            session.commit()

    def _issues(self):
        with self.session_factory() as session:
            return platform_watch.find_issues(session, now=self.now)

    def _keys(self):
        return [issue.key for issue in self._issues()]

    def test_a_healthy_restaurant_raises_nothing(self) -> None:
        self._restaurant()
        self.assertEqual(self._keys(), [])

    def test_a_paid_order_waiting_too_long_is_the_first_thing_said(self) -> None:
        rid, lid, uid = self._restaurant(commission="0")
        self._order(rid, lid, uid, status=OrderStatus.PLACED, minutes_ago=25)
        issues = self._issues()
        self.assertEqual(issues[0].key, "orders_not_accepted")
        self.assertEqual(issues[0].severity, platform_watch.HIGH)
        self.assertIn("25 min", issues[0].detail)

    def test_a_new_order_or_an_unpaid_one_is_not_late(self) -> None:
        rid, lid, uid = self._restaurant()
        self._order(rid, lid, uid, status=OrderStatus.PLACED, minutes_ago=3)
        self._order(rid, lid, uid, status=OrderStatus.PAYMENT_PENDING, payment=PaymentStatus.PENDING, minutes_ago=40)
        self.assertNotIn("orders_not_accepted", self._keys())

    def test_an_order_booked_for_tomorrow_is_not_late_tonight(self) -> None:
        rid, lid, uid = self._restaurant()
        self._order(rid, lid, uid, status=OrderStatus.PLACED, minutes_ago=60,
                    schedule=OrderScheduleType.SCHEDULED, scheduled_in=24 * 60)
        self.assertNotIn("orders_not_accepted", self._keys())

    def test_an_order_left_in_the_kitchen_is_noticed(self) -> None:
        rid, lid, uid = self._restaurant()
        self._order(rid, lid, uid, status=OrderStatus.PREPARING, minutes_ago=90)
        self.assertIn("orders_stuck_kitchen", self._keys())

    def test_a_branch_with_nothing_to_order_is_high(self) -> None:
        self._restaurant(dishes=0)
        issue = next(i for i in self._issues() if i.key == "branch_empty_menu")
        self.assertEqual(issue.severity, platform_watch.HIGH)

    def test_a_branch_that_cannot_take_payment_is_high(self) -> None:
        self._restaurant()
        with mock.patch("app.services.payments.registry.available_payment_methods", return_value=[]):
            self.assertIn("branch_no_payment", self._keys())

    def test_branch_setup_gaps_are_named(self) -> None:
        self._restaurant(located=False, fee="0", commission="0")
        keys = self._keys()
        for key in ("branch_not_on_map", "branch_no_delivery_fee", "branch_no_commission"):
            self.assertIn(key, keys)

    def test_a_restaurant_awaiting_approval_is_listed_but_its_branches_are_not_judged(self) -> None:
        self._restaurant(approved=False, dishes=0)
        keys = self._keys()
        self.assertIn("restaurant_pending", keys)
        self.assertNotIn("branch_empty_menu", keys)

    def test_issues_come_worst_first(self) -> None:
        rid, lid, uid = self._restaurant(commission="0")
        self._order(rid, lid, uid, status=OrderStatus.PLACED, minutes_ago=30)
        order = {platform_watch.HIGH: 0, platform_watch.MEDIUM: 1, platform_watch.LOW: 2}
        ranks = [order[issue.severity] for issue in self._issues()]
        self.assertEqual(ranks, sorted(ranks))

    def test_today_counts_sales_and_leaves_out_unpaid_and_cancelled(self) -> None:
        rid, lid, uid = self._restaurant()
        self._order(rid, lid, uid, status=OrderStatus.DELIVERED)
        self._order(rid, lid, uid, status=OrderStatus.PLACED, minutes_ago=1)
        self._order(rid, lid, uid, status=OrderStatus.CANCELLED, payment=PaymentStatus.CANCELLED)
        self._order(rid, lid, uid, status=OrderStatus.PAYMENT_PENDING, payment=PaymentStatus.PENDING)
        with self.session_factory() as session:
            rows = platform_watch.restaurants_today(session, now=self.now, issues=[])
        row = next(r for r in rows if r.restaurant_id == rid)
        self.assertEqual(row.orders_today, 2)
        self.assertEqual(row.sales_today, Decimal("220.00"))
        self.assertEqual(row.awaiting_accept, 1)
        self.assertEqual((row.branches, row.branches_open), (1, 1))


if __name__ == "__main__":
    unittest.main()
