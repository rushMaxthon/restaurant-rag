"""The customer menu is served from Redis until it actually changes.

Found 2026-10-07: Supabase's free plan includes 5 GB of egress a month and
the project had used 5.35 GB. The database is 48 MB; the egress was the same
menus read again and again - `GET /menu-items` had no cache, so every
storefront page view pulled the whole branch (Bhagwati: 187 dishes and 298
sizes, ~90 KB of rows) from Supabase. The top query alone ran 7,564 times.

Now the customer view (anonymous or a customer) is cached per branch, keyed
by a fingerprint of the branch's menu: one small query returning counts,
latest edit times, and sums of prices and stock across dishes, sizes,
groups and options. Any change a customer could see changes the fingerprint,
so the cache never shows a stale menu - including stock set by a bulk UPDATE
that does not touch `updated_at`. The order-count badges inside the cached
answer are at most `MENU_CACHE_TTL_SECONDS` old. Favourites are per customer
and applied after the cache. Staff views (typed prices, commission) are not
cached.
"""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, text, update
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.menu_item import MenuItem  # noqa: E402
from app.models.menu_item_size import MenuItemSize  # noqa: E402
from app.models.restaurant import Restaurant  # noqa: E402
from app.models.restaurant_location import RestaurantLocation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import menu_cache  # noqa: E402

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_menu_cache_test"


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


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value
        return True


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class TheMenuCache(unittest.TestCase):
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
        self.redis = FakeRedis()
        patcher = mock.patch.object(menu_cache, "get_redis_client", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)
        owner = User(email=f"o-{uuid.uuid4().hex[:8]}@t.local", full_name="O", hashed_password="x", role=UserRole.OWNER)
        self.db.add(owner)
        self.db.flush()
        restaurant = Restaurant(
            owner_id=owner.id, name="R", slug=f"r-{uuid.uuid4().hex[:8]}", cuisine_type="Bakery",
            address_line_1="1 St", city="Surat", state="Gujarat", postal_code="395004",
            is_approved=True, is_active=True,
        )
        self.db.add(restaurant)
        self.db.flush()
        self.location = RestaurantLocation(
            restaurant_id=restaurant.id, branch_name="Main", address_line_1="1 St",
            city="Surat", state="Gujarat", postal_code="395004", is_open=True,
        )
        self.db.add(self.location)
        self.db.flush()
        self.bun = MenuItem(
            restaurant_id=restaurant.id, restaurant_location_id=self.location.id, name="Fruit Bun",
            category="Breads", price=Decimal("27.60"), is_available=True, has_sizes=True,
        )
        self.db.add(self.bun)
        self.db.flush()
        self.size = MenuItemSize(menu_item_id=self.bun.id, name="Large", price=Decimal("40"), is_active=True)
        self.db.add(self.size)
        self.db.commit()

    def _fingerprint(self) -> str:
        return menu_cache.fingerprint(self.db, self.location.id)

    # --- the fingerprint moves with anything a customer could see -------------

    def test_nothing_changed_same_fingerprint(self) -> None:
        self.assertEqual(self._fingerprint(), self._fingerprint())

    def test_a_price_change(self) -> None:
        before = self._fingerprint()
        self.bun.price = Decimal("30.00")
        self.db.commit()
        self.assertNotEqual(before, self._fingerprint())

    def test_stock_set_by_a_bulk_update_that_skips_updated_at(self) -> None:
        before = self._fingerprint()
        self.db.execute(
            update(MenuItem.__table__).where(MenuItem.__table__.c.id == self.bun.id).values(stock_quantity=2)
        )
        self.db.commit()
        self.assertNotEqual(before, self._fingerprint())

    def test_out_of_stock(self) -> None:
        before = self._fingerprint()
        self.db.execute(
            update(MenuItem.__table__).where(MenuItem.__table__.c.id == self.bun.id).values(out_of_stock=True)
        )
        self.db.commit()
        self.assertNotEqual(before, self._fingerprint())

    def test_a_size_price_or_stock(self) -> None:
        before = self._fingerprint()
        self.db.execute(
            update(MenuItemSize.__table__).where(MenuItemSize.__table__.c.id == self.size.id).values(stock_quantity=0)
        )
        self.db.commit()
        self.assertNotEqual(before, self._fingerprint())

    def test_a_dish_deleted(self) -> None:
        before = self._fingerprint()
        self.db.delete(self.size)
        self.db.delete(self.bun)
        self.db.commit()
        self.assertNotEqual(before, self._fingerprint())

    def test_another_branchs_edit_does_not_touch_this_one(self) -> None:
        before = self._fingerprint()
        other = RestaurantLocation(
            restaurant_id=self.location.restaurant_id, branch_name="Other", address_line_1="2 St",
            city="Surat", state="Gujarat", postal_code="395004", is_open=True,
        )
        self.db.add(other)
        self.db.flush()
        self.db.add(MenuItem(
            restaurant_id=self.location.restaurant_id, restaurant_location_id=other.id, name="X",
            category="Y", price=Decimal("1"), is_available=True,
        ))
        self.db.commit()
        self.assertEqual(before, self._fingerprint())

    # --- reading through the cache --------------------------------------------

    def test_the_second_read_comes_from_redis(self) -> None:
        built = []

        def build():
            built.append(1)
            return [{"id": str(self.bun.id), "name": "Fruit Bun", "is_favorite": False}]

        first = menu_cache.cached_menu(self.db, self.location.id, variant="available", build=build)
        second = menu_cache.cached_menu(self.db, self.location.id, variant="available", build=build)
        self.assertEqual(first, second)
        self.assertEqual(len(built), 1)

    def test_a_change_rebuilds(self) -> None:
        built = []

        def build():
            built.append(1)
            return [{"id": str(self.bun.id)}]

        menu_cache.cached_menu(self.db, self.location.id, variant="available", build=build)
        self.bun.price = Decimal("31")
        self.db.commit()
        menu_cache.cached_menu(self.db, self.location.id, variant="available", build=build)
        self.assertEqual(len(built), 2)

    def test_the_variants_do_not_share_an_entry(self) -> None:
        menu_cache.cached_menu(self.db, self.location.id, variant="available", build=lambda: [{"v": "a"}])
        all_items = menu_cache.cached_menu(self.db, self.location.id, variant="all", build=lambda: [{"v": "b"}])
        self.assertEqual(all_items, [{"v": "b"}])

    def test_redis_down_still_answers(self) -> None:
        from redis.exceptions import RedisError

        broken = mock.Mock()
        broken.get.side_effect = RedisError("down")
        broken.set.side_effect = RedisError("down")
        with mock.patch.object(menu_cache, "get_redis_client", return_value=broken):
            self.assertEqual(
                menu_cache.cached_menu(self.db, self.location.id, variant="available", build=lambda: [{"ok": 1}]),
                [{"ok": 1}],
            )

    def test_entries_expire_for_the_order_count_badges(self) -> None:
        recorded = {}

        class Recording(FakeRedis):
            def set(self, key, value, ex=None):
                recorded["ex"] = ex
                return super().set(key, value, ex)

        with mock.patch.object(menu_cache, "get_redis_client", return_value=Recording()):
            menu_cache.cached_menu(self.db, self.location.id, variant="available", build=lambda: [])
        self.assertEqual(recorded["ex"], menu_cache.MENU_CACHE_TTL_SECONDS)
        self.assertLessEqual(menu_cache.MENU_CACHE_TTL_SECONDS, 120)

    def test_what_is_stored_is_plain_json(self) -> None:
        menu_cache.cached_menu(self.db, self.location.id, variant="available", build=lambda: [{"a": 1}])
        stored = next(iter(self.redis.data.values()))
        self.assertEqual(json.loads(stored), [{"a": 1}])


if __name__ == "__main__":
    unittest.main()
