"""Storefront traffic: who is on each restaurant's website, and how many came.

Asked for on 2026-10-07: "which restaurant has how many online users and how
much daily visitor count ... make sure we will get the real count, not random
or repeated". What "real" means here, each a test below:

- **One person is one visitor a day.** The browser keeps an anonymous id;
  reloads, new tabs and the 60-second heartbeat all land on one row per
  restaurant per day (`storefront_visitor_days`), so nothing is counted twice.
- **Online now is the last 2 minutes.** The page beats every 60 seconds while
  it is on screen; someone who closed the tab drops off within 2 minutes.
- **The restaurant is decided by the server**, from the address the page was
  opened on, never from anything the browser says.
- **Robots, previews and local development are not visitors.** `localhost`
  is mapped to a real restaurant and local development uses the live
  database, so a developer's own testing would otherwise count.
- **"Ordered" means a visitor whose account placed an order that day**, not a
  payment that never finished.
- A day is the business's day (Asia/Kolkata), not UTC's.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import (  # noqa: E402
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
from app.models.storefront_visit import StorefrontVisitorDay  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import traffic  # noqa: E402
from app.services.auth import get_current_user  # noqa: E402

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_traffic_test"

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
ANDROID_PHONE = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36"
ANDROID_TABLET = "Mozilla/5.0 (Linux; Android 13; SM-X710) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
IPAD = "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

# 14:30 in Kolkata on 7 Oct 2026.
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


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


class ReadingTheBrowser(unittest.TestCase):
    def test_devices(self) -> None:
        self.assertEqual(traffic.device_of(IPHONE), "phone")
        self.assertEqual(traffic.device_of(ANDROID_PHONE), "phone")
        self.assertEqual(traffic.device_of(IPAD), "tablet")
        self.assertEqual(traffic.device_of(ANDROID_TABLET), "tablet")
        self.assertEqual(traffic.device_of(DESKTOP), "desktop")
        self.assertEqual(traffic.device_of(""), "desktop")

    def test_robots_and_previews_are_not_visitors(self) -> None:
        for agent in (
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HeadlessChrome/126.0 Safari/537.36",
            "Mozilla/5.0 (Linux; Android 11; moto g power) Chrome-Lighthouse",
            "WhatsApp/2.23.20.0",
            "facebookexternalhit/1.1",
            "curl/8.4.0",
            "python-requests/2.32",
            "",
        ):
            with self.subTest(agent=agent):
                self.assertTrue(traffic.is_bot(agent))
        self.assertFalse(traffic.is_bot(IPHONE))
        self.assertFalse(traffic.is_bot(DESKTOP))

    def test_local_addresses(self) -> None:
        for host in ("localhost", "localhost:5173", "bhagwati-bakery.localhost", "127.0.0.1", "192.168.29.236", "10.0.0.4"):
            with self.subTest(host=host):
                self.assertTrue(traffic.is_local_host(host))
        self.assertFalse(traffic.is_local_host("restaurant-rag-storefront.vercel.app"))
        self.assertFalse(traffic.is_local_host("bhagwati.example.com"))

    def test_the_business_day_is_kolkatas(self) -> None:
        # 20:00 UTC on the 6th is 01:30 on the 7th in Kolkata.
        late = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)
        self.assertEqual(str(traffic.business_day(late)), "2026-10-07")
        self.assertEqual(traffic.business_hour(late), 1)


class TheNewVisitorCap(unittest.TestCase):
    """One address inventing visitor ids (a script, a refresh-in-incognito
    loop) must not be able to inflate a restaurant's numbers."""

    def test_past_the_cap_new_ids_are_refused(self) -> None:
        counts: dict[str, int] = {}

        class FakeRedis:
            def incr(self, key):
                counts[key] = counts.get(key, 0) + 1
                return counts[key]

            def expire(self, *_):
                return True

        with mock.patch.object(traffic, "get_redis_client", return_value=FakeRedis()):
            allowed = [
                traffic.allow_new_visitor("1.2.3.4", uuid.UUID(int=1), NOW) for _ in range(traffic.NEW_VISITORS_PER_ADDRESS + 3)
            ]
        self.assertEqual(allowed.count(True), traffic.NEW_VISITORS_PER_ADDRESS)
        self.assertEqual(allowed[-1], False)

    def test_redis_down_does_not_lose_visitors(self) -> None:
        from redis.exceptions import RedisError

        broken = mock.Mock()
        broken.incr.side_effect = RedisError("down")
        with mock.patch.object(traffic, "get_redis_client", return_value=broken):
            self.assertTrue(traffic.allow_new_visitor("1.2.3.4", uuid.UUID(int=1), NOW))


