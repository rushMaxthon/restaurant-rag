"""What a kitchen account can reach, and what the database refuses to store.

Advancing an order used to be `require_owner`, so the only way to run a screen
in a kitchen was to leave the owner signed in on it — one token that also edits
the menu, spends money on marketing and reads revenue, on a tablet anyone
walking past can pick up. KITCHEN exists to be the narrow alternative, and
"narrow" is the whole claim, so these tests are mostly about what it CANNOT do.

Two layers are covered on purpose, because either alone would be a false
comfort:

* the database, which refuses a kitchen row with no restaurant and a branch
  belonging to a different restaurant — states that would widen a cook's scope
  without any code being wrong;
* `resolve_order_board_scope`, the single function the order list and the
  status write both call, so a cook can never be shown an order they may not
  advance or advance one they were never shown.

The last group pins the thing that would be worst to get wrong: a cook at one
branch advancing another branch's order by pasting its id.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401  imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import (
    OrderEventActor,
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.auth import (
    ORDER_BOARD_ROLES,
    resolve_kitchen_assignment,
    resolve_order_board_scope,
)
from app.services.order_events import actor_for_user
from app.services.orders import get_order_for_user, update_order_status
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()
TEST_DB_NAME = os.environ.get("KITCHEN_TEST_DB", "restaurant_rag_kitchen_test")


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
    """A cook's advance is a cook's, not the platform's."""

    def test_kitchen_has_its_own_actor(self) -> None:
        user = User(
            id=uuid.uuid4(),
            full_name="Cook",
            email="c@example.com",
            hashed_password="x",
            role=UserRole.KITCHEN,
        )
        # Before KITCHEN was added to OrderEventActor this fell through to
        # SYSTEM, which reads as "nobody did this".
        self.assertEqual(actor_for_user(user), OrderEventActor.KITCHEN)

    def test_kitchen_is_an_order_board_role(self) -> None:
        self.assertIn(UserRole.KITCHEN, ORDER_BOARD_ROLES)
        self.assertNotIn(UserRole.CUSTOMER, ORDER_BOARD_ROLES)


