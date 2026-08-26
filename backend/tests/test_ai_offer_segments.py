"""Segment-based AI offer generation.

The behaviour being pinned down: analysing a restaurant produces a small set of
distinct offers, each matched to the customers whose own order history makes
them eligible - rather than one offer per customer.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.main import app  # noqa: F401 - imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import (
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PersonalizedOfferState,
    PersonalizedOfferType,
    UserRole,
)
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.personalized_offer import GeneratedOffer, GeneratedOfferUserMatch
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.ai_offer_segments import (
    analyze_restaurant,
    derive_segments,
    generate_segment_offers,
)

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_offer_segments_test"


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
class SegmentOfferGenerationTests(unittest.TestCase):
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
        owner = User(
            id=uuid.uuid4(), app_client_id=None, full_name="Seg Owner",
            email="seg-owner@test.local", hashed_password="x", role=UserRole.OWNER,
        )
        session.add(owner)
        session.flush()

        restaurant = Restaurant(
            id=uuid.uuid4(), owner_id=owner.id, name="Segment Pizzeria",
            slug="segment-pizzeria", cuisine_type="Italian",
            address_line_1="1 Test Street", city="Bengaluru", state="Karnataka",
            postal_code="560001", is_approved=True, is_active=True,
        )
        session.add(restaurant)
        session.flush()
        cls.restaurant_id = restaurant.id

        location = RestaurantLocation(
            id=uuid.uuid4(), restaurant_id=restaurant.id, branch_name="Main",
            address_line_1="1 Test Street", city="Bengaluru", state="Karnataka",
            postal_code="560001",
        )
        # A second branch, because a restaurant-wide offer that only redeems at
        # the first one is the failure this suite exists to catch.
        second = RestaurantLocation(
            id=uuid.uuid4(), restaurant_id=restaurant.id, branch_name="Riverside",
            address_line_1="2 Test Street", city="Bengaluru", state="Karnataka",
            postal_code="560002",
        )
        session.add_all([location, second])
        session.flush()
        cls.location_id = location.id
        cls.second_location_id = second.id

        def make_item(name: str, category: str, price: str) -> MenuItem:
            row = MenuItem(
                id=uuid.uuid4(), restaurant_id=restaurant.id,
                restaurant_location_id=location.id, name=name, category=category,
                price=Decimal(price), is_available=True,
            )
            session.add(row)
            return row

        margherita = make_item("Margherita Pizza", "Pizza", "400.00")
        pepperoni = make_item("Pepperoni Pizza", "Pizza", "450.00")
        tiramisu = make_item("Tiramisu", "Dessert", "200.00")
        session.flush()
        cls.margherita_id = margherita.id

        def make_customer(name: str, email: str) -> User:
            row = User(
                id=uuid.uuid4(), app_client_id=None, full_name=name, email=email,
                hashed_password="x", role=UserRole.CUSTOMER,
            )
            session.add(row)
            session.flush()
            return row

        def order(customer: User, item: MenuItem, days_ago: int, quantity: int = 1) -> None:
            placed = datetime.now(UTC) - timedelta(days=days_ago)
            row = Order(
                id=uuid.uuid4(), customer_id=customer.id, restaurant_id=restaurant.id,
                restaurant_location_id=location.id, status=OrderStatus.DELIVERED,
                payment_status=PaymentStatus.PAID, payment_method=PaymentMethod.CARD,
                subtotal=item.price * quantity, total_amount=item.price * quantity,
                delivery_address="1 Test Street", scheduled_at=placed, placed_at=placed,
            )
            session.add(row)
            session.flush()
            session.add(
                OrderItem(
                    id=uuid.uuid4(), order_id=row.id, menu_item_id=item.id,
                    item_name_snapshot=item.name, quantity=quantity,
                    base_unit_price=item.price, unit_price=item.price,
                    total_price=item.price * quantity,
                )
            )

        # Four pizza regulars, all recent.
        cls.pizza_customer_ids = []
        for index in range(4):
            customer = make_customer(f"Pizza Fan {index}", f"seg-pizza{index}@test.local")
            cls.pizza_customer_ids.append(customer.id)
            order(customer, margherita, days_ago=2 + index, quantity=2)
            order(customer, pepperoni, days_ago=5 + index)

        # One dessert-only customer, who must not qualify for a pizza offer.
        dessert = make_customer("Dessert Only", "seg-dessert@test.local")
        cls.dessert_customer_id = dessert.id
        order(dessert, tiramisu, days_ago=3, quantity=3)

        # Three customers who have not ordered in a long time.
        cls.lapsed_ids = []
        for index in range(3):
            lapsed = make_customer(f"Lapsed {index}", f"seg-lapsed{index}@test.local")
            cls.lapsed_ids.append(lapsed.id)
            order(lapsed, margherita, days_ago=90 + index)

        session.commit()

    # -- analysis -----------------------------------------------------------

    def test_the_analysis_describes_the_restaurant_not_its_customers(self) -> None:
        with self.session_factory() as session:
            analysis = analyze_restaurant(session, self.restaurant_id)

        self.assertEqual(analysis.total_customers, 8)
        self.assertEqual(analysis.inactive_customers, 3)
        self.assertEqual(analysis.active_customers, 5)
        top_category = analysis.top_categories[0]
        self.assertEqual(top_category.name, "Pizza")
        # Distinct customers, not units sold.
        self.assertEqual(top_category.customers, 7)

    # -- segments ------------------------------------------------------------

    def test_a_run_produces_a_handful_of_offers_not_one_per_customer(self) -> None:
        with self.session_factory() as session:
            segments = derive_segments(analyze_restaurant(session, self.restaurant_id))

        self.assertLessEqual(len(segments), 5)
        self.assertGreater(len(segments), 1)
        # Eight customers, far fewer offers - which is the entire point.
        self.assertLess(len(segments), 8)

    def test_a_category_segment_is_dropped_when_the_top_dish_already_covers_it(self) -> None:
        # Margherita is the top dish and it is a Pizza, so emitting a Pizza
        # category offer as well would target the same people twice.
        with self.session_factory() as session:
            segments = derive_segments(analyze_restaurant(session, self.restaurant_id))

        keys = [segment.key for segment in segments]
        self.assertIn(f"top_item:{self.margherita_id}", keys)
        self.assertNotIn("category:pizza", keys)

    def test_every_segment_in_a_run_is_distinct(self) -> None:
        with self.session_factory() as session:
            segments = derive_segments(analyze_restaurant(session, self.restaurant_id))
        keys = [segment.key for segment in segments]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_lapsed_audience_segment_is_produced(self) -> None:
        with self.session_factory() as session:
            segments = derive_segments(analyze_restaurant(session, self.restaurant_id))
        self.assertIn("winback", [segment.key for segment in segments])

    # -- generation and matching ---------------------------------------------

    def _generate(self, **kwargs) -> object:
        # No live model in tests: the deterministic fallback is exercised, which
        # is also the path that guarantees the guardrails.
        with self.session_factory() as session:
            with patch(
                "app.services.ai_offer_generation.GENERATE_CLIENT.post",
                side_effect=ValueError("no model in tests"),
            ):
                return generate_segment_offers(
                    session, restaurant_id=self.restaurant_id, allow_disabled=True, **kwargs
                )

    def test_generation_creates_shared_offers_with_no_owning_customer(self) -> None:
        summary = self._generate()
        self.assertGreater(summary.offers_generated, 0)

        with self.session_factory() as session:
            offers = session.scalars(
                select(GeneratedOffer).where(
                    GeneratedOffer.restaurant_id == self.restaurant_id,
                    GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
                )
            ).all()

        self.assertEqual(len(offers), summary.offers_generated)
        for offer in offers:
            # A shared offer is what lets the read path evaluate it per customer.
            self.assertIsNone(offer.generated_for_user_id)
            self.assertEqual(offer.business_metadata["strategy"], "segment")

    def test_far_fewer_offers_than_customers_are_created(self) -> None:
        summary = self._generate()
        self.assertGreater(summary.users_scanned, summary.offers_generated)
        self.assertLessEqual(summary.offers_generated, 5)

    def test_a_pizza_offer_reaches_pizza_customers_and_not_the_dessert_one(self) -> None:
        self._generate()

        with self.session_factory() as session:
            pizza_offer = session.scalar(
                select(GeneratedOffer).where(
                    GeneratedOffer.restaurant_id == self.restaurant_id,
                    GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
                    GeneratedOffer.applicable_item_id == self.margherita_id,
                )
            )
            self.assertIsNotNone(pizza_offer, "no offer was built for the top dish")
            matched = set(
                session.scalars(
                    select(GeneratedOfferUserMatch.user_id).where(
                        GeneratedOfferUserMatch.generated_offer_id == pizza_offer.id,
                        GeneratedOfferUserMatch.is_current.is_(True),
                    )
                ).all()
            )

        # Eligibility is decided from each customer's own order history.
        self.assertTrue(set(self.pizza_customer_ids) & matched, "no pizza regular matched")
        self.assertNotIn(
            self.dessert_customer_id,
            matched,
            "a customer who has never ordered pizza was matched to a pizza offer",
        )

    def test_the_eligible_count_reflects_real_matches(self) -> None:
        self._generate()
        with self.session_factory() as session:
            offers = session.scalars(
                select(GeneratedOffer).where(
                    GeneratedOffer.restaurant_id == self.restaurant_id,
                    GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
                )
            ).all()
            for offer in offers:
                real = session.scalar(
                    select(GeneratedOfferUserMatch)
                    .where(
                        GeneratedOfferUserMatch.generated_offer_id == offer.id,
                        GeneratedOfferUserMatch.is_current.is_(True),
                    )
                    .limit(1)
                )
                if offer.eligible_user_count > 0:
                    self.assertIsNotNone(real, f"{offer.generated_title} claims eligibility it lacks")

    def test_running_again_does_not_duplicate_the_same_segments(self) -> None:
        first = self._generate()
        second = self._generate()

        self.assertGreater(first.offers_generated, 0)
        self.assertEqual(second.offers_generated, 0)
        self.assertEqual(second.segments_skipped, second.segments_considered)

        with self.session_factory() as session:
            keys = [
                (offer.business_metadata or {}).get("segment_key")
                for offer in session.scalars(
                    select(GeneratedOffer).where(
                        GeneratedOffer.restaurant_id == self.restaurant_id,
                        GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
                    )
                ).all()
            ]
        self.assertEqual(len(keys), len(set(keys)), "the same segment ran twice")

    def test_force_refresh_replaces_rather_than_accumulates(self) -> None:
        self._generate()
        refreshed = self._generate(force_refresh=True)

        self.assertGreater(refreshed.offers_generated, 0)
        self.assertEqual(refreshed.offers_replaced, refreshed.offers_generated)

        with self.session_factory() as session:
            live = session.scalars(
                select(GeneratedOffer).where(
                    GeneratedOffer.restaurant_id == self.restaurant_id,
                    GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
                )
            ).all()
        self.assertEqual(len(live), refreshed.offers_generated)

    def test_guardrails_still_apply_to_every_generated_offer(self) -> None:
        self._generate()
        with self.session_factory() as session:
            offers = session.scalars(
                select(GeneratedOffer).where(
                    GeneratedOffer.restaurant_id == self.restaurant_id,
                    GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
                )
            ).all()

        self.assertTrue(offers)
        for offer in offers:
            self.assertGreaterEqual(offer.minimum_order_amount, settings.ai_min_order_threshold)
            if offer.discount_type == PersonalizedOfferType.__class__:  # pragma: no cover
                continue
            if offer.discount_type.value == "PERCENTAGE":
                self.assertLessEqual(offer.discount_value, settings.ai_max_percentage_discount)
            if offer.discount_type.value == "FLAT":
                self.assertLessEqual(offer.discount_value, settings.ai_max_flat_discount)

    def setUp(self) -> None:
        # Each test starts from a clean offer table so ordering cannot matter.
        with self.session_factory() as session:
            session.execute(text("DELETE FROM generated_offer_user_matches"))
            session.execute(text("DELETE FROM generated_offers"))
            session.commit()


    # -- redeeming it ---------------------------------------------------------

    def test_a_generated_offer_applies_at_a_branch_it_was_not_built_from(self) -> None:
        """The home-screen/checkout asymmetry.

        Eligibility, which decides what a customer sees, has no branch filter.
        `_matches_generated_offer_scope` at checkout demands an exact match. An
        offer carrying a branch is therefore visible to every customer and
        redeemable by only some of them - visible on Home, rejected at payment.
        """
        from app.services.personalized_offers import validate_generated_offer_for_order

        self._generate()
        with self.session_factory() as session:
            offer = session.scalar(
                select(GeneratedOffer).where(
                    GeneratedOffer.restaurant_id == self.restaurant_id,
                    GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
                    GeneratedOffer.applicable_item_id == self.margherita_id,
                )
            )
            self.assertIsNotNone(offer)
            self.assertIsNone(
                offer.restaurant_location_id,
                "a segment offer must not be pinned to one branch",
            )

            customer = session.get(User, self.pizza_customer_ids[0])
            item = session.get(MenuItem, self.margherita_id)

            # The cart is at the *other* branch.
            _, discount = validate_generated_offer_for_order(
                session,
                user=customer,
                generated_offer_id=offer.id,
                restaurant_id=self.restaurant_id,
                restaurant_location_id=self.second_location_id,
                menu_items=[item],
                subtotal=Decimal("2000.00"),
                delivery_fee=Decimal("40.00"),
            )
        self.assertGreater(discount, Decimal("0.00"))

    def test_an_ineligible_customer_cannot_redeem_a_segment_offer(self) -> None:
        # The other half: a shared offer is not a free-for-all. Without a
        # current match the checkout validator must refuse it.
        from fastapi import HTTPException

        from app.services.personalized_offers import validate_generated_offer_for_order

        self._generate()
        with self.session_factory() as session:
            offer = session.scalar(
                select(GeneratedOffer).where(
                    GeneratedOffer.restaurant_id == self.restaurant_id,
                    GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
                    GeneratedOffer.applicable_item_id == self.margherita_id,
                )
            )
            dessert_customer = session.get(User, self.dessert_customer_id)
            item = session.get(MenuItem, self.margherita_id)
            with self.assertRaises(HTTPException) as caught:
                validate_generated_offer_for_order(
                    session,
                    user=dessert_customer,
                    generated_offer_id=offer.id,
                    restaurant_id=self.restaurant_id,
                    restaurant_location_id=self.location_id,
                    menu_items=[item],
                    subtotal=Decimal("2000.00"),
                )
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