class WhoMayLook(unittest.TestCase):
    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _as(self, role: UserRole, path: str) -> int:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(), role=role, is_active=True, restaurant_id=None
        )
        return TestClient(app).get(path).status_code

    def test_only_the_admin_sees_every_restaurant(self) -> None:
        self.assertEqual(self._as(UserRole.OWNER, "/api/traffic/overview"), 403)
        self.assertEqual(self._as(UserRole.KITCHEN, "/api/traffic/overview"), 403)
        self.assertEqual(self._as(UserRole.CUSTOMER, "/api/traffic/overview"), 403)

    def test_a_cook_or_customer_cannot_read_a_restaurants_traffic(self) -> None:
        self.assertEqual(self._as(UserRole.KITCHEN, f"/api/traffic/summary?restaurant_id={uuid.uuid4()}"), 403)
        self.assertEqual(self._as(UserRole.CUSTOMER, f"/api/traffic/summary?restaurant_id={uuid.uuid4()}"), 403)


class _Database(unittest.TestCase):
    """A throwaway database and the fixtures both classes below use."""

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

    # --- fixtures -----------------------------------------------------------

    def _restaurant(self, *, demo: bool = False) -> uuid.UUID:
        owner = User(
            email=f"o-{uuid.uuid4().hex[:8]}@test.local", full_name="Owner",
            hashed_password="x", role=UserRole.OWNER,
        )
        self.db.add(owner)
        self.db.flush()
        restaurant = Restaurant(
            owner_id=owner.id, name=f"R {uuid.uuid4().hex[:4]}", slug=f"r-{uuid.uuid4().hex[:8]}",
            cuisine_type="Bakery", address_line_1="1 St", city="Surat", state="Gujarat",
            postal_code="395004", is_approved=True, is_active=True, is_demo=demo,
        )
        self.db.add(restaurant)
        self.db.flush()
        self.db.add(RestaurantLocation(
            restaurant_id=restaurant.id, branch_name="Main", address_line_1="1 St",
            city="Surat", state="Gujarat", postal_code="395004", is_open=True,
        ))
        self.db.commit()
        return restaurant.id

    def _customer(self) -> uuid.UUID:
        user = User(
            email=f"c-{uuid.uuid4().hex[:8]}@test.local", full_name="Customer",
            hashed_password="x", role=UserRole.ADMIN,
        )
        self.db.add(user)
        self.db.commit()
        return user.id

    def _order(self, rid, uid, *, status=OrderStatus.PLACED, at=NOW) -> None:
        lid = self.db.scalar(select(RestaurantLocation.id).where(RestaurantLocation.restaurant_id == rid))
        self.db.add(Order(
            customer_id=uid, restaurant_id=rid, restaurant_location_id=lid,
            status=status, payment_status=PaymentStatus.PAID, payment_method=PaymentMethod.CARD,
            fulfillment_type=OrderFulfillmentType.PICKUP, schedule_type=OrderScheduleType.ASAP,
            scheduled_at=at, placed_at=at, updated_at=at, subtotal=Decimal("100"),
            delivery_fee=Decimal("0"), tax_amount=Decimal("0"), discount_amount=Decimal("0"),
            total_amount=Decimal("100"), delivery_address="Pickup",
        ))
        self.db.commit()

    def _beat(self, rid, visitor, *, at=NOW, agent=IPHONE, user_id=None) -> None:
        traffic.record_beat(
            self.db, restaurant_id=rid, visitor_id=visitor, user_id=user_id, user_agent=agent, now=at
        )