class KitchenFixture:
    """Two restaurants, one branch each, on a throwaway database.

    A mixin rather than a base TestCase: subclassing a class that carries its
    own test methods would re-run every one of them in each suite below.
    """

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
    def _restaurant(cls, session: Session, owner_email: str, slug: str) -> tuple[Restaurant, RestaurantLocation]:
        owner = User(
            id=uuid.uuid4(),
            full_name="Owner",
            email=owner_email,
            hashed_password="x",
            role=UserRole.OWNER,
        )
        session.add(owner)
        session.flush()
        restaurant = Restaurant(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name=slug,
            slug=slug,
            cuisine_type="Thai",
            address_line_1="1 St",
            city="BLR",
            state="KA",
            postal_code="560001",
            is_approved=True,
            is_active=True,
        )
        session.add(restaurant)
        session.flush()
        location = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            branch_name="Main",
            address_line_1="1 St",
            city="BLR",
            state="KA",
            postal_code="560001",
        )
        session.add(location)
        session.flush()
        return restaurant, location

    @classmethod
    def _seed(cls, session: Session) -> None:
        restaurant_a, location_a = cls._restaurant(session, "k-owner-a@example.com", "kitchen-a")
        restaurant_b, location_b = cls._restaurant(session, "k-owner-b@example.com", "kitchen-b")
        session.commit()
        cls.restaurant_a_id = restaurant_a.id
        cls.location_a_id = location_a.id
        cls.restaurant_b_id = restaurant_b.id
        cls.location_b_id = location_b.id

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)

    def _cook(self, **kwargs) -> User:
        return User(
            id=uuid.uuid4(),
            full_name="Cook",
            email=f"cook-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            role=UserRole.KITCHEN,
            **kwargs,
        )


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class KitchenAssignmentConstraintTests(KitchenFixture, unittest.TestCase):
    """States the database itself must refuse to hold."""

    def test_kitchen_without_a_restaurant_is_rejected(self) -> None:
        # The one state that would let a kitchen account read every order on
        # the platform, so the database refuses it rather than the service.
        self.session.add(self._cook())
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_kitchen_pinned_to_another_restaurants_branch_is_rejected(self) -> None:
        # The composite foreign key, doing the job a plain one onto
        # `restaurant_locations.id` would have missed entirely.
        self.session.add(
            self._cook(
                staff_restaurant_id=self.restaurant_a_id,
                staff_restaurant_location_id=self.location_b_id,
            )
        )
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_non_kitchen_roles_carry_no_assignment(self) -> None:
        admin = User(
            id=uuid.uuid4(),
            full_name="Admin",
            email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            role=UserRole.ADMIN,
            staff_restaurant_id=self.restaurant_a_id,
        )
        self.session.add(admin)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_restaurant_without_a_branch_is_allowed(self) -> None:
        # NULL is a real answer: a single-branch restaurant has nothing to pin.
        cook = self._cook(staff_restaurant_id=self.restaurant_a_id)
        self.session.add(cook)
        self.session.commit()
        self.assertIsNone(cook.staff_restaurant_location_id)

    def test_restaurant_with_its_own_branch_is_allowed(self) -> None:
        cook = self._cook(
            staff_restaurant_id=self.restaurant_a_id,
            staff_restaurant_location_id=self.location_a_id,
        )
        self.session.add(cook)
        self.session.commit()
        assignment = resolve_kitchen_assignment(self.session, cook)
        self.assertEqual(assignment.restaurant_id, self.restaurant_a_id)
        self.assertEqual(assignment.restaurant_location_id, self.location_a_id)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class OrderBoardScopeTests(KitchenFixture, unittest.TestCase):
    """The one resolver the list and the write both go through."""

    def test_pinned_cook_gets_their_own_branch(self) -> None:
        cook = self._cook(
            staff_restaurant_id=self.restaurant_a_id,
            staff_restaurant_location_id=self.location_a_id,
        )
        self.session.add(cook)
        self.session.commit()

        scope = resolve_order_board_scope(self.session, cook)
        self.assertEqual(scope.restaurant_id, self.restaurant_a_id)
        self.assertEqual(scope.restaurant_location_id, self.location_a_id)

    def test_pinned_cook_cannot_ask_for_another_branch(self) -> None:
        cook = self._cook(
            staff_restaurant_id=self.restaurant_a_id,
            staff_restaurant_location_id=self.location_a_id,
        )
        self.session.add(cook)
        self.session.commit()

        with self.assertRaises(HTTPException) as caught:
            resolve_order_board_scope(
                self.session,
                cook,
                requested_restaurant_location_id=self.location_b_id,
            )
        self.assertEqual(caught.exception.status_code, 403)

    def test_cook_cannot_ask_for_another_restaurant(self) -> None:
        cook = self._cook(staff_restaurant_id=self.restaurant_a_id)
        self.session.add(cook)
        self.session.commit()

        with self.assertRaises(HTTPException) as caught:
            resolve_order_board_scope(
                self.session,
                cook,
                requested_restaurant_id=self.restaurant_b_id,
            )
        self.assertEqual(caught.exception.status_code, 403)

    def test_unpinned_cook_may_narrow_to_a_branch(self) -> None:
        # Assigned to the restaurant rather than one branch, so choosing a
        # branch is narrowing their own scope, not escaping it.
        cook = self._cook(staff_restaurant_id=self.restaurant_a_id)
        self.session.add(cook)
        self.session.commit()

        scope = resolve_order_board_scope(
            self.session,
            cook,
            requested_restaurant_location_id=self.location_a_id,
        )
        self.assertEqual(scope.restaurant_id, self.restaurant_a_id)
        self.assertEqual(scope.restaurant_location_id, self.location_a_id)

    def test_admin_without_a_restaurant_is_unnarrowed(self) -> None:
        # Platform staff have no restaurant of their own, by design.
        admin = User(
            id=uuid.uuid4(),
            full_name="Admin",
            email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            role=UserRole.ADMIN,
        )
        self.session.add(admin)
        self.session.commit()

        scope = resolve_order_board_scope(self.session, admin)
        self.assertIsNone(scope.restaurant_id)
        self.assertIsNone(scope.restaurant_location_id)

        named = resolve_order_board_scope(
            self.session, admin, requested_restaurant_id=self.restaurant_b_id
        )
        self.assertEqual(named.restaurant_id, self.restaurant_b_id)

    def test_customer_is_refused_outright(self) -> None:
        customer = User(
            id=uuid.uuid4(),
            full_name="Cust",
            email=f"cust-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            role=UserRole.CUSTOMER,
        )
        self.session.add(customer)
        self.session.commit()

        with self.assertRaises(HTTPException) as caught:
            resolve_order_board_scope(self.session, customer)
        self.assertEqual(caught.exception.status_code, 403)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class KitchenOrderAccessTests(KitchenFixture, unittest.TestCase):
    """A cook at one branch must not reach another branch's order."""

    def setUp(self) -> None:
        super().setUp()
        self.customer = User(
            id=uuid.uuid4(),
            full_name="Cust",
            email=f"cust-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            role=UserRole.CUSTOMER,
        )
        self.session.add(self.customer)
        self.session.commit()

    def _order(self, restaurant_id, location_id, status=OrderStatus.PLACED) -> Order:
        order = Order(
            id=uuid.uuid4(),
            customer_id=self.customer.id,
            restaurant_id=restaurant_id,
            restaurant_location_id=location_id,
            status=status,
            payment_status=PaymentStatus.PAID,
            payment_method=PaymentMethod.CARD,
            payment_provider="test",
            fulfillment_type=OrderFulfillmentType.DELIVERY,
            schedule_type=OrderScheduleType.ASAP,
            scheduled_at=datetime.now(UTC),
            subtotal=Decimal("500.00"),
            delivery_fee=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("500.00"),
            currency="INR",
            delivery_address="1 St",
            placed_at=datetime.now(UTC),
        )
        self.session.add(order)
        self.session.commit()
        return order

    def _pinned_cook(self) -> User:
        cook = self._cook(
            staff_restaurant_id=self.restaurant_a_id,
            staff_restaurant_location_id=self.location_a_id,
        )
        self.session.add(cook)
        self.session.commit()
        return cook

    def test_cook_cannot_read_another_restaurants_order(self) -> None:
        cook = self._pinned_cook()
        other = self._order(self.restaurant_b_id, self.location_b_id)
        scope = resolve_order_board_scope(self.session, cook)

        # 404, not 403: the caller learns nothing about an order that is not
        # theirs, including whether it exists.
        with self.assertRaises(HTTPException) as caught:
            get_order_for_user(
                self.session,
                cook,
                other.id,
                owner_restaurant_id=scope.restaurant_id,
                owner_restaurant_location_id=scope.restaurant_location_id,
            )
        self.assertEqual(caught.exception.status_code, 404)

    def test_cook_cannot_advance_another_restaurants_order(self) -> None:
        cook = self._pinned_cook()
        other = self._order(self.restaurant_b_id, self.location_b_id)
        scope = resolve_order_board_scope(self.session, cook)

        with self.assertRaises(HTTPException) as caught:
            update_order_status(
                self.session,
                cook,
                order_id=other.id,
                new_status=OrderStatus.ACCEPTED,
                owner_restaurant_id=scope.restaurant_id,
                owner_restaurant_location_id=scope.restaurant_location_id,
            )
        self.assertEqual(caught.exception.status_code, 404)
        self.session.refresh(other)
        self.assertEqual(other.status, OrderStatus.PLACED)

    def test_cook_cannot_advance_a_sibling_branchs_order(self) -> None:
        # The sharper case: same restaurant, different branch. Without the
        # location narrowing this one would have gone through.
        sibling = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=self.restaurant_a_id,
            branch_name=f"Second-{uuid.uuid4().hex[:6]}",
            address_line_1="2 St",
            city="BLR",
            state="KA",
            postal_code="560002",
        )
        self.session.add(sibling)
        self.session.commit()

        cook = self._pinned_cook()
        order = self._order(self.restaurant_a_id, sibling.id)
        scope = resolve_order_board_scope(self.session, cook)

        with self.assertRaises(HTTPException) as caught:
            update_order_status(
                self.session,
                cook,
                order_id=order.id,
                new_status=OrderStatus.ACCEPTED,
                owner_restaurant_id=scope.restaurant_id,
                owner_restaurant_location_id=scope.restaurant_location_id,
            )
        self.assertEqual(caught.exception.status_code, 404)
        self.session.refresh(order)
        self.assertEqual(order.status, OrderStatus.PLACED)

    def test_cook_advances_their_own_branchs_order(self) -> None:
        cook = self._pinned_cook()
        order = self._order(self.restaurant_a_id, self.location_a_id)
        scope = resolve_order_board_scope(self.session, cook)

        result = update_order_status(
            self.session,
            cook,
            order_id=order.id,
            new_status=OrderStatus.ACCEPTED,
            owner_restaurant_id=scope.restaurant_id,
            owner_restaurant_location_id=scope.restaurant_location_id,
        )
        self.assertEqual(result.status, OrderStatus.ACCEPTED)

    def test_the_flow_stays_one_step_at_a_time(self) -> None:
        # KITCHEN gains no power to skip states; the linear flow is unchanged.
        cook = self._pinned_cook()
        order = self._order(self.restaurant_a_id, self.location_a_id)
        scope = resolve_order_board_scope(self.session, cook)

        with self.assertRaises(HTTPException) as caught:
            update_order_status(
                self.session,
                cook,
                order_id=order.id,
                new_status=OrderStatus.DELIVERED,
                owner_restaurant_id=scope.restaurant_id,
                owner_restaurant_location_id=scope.restaurant_location_id,
            )
        self.assertEqual(caught.exception.status_code, 400)

    def test_an_unpaid_order_is_still_refused(self) -> None:
        cook = self._pinned_cook()
        order = self._order(self.restaurant_a_id, self.location_a_id)
        order.payment_status = PaymentStatus.PENDING
        self.session.commit()
        scope = resolve_order_board_scope(self.session, cook)

        with self.assertRaises(HTTPException) as caught:
            update_order_status(
                self.session,
                cook,
                order_id=order.id,
                new_status=OrderStatus.ACCEPTED,
                owner_restaurant_id=scope.restaurant_id,
                owner_restaurant_location_id=scope.restaurant_location_id,
            )
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class KitchenStaffProvisioningTests(KitchenFixture, unittest.TestCase):
    """Creating the accounts, which nothing else on the platform does.

    The role would be unreachable without this route: the only other thing that
    makes a staff account is `POST /restaurants`, which makes one OWNER beside
    a new restaurant and nothing else.
    """

    def _client_as(self, user_id):
        from fastapi.testclient import TestClient
        from app.config.database import get_db
        from app.services.auth import get_current_user

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

    def _owner_of(self, restaurant_id):
        return self.session.scalar(
            __import__("sqlalchemy").select(User).join(
                Restaurant, Restaurant.owner_id == User.id
            ).where(Restaurant.id == restaurant_id)
        )

    def test_owner_creates_a_cook_for_their_own_restaurant(self) -> None:
        owner = self._owner_of(self.restaurant_a_id)
        client = self._client_as(owner.id)

        response = client.post(
            "/api/kitchen-staff",
            json={
                "full_name": "Night Cook",
                "email": f"cook-{uuid.uuid4().hex[:8]}@example.com",
                "password": "kitchen-pass-1",
                "restaurant_location_id": str(self.location_a_id),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["restaurant_id"], str(self.restaurant_a_id))
        self.assertEqual(body["restaurant_location_id"], str(self.location_a_id))
        self.assertEqual(body["branch_name"], "Main")

    def test_owner_cannot_pin_a_cook_to_another_restaurants_branch(self) -> None:
        owner = self._owner_of(self.restaurant_a_id)
        client = self._client_as(owner.id)

        response = client.post(
            "/api/kitchen-staff",
            json={
                "full_name": "Wrong Branch",
                "email": f"cook-{uuid.uuid4().hex[:8]}@example.com",
                "password": "kitchen-pass-1",
                "restaurant_location_id": str(self.location_b_id),
            },
        )
        # A readable refusal rather than the IntegrityError the composite
        # foreign key would otherwise raise as a 500.
        self.assertEqual(response.status_code, 400)

    def test_owner_cannot_create_for_another_restaurant(self) -> None:
        owner = self._owner_of(self.restaurant_a_id)
        client = self._client_as(owner.id)

        response = client.post(
            "/api/kitchen-staff",
            json={
                "full_name": "Somebody Else's",
                "email": f"cook-{uuid.uuid4().hex[:8]}@example.com",
                "password": "kitchen-pass-1",
                "restaurant_id": str(self.restaurant_b_id),
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_a_cook_cannot_create_another_cook(self) -> None:
        # The whole point of the role: it runs a board and nothing else.
        cook = self._cook(staff_restaurant_id=self.restaurant_a_id)
        self.session.add(cook)
        self.session.commit()
        client = self._client_as(cook.id)

        response = client.post(
            "/api/kitchen-staff",
            json={
                "full_name": "A Peer",
                "email": f"cook-{uuid.uuid4().hex[:8]}@example.com",
                "password": "kitchen-pass-1",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_must_name_a_restaurant(self) -> None:
        admin = User(
            id=uuid.uuid4(),
            full_name="Admin",
            email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            role=UserRole.ADMIN,
        )
        self.session.add(admin)
        self.session.commit()
        client = self._client_as(admin.id)

        response = client.post(
            "/api/kitchen-staff",
            json={
                "full_name": "Unscoped",
                "email": f"cook-{uuid.uuid4().hex[:8]}@example.com",
                "password": "kitchen-pass-1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("restaurant_id is required", response.json()["detail"])

    def test_listing_only_shows_this_restaurants_cooks(self) -> None:
        mine = self._cook(staff_restaurant_id=self.restaurant_a_id)
        theirs = self._cook(staff_restaurant_id=self.restaurant_b_id)
        self.session.add_all([mine, theirs])
        self.session.commit()

        owner = self._owner_of(self.restaurant_a_id)
        body = self._client_as(owner.id).get("/api/kitchen-staff").json()
        returned = {row["id"] for row in body}
        self.assertIn(str(mine.id), returned)
        self.assertNotIn(str(theirs.id), returned)

    def test_deactivating_ends_the_sessions_already_issued(self) -> None:
        cook = self._cook(staff_restaurant_id=self.restaurant_a_id)
        self.session.add(cook)
        self.session.commit()
        before = cook.token_version

        owner = self._owner_of(self.restaurant_a_id)
        response = self._client_as(owner.id).patch(
            f"/api/kitchen-staff/{cook.id}", json={"is_active": False}
        )
        self.assertEqual(response.status_code, 200, response.text)

        self.session.expire_all()
        refreshed = self.session.get(User, cook.id)
        self.assertFalse(refreshed.is_active)
        # Otherwise the tablet on the wall keeps working until the token
        # happens to expire on its own.
        self.assertGreater(refreshed.token_version, before)

    def test_another_restaurants_cook_is_not_found(self) -> None:
        theirs = self._cook(staff_restaurant_id=self.restaurant_b_id)
        self.session.add(theirs)
        self.session.commit()

        owner = self._owner_of(self.restaurant_a_id)
        response = self._client_as(owner.id).patch(
            f"/api/kitchen-staff/{theirs.id}", json={"is_active": False}
        )
        self.assertEqual(response.status_code, 404)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class KitchenBoardRouteTests(KitchenFixture, unittest.TestCase):
    """The two HTTP calls the kitchen board actually makes.

    The service-level tests above pin the rules; these pin that the routes are
    wired to them — that `GET /orders` and `PATCH /orders/{id}/status` reach
    `resolve_order_board_scope` rather than one of them having been left on the
    old owner-only path.
    """

    def _client_as(self, user_id):
        from fastapi.testclient import TestClient
        from app.config.database import get_db
        from app.services.auth import get_current_user

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

    def setUp(self) -> None:
        super().setUp()
        self.customer = User(
            id=uuid.uuid4(),
            full_name="Cust",
            email=f"cust-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            role=UserRole.CUSTOMER,
        )
        self.session.add(self.customer)
        self.session.commit()

    def _order(self, restaurant_id, location_id) -> Order:
        order = Order(
            id=uuid.uuid4(),
            customer_id=self.customer.id,
            restaurant_id=restaurant_id,
            restaurant_location_id=location_id,
            status=OrderStatus.PLACED,
            payment_status=PaymentStatus.PAID,
            payment_method=PaymentMethod.CARD,
            payment_provider="test",
            fulfillment_type=OrderFulfillmentType.DELIVERY,
            schedule_type=OrderScheduleType.ASAP,
            scheduled_at=datetime.now(UTC),
            subtotal=Decimal("500.00"),
            delivery_fee=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("500.00"),
            currency="INR",
            delivery_address="1 St",
            placed_at=datetime.now(UTC),
        )
        self.session.add(order)
        self.session.commit()
        return order

    def _pinned_cook(self) -> User:
        cook = self._cook(
            staff_restaurant_id=self.restaurant_a_id,
            staff_restaurant_location_id=self.location_a_id,
        )
        self.session.add(cook)
        self.session.commit()
        return cook

    def test_the_board_lists_only_this_branch(self) -> None:
        mine = self._order(self.restaurant_a_id, self.location_a_id)
        theirs = self._order(self.restaurant_b_id, self.location_b_id)
        cook = self._pinned_cook()

        response = self._client_as(cook.id).get("/api/orders", params={"order_status": "PLACED"})
        self.assertEqual(response.status_code, 200, response.text)
        returned = {row["id"] for row in response.json()}
        self.assertIn(str(mine.id), returned)
        self.assertNotIn(str(theirs.id), returned)

    def test_a_cook_advances_their_own_order_over_http(self) -> None:
        order = self._order(self.restaurant_a_id, self.location_a_id)
        cook = self._pinned_cook()

        response = self._client_as(cook.id).patch(
            f"/api/orders/{order.id}/status", json={"status": "ACCEPTED"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "ACCEPTED")

    def test_a_cook_cannot_advance_another_branchs_order_over_http(self) -> None:
        # The attack this whole slice exists to stop: a valid kitchen token and
        # somebody else's order id.
        order = self._order(self.restaurant_b_id, self.location_b_id)
        cook = self._pinned_cook()

        response = self._client_as(cook.id).patch(
            f"/api/orders/{order.id}/status", json={"status": "ACCEPTED"}
        )
        self.assertEqual(response.status_code, 404)
        self.session.expire_all()
        self.assertEqual(self.session.get(Order, order.id).status, OrderStatus.PLACED)

    def test_a_customer_still_cannot_advance_anything(self) -> None:
        # Unchanged by this slice, and worth a test because the route moved off
        # `require_owner` and a wider dependency is exactly how that breaks.
        order = self._order(self.restaurant_a_id, self.location_a_id)
        response = self._client_as(self.customer.id).patch(
            f"/api/orders/{order.id}/status", json={"status": "ACCEPTED"}
        )
        self.assertEqual(response.status_code, 403)

    def test_an_owner_still_advances_their_own_order(self) -> None:
        # The behaviour that existed before KITCHEN did, still working.
        import sqlalchemy as sa

        owner = self.session.scalar(
            sa.select(User).join(Restaurant, Restaurant.owner_id == User.id).where(
                Restaurant.id == self.restaurant_a_id
            )
        )
        order = self._order(self.restaurant_a_id, self.location_a_id)
        response = self._client_as(owner.id).patch(
            f"/api/orders/{order.id}/status", json={"status": "ACCEPTED"}
        )
        self.assertEqual(response.status_code, 200, response.text)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class LiveWindowTests(KitchenFixture, unittest.TestCase):
    """`due_from`: the window that keeps the kitchen board a live queue.

    Written after a branch reached 206 PLACED orders, 178 of them more than a
    week old. The board asks for one page sorted oldest-first, so every order
    placed after the hundredth was invisible to the kitchen while appearing
    normally on the owner's list. Nothing errored; the board showed a page and
    presented it as the queue.

    The filter is on COALESCE(scheduled_at, placed_at) rather than `placed_at`,
    and that is the part most likely to be "simplified" later by someone who
    reads `placed_at` as the obvious column. It is not: a scheduled order is
    placed before its slot — one in the live database 21 days before — so a
    `placed_at` window hides tonight's work because it was ordered last week.
    The second test is the one that fails if anyone makes that change.
    """

    def _client_as(self, user_id):
        from fastapi.testclient import TestClient
        from app.config.database import get_db
        from app.services.auth import get_current_user

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

    def setUp(self) -> None:
        super().setUp()
        # The fixture builds one database per CLASS, so orders written by an
        # earlier test in this class are still here. These tests assert on
        # counts — `X-Total-Count` is the whole point of two of them — so they
        # start from an empty table rather than from whatever ran first.
        self.session.query(Order).delete()
        self.session.commit()
        self.customer = User(
            id=uuid.uuid4(),
            full_name="Cust",
            email=f"cust-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            role=UserRole.CUSTOMER,
        )
        self.session.add(self.customer)
        self.session.commit()

    def _order_at(self, placed_at, *, scheduled_at=None, schedule_type=OrderScheduleType.ASAP):
        order = Order(
            id=uuid.uuid4(),
            customer_id=self.customer.id,
            restaurant_id=self.restaurant_a_id,
            restaurant_location_id=self.location_a_id,
            status=OrderStatus.PLACED,
            payment_status=PaymentStatus.PAID,
            payment_method=PaymentMethod.CARD,
            payment_provider="test",
            fulfillment_type=OrderFulfillmentType.DELIVERY,
            schedule_type=schedule_type,
            scheduled_at=scheduled_at if scheduled_at is not None else placed_at,
            subtotal=Decimal("500.00"),
            delivery_fee=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("500.00"),
            currency="INR",
            delivery_address="1 St",
            placed_at=placed_at,
        )
        self.session.add(order)
        self.session.commit()
        return order

    def _cook_on_a(self) -> User:
        cook = self._cook(
            staff_restaurant_id=self.restaurant_a_id,
            staff_restaurant_location_id=self.location_a_id,
        )
        self.session.add(cook)
        self.session.commit()
        return cook

    def _board(self, cook, **params):
        query = {"order_status": "PLACED", **params}
        response = self._client_as(cook.id).get("/api/orders", params=query)
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_the_window_drops_the_stale_and_keeps_the_fresh(self) -> None:
        now = datetime.now(UTC)
        fresh = self._order_at(now - timedelta(minutes=5))
        stale = self._order_at(now - timedelta(days=9))
        cook = self._cook_on_a()

        returned = {
            row["id"]
            for row in self._board(
                cook, due_from=(now - timedelta(hours=24)).isoformat()
            ).json()
        }
        self.assertIn(str(fresh.id), returned)
        self.assertNotIn(str(stale.id), returned)

    def test_an_order_scheduled_for_tonight_survives_being_ordered_last_week(self) -> None:
        """The reason the filter is not on `placed_at`."""

        now = datetime.now(UTC)
        booked_ahead = self._order_at(
            now - timedelta(days=7),
            scheduled_at=now - timedelta(minutes=30),
            schedule_type=OrderScheduleType.SCHEDULED,
        )
        cook = self._cook_on_a()

        returned = {
            row["id"]
            for row in self._board(
                cook, due_from=(now - timedelta(hours=24)).isoformat()
            ).json()
        }
        self.assertIn(str(booked_ahead.id), returned)

    def test_the_total_counts_the_window_not_all_history(self) -> None:
        """`X-Total-Count` is what tells the board it is showing everything."""

        now = datetime.now(UTC)
        self._order_at(now - timedelta(minutes=5))
        for day in range(1, 6):
            self._order_at(now - timedelta(days=day + 2))
        cook = self._cook_on_a()

        response = self._board(cook, due_from=(now - timedelta(hours=24)).isoformat())
        self.assertEqual(response.headers["X-Total-Count"], "1")

    def test_the_total_ignores_the_page_limit(self) -> None:
        now = datetime.now(UTC)
        for minute in range(5):
            self._order_at(now - timedelta(minutes=minute))
        cook = self._cook_on_a()

        response = self._board(
            cook, due_from=(now - timedelta(hours=24)).isoformat(), limit=2
        )
        self.assertEqual(len(response.json()), 2)
        # The count the overflow notice is computed from: five match, two fit.
        self.assertEqual(response.headers["X-Total-Count"], "5")

    def test_the_window_does_not_widen_the_branch_scope(self) -> None:
        """A filter is not a licence. The scope still comes first."""

        now = datetime.now(UTC)
        theirs = Order(
            id=uuid.uuid4(),
            customer_id=self.customer.id,
            restaurant_id=self.restaurant_b_id,
            restaurant_location_id=self.location_b_id,
            status=OrderStatus.PLACED,
            payment_status=PaymentStatus.PAID,
            payment_method=PaymentMethod.CARD,
            payment_provider="test",
            fulfillment_type=OrderFulfillmentType.DELIVERY,
            schedule_type=OrderScheduleType.ASAP,
            scheduled_at=now,
            subtotal=Decimal("500.00"),
            delivery_fee=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("500.00"),
            currency="INR",
            delivery_address="1 St",
            placed_at=now,
        )
        self.session.add(theirs)
        self.session.commit()
        mine = self._order_at(now - timedelta(minutes=5))
        cook = self._cook_on_a()

        returned = {
            row["id"]
            for row in self._board(
                cook, due_from=(now - timedelta(hours=24)).isoformat()
            ).json()
        }
        self.assertIn(str(mine.id), returned)
        self.assertNotIn(str(theirs.id), returned)

    def test_without_the_window_nothing_changes(self) -> None:
        """The owner and admin lists pass no `due_from` and want all history."""

        now = datetime.now(UTC)
        fresh = self._order_at(now - timedelta(minutes=5))
        stale = self._order_at(now - timedelta(days=30))
        cook = self._cook_on_a()

        returned = {row["id"] for row in self._board(cook).json()}
        self.assertIn(str(fresh.id), returned)
        self.assertIn(str(stale.id), returned)


class DeactivationEndsSessionsTests(KitchenFixture, unittest.TestCase):
    """Switching an account off has to sign it out, by either route.

    There are two ways to deactivate a kitchen account: this feature's own
    `PATCH /kitchen-staff/{id}`, and the platform-wide
    `PATCH /admin/users/{id}` that the Users page uses. Only the first bumped
    `token_version`, so an owner who switched a cook off from the Users screen
    watched the tablet on the wall carry on taking orders until its token
    happened to expire.
    """

    def _client_as(self, user_id):
        from fastapi.testclient import TestClient
        from app.config.database import get_db
        from app.services.auth import get_current_user

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

    def _admin(self) -> User:
        admin = User(
            id=uuid.uuid4(),
            full_name="Admin",
            email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            role=UserRole.ADMIN,
        )
        self.session.add(admin)
        self.session.commit()
        return admin

    def test_the_platform_user_route_also_ends_sessions(self) -> None:
        cook = self._cook(staff_restaurant_id=self.restaurant_a_id)
        self.session.add(cook)
        self.session.commit()
        before = cook.token_version

        response = self._client_as(self._admin().id).patch(
            f"/api/admin/users/{cook.id}", json={"is_active": False}
        )
        self.assertEqual(response.status_code, 200, response.text)

        self.session.expire_all()
        refreshed = self.session.get(User, cook.id)
        self.assertFalse(refreshed.is_active)
        self.assertGreater(refreshed.token_version, before)

    def test_reactivating_leaves_the_token_version_alone(self) -> None:
        # Only switching OFF is urgent. Bumping on reactivation would sign out
        # a session that was about to become valid again for no reason.
        cook = self._cook(staff_restaurant_id=self.restaurant_a_id, is_active=False)
        self.session.add(cook)
        self.session.commit()
        before = cook.token_version

        response = self._client_as(self._admin().id).patch(
            f"/api/admin/users/{cook.id}", json={"is_active": True}
        )
        self.assertEqual(response.status_code, 200, response.text)

        self.session.expire_all()
        refreshed = self.session.get(User, cook.id)
        self.assertTrue(refreshed.is_active)
        self.assertEqual(refreshed.token_version, before)
