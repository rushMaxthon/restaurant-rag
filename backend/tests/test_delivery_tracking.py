"""What a courier's update does to an order, end to end.

Read against Pidge's own sandbox. `fixtures/pidge_sandbox_states.json` is
the status response at eight stages of one trip, captured with their
`dummy_status` parameter on 2026-10-05 - the same body their webhook pushes.

The failures pinned here were all silent:

**A delivered order that never said so.** `record` set `order.status` and
nothing else. No status event, so the order never appeared under Done today;
no notification, so the customer was never told the food had arrived.

**Times nobody sends.** The reader looked for `picked_up_at` and
`delivered_at`. Pidge sends `fulfillment.pickup.timestamp` and
`fulfillment.drop.timestamp`, so both were always empty, as were the ETAs,
the courier's charge, the rider's position and why a trip failed.

**A rider re-booked into a refusal.** Pidge rejects a reference it has seen,
so a second booking for the same order must carry a new one.
"""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException  # noqa: F401
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402,F401
from app.config import get_settings  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import (  # noqa: E402
    OrderEventActor,
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.order import Order  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.order_status_event import OrderStatusEvent  # noqa: E402
from app.models.restaurant import Restaurant  # noqa: E402
from app.models.restaurant_location import RestaurantLocation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.order import OrderDeliveryResponse  # noqa: E402
from app.services.delivery import service  # noqa: E402
from app.services.delivery.base import DeliveryProviderError, DeliveryResult, DeliveryState  # noqa: E402
from app.services.delivery.pidge_provider import PidgeProvider  # noqa: E402

STATES = json.loads((BACKEND_ROOT / "tests" / "fixtures" / "pidge_sandbox_states.json").read_text())
settings = get_settings()
TEST_DB_NAME = "restaurant_rag_delivery_tracking_test"


def read(stage: str) -> DeliveryResult:
    provider = PidgeProvider(base_url="https://store.dev.pidge.in", username="u", password="p")
    return provider.parse_webhook(STATES[stage])


class ReadingWhatPidgeSendsTests(unittest.TestCase):
    def test_a_trip_on_its_way_to_the_restaurant(self) -> None:
        result = read("fulfilled|out for pickup")
        self.assertEqual(result.state, DeliveryState.ASSIGNED)
        self.assertTrue(result.rider_name)
        self.assertIsNotNone(result.pickup_eta)
        self.assertTrue(result.tracking_url.startswith("https://"))
        self.assertEqual(result.courier_charge, Decimal("189"))

    def test_picked_up_carries_its_time_and_the_drop_eta(self) -> None:
        result = read("fulfilled|picked up")
        self.assertEqual(result.state, DeliveryState.PICKED_UP)
        self.assertIsNotNone(result.picked_up_at)
        self.assertIsNotNone(result.drop_eta)
        self.assertIsNone(result.delivered_at)

    def test_delivered_carries_when(self) -> None:
        result = read("fulfilled|delivered")
        self.assertEqual(result.state, DeliveryState.DELIVERED)
        self.assertIsNotNone(result.delivered_at)

    def test_the_timeline_is_every_step_oldest_first(self) -> None:
        steps = read("fulfilled|delivered").timeline
        self.assertEqual(
            [step["status"] for step in steps],
            ["CREATED", "OUT_FOR_PICKUP", "PICKED_UP", "OUT_FOR_DELIVERY", "DELIVERED"],
        )
        self.assertEqual(steps[1]["remark"], "Start for Pickup")

    def test_the_rider_is_placed_at_their_last_reported_point(self) -> None:
        result = read("fulfilled|ofd")
        self.assertIsNotNone(result.rider_latitude)
        self.assertIsNotNone(result.rider_location_at)

    def test_a_failed_trip_says_why(self) -> None:
        result = read("fulfilled|undelivered")
        self.assertEqual(result.state, DeliveryState.FAILED)
        self.assertIn("Customer reject", result.failure_reason)

    def test_food_brought_back_is_not_delivered_even_with_a_drop_time(self) -> None:
        result = read("fulfilled|rto delivered")
        self.assertEqual(result.state, DeliveryState.FAILED)
        self.assertIsNone(result.delivered_at)

    def test_before_anyone_is_assigned_nothing_is_invented(self) -> None:
        result = read("pending")
        self.assertEqual(result.state, DeliveryState.PENDING)
        self.assertEqual((result.rider_name, result.timeline, result.failure_reason), ("", [], ""))


class WhoSeesTheCouriersChargeTests(unittest.TestCase):
    def _response(self) -> OrderDeliveryResponse:
        now = datetime.now(UTC)
        return OrderDeliveryResponse(
            provider="pidge", provider_order_id="x", state="ASSIGNED", provider_status="OUT_FOR_PICKUP",
            rider_name="", rider_mobile="", tracking_url="", distance_metres=None, picked_up_at=None,
            delivered_at=None, last_error="", created_at=now, updated_at=now, courier_charge=Decimal("189"),
        )

    def test_the_platform_admin_does(self) -> None:
        self.assertEqual(self._response().for_viewer(SimpleNamespace(role=UserRole.ADMIN)).courier_charge, Decimal("189"))

    def test_nobody_else_does(self) -> None:
        for role in (UserRole.OWNER, UserRole.KITCHEN, UserRole.CUSTOMER):
            with self.subTest(role=role):
                self.assertIsNone(self._response().for_viewer(SimpleNamespace(role=role)).courier_charge)


class SimulatingTests(unittest.TestCase):
    def test_refused_anywhere_but_the_sandbox(self) -> None:
        with mock.patch.object(service, "get_settings", return_value=SimpleNamespace(pidge_base_url="https://api.pidge.in")):
            with self.assertRaises(DeliveryProviderError):
                service.simulate(mock.Mock(), SimpleNamespace(id=uuid.uuid4()), "fulfilled|ofd")


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
class WhatAnUpdateDoesToTheOrderTests(unittest.TestCase):
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
        with cls.session_factory() as session:
            owner = User(id=uuid.uuid4(), app_client_id=None, full_name="O", email="o@t.local",
                         hashed_password="x", role=UserRole.OWNER)
            session.add(owner)
            session.flush()
            restaurant = Restaurant(id=uuid.uuid4(), owner_id=owner.id, name="R", slug="r", cuisine_type="B",
                                    address_line_1="1", city="Surat", state="GJ", postal_code="395004",
                                    is_approved=True, is_active=True)
            session.add(restaurant)
            session.flush()
            location = RestaurantLocation(id=uuid.uuid4(), restaurant_id=restaurant.id, branch_name="Main",
                                          address_line_1="1", city="Surat", state="GJ", postal_code="395004")
            session.add(location)
            session.commit()
            cls.ids = (restaurant.id, location.id, owner.id)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.engine is not None:
            cls.engine.dispose()
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin.dispose()

    def setUp(self) -> None:
        patcher = mock.patch("app.config.celery.celery_app.send_task")
        self.sent = patcher.start()
        self.addCleanup(patcher.stop)

    def _order(self, status: OrderStatus) -> uuid.UUID:
        rid, lid, uid = self.ids
        now = datetime.now(UTC)
        with self.session_factory() as session:
            order = Order(
                id=uuid.uuid4(), customer_id=uid, restaurant_id=rid, restaurant_location_id=lid,
                status=status, payment_status=PaymentStatus.PAID, payment_method=PaymentMethod.CARD,
                fulfillment_type=OrderFulfillmentType.DELIVERY, schedule_type=OrderScheduleType.ASAP,
                scheduled_at=now, placed_at=now, subtotal=Decimal("110"), delivery_fee=Decimal("40"),
                tax_amount=Decimal("0"), discount_amount=Decimal("0"), total_amount=Decimal("150"),
                delivery_address="1 Street",
            )
            session.add(order)
            session.add(OrderDelivery(order_id=order.id, provider="pidge", provider_order_id="P1", state="PENDING"))
            session.commit()
            return order.id

    def _apply(self, order_id: uuid.UUID, stage: str) -> None:
        with self.session_factory() as session:
            row = session.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order_id))
            service.record(session, row, read(stage))
            session.commit()

    def _events(self, order_id: uuid.UUID) -> list[OrderStatusEvent]:
        with self.session_factory() as session:
            return list(session.scalars(
                select(OrderStatusEvent).where(OrderStatusEvent.order_id == order_id).order_by(OrderStatusEvent.occurred_at)
            ))

    def _notified(self) -> list[str]:
        return [call.kwargs["kwargs"]["new_status"] for call in self.sent.call_args_list
                if call.args and call.args[0] == "app.tasks.notifications.send_order_status_notification"]

    def test_picked_up_moves_the_order_and_says_so_like_a_kitchen_tap(self) -> None:
        order_id = self._order(OrderStatus.PREPARING)
        self._apply(order_id, "fulfilled|picked up")
        events = self._events(order_id)
        self.assertEqual([e.to_status for e in events], [OrderStatus.OUT_FOR_DELIVERY])
        self.assertEqual(events[0].from_status, OrderStatus.PREPARING)
        self.assertEqual(events[0].actor, OrderEventActor.SYSTEM)
        self.assertIn("courier", events[0].note)
        self.assertEqual(self._notified(), ["OUT_FOR_DELIVERY"])

    def test_delivered_is_recorded_at_the_moment_it_happened(self) -> None:
        order_id = self._order(OrderStatus.OUT_FOR_DELIVERY)
        self._apply(order_id, "fulfilled|delivered")
        event = self._events(order_id)[-1]
        self.assertEqual(event.to_status, OrderStatus.DELIVERED)
        self.assertEqual(event.occurred_at, read("fulfilled|delivered").delivered_at)
        self.assertEqual(self._notified(), ["DELIVERED"])

    def test_a_late_push_after_delivery_records_nothing(self) -> None:
        order_id = self._order(OrderStatus.OUT_FOR_DELIVERY)
        self._apply(order_id, "fulfilled|delivered")
        self._apply(order_id, "fulfilled|ofd")
        self.assertEqual([e.to_status for e in self._events(order_id)], [OrderStatus.DELIVERED])
        self.assertEqual(self._notified(), ["DELIVERED"])

    def test_the_details_land_on_the_delivery(self) -> None:
        order_id = self._order(OrderStatus.PREPARING)
        self._apply(order_id, "fulfilled|picked up")
        with self.session_factory() as session:
            row = session.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order_id))
            self.assertEqual(row.courier_charge, Decimal("189.00"))
            self.assertIsNotNone(row.drop_eta)
            self.assertIsNotNone(row.picked_up_at)
            self.assertTrue(row.timeline)
            self.assertIsNotNone(row.rider_latitude)

    def test_nothing_is_announced_if_the_update_is_rolled_back(self) -> None:
        order_id = self._order(OrderStatus.PREPARING)
        with self.session_factory() as session:
            row = session.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order_id))
            service.record(session, row, read("fulfilled|picked up"))
            session.rollback()
        self.assertEqual(self._notified(), [])
        self.assertEqual(self._events(order_id), [])

    def test_a_failed_trip_can_be_rebooked_with_a_new_reference(self) -> None:
        order_id = self._order(OrderStatus.OUT_FOR_DELIVERY)
        self._apply(order_id, "fulfilled|undelivered")
        provider = mock.Mock(name="pidge")
        provider.create.return_value = DeliveryResult(provider_order_id="P2", state=DeliveryState.PENDING)
        with self.session_factory() as session, \
                mock.patch.object(service, "delivery_provider", return_value=provider), \
                mock.patch.object(service, "should_dispatch", return_value=True), \
                mock.patch.object(service, "build_request", return_value=SimpleNamespace(reference="r")):
            order = session.get(Order, order_id)
            row = session.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order_id))
            self.assertTrue(service.can_rebook(order, row))
            service.rebook(session, order)
            session.commit()
            self.assertEqual(provider.create.call_args.args[0].reference, f"{order_id}-2")
            self.assertEqual((row.provider_order_id, row.attempt, row.state, row.failure_reason), ("P2", 2, "PENDING", ""))

    def test_a_trip_still_running_cannot_be_rebooked(self) -> None:
        order_id = self._order(OrderStatus.PREPARING)
        self._apply(order_id, "fulfilled|out for pickup")
        with self.session_factory() as session:
            order = session.get(Order, order_id)
            row = session.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order_id))
            self.assertFalse(service.can_rebook(order, row))
            with self.assertRaises(DeliveryProviderError):
                service.rebook(session, order)

    def test_a_rider_on_the_way_to_the_restaurant_can_be_called_off(self) -> None:
        order_id = self._order(OrderStatus.PREPARING)
        self._apply(order_id, "fulfilled|out for pickup")
        with self.session_factory() as session:
            order = session.get(Order, order_id)
            row = session.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order_id))
            self.assertTrue(service.can_cancel(order, row))

    def test_a_finished_order_offers_no_rider_to_call_off(self) -> None:
        # Seen on the admin: an order marked DELIVERED by hand, whose courier
        # row never moved past PENDING, offered "Cancel rider".
        for status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED):
            order_id = self._order(status)
            self._apply(order_id, "fulfilled|out for pickup")
            with self.session_factory() as session:
                order = session.get(Order, order_id)
                row = session.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order_id))
                self.assertFalse(service.can_cancel(order, row), status)

    def test_food_already_collected_cannot_be_called_off(self) -> None:
        order_id = self._order(OrderStatus.OUT_FOR_DELIVERY)
        self._apply(order_id, "fulfilled|picked up")
        with self.session_factory() as session:
            order = session.get(Order, order_id)
            row = session.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order_id))
            self.assertFalse(service.can_cancel(order, row))
            self.assertFalse(service.can_cancel(order, None))


if __name__ == "__main__":
    unittest.main()
