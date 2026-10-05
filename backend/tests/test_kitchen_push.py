"""New-order pushes to the kitchen app: who is paged, when, and with what.

Three things are pinned here because each would be a quiet failure:

* **Scope.** The recipients must be exactly the board's scope for the order.
  Paging a cook pinned to another branch is noise they learn to ignore;
  paging another restaurant's owner leaks its orders.
* **Timing.** Queued on the transition INTO PLACED and handed to the worker
  only after the commit — a rolled-back order must page nobody, and an unpaid
  (PAYMENT_PENDING) order is not work yet.
* **Cleanup.** Signing out deactivates only the caller's own device, and a
  token Firebase reports dead is switched off after a send.

Firebase and Celery are replaced at their seams; nothing leaves the process.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401  imported first to settle import order
from app.config import get_settings
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
from app.models.user_device_token import UserDeviceToken
from app.services import kitchen_push
from app.services.kitchen_push import (
    ANDROID_CHANNEL_ID,
    ANDROID_SOUND,
    IOS_SOUND,
    build_kitchen_message,
    kitchen_recipients,
    send_kitchen_new_order_push,
)
from app.services.notifications import deactivate_device_token
from app.services.order_events import record_order_status_event
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()
TEST_DB_NAME = os.environ.get("KITCHEN_PUSH_TEST_DB", "restaurant_rag_kitchen_push_test")


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


def _flag(on: bool):
    """Patch the kitchen-push switch, leaving every other setting real."""

    real = get_settings()
    fake = SimpleNamespace(**{**real.model_dump(), "enable_kitchen_push": on})
    return mock.patch.object(kitchen_push, "get_settings", return_value=fake)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class KitchenPushTests(unittest.TestCase):
    """Restaurant A has two branches (Downtown, Airport); restaurant B one."""

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
            cls._seed(session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin.dispose()

    @classmethod
    def _user(cls, session: Session, role: UserRole, **kwargs) -> User:
        user = User(
            id=uuid.uuid4(),
            full_name=kwargs.pop("full_name", role.value.title()),
            email=f"{role.value.lower()}-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            role=role,
            **kwargs,
        )
        session.add(user)
        session.flush()
        return user

    @classmethod
    def _restaurant(cls, session: Session, slug: str, owner: User) -> Restaurant:
        restaurant = Restaurant(
            id=uuid.uuid4(), owner_id=owner.id, name=slug, slug=slug, cuisine_type="Thai",
            address_line_1="1 St", city="BLR", state="KA", postal_code="560001",
            is_approved=True, is_active=True,
        )
        session.add(restaurant)
        session.flush()
        return restaurant

    @classmethod
    def _branch(cls, session: Session, restaurant: Restaurant, name: str) -> RestaurantLocation:
        location = RestaurantLocation(
            id=uuid.uuid4(), restaurant_id=restaurant.id, branch_name=name,
            address_line_1="1 St", city="BLR", state="KA", postal_code="560001",
        )
        session.add(location)
        session.flush()
        dish = MenuItem(
            id=uuid.uuid4(), restaurant_id=restaurant.id, restaurant_location_id=location.id,
            name="Pad Thai", category="Noodles", price=Decimal("10.00"), is_available=True,
        )
        session.add(dish)
        session.flush()
        cls.dish_by_location[location.id] = dish.id
        return location

    dish_by_location: dict = {}

    @classmethod
    def _seed(cls, session: Session) -> None:
        cls.owner_a = cls._user(session, UserRole.OWNER)
        cls.owner_b = cls._user(session, UserRole.OWNER)
        restaurant_a = cls._restaurant(session, "push-a", cls.owner_a)
        restaurant_b = cls._restaurant(session, "push-b", cls.owner_b)
        cls.downtown = cls._branch(session, restaurant_a, "Downtown")
        cls.airport = cls._branch(session, restaurant_a, "Airport")
        cls.branch_b = cls._branch(session, restaurant_b, "Main")
        cls.restaurant_a_id = restaurant_a.id
        cls.restaurant_b_id = restaurant_b.id

        cls.cook_downtown = cls._user(
            session, UserRole.KITCHEN,
            staff_restaurant_id=restaurant_a.id, staff_restaurant_location_id=cls.downtown.id,
        )
        cls.cook_airport = cls._user(
            session, UserRole.KITCHEN,
            staff_restaurant_id=restaurant_a.id, staff_restaurant_location_id=cls.airport.id,
        )
        cls.cook_any_branch = cls._user(session, UserRole.KITCHEN, staff_restaurant_id=restaurant_a.id)
        cls.cook_other_restaurant = cls._user(session, UserRole.KITCHEN, staff_restaurant_id=restaurant_b.id)
        cls.cook_switched_off = cls._user(
            session, UserRole.KITCHEN, staff_restaurant_id=restaurant_a.id, is_active=False,
        )
        cls.admin = cls._user(session, UserRole.ADMIN)
        cls.customer = cls._user(session, UserRole.CUSTOMER, full_name="Asha")
        session.commit()

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)

    def _order(self, location: RestaurantLocation, status=OrderStatus.PLACED, **kwargs) -> Order:
        order = Order(
            id=uuid.uuid4(), customer_id=self.customer.id,
            restaurant_id=location.restaurant_id, restaurant_location_id=location.id,
            status=status, payment_status=PaymentStatus.PAID, payment_method=PaymentMethod.CARD,
            payment_provider="test", fulfillment_type=kwargs.pop("fulfillment", OrderFulfillmentType.DELIVERY),
            schedule_type=kwargs.pop("schedule", OrderScheduleType.ASAP), scheduled_at=datetime.now(UTC),
            subtotal=Decimal("500.00"), delivery_fee=Decimal("0.00"), tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"), total_amount=Decimal("500.00"), currency="INR",
            delivery_address="1 St", placed_at=datetime.now(UTC), **kwargs,
        )
        self.session.add(order)
        self.session.flush()
        for quantity in (2, 1):
            self.session.add(
                OrderItem(
                    id=uuid.uuid4(), order_id=order.id, menu_item_id=self.dish_by_location[location.id],
                    item_name_snapshot="Pad Thai", quantity=quantity,
                    base_unit_price=Decimal("10"), customization_total_price=Decimal("0"),
                    unit_price=Decimal("10"), total_price=Decimal("10") * quantity,
                )
            )
        self.session.commit()
        return order

    def _device(self, user: User, token: str) -> UserDeviceToken:
        device = UserDeviceToken(
            id=uuid.uuid4(), user_id=user.id, installation_id=f"inst-{token}",
            fcm_token=f"{token}-{uuid.uuid4().hex[:6]}", platform="ANDROID", is_active=True,
        )
        self.session.add(device)
        self.session.commit()
        return device

    # --- who -------------------------------------------------------------

    def test_recipients_are_exactly_the_boards_scope(self) -> None:
        order = self._order(self.downtown)
        ids = {user.id for user in kitchen_recipients(self.session, order)}
        self.assertEqual(ids, {self.cook_downtown.id, self.cook_any_branch.id, self.owner_a.id})

    def test_a_cook_pinned_to_another_branch_is_not_woken(self) -> None:
        order = self._order(self.airport)
        ids = {user.id for user in kitchen_recipients(self.session, order)}
        self.assertIn(self.cook_airport.id, ids)
        self.assertNotIn(self.cook_downtown.id, ids)

    def test_nobody_outside_the_restaurant_is_paged(self) -> None:
        order = self._order(self.downtown)
        ids = {user.id for user in kitchen_recipients(self.session, order)}
        for outsider in (self.cook_other_restaurant, self.owner_b, self.admin, self.customer, self.cook_switched_off):
            self.assertNotIn(outsider.id, ids)

    # --- what --------------------------------------------------------------

    def test_message_says_what_a_cook_needs_and_nothing_more(self) -> None:
        order = self._order(self.downtown, contact_name="Priya")
        self.session.refresh(order, ["items"])
        title, body, data = build_kitchen_message(order)
        self.assertEqual(title, f"New order #{str(order.id)[:8].upper()}")
        self.assertEqual(body, "Delivery · 3 items · Priya")
        self.assertEqual(data["notification_type"], "kitchen_new_order")
        self.assertEqual(data["order_id"], str(order.id))
        self.assertTrue(all(isinstance(value, str) for value in data.values()))

    def test_scheduled_pickup_says_so(self) -> None:
        order = self._order(
            self.downtown, fulfillment=OrderFulfillmentType.PICKUP, schedule=OrderScheduleType.SCHEDULED,
        )
        self.session.refresh(order, ["items"])
        _title, body, _data = build_kitchen_message(order)
        self.assertTrue(body.startswith("Pickup · 3 items"))
        self.assertTrue(body.endswith("Scheduled"))

    # --- when -------------------------------------------------------------

    def _record(self, order: Order, to_status: OrderStatus) -> None:
        record_order_status_event(self.session, order=order, to_status=to_status)

    def test_placed_is_queued_and_handed_over_only_after_commit(self) -> None:
        order = self._order(self.downtown, status=OrderStatus.PAYMENT_PENDING)
        with _flag(True), mock.patch.object(kitchen_push, "_enqueue") as enqueue:
            self._record(order, OrderStatus.PLACED)
            enqueue.assert_not_called()
            self.session.commit()
        enqueue.assert_called_once_with([str(order.id)])

    def test_a_rolled_back_order_pages_nobody(self) -> None:
        order = self._order(self.downtown, status=OrderStatus.PAYMENT_PENDING)
        with _flag(True), mock.patch.object(kitchen_push, "_enqueue") as enqueue:
            self._record(order, OrderStatus.PLACED)
            self.session.rollback()
            self.session.commit()
        enqueue.assert_not_called()

    def test_unpaid_and_later_transitions_are_not_pages(self) -> None:
        order = self._order(self.downtown, status=OrderStatus.PAYMENT_PENDING)
        with _flag(True), mock.patch.object(kitchen_push, "_enqueue") as enqueue:
            self._record(order, OrderStatus.PAYMENT_PENDING)
            self._record(order, OrderStatus.ACCEPTED)
            self.session.commit()
        enqueue.assert_not_called()

    def test_with_the_flag_off_nothing_is_queued(self) -> None:
        order = self._order(self.downtown, status=OrderStatus.PAYMENT_PENDING)
        with _flag(False), mock.patch.object(kitchen_push, "_enqueue") as enqueue:
            self._record(order, OrderStatus.PLACED)
            self.session.commit()
        enqueue.assert_not_called()

    # --- send ---------------------------------------------------------------

    def _fake_response(self, tokens: list[str], dead: set[str]):
        responses = [
            SimpleNamespace(success=token not in dead, exception=None if token not in dead else SimpleNamespace(
                code="messaging/registration-token-not-registered"))
            for token in tokens
        ]
        return SimpleNamespace(
            success_count=sum(r.success for r in responses),
            failure_count=sum(not r.success for r in responses),
            responses=responses,
        )

    def test_send_reaches_only_scoped_devices_with_the_kitchen_chime(self) -> None:
        order = self._order(self.downtown)
        mine = self._device(self.cook_downtown, "downtown")
        owners = self._device(self.owner_a, "owner")
        other_branch = self._device(self.cook_airport, "airport")
        other_restaurant = self._device(self.cook_other_restaurant, "elsewhere")
        sent: list = []

        def fake_send(message, app=None):
            sent.append(message)
            return self._fake_response(message.tokens, set())

        with mock.patch("app.services.notifications._get_firebase_app", return_value=object()), \
                mock.patch.object(kitchen_push.messaging, "send_each_for_multicast", side_effect=fake_send):
            result = send_kitchen_new_order_push(self.session, order_id=order.id)

        self.assertEqual(result["status"], "sent")
        message = sent[0]
        # Other tests share this database and may have registered more devices
        # for the same in-scope accounts, so assert inclusion and exclusion
        # rather than an exact set.
        self.assertLessEqual({mine.fcm_token, owners.fcm_token}, set(message.tokens))
        self.assertNotIn(other_branch.fcm_token, message.tokens)
        self.assertNotIn(other_restaurant.fcm_token, message.tokens)
        self.assertEqual(message.android.priority, "high")
        self.assertEqual(message.android.notification.channel_id, ANDROID_CHANNEL_ID)
        self.assertEqual(message.android.notification.sound, ANDROID_SOUND)
        self.assertEqual(message.apns.payload.aps.sound, IOS_SOUND)
        self.assertEqual(message.data["order_id"], str(order.id))

    def test_a_dead_token_is_switched_off(self) -> None:
        order = self._order(self.downtown)
        gone = self._device(self.cook_downtown, "uninstalled")
        with mock.patch("app.services.notifications._get_firebase_app", return_value=object()), \
                mock.patch.object(
                    kitchen_push.messaging, "send_each_for_multicast",
                    side_effect=lambda message, app=None: self._fake_response(message.tokens, {gone.fcm_token}),
                ):
            send_kitchen_new_order_push(self.session, order_id=order.id)
        self.session.refresh(gone)
        self.assertFalse(gone.is_active)

    def test_an_order_already_accepted_is_not_announced(self) -> None:
        order = self._order(self.downtown, status=OrderStatus.ACCEPTED)
        self._device(self.cook_downtown, "accepted")
        with mock.patch.object(kitchen_push.messaging, "send_each_for_multicast") as send:
            result = send_kitchen_new_order_push(self.session, order_id=order.id)
        send.assert_not_called()
        self.assertEqual(result["reason"], "order_is_accepted")

    # --- sign-out ---------------------------------------------------------

    def test_signing_out_silences_only_your_own_device(self) -> None:
        mine = self._device(self.cook_airport, "shared")
        theirs = UserDeviceToken(
            id=uuid.uuid4(), user_id=self.cook_downtown.id, installation_id=mine.installation_id,
            fcm_token=f"other-{uuid.uuid4().hex[:6]}", platform="IOS", is_active=True,
        )
        self.session.add(theirs)
        self.session.commit()

        changed = deactivate_device_token(
            self.session, current_user=self.cook_airport, installation_id=mine.installation_id,
        )

        self.assertEqual(changed, 1)
        self.session.refresh(mine)
        self.session.refresh(theirs)
        self.assertFalse(mine.is_active)
        self.assertTrue(theirs.is_active)


if __name__ == "__main__":
    unittest.main()
