"""Realtime order pushes: who hears what, and never before the commit.

The socket is a hint, never a source of data — every client refetches over
REST when it hears one — so the claims worth pinning are the ones where a
wrong push would matter anyway:

* **The room is the scope.** A socket joins one staff room, chosen by
  `resolve_order_board_scope` — the same function `GET /orders` uses — and an
  order event goes to the rooms of its branch, its restaurant, `admin:all` and
  its customer. A cook pinned to one branch must not sit in the restaurant
  room, or they would hear every branch.
* **After commit, never before.** A push that arrives before the commit sends
  a board to refetch the OLD row; a push for a rolled-back write announces a
  transition that never happened.
* **A push can never cost an order.** Redis down, emitter broken — the order
  still commits.
* **The handshake is `get_current_user`.** A token REST would refuse (stale
  `token_version`, inactive account, wrong app) cannot open a socket.
* **WebSocket only.** The polling transport needs sticky sessions that
  gunicorn cannot give, so the server refuses it outright.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402  imported first to settle import order
from app.config import get_settings  # noqa: E402
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
from app.services.auth import OrderBoardScope, create_access_token  # noqa: E402
from app.services.orders import update_order_status  # noqa: E402
from app.services.realtime import outbox  # noqa: E402
from app.services.realtime import server as rt_server  # noqa: E402
from app.services.realtime.rooms import (  # noqa: E402
    ADMIN_ALL_ROOM,
    location_room,
    order_event_rooms,
    restaurant_room,
    staff_room,
    user_room,
)
from app.services.realtime.server import (  # noqa: E402
    Principal,
    RealtimeRefused,
    authenticate,
    origin_allowed,
    resubscribe,
    stale_principals,
)
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

settings = get_settings()
TEST_DB_NAME = os.environ.get("REALTIME_TEST_DB", "restaurant_rag_realtime_test")


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


class RecordingEmitter:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.emitted: list[tuple[str, dict, object]] = []

    def emit(self, event, data, *, room=None):
        if self.fail:
            raise ConnectionError("redis is down")
        self.emitted.append((event, data, room))


class RoomTests(unittest.TestCase):
    """Pure: the scope-to-room rule and the order-to-rooms rule."""

    def test_pinned_scope_is_the_branch_room_only(self) -> None:
        restaurant_id, location_id = uuid.uuid4(), uuid.uuid4()
        room = staff_room(OrderBoardScope(restaurant_id, location_id))
        # Not the restaurant room: a pinned cook must not hear other branches.
        self.assertEqual(room, location_room(location_id))

    def test_restaurant_scope_is_the_restaurant_room(self) -> None:
        restaurant_id = uuid.uuid4()
        self.assertEqual(staff_room(OrderBoardScope(restaurant_id, None)), restaurant_room(restaurant_id))

    def test_unnarrowed_admin_is_admin_all(self) -> None:
        self.assertEqual(staff_room(OrderBoardScope(None, None)), ADMIN_ALL_ROOM)

    def test_order_reaches_branch_restaurant_admin_and_its_customer(self) -> None:
        r, loc, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        rooms = order_event_rooms(restaurant_id=r, restaurant_location_id=loc, customer_id=c)
        self.assertEqual(
            set(rooms), {location_room(loc), restaurant_room(r), ADMIN_ALL_ROOM, user_room(c)}
        )


class OriginTests(unittest.TestCase):
    """The socket's Origin rule is CORSMiddleware's, not a second copy."""

    def test_listed_origin_is_allowed(self) -> None:
        self.assertTrue(origin_allowed(settings.backend_cors_origins_list[0]))

    def test_foreign_origin_is_refused(self) -> None:
        self.assertFalse(origin_allowed("https://evil.example"))

    def test_missing_origin_is_allowed(self) -> None:
        # The mobile app is not a browser and sends none; a token is still
        # required, so this admits nobody unauthenticated.
        self.assertTrue(origin_allowed(None))


class TransportTests(unittest.TestCase):
    """The mount exists, and the polling transport is refused."""

    def test_polling_transport_is_refused(self) -> None:
        client = TestClient(app)
        response = client.get(f"{settings.api_v1_prefix}/socket.io/?EIO=4&transport=polling")
        self.assertEqual(response.status_code, 400)

    def test_disabled_flag_refuses_the_handshake_with_a_reason(self) -> None:
        # Clients stop retrying on exactly this reason and keep polling.
        with mock.patch.object(settings, "enable_realtime", False):
            reason = _socketio_handshake({"token": "irrelevant"})
        self.assertEqual(reason, ("refused", "realtime_disabled"))


def _socketio_handshake(auth: dict) -> tuple[str, str]:
    """Speak just enough Engine.IO/Socket.IO over TestClient's WebSocket.

    `0{...}` is the Engine.IO open packet; `40{auth}` asks to join the default
    namespace; the answer is `40{"sid":...}` (accepted) or `44{"message":...}`
    (refused). Returns ("connected", sid) or ("refused", reason).
    """

    client = TestClient(app)
    path = f"{settings.api_v1_prefix}/socket.io/?EIO=4&transport=websocket"
    # TestClient omits the Upgrade header a browser sends; engine.io checks it.
    with client.websocket_connect(path, headers={"Upgrade": "websocket"}) as ws:
        opened = ws.receive_text()
        assert opened.startswith("0"), opened
        ws.send_text("40" + json.dumps(auth))
        while True:
            packet = ws.receive_text()
            if packet.startswith("40"):
                return ("connected", json.loads(packet[2:])["sid"])
            if packet.startswith("44"):
                return ("refused", json.loads(packet[2:])["message"])


class RealtimeFixture:
    """One restaurant with two branches, its owner, and a marketplace client."""

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
        marketplace = AppClient(
            id=uuid.uuid4(),
            key=settings.default_app_client_key,
            display_name="Marketplace",
            app_mode=AppMode.MARKETPLACE,
            order_number_prefix="MP",
        )
        owner = User(
            id=uuid.uuid4(), full_name="Owner", email="rt-owner@example.com",
            hashed_password="x", role=UserRole.OWNER,
        )
        other_owner = User(
            id=uuid.uuid4(), full_name="Other", email="rt-other@example.com",
            hashed_password="x", role=UserRole.OWNER,
        )
        session.add_all([marketplace, owner, other_owner])
        session.flush()
        restaurants = []
        for who, slug in ((owner, "rt-a"), (other_owner, "rt-b")):
            restaurant = Restaurant(
                id=uuid.uuid4(), owner_id=who.id, name=slug, slug=slug, cuisine_type="Thai",
                address_line_1="1 St", city="BLR", state="KA", postal_code="560001",
                is_approved=True, is_active=True,
            )
            session.add(restaurant)
            restaurants.append(restaurant)
        session.flush()
        branches = []
        for name in ("Main", "Second"):
            branch = RestaurantLocation(
                id=uuid.uuid4(), restaurant_id=restaurants[0].id, branch_name=name,
                address_line_1="1 St", city="BLR", state="KA", postal_code="560001",
            )
            session.add(branch)
            branches.append(branch)
        customer = User(
            id=uuid.uuid4(), full_name="Cust", email="rt-cust@example.com",
            hashed_password="x", role=UserRole.CUSTOMER, app_client_id=marketplace.id,
        )
        admin = User(
            id=uuid.uuid4(), full_name="Admin", email="rt-admin@example.com",
            hashed_password="x", role=UserRole.ADMIN,
        )
        session.add_all([customer, admin])
        session.commit()
        cls.owner_id = owner.id
        cls.admin_id = admin.id
        cls.customer_id = customer.id
        cls.restaurant_id = restaurants[0].id
        cls.other_restaurant_id = restaurants[1].id
        cls.branch_id = branches[0].id
        cls.second_branch_id = branches[1].id

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)
        self.emitter = RecordingEmitter()
        self.published: list[tuple[str, str]] = []
        outbox.set_emitter_for_tests(self.emitter, lambda ch, msg: self.published.append((ch, msg)))
        self.addCleanup(outbox.set_emitter_for_tests, None, None)
        flag = mock.patch.object(settings, "enable_realtime", True)
        flag.start()
        self.addCleanup(flag.stop)

    def _user(self, user_id: uuid.UUID) -> User:
        return self.session.get(User, user_id)

    def _cook(self, *, pinned: bool) -> User:
        cook = User(
            id=uuid.uuid4(), full_name="Cook", email=f"rt-cook-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x", role=UserRole.KITCHEN, staff_restaurant_id=self.restaurant_id,
            staff_restaurant_location_id=self.branch_id if pinned else None,
        )
        self.session.add(cook)
        self.session.commit()
        return cook

    def _order(self, status: OrderStatus = OrderStatus.PLACED) -> Order:
        order = Order(
            id=uuid.uuid4(), customer_id=self.customer_id, restaurant_id=self.restaurant_id,
            restaurant_location_id=self.branch_id, status=status,
            payment_status=PaymentStatus.PAID, payment_method=PaymentMethod.CARD,
            payment_provider="test", fulfillment_type=OrderFulfillmentType.DELIVERY,
            schedule_type=OrderScheduleType.ASAP, scheduled_at=datetime.now(UTC),
            subtotal=Decimal("500.00"), delivery_fee=Decimal("0.00"), tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"), total_amount=Decimal("500.00"), currency="INR",
            delivery_address="1 St", placed_at=datetime.now(UTC),
        )
        self.session.add(order)
        self.session.commit()
        self.emitter.emitted.clear()
        return order


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class OutboxTests(RealtimeFixture, unittest.TestCase):
    """Emitted after the commit, discarded on rollback, never fatal."""

    def _advance(self, order: Order) -> None:
        with mock.patch("app.services.orders.celery_app"):
            update_order_status(
                self.session, self._user(self.owner_id), order_id=order.id,
                new_status=OrderStatus.ACCEPTED, owner_restaurant_id=self.restaurant_id,
            )

    def test_committed_transition_is_pushed_to_every_room_with_a_viewer(self) -> None:
        order = self._order()
        self._advance(order)

        self.assertEqual(len(self.emitter.emitted), 1)
        event, payload, rooms = self.emitter.emitted[0]
        self.assertEqual(event, "order:updated")
        self.assertEqual(payload["order_id"], str(order.id))
        self.assertEqual(payload["status"], "ACCEPTED")
        self.assertEqual(payload["from_status"], "PLACED")
        self.assertEqual(
            set(rooms),
            {location_room(self.branch_id), restaurant_room(self.restaurant_id),
             ADMIN_ALL_ROOM, user_room(self.customer_id)},
        )

    def test_payload_carries_no_order_contents(self) -> None:
        # Thin on purpose: the client refetches through REST, whose scope is
        # the only one that decides what anybody sees.
        order = self._order()
        self._advance(order)
        _, payload, _ = self.emitter.emitted[0]
        self.assertEqual(
            set(payload),
            {"order_id", "restaurant_id", "restaurant_location_id", "status", "from_status", "occurred_at"},
        )

    def test_nothing_is_pushed_before_the_commit(self) -> None:
        order = self._order()
        outbox.queue_order_updated(
            self.session, order_id=order.id, restaurant_id=order.restaurant_id,
            restaurant_location_id=order.restaurant_location_id, customer_id=order.customer_id,
            to_status=OrderStatus.ACCEPTED, from_status=OrderStatus.PLACED, occurred_at=None,
        )
        self.session.flush()
        self.assertEqual(self.emitter.emitted, [])
        self.session.commit()
        self.assertEqual(len(self.emitter.emitted), 1)

    def test_rolled_back_transition_is_never_pushed(self) -> None:
        order = self._order()
        outbox.queue_order_updated(
            self.session, order_id=order.id, restaurant_id=order.restaurant_id,
            restaurant_location_id=order.restaurant_location_id, customer_id=order.customer_id,
            to_status=OrderStatus.ACCEPTED, from_status=OrderStatus.PLACED, occurred_at=None,
        )
        self.session.rollback()
        # And a later, unrelated commit on the same session must not carry it.
        self.session.commit()
        self.assertEqual(self.emitter.emitted, [])

    def test_a_broken_emitter_never_costs_the_order(self) -> None:
        self.emitter.fail = True
        order = self._order()
        self._advance(order)
        self.session.expire_all()
        self.assertEqual(self.session.get(Order, order.id).status, OrderStatus.ACCEPTED)

    def test_flag_off_queues_nothing(self) -> None:
        order = self._order()
        with mock.patch.object(settings, "enable_realtime", False):
            self._advance(order)
        self.assertEqual(self.emitter.emitted, [])

    def test_revocation_announces_and_publishes_after_commit(self) -> None:
        outbox.queue_session_revoked(self.session, user_id=self.owner_id)
        self.assertEqual(self.published, [])
        self.session.commit()
        self.assertEqual(self.emitter.emitted[0][0], "session:revoked")
        self.assertEqual(self.emitter.emitted[0][2], user_room(self.owner_id))
        channel, message = self.published[0]
        self.assertEqual(channel, outbox.control_channel())
        self.assertEqual(json.loads(message), {"type": "revoke", "user_id": str(self.owner_id)})


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class HandshakeTests(RealtimeFixture, unittest.TestCase):
    """A socket opens only for a token REST would accept, into its own scope."""

    def _auth(self, user: User, **extra) -> dict:
        return {"token": create_access_token(user), **extra}

    def test_pinned_cook_sits_in_their_branch_room(self) -> None:
        cook = self._cook(pinned=True)
        principal = authenticate(self.session, self._auth(cook))
        self.assertEqual(principal.staff_room, location_room(self.branch_id))

    def test_unpinned_cook_sits_in_the_restaurant_room(self) -> None:
        cook = self._cook(pinned=False)
        principal = authenticate(self.session, self._auth(cook))
        self.assertEqual(principal.staff_room, restaurant_room(self.restaurant_id))

    def test_owner_may_narrow_to_a_branch(self) -> None:
        owner = self._user(self.owner_id)
        principal = authenticate(
            self.session, self._auth(owner, restaurant_location_id=str(self.second_branch_id))
        )
        self.assertEqual(principal.staff_room, location_room(self.second_branch_id))

    def test_owner_cannot_ask_for_another_restaurant(self) -> None:
        owner = self._user(self.owner_id)
        with self.assertRaises(RealtimeRefused) as caught:
            authenticate(self.session, self._auth(owner, restaurant_id=str(self.other_restaurant_id)))
        self.assertEqual(caught.exception.reason, "forbidden")

    def test_admin_without_a_restaurant_hears_everything(self) -> None:
        principal = authenticate(self.session, self._auth(self._user(self.admin_id)))
        self.assertEqual(principal.staff_room, ADMIN_ALL_ROOM)

    def test_customer_has_no_staff_room(self) -> None:
        principal = authenticate(self.session, self._auth(self._user(self.customer_id)))
        self.assertIsNone(principal.staff_room)
        self.assertEqual(principal.role, UserRole.CUSTOMER)

    def test_missing_or_garbage_token_is_auth(self) -> None:
        for auth in (None, {}, {"token": ""}, {"token": "not-a-jwt"}):
            with self.assertRaises(RealtimeRefused) as caught:
                authenticate(self.session, auth)
            self.assertEqual(caught.exception.reason, "auth", auth)

    def test_stale_token_version_is_auth(self) -> None:
        cook = self._cook(pinned=True)
        token = create_access_token(cook)
        cook.token_version += 1
        self.session.commit()
        with self.assertRaises(RealtimeRefused) as caught:
            authenticate(self.session, {"token": token})
        self.assertEqual(caught.exception.reason, "auth")

    def test_inactive_account_is_refused(self) -> None:
        cook = self._cook(pinned=True)
        token = create_access_token(cook)
        cook.is_active = False
        self.session.commit()
        with self.assertRaises(RealtimeRefused) as caught:
            authenticate(self.session, {"token": token})
        self.assertEqual(caught.exception.reason, "forbidden")

    def test_pinned_cook_cannot_resubscribe_to_another_branch(self) -> None:
        cook = self._cook(pinned=True)
        principal = authenticate(self.session, self._auth(cook))
        with self.assertRaises(RealtimeRefused) as caught:
            resubscribe(self.session, principal, {"restaurant_location_id": str(self.second_branch_id)})
        self.assertEqual(caught.exception.reason, "forbidden")

    def test_resubscribe_rereads_the_account(self) -> None:
        cook = self._cook(pinned=False)
        principal = authenticate(self.session, self._auth(cook))
        moved = resubscribe(self.session, principal, {"restaurant_location_id": str(self.branch_id)})
        self.assertEqual(moved.staff_room, location_room(self.branch_id))

        cook.token_version += 1
        self.session.commit()
        with self.assertRaises(RealtimeRefused) as caught:
            resubscribe(self.session, principal, {})
        self.assertEqual(caught.exception.reason, "auth")

    def test_sweep_finds_expired_revoked_and_deactivated_sockets(self) -> None:
        live, revoked, gone = self._cook(pinned=True), self._cook(pinned=True), self._cook(pinned=True)
        principals = {
            sid: Principal(u.id, u.role, u.token_version, int(time.time()) + 3600, None)
            for sid, u in (("live", live), ("revoked", revoked), ("gone", gone))
        }
        principals["expired"] = Principal(live.id, live.role, live.token_version, int(time.time()) - 1, None)
        revoked.token_version += 1
        gone.is_active = False
        self.session.commit()

        stale = stale_principals(self.session, principals, now=time.time())
        self.assertEqual(set(stale), {"revoked", "gone", "expired"})

    def test_real_handshake_over_the_mounted_endpoint(self) -> None:
        # End to end through the ASGI mount, Engine.IO and the connect handler,
        # with only the session factory pointed at the test database.
        cook = self._cook(pinned=True)
        with mock.patch.object(rt_server, "SessionLocal", self.session_factory):
            self.assertEqual(_socketio_handshake({"token": "nope"}), ("refused", "auth"))
            outcome, _sid = _socketio_handshake({"token": create_access_token(cook)})
        self.assertEqual(outcome, "connected")


if __name__ == "__main__":
    unittest.main()