@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class Counting(_Database):
    # --- one person, one visitor --------------------------------------------

    def test_reloads_tabs_and_heartbeats_are_one_visitor(self) -> None:
        rid = self._restaurant()
        visitor = uuid.uuid4()
        for minute in range(0, 10):
            self._beat(rid, visitor, at=NOW - timedelta(minutes=minute))
        rows = self.db.scalar(
            select(func.count()).select_from(StorefrontVisitorDay).where(StorefrontVisitorDay.restaurant_id == rid)
        )
        self.assertEqual(rows, 1)
        self.assertEqual(traffic.summary(self.db, rid, now=NOW).today.visitors, 1)

    def test_two_people_are_two_visitors(self) -> None:
        rid = self._restaurant()
        self._beat(rid, uuid.uuid4())
        self._beat(rid, uuid.uuid4(), agent=DESKTOP)
        today = traffic.summary(self.db, rid, now=NOW).today
        self.assertEqual(today.visitors, 2)
        self.assertEqual(today.devices, {"phone": 1, "tablet": 0, "desktop": 1})

    def test_another_restaurants_visitors_are_not_counted(self) -> None:
        mine, theirs = self._restaurant(), self._restaurant()
        self._beat(theirs, uuid.uuid4())
        self.assertEqual(traffic.summary(self.db, mine, now=NOW).today.visitors, 0)

    def test_the_same_person_on_two_restaurants_counts_once_on_each(self) -> None:
        a, b = self._restaurant(), self._restaurant()
        visitor = uuid.uuid4()
        self._beat(a, visitor)
        self._beat(b, visitor)
        self.assertEqual(traffic.summary(self.db, a, now=NOW).today.visitors, 1)
        self.assertEqual(traffic.summary(self.db, b, now=NOW).today.visitors, 1)

    # --- new and returning ---------------------------------------------------

    def test_a_first_visit_is_new_and_a_later_day_is_returning(self) -> None:
        rid = self._restaurant()
        visitor = uuid.uuid4()
        self._beat(rid, visitor, at=NOW - timedelta(days=3))
        self._beat(rid, visitor)
        self._beat(rid, uuid.uuid4())
        today = traffic.summary(self.db, rid, now=NOW).today
        self.assertEqual((today.visitors, today.new, today.returning), (2, 1, 1))

    # --- online now ----------------------------------------------------------

    def test_online_is_the_last_two_minutes(self) -> None:
        rid = self._restaurant()
        self._beat(rid, uuid.uuid4(), at=NOW - timedelta(seconds=50))
        self._beat(rid, uuid.uuid4(), at=NOW - timedelta(seconds=110))
        self._beat(rid, uuid.uuid4(), at=NOW - timedelta(minutes=3))
        self.assertEqual(traffic.summary(self.db, rid, now=NOW).online_now, 2)

    def test_online_spans_midnight(self) -> None:
        # Someone who arrived at 23:59 and is still browsing at 00:00:30 is
        # online, though their row belongs to yesterday.
        rid = self._restaurant()
        midnight = datetime(2026, 10, 7, 18, 30, tzinfo=UTC)  # 00:00 in Kolkata on the 8th
        self._beat(rid, uuid.uuid4(), at=midnight - timedelta(seconds=40))
        self.assertEqual(traffic.summary(self.db, rid, now=midnight + timedelta(seconds=30)).online_now, 1)

    # --- busiest hours and the 30 days --------------------------------------

    def test_busiest_hours_count_people_not_heartbeats(self) -> None:
        rid = self._restaurant()
        visitor = uuid.uuid4()
        ten = datetime(2026, 10, 7, 4, 40, tzinfo=UTC)  # 10:10 in Kolkata
        for minute in range(0, 30):  # 30 beats, all at ten
            self._beat(rid, visitor, at=ten + timedelta(minutes=minute))
        self._beat(rid, visitor, at=datetime(2026, 10, 7, 8, 40, tzinfo=UTC))  # 14:10
        hours = traffic.summary(self.db, rid, now=NOW).hours
        self.assertEqual(hours[10], 1)
        self.assertEqual(hours[14], 1)
        self.assertEqual(sum(hours), 2)

    def test_thirty_days_with_the_quiet_ones_as_zero(self) -> None:
        rid = self._restaurant()
        self._beat(rid, uuid.uuid4(), at=NOW - timedelta(days=2))
        self._beat(rid, uuid.uuid4())
        daily = traffic.summary(self.db, rid, now=NOW).daily
        self.assertEqual(len(daily), 30)
        self.assertEqual(str(daily[-1].day), "2026-10-07")
        self.assertEqual([d.visitors for d in daily[-3:]], [1, 0, 1])

    # --- who ordered ---------------------------------------------------------

    def test_conversion_counts_visitors_whose_account_ordered_today(self) -> None:
        rid = self._restaurant()
        buyer, browser = self._customer(), self._customer()
        anonymous_then_signed_in = uuid.uuid4()
        self._beat(rid, anonymous_then_signed_in, at=NOW - timedelta(minutes=20))
        self._beat(rid, anonymous_then_signed_in, user_id=buyer, at=NOW - timedelta(minutes=10))
        self._beat(rid, uuid.uuid4(), user_id=browser)
        self._beat(rid, uuid.uuid4())
        self._order(rid, buyer)
        today = traffic.summary(self.db, rid, now=NOW).today
        self.assertEqual(today.visitors, 3)
        self.assertEqual(today.ordered, 1)
        self.assertAlmostEqual(today.conversion_percent, 33.3, places=1)

    def test_signing_out_does_not_forget_who_it_was(self) -> None:
        rid = self._restaurant()
        buyer = self._customer()
        visitor = uuid.uuid4()
        self._beat(rid, visitor, user_id=buyer)
        self._beat(rid, visitor)  # signed out, same browser
        self._order(rid, buyer)
        self.assertEqual(traffic.summary(self.db, rid, now=NOW).today.ordered, 1)

    def test_an_unpaid_checkout_is_not_an_order(self) -> None:
        rid = self._restaurant()
        buyer = self._customer()
        self._beat(rid, uuid.uuid4(), user_id=buyer)
        self._order(rid, buyer, status=OrderStatus.PAYMENT_PENDING)
        self.assertEqual(traffic.summary(self.db, rid, now=NOW).today.ordered, 0)

    def test_an_order_at_another_restaurant_does_not_convert_this_one(self) -> None:
        rid, other = self._restaurant(), self._restaurant()
        buyer = self._customer()
        self._beat(rid, uuid.uuid4(), user_id=buyer)
        self._order(other, buyer)
        self.assertEqual(traffic.summary(self.db, rid, now=NOW).today.ordered, 0)

    # --- the admin's overview -----------------------------------------------

    def test_the_overview_has_every_real_restaurant_and_no_demo_one(self) -> None:
        busy, quiet, demo = self._restaurant(), self._restaurant(), self._restaurant(demo=True)
        self._beat(busy, uuid.uuid4())
        self._beat(busy, uuid.uuid4(), at=NOW - timedelta(minutes=30))
        self._beat(demo, uuid.uuid4())
        rows = {row.restaurant_id: row for row in traffic.overview(self.db, now=NOW)}
        self.assertNotIn(demo, rows)
        self.assertEqual((rows[busy].online_now, rows[busy].visitors_today), (1, 2))
        self.assertEqual(rows[quiet].visitors_today, 0)
        order = list(rows)
        self.assertLess(order.index(busy), order.index(quiet))  # busiest first


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class TheBeatEndpoint(_Database):
    """`POST /api/traffic/beat` as a browser calls it."""

    def _post(self, rid, *, host="bhagwati.example.com", agent=IPHONE, visitor=None):
        from app.config.database import get_db
        from app.dependencies import get_app_scope
        from app.models.enums import AppMode
        from app.services.app_clients import AppScope

        def _db():
            yield self.db

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_app_scope] = lambda: (
            AppScope(mode=AppMode.SINGLE_RESTAURANT, restaurant_id=rid) if rid else AppScope()
        )
        self.addCleanup(app.dependency_overrides.clear)
        with mock.patch.object(traffic, "allow_new_visitor", return_value=True):
            return TestClient(app).post(
                "/api/traffic/beat",
                json={"visitor_id": str(visitor or uuid.uuid4())},
                headers={"User-Agent": agent, "X-Forwarded-Host": host},
            )

    def _count(self, rid) -> int:
        return self.db.scalar(
            select(func.count()).select_from(StorefrontVisitorDay).where(StorefrontVisitorDay.restaurant_id == rid)
        )

    def test_a_storefront_visit_is_recorded(self) -> None:
        rid = self._restaurant()
        self.assertEqual(self._post(rid).status_code, 204)
        self.assertEqual(self._count(rid), 1)

    def test_the_marketplace_has_no_restaurant_to_count_for(self) -> None:
        before = self.db.scalar(select(func.count()).select_from(StorefrontVisitorDay))
        self.assertEqual(self._post(None).status_code, 204)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(StorefrontVisitorDay)), before)

    def test_a_robot_is_answered_and_not_counted(self) -> None:
        rid = self._restaurant()
        self.assertEqual(self._post(rid, agent="Googlebot/2.1").status_code, 204)
        self.assertEqual(self._count(rid), 0)

    def test_local_development_is_not_counted(self) -> None:
        rid = self._restaurant()
        self._post(rid, host="localhost:5173")
        self._post(rid, host="bhagwati-bakery.localhost:5173")
        self.assertEqual(self._count(rid), 0)

    def test_not_a_visitor_id_is_refused(self) -> None:
        rid = self._restaurant()
        from app.config.database import get_db

        def _db():
            yield self.db

        app.dependency_overrides[get_db] = _db
        self.addCleanup(app.dependency_overrides.clear)
        response = TestClient(app).post("/api/traffic/beat", json={"visitor_id": "not-a-uuid"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._count(rid), 0)

    def test_an_owner_reads_their_own_and_not_anothers(self) -> None:
        mine, theirs = self._restaurant(), self._restaurant()
        owner_id = self.db.scalar(select(Restaurant.owner_id).where(Restaurant.id == mine))
        owner = self.db.get(User, owner_id)
        from app.config.database import get_db

        def _db():
            yield self.db

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: owner
        self.addCleanup(app.dependency_overrides.clear)
        client = TestClient(app)
        self.assertEqual(client.get("/api/traffic/summary").status_code, 200)
        self.assertEqual(client.get(f"/api/traffic/summary?restaurant_id={theirs}").status_code, 403)


if __name__ == "__main__":
    unittest.main()
