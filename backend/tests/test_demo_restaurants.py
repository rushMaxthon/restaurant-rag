"""Demo restaurants are kept, and left out of what the platform admin reads.

The shared database still carries the seven restaurants seeded on 2026-09-13
to develop against - priced in Canadian dollars, with 427 orders between them.
Beside six real Indian kitchens they made the admin dashboard read as dummy
data, and because their currency differs, every platform total was printed
under a "$" and added rupees to dollars. They are not deleted (the Bangkok
Bowl app client and its WhatsApp setup still point at one of them); they are
marked `is_demo`, and anything the admin reads ACROSS restaurants leaves them
out. Naming one explicitly still answers, so the mark can always be undone.
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
from app.config.database import get_db  # noqa: E402
from app.models.app_client import AppClient  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import (  # noqa: E402
    AppMode,
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.order import Order  # noqa: E402
from app.models.restaurant import Restaurant  # noqa: E402
from app.models.restaurant_location import RestaurantLocation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import platform_watch  # noqa: E402
from app.services.auth import get_current_user  # noqa: E402

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_demo_restaurants_test"


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


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class DemoRestaurantTests(unittest.TestCase):
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
            names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
            session.execute(text(f"TRUNCATE {names} CASCADE"))
            session.commit()
        self.now = datetime.now(UTC)
        self.real, self.real_branch, self.customer = self._restaurant("Bhagwati", currency="INR")
        self.demo, self.demo_branch, _ = self._restaurant("Bangkok Bowl", currency="CAD", demo=True)

        factory = self.session_factory

        def override_db():
            with factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(), role=UserRole.ADMIN, is_active=True, restaurant_id=None
        )
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    # --- fixtures ---------------------------------------------------------

    def _restaurant(self, name: str, *, currency: str, demo: bool = False):
        with self.session_factory() as session:
            owner = User(
                id=uuid.uuid4(), app_client_id=None, full_name=f"{name} Owner",
                email=f"o-{uuid.uuid4().hex[:8]}@test.local", hashed_password="x", role=UserRole.OWNER,
            )
            customer = User(
                id=uuid.uuid4(), app_client_id=None, full_name="Customer",
                email=f"c-{uuid.uuid4().hex[:8]}@test.local", hashed_password="x", role=UserRole.ADMIN,
            )
            session.add_all([owner, customer])
            session.flush()
            restaurant = Restaurant(
                id=uuid.uuid4(), owner_id=owner.id, name=name, slug=f"r-{uuid.uuid4().hex[:8]}",
                cuisine_type="Bakery", address_line_1="1 St", city="Surat", state="Gujarat",
                postal_code="395004", is_approved=True, is_active=True, currency=currency, is_demo=demo,
            )
            session.add(restaurant)
            session.flush()
            location = RestaurantLocation(
                id=uuid.uuid4(), restaurant_id=restaurant.id, branch_name="Main",
                address_line_1="1 St", city="Surat", state="Gujarat", postal_code="395004",
                delivery_fee=Decimal("40"), is_open=True,
            )
            session.add(location)
            session.add(AppClient(
                id=uuid.uuid4(), key=f"k-{uuid.uuid4().hex[:8]}", display_name=name,
                app_mode=AppMode.SINGLE_RESTAURANT, restaurant_id=restaurant.id,
            ))
            session.commit()
            return restaurant.id, location.id, customer.id

    def _order(self, restaurant_id, location_id, *, status, total="110", minutes_ago=5,
               payment=PaymentStatus.PAID):
        placed = self.now - timedelta(minutes=minutes_ago)
        with self.session_factory() as session:
            order = Order(
                id=uuid.uuid4(), customer_id=self.customer, restaurant_id=restaurant_id,
                restaurant_location_id=location_id, status=status, payment_status=payment,
                payment_method=PaymentMethod.CARD, fulfillment_type=OrderFulfillmentType.PICKUP,
                schedule_type=OrderScheduleType.ASAP, scheduled_at=placed, placed_at=placed,
                updated_at=placed, subtotal=Decimal(total), delivery_fee=Decimal("0"),
                tax_amount=Decimal("0"), discount_amount=Decimal("0"), total_amount=Decimal(total),
                delivery_address="Pickup",
            )
            session.add(order)
            session.commit()
            return order.id

    # --- the dashboard ----------------------------------------------------

    def test_platform_totals_are_the_real_restaurants_and_only_real_sales(self) -> None:
        self._order(self.real, self.real_branch, status=OrderStatus.DELIVERED, total="110")
        self._order(self.real, self.real_branch, status=OrderStatus.PLACED, total="90")
        self._order(self.real, self.real_branch, status=OrderStatus.CANCELLED, total="500")
        self._order(self.real, self.real_branch, status=OrderStatus.PAYMENT_PENDING,
                    total="700", payment=PaymentStatus.PENDING)
        self._order(self.demo, self.demo_branch, status=OrderStatus.DELIVERED, total="999")

        stats = self.client.get("/api/admin/dashboard").json()

        # A cancelled order was still an order; an abandoned checkout was not.
        self.assertEqual(stats["total_orders"], 3)
        # Revenue is what was sold: not the cancelled one, not the unpaid one,
        # and not the demo kitchen's dollars added to rupees.
        self.assertEqual(stats["total_revenue"], 200.0)
        self.assertEqual(stats["total_restaurants"], 1)
        self.assertEqual(stats["currency"], "INR")

    # --- lists across restaurants ----------------------------------------

    def test_the_platform_order_list_leaves_demo_orders_out(self) -> None:
        real = self._order(self.real, self.real_branch, status=OrderStatus.PLACED)
        self._order(self.demo, self.demo_branch, status=OrderStatus.PLACED)
        ids = [row["id"] for row in self.client.get("/api/orders").json()]
        self.assertEqual(ids, [str(real)])

    def test_naming_a_demo_restaurant_still_answers(self) -> None:
        demo = self._order(self.demo, self.demo_branch, status=OrderStatus.PLACED)
        ids = [row["id"] for row in self.client.get(f"/api/orders?restaurant_id={self.demo}").json()]
        self.assertEqual(ids, [str(demo)])

    def test_the_restaurant_list_hides_demo_unless_asked(self) -> None:
        names = [row["name"] for row in self.client.get("/api/admin/restaurants").json()]
        self.assertEqual(names, ["Bhagwati"])
        rows = self.client.get("/api/admin/restaurants?include_demo=true").json()
        self.assertEqual({row["name"]: row["is_demo"] for row in rows}, {"Bhagwati": False, "Bangkok Bowl": True})

    def test_the_tenant_list_hides_demo_unless_asked(self) -> None:
        names = [row["display_name"] for row in self.client.get("/api/app-clients").json()]
        self.assertEqual(names, ["Bhagwati"])
        names = {row["display_name"] for row in self.client.get("/api/app-clients?include_demo=true").json()}
        self.assertEqual(names, {"Bhagwati", "Bangkok Bowl"})

    def test_the_mark_can_be_undone(self) -> None:
        response = self.client.patch(f"/api/admin/restaurants/{self.demo}/demo", json={"is_demo": False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_demo"])
        names = {row["name"] for row in self.client.get("/api/admin/restaurants").json()}
        self.assertEqual(names, {"Bhagwati", "Bangkok Bowl"})

    def test_only_the_platform_admin_may_mark_one(self) -> None:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(), role=UserRole.OWNER, is_active=True, restaurant_id=None
        )
        response = self.client.patch(f"/api/admin/restaurants/{self.real}/demo", json={"is_demo": True})
        self.assertEqual(response.status_code, 403)

    # --- platform watch ---------------------------------------------------

    def test_platform_watch_says_nothing_about_a_demo_kitchen(self) -> None:
        self._order(self.demo, self.demo_branch, status=OrderStatus.PLACED, minutes_ago=60)
        with mock.patch(
            "app.services.payments.registry.available_payment_methods",
            return_value=[PaymentMethod.CARD],
        ), self.session_factory() as session:
            issues = platform_watch.find_issues(session, now=self.now)
            rows = platform_watch.restaurants_today(session, now=self.now, issues=issues)
        self.assertNotIn(self.demo, {issue.restaurant_id for issue in issues})
        self.assertEqual([row.restaurant_id for row in rows], [self.real])


if __name__ == "__main__":
    unittest.main()
