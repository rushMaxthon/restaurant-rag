"""Root-cause analysis over the operational history from Phase 6A.

The failure mode that matters here is a *plausible* explanation: telling an owner
a dish declined because of a stock-out when it was actually available all week
would send them fixing the wrong thing. So these check both that real causes are
found and that absent ones are not invented.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

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
from app.services.insights.periods import build_period
from app.services.insights.root_cause import (
    acceptance_latency,
    cancellations_by_reason,
    explain_cancellations,
    explain_item_decline,
    explain_latency,
    preparation_time,
    stockouts_in_period,
)
from app.services.insights.scope import InsightsScope
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()
TEST_DB_NAME = os.environ.get("ROOT_CAUSE_TEST_DB", "restaurant_rag_root_cause_test")
IST = ZoneInfo("Asia/Kolkata")

WINDOW_START = date(2026, 3, 9)
WINDOW_END = date(2026, 3, 15)


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


def ist(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=IST)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class RootCauseTests(unittest.TestCase):
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
        # One owner per restaurant: `uq_restaurants_owner_id` enforces it.
        owner_a = User(id=uuid.uuid4(), full_name="O A", email="rc-oa@t.local",
                       hashed_password="x", role=UserRole.OWNER)
        owner_b = User(id=uuid.uuid4(), full_name="O B", email="rc-ob@t.local",
                       hashed_password="x", role=UserRole.OWNER)
        customer = User(id=uuid.uuid4(), full_name="C", email="rc-c@t.local",
                        hashed_password="x", role=UserRole.CUSTOMER)
        session.add_all([owner_a, owner_b, customer])
        session.flush()

        def restaurant(owner, name, slug):
            r = Restaurant(id=uuid.uuid4(), owner_id=owner.id, name=name, slug=slug,
                           cuisine_type="It", address_line_1="1 St", city="BLR",
                           state="KA", postal_code="560001", is_approved=True, is_active=True)
            session.add(r)
            return r

        restaurant_a = restaurant(owner_a, "RC A", "rc-a")
        restaurant_b = restaurant(owner_b, "RC B", "rc-b")
        session.flush()

        def location(r):
            loc = RestaurantLocation(id=uuid.uuid4(), restaurant_id=r.id, branch_name="M",
                                     address_line_1="1 St", city="BLR", state="KA",
                                     postal_code="560001")
            session.add(loc)
            return loc

        location_a = location(restaurant_a)
        location_b = location(restaurant_b)
        session.flush()

        def item(r, loc, name):
            mi = MenuItem(id=uuid.uuid4(), restaurant_id=r.id, restaurant_location_id=loc.id,
                          name=name, category="Pizza", price=Decimal("500.00"))
            session.add(mi)
            return mi

        pizza_a = item(restaurant_a, location_a, "Margherita Pizza")
        pasta_a = item(restaurant_a, location_a, "Pasta Alfredo")
        pizza_b = item(restaurant_b, location_b, "Pepperoni Pizza")
        session.commit()

        cls.restaurant_a = restaurant_a.id
        cls.restaurant_b = restaurant_b.id
        cls.location_a = location_a.id
        cls.location_b = location_b.id
        cls.pizza_a = pizza_a.id
        cls.pasta_a = pasta_a.id
        cls.pizza_b = pizza_b.id
        cls.customer_id = customer.id

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)
        self.addCleanup(self._reset)
        self.scope_a = InsightsScope(restaurant_id=self.restaurant_a)
        self.scope_b = InsightsScope(restaurant_id=self.restaurant_b)
        self.period = build_period(WINDOW_START, WINDOW_END, timezone_name="Asia/Kolkata")
        self.previous = build_period(
            WINDOW_START - timedelta(days=7), WINDOW_START - timedelta(days=1),
            timezone_name="Asia/Kolkata",
        )

    def _reset(self) -> None:
        with self.session_factory() as session:
            session.query(MenuItemAvailabilityEvent).delete()
            session.query(OrderStatusEvent).delete()
            session.query(Order).delete()
            session.commit()

    def _availability(self, item_id, restaurant_id, location_id, name, available, at):
        self.session.add(
            MenuItemAvailabilityEvent(
                id=uuid.uuid4(), menu_item_id=item_id, restaurant_id=restaurant_id,
                restaurant_location_id=location_id, is_available=available,
                item_name_snapshot=name, actor=OrderEventActor.OWNER, occurred_at=at,
            )
        )
        self.session.commit()

    def _order(self, *, status=OrderStatus.CANCELLED, reason=None, placed=None, total="500.00"):
        moment = placed or ist(WINDOW_START, 13)
        order = Order(
            id=uuid.uuid4(), customer_id=self.customer_id, restaurant_id=self.restaurant_a,
            restaurant_location_id=self.location_a, status=status,
            payment_status=PaymentStatus.PAID, payment_method=PaymentMethod.CARD,
            payment_provider="test", fulfillment_type=OrderFulfillmentType.DELIVERY,
            schedule_type=OrderScheduleType.ASAP, scheduled_at=moment,
            subtotal=Decimal(total), delivery_fee=Decimal("0.00"), tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"), total_amount=Decimal(total), currency="INR",
            delivery_address="1 St", placed_at=moment, cancellation_reason=reason,
        )
        self.session.add(order)
        self.session.commit()
        return order

    def _status_event(self, order, to_status, at, from_status=None):
        self.session.add(
            OrderStatusEvent(
                id=uuid.uuid4(), order_id=order.id, restaurant_id=order.restaurant_id,
                restaurant_location_id=order.restaurant_location_id,
                from_status=from_status, to_status=to_status,
                actor=OrderEventActor.OWNER, occurred_at=at,
            )
        )
        self.session.commit()

    # -- stock-outs --------------------------------------------------------

    def test_stockout_duration_is_measured(self) -> None:
        self._availability(self.pizza_a, self.restaurant_a, self.location_a,
                           "Margherita Pizza", False, ist(WINDOW_START, 10))
        self._availability(self.pizza_a, self.restaurant_a, self.location_a,
                           "Margherita Pizza", True, ist(WINDOW_START, 16))

        stockouts = stockouts_in_period(self.session, self.scope_a, self.period)
        self.assertIn("margherita pizza", stockouts)
        self.assertAlmostEqual(stockouts["margherita pizza"].hours_unavailable, 6.0)

    def test_dish_still_off_at_window_end_is_counted(self) -> None:
        # An outage that never ended must not silently vanish from the total.
        self._availability(self.pizza_a, self.restaurant_a, self.location_a,
                           "Margherita Pizza", False, ist(WINDOW_END, 10))
        stockouts = stockouts_in_period(self.session, self.scope_a, self.period)
        self.assertGreater(stockouts["margherita pizza"].hours_unavailable, 0)

    def test_brief_outage_is_ignored(self) -> None:
        # A few minutes off is operational noise, not an explanation.
        self._availability(self.pizza_a, self.restaurant_a, self.location_a,
                           "Margherita Pizza", False, ist(WINDOW_START, 10))
        self._availability(self.pizza_a, self.restaurant_a, self.location_a,
                           "Margherita Pizza", True, ist(WINDOW_START, 10, 30))
        self.assertEqual(stockouts_in_period(self.session, self.scope_a, self.period), {})

    def test_outage_outside_the_window_does_not_count(self) -> None:
        self._availability(self.pizza_a, self.restaurant_a, self.location_a,
                           "Margherita Pizza", False, ist(WINDOW_START - timedelta(days=20), 10))
        self._availability(self.pizza_a, self.restaurant_a, self.location_a,
                           "Margherita Pizza", True, ist(WINDOW_START - timedelta(days=20), 18))
        self.assertEqual(stockouts_in_period(self.session, self.scope_a, self.period), {})

    def test_stockouts_are_restaurant_scoped(self) -> None:
        self._availability(self.pizza_b, self.restaurant_b, self.location_b,
                           "Pepperoni Pizza", False, ist(WINDOW_START, 10))
        self._availability(self.pizza_b, self.restaurant_b, self.location_b,
                           "Pepperoni Pizza", True, ist(WINDOW_START, 20))

        self.assertEqual(stockouts_in_period(self.session, self.scope_a, self.period), {})
        self.assertIn(
            "pepperoni pizza",
            stockouts_in_period(self.session, self.scope_b, self.period),
        )

    # -- explanations ------------------------------------------------------

    def test_decline_during_a_stockout_is_explained(self) -> None:
        self._availability(self.pizza_a, self.restaurant_a, self.location_a,
                           "Margherita Pizza", False, ist(WINDOW_START, 8))
        self._availability(self.pizza_a, self.restaurant_a, self.location_a,
                           "Margherita Pizza", True, ist(WINDOW_START, 18))
        stockouts = stockouts_in_period(self.session, self.scope_a, self.period)

        explanation = explain_item_decline(subject="Margherita Pizza", stockouts=stockouts)
        self.assertIsNotNone(explanation)
        self.assertIn("unavailable", explanation)
        self.assertIn("lost supply", explanation)

    def test_decline_without_a_stockout_is_not_explained(self) -> None:
        # The dangerous case: a plausible-sounding cause that is not true would
        # send an owner fixing the wrong thing.
        self._availability(self.pizza_a, self.restaurant_a, self.location_a,
                           "Margherita Pizza", False, ist(WINDOW_START, 8))
        self._availability(self.pizza_a, self.restaurant_a, self.location_a,
                           "Margherita Pizza", True, ist(WINDOW_START, 18))
        stockouts = stockouts_in_period(self.session, self.scope_a, self.period)

        self.assertIsNone(explain_item_decline(subject="Pasta Alfredo", stockouts=stockouts))

    def test_no_subject_means_no_explanation(self) -> None:
        self.assertIsNone(explain_item_decline(subject=None, stockouts={}))

    # -- cancellations -----------------------------------------------------

    def test_cancellations_group_by_recorded_reason(self) -> None:
        for _ in range(3):
            self._order(reason=OrderCancellationReason.PAYMENT_NOT_COMPLETED)
        self._order(reason=OrderCancellationReason.PAYMENT_ABANDONED)

        breakdown = cancellations_by_reason(self.session, self.scope_a, self.period)
        self.assertEqual(breakdown[0].reason, OrderCancellationReason.PAYMENT_NOT_COMPLETED)
        self.assertEqual(breakdown[0].orders, 3)

        explanation = explain_cancellations(breakdown)
        self.assertIn("payment was never completed", explanation)
        self.assertIn("3 of 4", explanation)

    def test_unrecorded_reasons_say_so(self) -> None:
        self._order(reason=OrderCancellationReason.UNKNOWN)
        explanation = explain_cancellations(
            cancellations_by_reason(self.session, self.scope_a, self.period)
        )
        self.assertIn("not recorded", explanation)

    def test_no_cancellations_means_no_explanation(self) -> None:
        self.assertIsNone(explain_cancellations([]))

    def test_delivered_orders_are_not_counted_as_cancellations(self) -> None:
        self._order(status=OrderStatus.DELIVERED)
        self.assertEqual(cancellations_by_reason(self.session, self.scope_a, self.period), [])

    # -- latency -----------------------------------------------------------

    def test_acceptance_latency_is_measured_from_events(self) -> None:
        for index in range(6):
            order = self._order(status=OrderStatus.DELIVERED)
            placed = ist(WINDOW_START, 12) + timedelta(minutes=index)
            self._status_event(order, OrderStatus.PLACED, placed)
            self._status_event(order, OrderStatus.ACCEPTED, placed + timedelta(minutes=10))

        stats = acceptance_latency(self.session, self.scope_a, self.period)
        self.assertEqual(stats.sample_size, 6)
        self.assertAlmostEqual(stats.median_minutes, 10.0)

    def test_preparation_time_is_measured_from_events(self) -> None:
        for index in range(5):
            order = self._order(status=OrderStatus.DELIVERED)
            accepted = ist(WINDOW_START, 12) + timedelta(minutes=index)
            self._status_event(order, OrderStatus.ACCEPTED, accepted)
            self._status_event(
                order, OrderStatus.OUT_FOR_DELIVERY, accepted + timedelta(minutes=20)
            )

        stats = preparation_time(self.session, self.scope_a, self.period)
        self.assertAlmostEqual(stats.median_minutes, 20.0)

    def test_no_events_means_no_latency(self) -> None:
        # Older windows have no history at all, which must read as "unknown"
        # rather than "instant".
        stats = acceptance_latency(self.session, self.scope_a, self.period)
        self.assertIsNone(stats.median_minutes)
        self.assertEqual(stats.sample_size, 0)

    def test_latency_is_restaurant_scoped(self) -> None:
        order = self._order(status=OrderStatus.DELIVERED)
        placed = ist(WINDOW_START, 12)
        self._status_event(order, OrderStatus.PLACED, placed)
        self._status_event(order, OrderStatus.ACCEPTED, placed + timedelta(minutes=10))

        self.assertEqual(
            acceptance_latency(self.session, self.scope_b, self.period).sample_size, 0
        )

    def test_a_meaningful_slowdown_is_explained(self) -> None:
        from app.services.insights.root_cause import LatencyStats

        explanation = explain_latency(
            LatencyStats(median_minutes=30.0, sample_size=20),
            LatencyStats(median_minutes=10.0, sample_size=20),
        )
        self.assertIsNotNone(explanation)
        self.assertIn("30.0 minutes", explanation)

    def test_a_small_change_is_not_explained(self) -> None:
        from app.services.insights.root_cause import LatencyStats

        self.assertIsNone(
            explain_latency(
                LatencyStats(median_minutes=11.0, sample_size=20),
                LatencyStats(median_minutes=10.0, sample_size=20),
            )
        )

    def test_too_few_orders_means_no_claim(self) -> None:
        # A median over three orders is not evidence of anything.
        from app.services.insights.root_cause import LatencyStats

        self.assertIsNone(
            explain_latency(
                LatencyStats(median_minutes=40.0, sample_size=2),
                LatencyStats(median_minutes=10.0, sample_size=2),
            )
        )


if __name__ == "__main__":
    unittest.main()
