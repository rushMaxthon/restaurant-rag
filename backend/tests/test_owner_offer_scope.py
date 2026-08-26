"""Restaurant scoping for owner-triggered AI offer generation.

Generating offers used to be a platform-wide admin action. Moving the button to
the owner's own Offers screen means an owner now triggers it, so the run has to
be confined to their restaurant - otherwise pressing Generate would create
offers across every restaurant on the platform.

These tests seed two restaurants and assert the scope holds at both ends: which
customers are scanned, and which restaurant a candidate can name.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.main import app  # noqa: F401 - imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import (
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
from app.services.ai_offer_generation import (
    _build_offer_candidate_for_user,
    _pick_default_restaurant,
    generate_ai_offers,
)


def _stub_payload() -> dict[str, object]:
    """A valid offer payload, so no test here reaches the language model."""

    return {
        "title": "Scoped offer",
        "subtitle": "Built for this restaurant only.",
        "discount_type": "flat",
        "discount_value": 25,
        "minimum_order": 199,
        "cta": "Order Now",
        "reason": "Scope test.",
    }

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_owner_offer_scope_test"


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
            engine.dispose()


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class OwnerOfferScopeTests(unittest.TestCase):
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
        def make_user(name: str, email: str, role: UserRole) -> User:
            row = User(
                id=uuid.uuid4(),
                app_client_id=None,
                full_name=name,
                email=email,
                hashed_password="x",
                role=role,
            )
            session.add(row)
            return row

        owner_mine = make_user("Mine Owner", "scope-mine@test.local", UserRole.OWNER)
        owner_theirs = make_user("Theirs Owner", "scope-theirs@test.local", UserRole.OWNER)
        loyal = make_user("Loyal", "scope-loyal@test.local", UserRole.CUSTOMER)
        outsider = make_user("Outsider", "scope-outsider@test.local", UserRole.CUSTOMER)
        session.flush()
        cls.loyal_id = loyal.id
        cls.outsider_id = outsider.id

        def make_restaurant(owner: User, name: str, slug: str, cuisine: str) -> Restaurant:
            row = Restaurant(
                id=uuid.uuid4(),
                owner_id=owner.id,
                name=name,
                slug=slug,
                cuisine_type=cuisine,
                address_line_1="1 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                is_approved=True,
                is_active=True,
            )
            session.add(row)
            return row

        mine = make_restaurant(owner_mine, "Mine Kitchen", "mine-kitchen", "Thai")
        theirs = make_restaurant(owner_theirs, "Theirs Kitchen", "theirs-kitchen", "Italian")
        session.flush()
        cls.mine_id = mine.id
        cls.theirs_id = theirs.id

        def make_location(restaurant: Restaurant) -> RestaurantLocation:
            row = RestaurantLocation(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                branch_name="Main",
                address_line_1="1 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
            )
            session.add(row)
            return row

        mine_loc = make_location(mine)
        theirs_loc = make_location(theirs)
        session.flush()

        def make_item(restaurant, location, name: str, price: str) -> MenuItem:
            row = MenuItem(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                restaurant_location_id=location.id,
                name=name,
                category="Mains",
                price=Decimal(price),
                is_available=True,
            )
            session.add(row)
            return row

        mine_item = make_item(mine, mine_loc, "Pad Thai", "220.00")
        theirs_item = make_item(theirs, theirs_loc, "Carbonara", "320.00")
        session.flush()

        def make_orders(customer, restaurant, location, item, count: int) -> None:
            # Several paid orders for the same dish, which is what the repeated
            # item branch of the candidate builder keys on.
            for index in range(count):
                order = Order(
                    id=uuid.uuid4(),
                    customer_id=customer.id,
                    restaurant_id=restaurant.id,
                    restaurant_location_id=location.id,
                    status=OrderStatus.DELIVERED,
                    payment_status=PaymentStatus.PAID,
                    payment_method=PaymentMethod.CARD,
                    subtotal=item.price,
                    total_amount=item.price,
                    delivery_address="1 Test Street",
                    scheduled_at=datetime.now(UTC) - timedelta(days=index + 1),
                    placed_at=datetime.now(UTC) - timedelta(days=index + 1),
                )
                session.add(order)
                session.flush()
                session.add(
                    OrderItem(
                        id=uuid.uuid4(),
                        order_id=order.id,
                        menu_item_id=item.id,
                        item_name_snapshot=item.name,
                        quantity=1,
                        base_unit_price=item.price,
                        unit_price=item.price,
                        total_price=item.price,
                    )
                )

        # The loyal customer eats at both, but far more often at Theirs - so an
        # unscoped run would build them an offer for Theirs Kitchen.
        make_orders(loyal, theirs, theirs_loc, theirs_item, 4)
        make_orders(loyal, mine, mine_loc, mine_item, 1)
        # The outsider has never paid Mine Kitchen at all.
        make_orders(outsider, theirs, theirs_loc, theirs_item, 3)
        session.commit()

    # -- the restaurant picker ---------------------------------------------

    def test_the_picker_returns_only_the_scoped_restaurant(self) -> None:
        with self.session_factory() as session:
            picked = _pick_default_restaurant(session, restaurant_id=self.mine_id)
        self.assertIsNotNone(picked)
        self.assertEqual(picked[0].id, self.mine_id)

    def test_the_picker_ignores_a_cuisine_that_points_elsewhere(self) -> None:
        # "Italian" is Theirs Kitchen's cuisine. Under a scope it must not win.
        with self.session_factory() as session:
            picked = _pick_default_restaurant(
                session, preferred_cuisine="Italian", restaurant_id=self.mine_id
            )
        self.assertIsNotNone(picked)
        self.assertEqual(picked[0].id, self.mine_id)

    def test_an_unscoped_picker_is_unchanged(self) -> None:
        with self.session_factory() as session:
            picked = _pick_default_restaurant(session, preferred_cuisine="Italian")
        self.assertIsNotNone(picked)
        self.assertEqual(picked[0].id, self.theirs_id)

    # -- the candidate builder ----------------------------------------------

    def test_an_unscoped_run_follows_the_customer_to_another_restaurant(self) -> None:
        # Establishes that the scope below is doing real work: without it this
        # customer's offer is built for a restaurant the owner does not own.
        with self.session_factory() as session:
            loyal = session.get(User, self.loyal_id)
            candidate = _build_offer_candidate_for_user(session, loyal)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.restaurant_id, self.theirs_id)

    def test_a_scoped_run_never_names_another_restaurant(self) -> None:
        with self.session_factory() as session:
            loyal = session.get(User, self.loyal_id)
            candidate = _build_offer_candidate_for_user(
                session, loyal, restaurant_id=self.mine_id
            )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.restaurant_id, self.mine_id)

    def test_a_scoped_run_holds_even_for_a_customer_who_never_ordered_here(self) -> None:
        # The generator will not scan this customer for Mine Kitchen, but if a
        # future change ever hands them over, the branches must still not build
        # an offer for somebody else.
        with self.session_factory() as session:
            outsider = session.get(User, self.outsider_id)
            candidate = _build_offer_candidate_for_user(
                session, outsider, restaurant_id=self.mine_id
            )
        if candidate is not None:
            self.assertEqual(candidate.restaurant_id, self.mine_id)


    # -- the run itself -----------------------------------------------------

    def test_a_scoped_run_scans_only_customers_who_paid_this_restaurant(self) -> None:
        # The outsider has orders, but none with Mine Kitchen, so a scoped run
        # must not even look at them. Unscoped, both customers are scanned.
        with self.session_factory() as session:
            with patch(
                "app.services.ai_offer_generation._generate_payload_with_llm"
            ) as llm, patch(
                "app.services.ai_offer_generation._persist_ai_offer_for_user"
            ):
                llm.return_value = (_stub_payload(), True, "stubbed")
                scoped = generate_ai_offers(
                    session, restaurant_id=self.mine_id, allow_disabled=True
                )
                unscoped = generate_ai_offers(session, allow_disabled=True)

        self.assertEqual(scoped.users_scanned, 1)
        self.assertEqual(unscoped.users_scanned, 2)

    def test_every_offer_a_scoped_run_writes_belongs_to_that_restaurant(self) -> None:
        seen: list[uuid.UUID] = []

        def capture(db, *, candidate, **kwargs):  # noqa: ANN001, ANN003
            seen.append(candidate.restaurant_id)

        with self.session_factory() as session:
            with patch(
                "app.services.ai_offer_generation._generate_payload_with_llm"
            ) as llm, patch(
                "app.services.ai_offer_generation._persist_ai_offer_for_user",
                side_effect=capture,
            ):
                llm.return_value = (_stub_payload(), True, "stubbed")
                generate_ai_offers(
                    session, restaurant_id=self.mine_id, allow_disabled=True
                )

        self.assertTrue(seen, "the scoped run wrote nothing, so nothing was proved")
        self.assertEqual(set(seen), {self.mine_id})


if __name__ == "__main__":
    unittest.main()
