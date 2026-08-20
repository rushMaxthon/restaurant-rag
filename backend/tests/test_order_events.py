"""Operational history: order transitions, cancellations, and dish availability.

The order path is the most correctness-critical code in the platform, so these
cover the safety properties as much as the recording: an event must never commit
on its own, never survive a rolled-back order, and never be able to fail one.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import (
    OrderCancellationReason,
    OrderEventActor,
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.menu_availability_event import MenuItemAvailabilityEvent
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_status_event import OrderStatusEvent
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.order_events import (
    actor_for_user,
    mark_order_cancelled,
    record_menu_availability_event,
    record_order_status_event,
)
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()
TEST_DB_NAME = os.environ.get("EVENTS_TEST_DB", "restaurant_rag_events_test")


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
            engine.dispose()


class ActorMappingTests(unittest.TestCase):
    """Who did it — the first question asked of any operational log."""

    def _user(self, role: UserRole) -> User:
        return User(id=uuid.uuid4(), full_name="x", email="x@t.local", hashed_password="x", role=role)

    def test_roles_map_to_actors(self) -> None:
        self.assertEqual(actor_for_user(self._user(UserRole.OWNER)), OrderEventActor.OWNER)
        self.assertEqual(actor_for_user(self._user(UserRole.ADMIN)), OrderEventActor.ADMIN)
        self.assertEqual(actor_for_user(self._user(UserRole.CUSTOMER)), OrderEventActor.CUSTOMER)

    def test_no_user_is_the_system(self) -> None:
        # Unattended work (the reaper, a webhook) has no user behind it.
        self.assertEqual(actor_for_user(None), OrderEventActor.SYSTEM)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class OrderEventTests(unittest.TestCase):
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
        owner = User(id=uuid.uuid4(), full_name="Owner", email="ev-owner@t.local",
                     hashed_password="x", role=UserRole.OWNER)
        customer = User(id=uuid.uuid4(), full_name="Cust", email="ev-cust@t.local",
                        hashed_password="x", role=UserRole.CUSTOMER)
        session.add_all([owner, customer])
        session.flush()

        restaurant = Restaurant(
            id=uuid.uuid4(), owner_id=owner.id, name="Ev R", slug="ev-r",
            cuisine_type="Italian", address_line_1="1 St", city="BLR",
            state="KA", postal_code="560001", is_approved=True, is_active=True,
        )
        session.add(restaurant)
        session.flush()

        location = RestaurantLocation(
            id=uuid.uuid4(), restaurant_id=restaurant.id, branch_name="Main",
            address_line_1="1 St", city="BLR", state="KA", postal_code="560001",
        )
        session.add(location)
        session.flush()

        item = MenuItem(
            id=uuid.uuid4(), restaurant_id=restaurant.id,
            restaurant_location_id=location.id, name="Margherita Pizza",
            category="Pizza", price=Decimal("500.00"), is_available=True,
        )
        session.add(item)
        session.commit()

        cls.owner_id = owner.id
        cls.customer_id = customer.id
        cls.restaurant_id = restaurant.id
        cls.location_id = location.id
        cls.item_id = item.id

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)
        self.addCleanup(self._reset)

    def _reset(self) -> None:
        with self.session_factory() as session:
            session.query(OrderStatusEvent).delete()
            session.query(MenuItemAvailabilityEvent).delete()
            session.query(Order).delete()
            session.commit()

    def _order(self, status: OrderStatus = OrderStatus.PLACED) -> Order:
        order = Order(
            id=uuid.uuid4(), customer_id=self.customer_id,
            restaurant_id=self.restaurant_id, restaurant_location_id=self.location_id,
            status=status, payment_status=PaymentStatus.PAID,
            payment_method=PaymentMethod.CARD, payment_provider="test",
            fulfillment_type=OrderFulfillmentType.DELIVERY,
            schedule_type=OrderScheduleType.ASAP, scheduled_at=datetime.now(UTC),
            subtotal=Decimal("500.00"), delivery_fee=Decimal("0.00"),
            tax_amount=Decimal("0.00"), discount_amount=Decimal("0.00"),
            total_amount=Decimal("500.00"), currency="INR",
            delivery_address="1 St", placed_at=datetime.now(UTC),
        )
        self.session.add(order)
        self.session.commit()
        return order

    # -- recording ---------------------------------------------------------

    def test_transition_is_recorded_with_both_ends(self) -> None:
        order = self._order()
        record_order_status_event(
            self.session, order=order,
            from_status=OrderStatus.PLACED, to_status=OrderStatus.ACCEPTED,
            actor=OrderEventActor.OWNER, actor_user_id=self.owner_id,
        )
        self.session.commit()

        event = self.session.scalars(select(OrderStatusEvent)).one()
        self.assertEqual(event.from_status, OrderStatus.PLACED)
        self.assertEqual(event.to_status, OrderStatus.ACCEPTED)
        self.assertEqual(event.actor, OrderEventActor.OWNER)
        self.assertEqual(event.actor_user_id, self.owner_id)
        # Denormalised so the insights layer can scope without joining orders.
        self.assertEqual(event.restaurant_id, self.restaurant_id)

    def test_first_event_has_no_from_status(self) -> None:
        order = self._order()
        record_order_status_event(
            self.session, order=order, from_status=None, to_status=OrderStatus.PLACED,
            actor=OrderEventActor.CUSTOMER,
        )
        self.session.commit()
        self.assertIsNone(self.session.scalars(select(OrderStatusEvent)).one().from_status)

    def test_recording_does_not_commit_on_its_own(self) -> None:
        # The caller's transaction owns the write: an event must never be able
        # to commit a half-finished order.
        order = self._order()
        record_order_status_event(
            self.session, order=order, to_status=OrderStatus.ACCEPTED,
        )
        with self.session_factory() as other:
            self.assertEqual(other.query(OrderStatusEvent).count(), 0)

    def test_rolled_back_order_takes_its_event_with_it(self) -> None:
        order = self._order()
        record_order_status_event(self.session, order=order, to_status=OrderStatus.ACCEPTED)
        self.session.rollback()

        with self.session_factory() as other:
            self.assertEqual(other.query(OrderStatusEvent).count(), 0)

    def test_recording_never_raises(self) -> None:
        # A missing event is a gap in analytics; a failed order is lost revenue.
        order = self._order()
        with patch.object(self.session, "add", side_effect=RuntimeError("boom")):
            record_order_status_event(self.session, order=order, to_status=OrderStatus.ACCEPTED)
        # No exception escaped.

    # -- cancellation ------------------------------------------------------

    def test_cancellation_records_reason_and_event_together(self) -> None:
        order = self._order(status=OrderStatus.PAYMENT_PENDING)
        mark_order_cancelled(
            self.session, order=order,
            reason=OrderCancellationReason.PAYMENT_NOT_COMPLETED,
            actor=OrderEventActor.SYSTEM, note="unpaid past TTL",
        )
        order.status = OrderStatus.CANCELLED
        self.session.commit()

        refreshed = self.session.get(Order, order.id)
        self.assertEqual(
            refreshed.cancellation_reason, OrderCancellationReason.PAYMENT_NOT_COMPLETED
        )
        self.assertEqual(refreshed.cancelled_by, OrderEventActor.SYSTEM)
        self.assertIsNotNone(refreshed.cancelled_at)

        event = self.session.scalars(select(OrderStatusEvent)).one()
        self.assertEqual(event.to_status, OrderStatus.CANCELLED)
        self.assertEqual(event.from_status, OrderStatus.PAYMENT_PENDING)
        self.assertEqual(
            event.cancellation_reason, OrderCancellationReason.PAYMENT_NOT_COMPLETED
        )

    # -- availability ------------------------------------------------------

    def test_availability_change_is_recorded(self) -> None:
        item = self.session.get(MenuItem, self.item_id)
        record_menu_availability_event(
            self.session, menu_item=item, is_available=False,
            previous_available=True, actor=OrderEventActor.OWNER,
            actor_user_id=self.owner_id,
        )
        self.session.commit()

        event = self.session.scalars(select(MenuItemAvailabilityEvent)).one()
        self.assertFalse(event.is_available)
        self.assertEqual(event.item_name_snapshot, "Margherita Pizza")
        self.assertEqual(event.restaurant_id, self.restaurant_id)

    def test_unchanged_availability_records_nothing(self) -> None:
        # The log holds transitions, not one row per save.
        item = self.session.get(MenuItem, self.item_id)
        record_menu_availability_event(
            self.session, menu_item=item, is_available=True, previous_available=True,
        )
        self.session.commit()
        self.assertEqual(self.session.query(MenuItemAvailabilityEvent).count(), 0)

    def test_name_is_snapshotted_so_renames_do_not_rewrite_history(self) -> None:
        item = self.session.get(MenuItem, self.item_id)
        record_menu_availability_event(
            self.session, menu_item=item, is_available=False, previous_available=True,
        )
        self.session.commit()

        item.name = "Renamed Pizza"
        self.session.commit()

        event = self.session.scalars(select(MenuItemAvailabilityEvent)).one()
        self.assertEqual(event.item_name_snapshot, "Margherita Pizza")

    def test_availability_recording_never_raises(self) -> None:
        item = self.session.get(MenuItem, self.item_id)
        with patch.object(self.session, "add", side_effect=RuntimeError("boom")):
            record_menu_availability_event(
                self.session, menu_item=item, is_available=False, previous_available=True,
            )

    # -- reconstructing history --------------------------------------------

    def test_events_reconstruct_an_order_lifecycle_in_order(self) -> None:
        order = self._order(status=OrderStatus.PLACED)
        base = datetime.now(UTC)
        flow = [
            (None, OrderStatus.PLACED),
            (OrderStatus.PLACED, OrderStatus.ACCEPTED),
            (OrderStatus.ACCEPTED, OrderStatus.PREPARING),
            (OrderStatus.PREPARING, OrderStatus.OUT_FOR_DELIVERY),
            (OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED),
        ]
        for index, (previous, nxt) in enumerate(flow):
            record_order_status_event(
                self.session, order=order, from_status=previous, to_status=nxt,
                occurred_at=base + timedelta(minutes=index * 5),
            )
        self.session.commit()

        events = self.session.scalars(
            select(OrderStatusEvent).order_by(OrderStatusEvent.occurred_at)
        ).all()
        self.assertEqual([e.to_status for e in events], [row[1] for row in flow])
        # Acceptance latency becomes answerable: 5 minutes here.
        latency = events[1].occurred_at - events[0].occurred_at
        self.assertEqual(latency, timedelta(minutes=5))


if __name__ == "__main__":
    unittest.main()
