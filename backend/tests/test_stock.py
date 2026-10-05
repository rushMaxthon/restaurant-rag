"""How many of a dish are left, and who gets the last one.

A bakery bakes forty loaves. Until this existed the forty-first customer could
order one, pay for it, and learn there was none when the shop rang them — the
menu had a single switch, available or not, and somebody had to remember to
flip it at the moment the tray emptied.

The count lives on the dish. Blank means nobody is counting and nothing here
applies: that is every dish that existed before this, so adding the feature
changes no menu. A number is how many can still be sold.

Each case below is a way the count could be wrong.

**Two customers, one loaf.** Both checkouts read "1 left", both pass the
check, both orders go through. So the check is not what protects the last
loaf — the write is. Taking stock is a single UPDATE that only succeeds while
enough remains, and the second customer's finds nothing to update.

**The same dish twice in one cart.** A pack of four and a pack of eight are
two lines of one dish. Checked a line at a time, three and three both fit
into five.

**An order nobody paid for.** Stock is taken when the order is created,
before payment, so that paying for it cannot fail on stock. An unpaid order is
cancelled by the system later, and what it held has to come back — exactly
once, and only what THAT order took.

**An order from before the count existed.** Cancelled after the owner starts
counting, it must not add loaves that were never subtracted.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402,F401 - imported first to settle import order
from app.config import get_settings  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.menu_item import MenuItem  # noqa: E402
from app.models.menu_item_size import MenuItemSize  # noqa: E402
from app.models.restaurant import Restaurant  # noqa: E402
from app.models.restaurant_location import RestaurantLocation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import stock  # noqa: E402

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_stock_test"


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
    except Exception:  # noqa: BLE001 - any connection failure means "skip"
        return False
    finally:
        if engine is not None:
            engine.dispose()


def a_size(name: str, left: int | None):
    return SimpleNamespace(id=uuid.uuid4(), name=name, stock_quantity=left)


def a_dish(
    name: str,
    left: int | None,
    *,
    dish_id: uuid.UUID | None = None,
    out_of_stock: bool = False,
    sizes: tuple = (),
):
    return SimpleNamespace(
        id=dish_id or uuid.uuid4(),
        name=name,
        stock_quantity=left,
        out_of_stock=out_of_stock,
        sizes=list(sizes),
    )


def a_line(
    dish_id: uuid.UUID,
    quantity: int,
    *,
    reserved: bool = False,
    size_id: uuid.UUID | None = None,
    reserved_size: bool = False,
):
    return SimpleNamespace(
        menu_item_id=dish_id,
        menu_item_size_id=size_id,
        quantity=quantity,
        stock_reserved=reserved,
        stock_reserved_size=reserved_size,
    )


class WhatTheCustomerIsToldTests(unittest.TestCase):
    """Checked before anything is written, so the cart can say it early."""

    def _refusal(self, dishes, lines) -> str | None:
        try:
            stock.ensure_in_stock({dish.id: dish for dish in dishes}, lines)
        except HTTPException as error:
            self.assertEqual(error.status_code, 409)
            return str(error.detail)
        return None

    def test_a_dish_nobody_is_counting_can_always_be_ordered(self) -> None:
        bread = a_dish("Brown Bread", None)
        self.assertIsNone(self._refusal([bread], [a_line(bread.id, 500)]))

    def test_ordering_what_is_left_is_fine(self) -> None:
        bread = a_dish("Brown Bread", 3)
        self.assertIsNone(self._refusal([bread], [a_line(bread.id, 3)]))

    def test_one_more_than_is_left_is_refused_with_the_number(self) -> None:
        bread = a_dish("Brown Bread", 3)
        said = self._refusal([bread], [a_line(bread.id, 4)])
        self.assertIn("Only 3", said)
        self.assertIn("Brown Bread", said)

    def test_none_left_reads_as_sold_out_not_as_only_zero(self) -> None:
        bread = a_dish("Brown Bread", 0)
        said = self._refusal([bread], [a_line(bread.id, 1)])
        self.assertIn("out of stock", said)
        self.assertNotIn("Only 0", said)

    def test_two_lines_of_one_dish_are_counted_together(self) -> None:
        pav = a_dish("Brun Pav", 5)
        self.assertIsNotNone(self._refusal([pav], [a_line(pav.id, 3), a_line(pav.id, 3)]))
        self.assertIsNone(self._refusal([pav], [a_line(pav.id, 3), a_line(pav.id, 2)]))

    def test_a_dish_marked_out_of_stock_by_hand_is_refused_whatever_its_count(self) -> None:
        # Nobody is counting it, and there are forty by the count - but the
        # owner said none, and the owner is standing next to the tray.
        for left in (None, 40):
            bread = a_dish("Brown Bread", left, out_of_stock=True)
            said = self._refusal([bread], [a_line(bread.id, 1)])
            self.assertIn("out of stock", said)

    def test_a_size_with_its_own_count_is_checked_against_that_count(self) -> None:
        four, eight = a_size("Pack of 4", 2), a_size("Pack of 8", 10)
        pav = a_dish("Brun Pav", None, sizes=(four, eight))
        said = self._refusal([pav], [a_line(pav.id, 3, size_id=four.id)])
        # Named with its size: "Brun Pav" alone would send them to the wrong pack.
        self.assertIn("Only 2 Brun Pav (Pack of 4)", said)
        self.assertIsNone(self._refusal([pav], [a_line(pav.id, 3, size_id=eight.id)]))

    def test_a_size_without_a_count_draws_on_the_dishs_count(self) -> None:
        four, eight = a_size("Pack of 4", None), a_size("Pack of 8", None)
        pav = a_dish("Brun Pav", 5, sizes=(four, eight))
        lines = [a_line(pav.id, 3, size_id=four.id), a_line(pav.id, 3, size_id=eight.id)]
        self.assertIn("Only 5 Brun Pav", self._refusal([pav], lines))

    def test_a_counted_size_does_not_use_up_the_dishs_count(self) -> None:
        four, eight = a_size("Pack of 4", 10), a_size("Pack of 8", None)
        pav = a_dish("Brun Pav", 3, sizes=(four, eight))
        # Six of the counted size, three of the other: the dish's 3 is asked
        # for 3, not 9.
        lines = [a_line(pav.id, 6, size_id=four.id), a_line(pav.id, 3, size_id=eight.id)]
        self.assertIsNone(self._refusal([pav], lines))

    def test_every_short_dish_is_named_not_just_the_first(self) -> None:
        bread, pav = a_dish("Brown Bread", 1), a_dish("Brun Pav", 0)
        said = self._refusal([bread, pav], [a_line(bread.id, 2), a_line(pav.id, 1)])
        self.assertIn("Brown Bread", said)
        self.assertIn("Brun Pav", said)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class TakingAndGivingBackTests(unittest.TestCase):
    """Against a real database, because the rule IS the UPDATE."""

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
            owner = User(
                id=uuid.uuid4(), app_client_id=None, full_name="Stock Owner",
                email="stock-owner@test.local", hashed_password="x", role=UserRole.OWNER,
            )
            session.add(owner)
            session.flush()
            restaurant = Restaurant(
                id=uuid.uuid4(), owner_id=owner.id, name="Stock Bakery", slug="stock-bakery",
                cuisine_type="Bakery", address_line_1="1 Test Street", city="Surat",
                state="Gujarat", postal_code="395004", is_approved=True, is_active=True,
            )
            session.add(restaurant)
            session.flush()
            location = RestaurantLocation(
                id=uuid.uuid4(), restaurant_id=restaurant.id, branch_name="Main",
                address_line_1="1 Test Street", city="Surat", state="Gujarat",
                postal_code="395004",
            )
            session.add(location)
            session.commit()
            cls.restaurant_id, cls.location_id = restaurant.id, location.id

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.engine is not None:
            cls.engine.dispose()
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin.dispose()

    def _dish(self, left: int | None) -> uuid.UUID:
        with self.session_factory() as session:
            row = MenuItem(
                id=uuid.uuid4(), restaurant_id=self.restaurant_id,
                restaurant_location_id=self.location_id, name=f"Loaf {uuid.uuid4().hex[:6]}",
                category="Breads", price=Decimal("55.00"), is_available=True,
                stock_quantity=left,
            )
            session.add(row)
            session.commit()
            return row.id

    def _left(self, dish_id: uuid.UUID) -> int | None:
        with self.session_factory() as session:
            return session.get(MenuItem, dish_id).stock_quantity

    def _size(self, dish_id: uuid.UUID, left: int | None, *, daily: int | None = None) -> uuid.UUID:
        with self.session_factory() as session:
            row = MenuItemSize(
                id=uuid.uuid4(), menu_item_id=dish_id, name=f"Pack {uuid.uuid4().hex[:4]}",
                price=Decimal("44.00"), stock_quantity=left, stock_daily_quantity=daily,
            )
            session.add(row)
            session.commit()
            return row.id

    def _size_left(self, size_id: uuid.UUID) -> int | None:
        with self.session_factory() as session:
            return session.get(MenuItemSize, size_id).stock_quantity

    def test_an_order_takes_what_it_ordered(self) -> None:
        dish = self._dish(10)
        line = a_line(dish, 3)
        with self.session_factory() as session:
            stock.reserve(session, [line])
            session.commit()
        self.assertEqual(self._left(dish), 7)
        self.assertTrue(line.stock_reserved)

    def test_the_last_one_goes_to_whoever_writes_first(self) -> None:
        # Both customers passed the check a moment ago, when it said 1 left.
        dish = self._dish(1)
        with self.session_factory() as first, self.session_factory() as second:
            stock.reserve(first, [a_line(dish, 1)])
            first.commit()
            with self.assertRaises(HTTPException) as refused:
                stock.reserve(second, [a_line(dish, 1)])
            self.assertEqual(refused.exception.status_code, 409)
        self.assertEqual(self._left(dish), 0)

    def test_it_never_goes_below_zero(self) -> None:
        dish = self._dish(2)
        with self.session_factory() as session:
            with self.assertRaises(HTTPException):
                stock.reserve(session, [a_line(dish, 3)])
            session.rollback()
        self.assertEqual(self._left(dish), 2)

    def test_two_lines_of_one_dish_are_taken_as_one_amount(self) -> None:
        dish = self._dish(5)
        with self.session_factory() as session:
            with self.assertRaises(HTTPException):
                stock.reserve(session, [a_line(dish, 3), a_line(dish, 3)])
            session.rollback()
        self.assertEqual(self._left(dish), 5)

    def test_a_dish_nobody_is_counting_is_left_alone(self) -> None:
        dish = self._dish(None)
        line = a_line(dish, 40)
        with self.session_factory() as session:
            stock.reserve(session, [line])
            session.commit()
        self.assertIsNone(self._left(dish))
        # Nothing was taken, so there is nothing to give back later.
        self.assertFalse(line.stock_reserved)

    def test_a_cancelled_order_gives_back_what_it_took_once(self) -> None:
        dish = self._dish(10)
        line = a_line(dish, 4)
        with self.session_factory() as session:
            stock.reserve(session, [line])
            session.commit()
        with self.session_factory() as session:
            stock.release(session, [line])
            # Cancelled twice, by a retried webhook say. Still four, not eight.
            stock.release(session, [line])
            session.commit()
        self.assertEqual(self._left(dish), 10)
        self.assertFalse(line.stock_reserved)

    def test_an_order_from_before_the_count_existed_gives_nothing_back(self) -> None:
        dish = self._dish(6)
        with self.session_factory() as session:
            stock.release(session, [a_line(dish, 2, reserved=False)])
            session.commit()
        self.assertEqual(self._left(dish), 6)

    def test_nothing_comes_back_to_a_dish_the_owner_stopped_counting(self) -> None:
        dish = self._dish(3)
        line = a_line(dish, 1)
        with self.session_factory() as session:
            stock.reserve(session, [line])
            session.commit()
        with self.session_factory() as session:
            session.get(MenuItem, dish).stock_quantity = None
            session.commit()
        with self.session_factory() as session:
            stock.release(session, [line])
            session.commit()
        self.assertIsNone(self._left(dish))

    def test_a_dish_marked_out_of_stock_by_hand_takes_no_order(self) -> None:
        dish = self._dish(10)
        with self.session_factory() as session:
            session.get(MenuItem, dish).out_of_stock = True
            session.commit()
        with self.session_factory() as session:
            with self.assertRaises(HTTPException) as refused:
                stock.reserve(session, [a_line(dish, 1)])
            self.assertEqual(refused.exception.status_code, 409)
            session.rollback()
        self.assertEqual(self._left(dish), 10)

    def test_a_dish_marked_out_of_stock_by_hand_is_not_suggested(self) -> None:
        dish = self._dish(None)
        with self.session_factory() as session:
            row = session.get(MenuItem, dish)
            row.out_of_stock = True
            session.commit()
            self.assertFalse(row.is_on_sale)

    def test_a_counted_size_is_taken_from_its_own_count(self) -> None:
        dish = self._dish(10)
        size = self._size(dish, 4)
        line = a_line(dish, 3, size_id=size)
        with self.session_factory() as session:
            stock.reserve(session, [line])
            session.commit()
        self.assertEqual(self._size_left(size), 1)
        # The dish's own count is somebody else's tray.
        self.assertEqual(self._left(dish), 10)
        self.assertTrue(line.stock_reserved and line.stock_reserved_size)

    def test_a_size_without_a_count_is_taken_from_the_dish(self) -> None:
        dish = self._dish(10)
        size = self._size(dish, None)
        line = a_line(dish, 3, size_id=size)
        with self.session_factory() as session:
            stock.reserve(session, [line])
            session.commit()
        self.assertEqual(self._left(dish), 7)
        self.assertIsNone(self._size_left(size))
        self.assertTrue(line.stock_reserved)
        self.assertFalse(line.stock_reserved_size)

    def test_the_last_of_a_size_cannot_be_sold_twice(self) -> None:
        dish = self._dish(None)
        size = self._size(dish, 1)
        with self.session_factory() as first, self.session_factory() as second:
            stock.reserve(first, [a_line(dish, 1, size_id=size)])
            first.commit()
            with self.assertRaises(HTTPException):
                stock.reserve(second, [a_line(dish, 1, size_id=size)])
        self.assertEqual(self._size_left(size), 0)

    def test_a_cancelled_order_returns_stock_to_the_count_it_came_from(self) -> None:
        dish = self._dish(10)
        size = self._size(dish, 4)
        from_size, from_dish = a_line(dish, 2, size_id=size), a_line(dish, 3)
        with self.session_factory() as session:
            stock.reserve(session, [from_size, from_dish])
            session.commit()
        self.assertEqual((self._size_left(size), self._left(dish)), (2, 7))
        with self.session_factory() as session:
            stock.release(session, [from_size, from_dish])
            session.commit()
        self.assertEqual((self._size_left(size), self._left(dish)), (4, 10))

    def test_the_morning_refill_sets_counts_back_to_their_daily_amount(self) -> None:
        with self.session_factory() as session:
            # Everything else in this database first, so only these rows move.
            session.execute(MenuItem.__table__.update().values(stock_daily_quantity=None))
            session.execute(MenuItemSize.__table__.update().values(stock_daily_quantity=None))
            session.commit()
        sold_down, by_hand, overfull = self._dish(3), self._dish(2), self._dish(60)
        size = self._size(sold_down, 0, daily=12)
        with self.session_factory() as session:
            session.get(MenuItem, sold_down).stock_daily_quantity = 40
            session.get(MenuItem, overfull).stock_daily_quantity = 40
            session.commit()
        with self.session_factory() as session:
            changed = stock.restock_daily(session)
            session.commit()
        self.assertEqual(changed, 3)
        self.assertEqual(self._left(sold_down), 40)
        # Set TO forty, not topped up by forty: yesterday's loaves are gone.
        self.assertEqual(self._left(overfull), 40)
        # No daily amount: restocked by hand, so left exactly as it was.
        self.assertEqual(self._left(by_hand), 2)
        self.assertEqual(self._size_left(size), 12)

    def test_the_morning_refill_does_not_undo_a_manual_out_of_stock(self) -> None:
        dish = self._dish(0)
        with self.session_factory() as session:
            row = session.get(MenuItem, dish)
            row.out_of_stock = True
            row.stock_daily_quantity = 40
            session.commit()
        with self.session_factory() as session:
            stock.restock_daily(session)
            session.commit()
            row = session.get(MenuItem, dish)
            self.assertEqual(row.stock_quantity, 40)
            # A person said it. A person takes it back.
            self.assertTrue(row.out_of_stock)
            self.assertFalse(row.is_on_sale)

    def test_what_is_suggested_to_a_customer_leaves_out_the_sold_out_dish(self) -> None:
        # The chat, the recommendations and the cart's suggestions all filter
        # on `is_on_sale`. A dish at zero that is still recommended is tapped,
        # added, and refused at checkout.
        from sqlalchemy import select

        plenty, last_one, gone, uncounted = (
            self._dish(40), self._dish(1), self._dish(0), self._dish(None)
        )
        with self.session_factory() as session:
            on_sale = set(
                session.scalars(
                    select(MenuItem.id).where(
                        MenuItem.id.in_([plenty, last_one, gone, uncounted]), MenuItem.is_on_sale
                    )
                )
            )
            self.assertEqual(on_sale, {plenty, last_one, uncounted})
            # And the same answer from a loaded row as from the query.
            self.assertFalse(session.get(MenuItem, gone).is_on_sale)
            self.assertTrue(session.get(MenuItem, uncounted).is_on_sale)

    def test_a_dish_the_owner_switched_off_is_not_on_sale_whatever_its_count(self) -> None:
        dish = self._dish(10)
        with self.session_factory() as session:
            row = session.get(MenuItem, dish)
            row.is_available = False
            session.commit()
            self.assertFalse(row.is_on_sale)


if __name__ == "__main__":
    unittest.main()
