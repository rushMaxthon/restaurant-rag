"""Offer to order attribution and ROI.

Covers three things: that a new order records which offer produced it, that the
migration recovers the historical links safely from JSONB metadata, and that the
resulting revenue figures never cross a restaurant boundary.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import (
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PersonalizedOfferAudience,
    PersonalizedOfferDiscountType,
    PersonalizedOfferEventType,
    PersonalizedOfferState,
    PersonalizedOfferType,
    UserRole,
)
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.personalized_offer import PersonalizedOffer, PersonalizedOfferEvent
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.order import OrderCreateItem, OrderCreateRequest
from app.services.insights.offer_performance import fetch_offer_performance
from app.services.insights.periods import build_period
from app.services.insights.scope import InsightsScope
from app.services.orders import PreparedOrderDraft, _offer_attribution, create_order
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()

TEST_DB_NAME = os.environ.get("ATTRIBUTION_TEST_DB", "restaurant_rag_attribution_test")
IST = ZoneInfo("Asia/Kolkata")

PERIOD_START = date(2026, 3, 9)
PERIOD_END = date(2026, 3, 15)


def _load_migration_module():
    """Load migration 0040 so its backfill can be exercised directly."""

    path = BACKEND_ROOT / "alembic" / "versions" / "0040_offer_order_attribution.py"
    spec = importlib.util.spec_from_file_location("migration_0040", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def ist(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=IST)


class OfferAttributionMappingTests(unittest.TestCase):
    """The mapping from a validated draft to the columns stamped on the order."""

    def _draft(self, applied_offer) -> PreparedOrderDraft:
        return PreparedOrderDraft(
            restaurant=None,
            restaurant_location=None,
            scheduled_at=datetime.now(UTC),
            subtotal=Decimal("500.00"),
            delivery_fee=Decimal("0.00"),
            tax_amount=Decimal("25.00"),
            discount_amount=Decimal("50.00"),
            total_amount=Decimal("475.00"),
            order_items=[],
            applied_offer=applied_offer,
        )

    def _payload(self, **overrides) -> OrderCreateRequest:
        base = dict(
            restaurant_id=uuid.uuid4(),
            items=[OrderCreateItem(menu_item_id=uuid.uuid4(), quantity=1)],
            delivery_address="1 Test Street",
        )
        base.update(overrides)
        return OrderCreateRequest(**base)

    def test_order_without_an_offer_records_no_link(self) -> None:
        links = _offer_attribution(self._draft(None), self._payload())
        self.assertEqual(set(links.values()), {None})

    def test_template_offer_is_recorded_in_its_own_column(self) -> None:
        offer = PersonalizedOffer(id=uuid.uuid4(), restaurant_id=uuid.uuid4())
        links = _offer_attribution(
            self._draft(offer), self._payload(personalized_offer_id=offer.id)
        )
        self.assertEqual(links["applied_offer_id"], offer.id)
        self.assertIsNone(links["applied_generated_offer_id"])

    def test_generated_offer_is_recorded_separately(self) -> None:
        generated_id = uuid.uuid4()
        match_id = uuid.uuid4()
        # The draft returns the generated offer object; here it is stood in for
        # by the payload ids the service also receives.
        links = _offer_attribution(
            self._draft(PersonalizedOffer(id=uuid.uuid4(), restaurant_id=uuid.uuid4())),
            self._payload(
                generated_offer_id=generated_id,
                generated_offer_user_match_id=match_id,
            ),
        )
        self.assertEqual(links["applied_offer_user_match_id"], match_id)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class AttributionPersistenceTests(unittest.TestCase):
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
        cls.migration = _load_migration_module()

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
            user = User(
                id=uuid.uuid4(),
                app_client_id=None,
                full_name=name,
                email=email,
                hashed_password="x",
                role=role,
            )
            session.add(user)
            return user

        owner_a = make_user("Owner A", "attr-owner-a@test.local", UserRole.OWNER)
        owner_b = make_user("Owner B", "attr-owner-b@test.local", UserRole.OWNER)
        customer = make_user("Customer", "attr-customer@test.local", UserRole.CUSTOMER)
        session.flush()

        def make_restaurant(owner: User, name: str, slug: str) -> Restaurant:
            restaurant = Restaurant(
                id=uuid.uuid4(),
                owner_id=owner.id,
                name=name,
                slug=slug,
                cuisine_type="Italian",
                address_line_1="1 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                is_approved=True,
                is_active=True,
            )
            session.add(restaurant)
            return restaurant

        restaurant_a = make_restaurant(owner_a, "Attr Restaurant A", "attr-restaurant-a")
        restaurant_b = make_restaurant(owner_b, "Attr Restaurant B", "attr-restaurant-b")
        session.flush()

        def make_location(restaurant: Restaurant, branch: str) -> RestaurantLocation:
            location = RestaurantLocation(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                branch_name=branch,
                address_line_1="1 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                is_open=True,
                is_active=True,
            )
            session.add(location)
            return location

        location_a = make_location(restaurant_a, "A Main")
        location_b = make_location(restaurant_b, "B Main")
        session.flush()

        def make_menu_item(restaurant, location, name, price) -> MenuItem:
            item = MenuItem(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                restaurant_location_id=location.id,
                name=name,
                category="Pizza",
                price=Decimal(price),
            )
            session.add(item)
            return item

        item_a = make_menu_item(restaurant_a, location_a, "Margherita Pizza", "500.00")
        item_b = make_menu_item(restaurant_b, location_b, "Pepperoni Pizza", "600.00")
        session.flush()

        def make_offer(restaurant, name) -> PersonalizedOffer:
            offer = PersonalizedOffer(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                name=name,
                offer_type=PersonalizedOfferType.FAVORITE_ITEM,
                audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
                state=PersonalizedOfferState.ACTIVE,
                discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
                discount_value=Decimal("10.00"),
                minimum_order_amount=Decimal("199.00"),
            )
            session.add(offer)
            return offer

        offer_a = make_offer(restaurant_a, "A Pizza Offer")
        offer_b = make_offer(restaurant_b, "B Pizza Offer")
        session.commit()

        cls.restaurant_a = restaurant_a.id
        cls.restaurant_b = restaurant_b.id
        cls.location_a = location_a.id
        cls.location_b = location_b.id
        cls.item_a = item_a.id
        cls.item_b = item_b.id
        cls.offer_a = offer_a.id
        cls.offer_b = offer_b.id
        cls.customer_id = customer.id

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)
        self.addCleanup(self._reset)
        self.period = build_period(PERIOD_START, PERIOD_END, timezone_name="Asia/Kolkata")
        self.scope_a = InsightsScope(restaurant_id=self.restaurant_a)
        self.scope_b = InsightsScope(restaurant_id=self.restaurant_b)

    def _reset(self) -> None:
        with self.session_factory() as session:
            session.query(PersonalizedOfferEvent).delete()
            session.query(OrderItem).delete()
            session.query(Order).delete()
            session.commit()

    def _make_order(
        self,
        *,
        restaurant_id: uuid.UUID,
        location_id: uuid.UUID,
        total: str,
        discount: str = "0.00",
        offer_id: uuid.UUID | None = None,
        placed_at: datetime | None = None,
        status: OrderStatus = OrderStatus.DELIVERED,
    ) -> Order:
        order = Order(
            id=uuid.uuid4(),
            customer_id=self.customer_id,
            restaurant_id=restaurant_id,
            restaurant_location_id=location_id,
            status=status,
            payment_status=PaymentStatus.PAID,
            payment_method=PaymentMethod.CARD,
            payment_provider="test",
            fulfillment_type=OrderFulfillmentType.DELIVERY,
            schedule_type=OrderScheduleType.ASAP,
            scheduled_at=placed_at or ist(PERIOD_START, 20),
            subtotal=Decimal(total),
            delivery_fee=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal(discount),
            total_amount=Decimal(total),
            currency="INR",
            delivery_address="1 Test Street",
            placed_at=placed_at or ist(PERIOD_START, 20),
            applied_offer_id=offer_id,
        )
        self.session.add(order)
        self.session.commit()
        return order

    # -- the real order path ----------------------------------------------

    def test_create_order_stamps_the_offer_that_produced_it(self) -> None:
        offer = self.session.get(PersonalizedOffer, self.offer_a)
        restaurant = self.session.get(Restaurant, self.restaurant_a)
        location = self.session.get(RestaurantLocation, self.location_a)
        menu_item = self.session.get(MenuItem, self.item_a)

        draft = PreparedOrderDraft(
            restaurant=restaurant,
            restaurant_location=location,
            scheduled_at=datetime.now(UTC),
            subtotal=Decimal("500.00"),
            delivery_fee=Decimal("0.00"),
            tax_amount=Decimal("25.00"),
            discount_amount=Decimal("50.00"),
            total_amount=Decimal("475.00"),
            order_items=[
                OrderItem(
                    id=uuid.uuid4(),
                    menu_item_id=menu_item.id,
                    item_name_snapshot=menu_item.name,
                    quantity=1,
                    base_unit_price=Decimal("500.00"),
                    customization_total_price=Decimal("0.00"),
                    unit_price=Decimal("500.00"),
                    total_price=Decimal("500.00"),
                    selected_options_snapshot=[],
                )
            ],
            applied_offer=offer,
        )
        payload = OrderCreateRequest(
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            personalized_offer_id=offer.id,
            items=[OrderCreateItem(menu_item_id=menu_item.id, quantity=1)],
            delivery_address="1 Test Street",
            # Card, so the order is PAYMENT_PENDING and the placed-order side
            # effects (notifications, combo rebuilds) stay out of this test.
            payment_method=PaymentMethod.CARD,
        )
        customer = self.session.get(User, self.customer_id)

        with patch("app.services.orders._prepare_order_draft", return_value=draft):
            response = create_order(self.session, customer, payload)

        stored = self.session.get(Order, response.id)
        self.assertEqual(stored.applied_offer_id, offer.id)
        self.assertIsNone(stored.applied_generated_offer_id)
        self.assertEqual(stored.discount_amount, Decimal("50.00"))

        # The conversion event now carries a real foreign key as well as the
        # legacy metadata key.
        event = self.session.scalars(
            select(PersonalizedOfferEvent).where(
                PersonalizedOfferEvent.event_type == PersonalizedOfferEventType.CONVERTED
            )
        ).first()
        self.assertEqual(event.order_id, stored.id)
        self.assertEqual(event.event_metadata["order_id"], str(stored.id))

    def test_order_without_an_offer_still_works(self) -> None:
        restaurant = self.session.get(Restaurant, self.restaurant_a)
        location = self.session.get(RestaurantLocation, self.location_a)
        menu_item = self.session.get(MenuItem, self.item_a)

        draft = PreparedOrderDraft(
            restaurant=restaurant,
            restaurant_location=location,
            scheduled_at=datetime.now(UTC),
            subtotal=Decimal("500.00"),
            delivery_fee=Decimal("0.00"),
            tax_amount=Decimal("25.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("525.00"),
            order_items=[
                OrderItem(
                    id=uuid.uuid4(),
                    menu_item_id=menu_item.id,
                    item_name_snapshot=menu_item.name,
                    quantity=1,
                    base_unit_price=Decimal("500.00"),
                    customization_total_price=Decimal("0.00"),
                    unit_price=Decimal("500.00"),
                    total_price=Decimal("500.00"),
                    selected_options_snapshot=[],
                )
            ],
            applied_offer=None,
        )
        payload = OrderCreateRequest(
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            items=[OrderCreateItem(menu_item_id=menu_item.id, quantity=1)],
            delivery_address="1 Test Street",
            payment_method=PaymentMethod.CARD,
        )
        customer = self.session.get(User, self.customer_id)

        with patch("app.services.orders._prepare_order_draft", return_value=draft):
            response = create_order(self.session, customer, payload)

        stored = self.session.get(Order, response.id)
        self.assertIsNone(stored.applied_offer_id)
        self.assertIsNone(stored.applied_generated_offer_id)
        self.assertIsNone(stored.applied_offer_user_match_id)

    # -- backfill ----------------------------------------------------------

    def _legacy_event(
        self,
        *,
        order: Order | None,
        offer_id: uuid.UUID | None,
        metadata_order_id: str | None,
        event_type: PersonalizedOfferEventType = PersonalizedOfferEventType.CONVERTED,
    ) -> PersonalizedOfferEvent:
        """An event as it looked before the column existed: metadata only."""

        event = PersonalizedOfferEvent(
            id=uuid.uuid4(),
            offer_id=offer_id,
            user_id=self.customer_id,
            event_type=event_type,
            converted_at=datetime.now(UTC),
            order_id=None,
            event_metadata=(
                {"order_id": metadata_order_id} if metadata_order_id is not None else {}
            ),
        )
        self.session.add(event)
        self.session.commit()
        return event

    def _run_backfill(self) -> None:
        self.migration._backfill(self.session)
        self.session.commit()

    def test_backfill_recovers_the_historical_link(self) -> None:
        order = self._make_order(
            restaurant_id=self.restaurant_a,
            location_id=self.location_a,
            total="500.00",
            discount="50.00",
            offer_id=None,
        )
        event = self._legacy_event(
            order=order, offer_id=self.offer_a, metadata_order_id=str(order.id)
        )

        self._run_backfill()

        self.session.refresh(order)
        self.session.refresh(event)
        self.assertEqual(event.order_id, order.id)
        self.assertEqual(order.applied_offer_id, self.offer_a)

    def test_backfill_skips_a_malformed_order_id(self) -> None:
        # A bad value must be skipped, not abort the whole migration.
        event = self._legacy_event(
            order=None, offer_id=self.offer_a, metadata_order_id="not-a-uuid"
        )
        self._run_backfill()
        self.session.refresh(event)
        self.assertIsNone(event.order_id)

    def test_backfill_skips_an_order_that_no_longer_exists(self) -> None:
        event = self._legacy_event(
            order=None, offer_id=self.offer_a, metadata_order_id=str(uuid.uuid4())
        )
        self._run_backfill()
        self.session.refresh(event)
        self.assertIsNone(event.order_id)

    def test_backfill_ignores_events_without_metadata(self) -> None:
        event = self._legacy_event(
            order=None, offer_id=self.offer_a, metadata_order_id=None
        )
        self._run_backfill()
        self.session.refresh(event)
        self.assertIsNone(event.order_id)

    def test_backfill_ignores_non_conversion_events(self) -> None:
        order = self._make_order(
            restaurant_id=self.restaurant_a, location_id=self.location_a, total="500.00"
        )
        event = self._legacy_event(
            order=order,
            offer_id=self.offer_a,
            metadata_order_id=str(order.id),
            event_type=PersonalizedOfferEventType.VIEWED,
        )
        self._run_backfill()
        self.session.refresh(event)
        self.assertIsNone(event.order_id)

    def test_backfill_is_safe_to_run_twice(self) -> None:
        order = self._make_order(
            restaurant_id=self.restaurant_a,
            location_id=self.location_a,
            total="500.00",
            discount="50.00",
        )
        self._legacy_event(
            order=order, offer_id=self.offer_a, metadata_order_id=str(order.id)
        )

        self._run_backfill()
        self._run_backfill()

        self.session.refresh(order)
        self.assertEqual(order.applied_offer_id, self.offer_a)
        events = self.session.scalars(select(PersonalizedOfferEvent)).all()
        self.assertEqual(len(events), 1)

    def test_backfill_does_not_overwrite_an_existing_link(self) -> None:
        order = self._make_order(
            restaurant_id=self.restaurant_a,
            location_id=self.location_a,
            total="500.00",
            offer_id=self.offer_a,
        )
        # An event claiming a different offer must not rewrite what the order
        # already recorded at creation time.
        self._legacy_event(
            order=order, offer_id=self.offer_b, metadata_order_id=str(order.id)
        )

        self._run_backfill()

        self.session.refresh(order)
        self.assertEqual(order.applied_offer_id, self.offer_a)

    # -- ROI ---------------------------------------------------------------

    def test_offer_performance_reports_revenue_and_cost(self) -> None:
        for _ in range(3):
            self._make_order(
                restaurant_id=self.restaurant_a,
                location_id=self.location_a,
                total="450.00",
                discount="50.00",
                offer_id=self.offer_a,
            )

        rows = fetch_offer_performance(self.session, self.scope_a, self.period)
        self.assertEqual(len(rows), 1)
        row = rows[0]

        self.assertEqual(row.offer_name, "A Pizza Offer")
        self.assertEqual(row.offer_kind, "TEMPLATE")
        self.assertEqual(row.orders, 3)
        self.assertAlmostEqual(row.gross_revenue, 1350.0)
        self.assertAlmostEqual(row.discount_cost, 150.0)
        self.assertAlmostEqual(row.net_revenue, 1200.0)
        self.assertAlmostEqual(row.average_order_value, 450.0)
        self.assertAlmostEqual(row.return_per_unit_discount, 9.0)

    def test_orders_without_an_offer_are_not_attributed(self) -> None:
        self._make_order(
            restaurant_id=self.restaurant_a, location_id=self.location_a, total="900.00"
        )
        rows = fetch_offer_performance(self.session, self.scope_a, self.period)
        self.assertEqual(rows, [])

    def test_cancelled_orders_do_not_count_as_offer_revenue(self) -> None:
        self._make_order(
            restaurant_id=self.restaurant_a,
            location_id=self.location_a,
            total="450.00",
            discount="50.00",
            offer_id=self.offer_a,
            status=OrderStatus.CANCELLED,
        )
        rows = fetch_offer_performance(self.session, self.scope_a, self.period)
        self.assertEqual(rows, [])

    def test_orders_outside_the_window_are_excluded(self) -> None:
        self._make_order(
            restaurant_id=self.restaurant_a,
            location_id=self.location_a,
            total="450.00",
            discount="50.00",
            offer_id=self.offer_a,
            placed_at=ist(PERIOD_START - timedelta(days=30), 20),
        )
        rows = fetch_offer_performance(self.session, self.scope_a, self.period)
        self.assertEqual(rows, [])

    def test_no_ratio_is_invented_when_nothing_was_discounted(self) -> None:
        self._make_order(
            restaurant_id=self.restaurant_a,
            location_id=self.location_a,
            total="450.00",
            discount="0.00",
            offer_id=self.offer_a,
        )
        rows = fetch_offer_performance(self.session, self.scope_a, self.period)
        self.assertIsNone(rows[0].return_per_unit_discount)

    def test_roi_is_scoped_to_one_restaurant(self) -> None:
        self._make_order(
            restaurant_id=self.restaurant_a,
            location_id=self.location_a,
            total="450.00",
            discount="50.00",
            offer_id=self.offer_a,
        )
        self._make_order(
            restaurant_id=self.restaurant_b,
            location_id=self.location_b,
            total="5000.00",
            discount="500.00",
            offer_id=self.offer_b,
        )

        rows_a = fetch_offer_performance(self.session, self.scope_a, self.period)
        rows_b = fetch_offer_performance(self.session, self.scope_b, self.period)

        self.assertEqual([row.offer_name for row in rows_a], ["A Pizza Offer"])
        self.assertEqual([row.offer_name for row in rows_b], ["B Pizza Offer"])
        self.assertAlmostEqual(rows_a[0].gross_revenue, 450.0)
        self.assertAlmostEqual(rows_b[0].gross_revenue, 5000.0)

    def test_engagement_counts_do_not_cross_restaurants(self) -> None:
        self._make_order(
            restaurant_id=self.restaurant_a,
            location_id=self.location_a,
            total="450.00",
            discount="50.00",
            offer_id=self.offer_a,
        )
        # Events for another restaurant's offer, inside the same window.
        for _ in range(5):
            self.session.add(
                PersonalizedOfferEvent(
                    id=uuid.uuid4(),
                    offer_id=self.offer_b,
                    user_id=self.customer_id,
                    event_type=PersonalizedOfferEventType.VIEWED,
                    created_at=ist(PERIOD_START, 12),
                    event_metadata={},
                )
            )
        self.session.commit()

        rows = fetch_offer_performance(self.session, self.scope_a, self.period)
        self.assertEqual(rows[0].views, 0)

    def test_location_filter_narrows_attribution(self) -> None:
        self._make_order(
            restaurant_id=self.restaurant_a,
            location_id=self.location_a,
            total="450.00",
            discount="50.00",
            offer_id=self.offer_a,
        )
        branch_scope = InsightsScope(
            restaurant_id=self.restaurant_a, restaurant_location_id=self.location_a
        )
        rows = fetch_offer_performance(self.session, branch_scope, self.period)
        self.assertEqual(len(rows), 1)

        other_branch = InsightsScope(
            restaurant_id=self.restaurant_a, restaurant_location_id=uuid.uuid4()
        )
        self.assertEqual(fetch_offer_performance(self.session, other_branch, self.period), [])


if __name__ == "__main__":
    unittest.main()
