"""The welcome discount is for a customer's first order, and only that one.

Found in the 2026-10-07 security review. "Has this customer ordered before?"
was answered by looking for a PAID order. A cash-on-delivery order is never
marked paid, so a COD customer was a new customer forever and took the
welcome discount (up to Rs 500) on every order. A card customer could open
several checkouts before paying any and have the discount on each.

Decided with the platform owner: any real order counts - COD, paid, or a
checkout still waiting for payment. Only an order cancelled because its
payment failed or was abandoned does not, because nothing was bought; the
reaper closes an abandoned checkout, which frees the discount again.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import (  # noqa: E402
    OrderCancellationReason,
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
from app.services import personalized_offers  # noqa: E402

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_welcome_once_test"


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
class WhoHasOrdered(unittest.TestCase):
    engine = None

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
        self.db = self.session_factory()
        self.addCleanup(self.db.close)
        owner = User(email=f"o-{uuid.uuid4().hex[:8]}@t.local", full_name="O", hashed_password="x", role=UserRole.OWNER)
        self.db.add(owner)
        self.db.flush()
        restaurant = Restaurant(
            owner_id=owner.id, name="R", slug=f"r-{uuid.uuid4().hex[:8]}", cuisine_type="Bakery",
            address_line_1="1 St", city="Surat", state="Gujarat", postal_code="395004",
            is_approved=True, is_active=True,
        )
        self.db.add(restaurant)
        self.db.flush()
        location = RestaurantLocation(
            restaurant_id=restaurant.id, branch_name="Main", address_line_1="1 St",
            city="Surat", state="Gujarat", postal_code="395004", is_open=True,
        )
        customer = User(email=f"c-{uuid.uuid4().hex[:8]}@t.local", full_name="C", hashed_password="x", role=UserRole.ADMIN)
        self.db.add_all([location, customer])
        self.db.commit()
        self.restaurant, self.location, self.customer = restaurant, location, customer

    def _order(self, *, status, payment_status, method=PaymentMethod.CARD, reason=None) -> None:
        now = datetime.now(UTC) - timedelta(hours=1)
        self.db.add(Order(
            customer_id=self.customer.id, restaurant_id=self.restaurant.id,
            restaurant_location_id=self.location.id, status=status, payment_status=payment_status,
            payment_method=method, fulfillment_type=OrderFulfillmentType.PICKUP,
            schedule_type=OrderScheduleType.ASAP, scheduled_at=now, placed_at=now, updated_at=now,
            subtotal=Decimal("100"), delivery_fee=Decimal("0"), tax_amount=Decimal("0"),
            discount_amount=Decimal("0"), total_amount=Decimal("100"), delivery_address="Pickup",
            cancellation_reason=reason,
        ))
        self.db.commit()

    def _has_ordered(self) -> bool:
        return personalized_offers._latest_order_at(self.db, self.customer.id) is not None

    def test_a_brand_new_customer_has_not(self) -> None:
        self.assertFalse(self._has_ordered())

    def test_a_cash_on_delivery_order_counts(self) -> None:
        self._order(status=OrderStatus.DELIVERED, payment_status=PaymentStatus.COD, method=PaymentMethod.COD)
        self.assertTrue(self._has_ordered())

    def test_a_checkout_still_waiting_for_payment_counts(self) -> None:
        self._order(status=OrderStatus.PAYMENT_PENDING, payment_status=PaymentStatus.PENDING)
        self.assertTrue(self._has_ordered())

    def test_a_paid_order_counts(self) -> None:
        self._order(status=OrderStatus.PLACED, payment_status=PaymentStatus.PAID)
        self.assertTrue(self._has_ordered())

    def test_a_cancelled_order_the_restaurant_could_not_make_still_counts(self) -> None:
        self._order(
            status=OrderStatus.CANCELLED, payment_status=PaymentStatus.REFUNDED,
            reason=OrderCancellationReason.OUT_OF_STOCK,
        )
        self.assertTrue(self._has_ordered())

    def test_a_checkout_whose_payment_failed_does_not(self) -> None:
        for reason in (
            OrderCancellationReason.PAYMENT_FAILED,
            OrderCancellationReason.PAYMENT_ABANDONED,
            OrderCancellationReason.PAYMENT_NOT_COMPLETED,
        ):
            self._order(status=OrderStatus.CANCELLED, payment_status=PaymentStatus.FAILED, reason=reason)
        self.assertFalse(self._has_ordered())


if __name__ == "__main__":
    unittest.main()
