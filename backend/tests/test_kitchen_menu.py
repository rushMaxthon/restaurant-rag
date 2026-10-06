"""Menu stock from the kitchen: what a cook may see, and what they may change.

The line this feature draws is the one the stock fields already drew: the
OWNER decides what is on the menu and at what price; the KITCHEN says what is
in stock right now. These tests pin both halves:

* **Scope** is the order board's (`resolve_order_board_scope`). A pinned cook
  reaches one branch, never another branch's or restaurant's dish — and gets
  404 for one, exactly as for an order, learning nothing about it.
* **Writes** are stock only. The request schemas cannot name `price` or
  `is_available`, so trying is a 422, not a quiet no-op that looks done.
* **Empty is not zero.** `stock_quantity: null` stops counting (unlimited);
  0 is sold out; leaving the field out keeps whatever orders left behind.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401  imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import UserRole
from app.models.menu_item import MenuItem
from app.models.menu_item_size import MenuItemSize
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.kitchen_menu import KitchenSizeStockUpdate, KitchenStockUpdate
from app.services.auth import require_order_board
from app.services.kitchen_menu import (
    kitchen_scope,
    list_kitchen_menu,
    update_dish_stock,
    update_size_stock,
)
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()
TEST_DB_NAME = os.environ.get("KITCHEN_MENU_TEST_DB", "restaurant_rag_kitchen_menu_test")


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


class StockRequestShapeTests(unittest.TestCase):
    """No database needed: what a kitchen request can even say."""

    def test_price_and_visibility_cannot_be_sent(self) -> None:
        for field in ("price", "is_available", "base_price", "name"):
            with self.assertRaises(ValidationError, msg=field):
                KitchenStockUpdate.model_validate({field: 1})
        with self.assertRaises(ValidationError):
            KitchenSizeStockUpdate.model_validate({"price": 10})

    def test_counts_are_whole_and_not_negative(self) -> None:
        with self.assertRaises(ValidationError):
            KitchenStockUpdate.model_validate({"stock_quantity": -1})
        with self.assertRaises(ValidationError):
            KitchenStockUpdate.model_validate({"stock_daily_quantity": -5})

    def test_null_and_absent_are_different_requests(self) -> None:
        self.assertIn("stock_quantity", KitchenStockUpdate.model_validate({"stock_quantity": None}).model_fields_set)
        self.assertNotIn("stock_quantity", KitchenStockUpdate.model_validate({}).model_fields_set)

    def test_customers_are_refused_at_the_door(self) -> None:
        customer = User(id=uuid.uuid4(), full_name="C", email="c@example.com", hashed_password="x", role=UserRole.CUSTOMER)
        with self.assertRaises(HTTPException) as refused:
            require_order_board(customer)
        self.assertEqual(refused.exception.status_code, 403)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class KitchenMenuTests(unittest.TestCase):
    """Restaurant A: Downtown and Airport. Restaurant B: Main."""

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
            id=uuid.uuid4(), full_name=role.value.title(),
            email=f"{role.value.lower()}-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x", role=role, **kwargs,
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
        return location

    @classmethod
    def _dish(cls, session: Session, location: RestaurantLocation, name: str, **kwargs) -> MenuItem:
        dish = MenuItem(
            id=uuid.uuid4(), restaurant_id=location.restaurant_id, restaurant_location_id=location.id,
            name=name, category="Mains", price=Decimal("100.00"), **kwargs,
        )
        session.add(dish)
        session.flush()
        return dish

    @classmethod
    def _seed(cls, session: Session) -> None:
        cls.owner_a = cls._user(session, UserRole.OWNER)
        owner_b = cls._user(session, UserRole.OWNER)
        restaurant_a = cls._restaurant(session, "menu-a", cls.owner_a)
        restaurant_b = cls._restaurant(session, "menu-b", owner_b)
        cls.restaurant_a_id = restaurant_a.id
        cls.downtown = cls._branch(session, restaurant_a, "Downtown")
        cls.airport = cls._branch(session, restaurant_a, "Airport")
        branch_b = cls._branch(session, restaurant_b, "Main")

        cls.curry = cls._dish(session, cls.downtown, "Green Curry", stock_quantity=5)
        cls.hidden = cls._dish(session, cls.downtown, "Seasonal Soup", is_available=False)
        cls.pizza = cls._dish(session, cls.downtown, "Pizza")
        cls.large = MenuItemSize(id=uuid.uuid4(), menu_item_id=cls.pizza.id, name="Large", price=Decimal("150.00"), sort_order=1)
        cls.retired = MenuItemSize(
            id=uuid.uuid4(), menu_item_id=cls.pizza.id, name="Family", price=Decimal("250.00"),
            is_active=False, sort_order=2,
        )
        session.add_all([cls.large, cls.retired])
        cls.airport_dish = cls._dish(session, cls.airport, "Airport Noodles")
        cls.other_restaurant_dish = cls._dish(session, branch_b, "Elsewhere Rice")

        cls.cook_downtown = cls._user(
            session, UserRole.KITCHEN,
            staff_restaurant_id=restaurant_a.id, staff_restaurant_location_id=cls.downtown.id,
        )
        cls.cook_any = cls._user(session, UserRole.KITCHEN, staff_restaurant_id=restaurant_a.id)
        cls.admin = cls._user(session, UserRole.ADMIN)
        session.commit()

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)

    def _scope(self, user: User, restaurant_id=None, location_id=None):
        return kitchen_scope(self.session, user, restaurant_id=restaurant_id, location_id=location_id)

    # --- read ---------------------------------------------------------------

    def test_a_pinned_cook_sees_their_branch_including_switched_off_dishes(self) -> None:
        names = {d.name for d in list_kitchen_menu(self.session, self._scope(self.cook_downtown))}
        self.assertEqual(names, {"Green Curry", "Seasonal Soup", "Pizza"})

    def test_switched_off_dishes_say_so_and_are_not_on_sale(self) -> None:
        soup = next(d for d in list_kitchen_menu(self.session, self._scope(self.cook_downtown)) if d.name == "Seasonal Soup")
        self.assertFalse(soup.is_available)
        self.assertFalse(soup.is_on_sale)

    def test_an_unpinned_cook_sees_every_branch_or_narrows_to_one(self) -> None:
        everything = {d.name for d in list_kitchen_menu(self.session, self._scope(self.cook_any))}
        self.assertIn("Airport Noodles", everything)
        self.assertNotIn("Elsewhere Rice", everything)
        airport = {d.name for d in list_kitchen_menu(self.session, self._scope(self.cook_any, location_id=self.airport.id))}
        self.assertEqual(airport, {"Airport Noodles"})

    def test_a_pinned_cook_cannot_ask_for_another_branch(self) -> None:
        with self.assertRaises(HTTPException) as refused:
            self._scope(self.cook_downtown, location_id=self.airport.id)
        self.assertEqual(refused.exception.status_code, 403)

    def test_the_menu_carries_no_prices(self) -> None:
        dish = list_kitchen_menu(self.session, self._scope(self.cook_downtown))[0]
        self.assertFalse({"price", "base_price", "commission_percent"} & set(dish.model_dump()))

    def test_retired_sizes_are_left_out(self) -> None:
        pizza = next(d for d in list_kitchen_menu(self.session, self._scope(self.cook_downtown)) if d.name == "Pizza")
        self.assertEqual([size.name for size in pizza.sizes], ["Large"])

    def test_an_admin_must_name_a_restaurant(self) -> None:
        with self.assertRaises(HTTPException) as refused:
            self._scope(self.admin)
        self.assertEqual(refused.exception.status_code, 400)
        names = {d.name for d in list_kitchen_menu(self.session, self._scope(self.admin, restaurant_id=self.restaurant_a_id))}
        self.assertIn("Airport Noodles", names)

    # --- write --------------------------------------------------------------

    def test_marking_out_of_stock_takes_it_off_sale_and_back(self) -> None:
        scope = self._scope(self.cook_downtown)
        out = update_dish_stock(self.session, scope, self.cook_downtown, self.pizza.id, KitchenStockUpdate(out_of_stock=True))
        self.assertTrue(out.out_of_stock)
        self.assertFalse(out.is_on_sale)
        back = update_dish_stock(self.session, scope, self.cook_downtown, self.pizza.id, KitchenStockUpdate(out_of_stock=False))
        self.assertTrue(back.is_on_sale)

    def test_counts_and_the_daily_refill_change_only_what_is_sent(self) -> None:
        scope = self._scope(self.cook_downtown)
        result = update_dish_stock(
            self.session, scope, self.cook_downtown, self.curry.id,
            KitchenStockUpdate.model_validate({"stock_daily_quantity": 12}),
        )
        self.assertEqual(result.stock_daily_quantity, 12)
        self.assertEqual(result.stock_quantity, 5)  # untouched: not sent

        zero = update_dish_stock(
            self.session, scope, self.cook_downtown, self.curry.id,
            KitchenStockUpdate.model_validate({"stock_quantity": 0}),
        )
        self.assertEqual(zero.stock_quantity, 0)
        self.assertFalse(zero.is_on_sale)

        uncounted = update_dish_stock(
            self.session, scope, self.cook_downtown, self.curry.id,
            KitchenStockUpdate.model_validate({"stock_quantity": None}),
        )
        self.assertIsNone(uncounted.stock_quantity)
        self.assertTrue(uncounted.is_on_sale)

    def test_a_cook_cannot_switch_on_a_dish_the_owner_switched_off(self) -> None:
        result = update_dish_stock(
            self.session, self._scope(self.cook_downtown), self.cook_downtown, self.hidden.id,
            KitchenStockUpdate(out_of_stock=False),
        )
        self.assertFalse(result.is_available)
        self.assertFalse(result.is_on_sale)

    def test_another_branchs_or_restaurants_dish_is_not_found(self) -> None:
        scope = self._scope(self.cook_downtown)
        for dish in (self.airport_dish, self.other_restaurant_dish):
            with self.assertRaises(HTTPException) as refused:
                update_dish_stock(self.session, scope, self.cook_downtown, dish.id, KitchenStockUpdate(out_of_stock=True))
            self.assertEqual(refused.exception.status_code, 404)

    def test_a_size_keeps_its_own_count_and_refill(self) -> None:
        result = update_size_stock(
            self.session, self._scope(self.cook_downtown), self.cook_downtown, self.pizza.id, self.large.id,
            KitchenSizeStockUpdate.model_validate({"stock_quantity": 3, "stock_daily_quantity": 8}),
        )
        large = result.sizes[0]
        self.assertEqual((large.stock_quantity, large.stock_daily_quantity), (3, 8))

    def test_a_size_of_another_dish_is_not_found(self) -> None:
        with self.assertRaises(HTTPException) as refused:
            update_size_stock(
                self.session, self._scope(self.cook_downtown), self.cook_downtown, self.curry.id, self.large.id,
                KitchenSizeStockUpdate.model_validate({"stock_quantity": 1}),
            )
        self.assertEqual(refused.exception.status_code, 404)

    def test_the_owner_uses_the_same_routes(self) -> None:
        result = update_dish_stock(
            self.session, self._scope(self.owner_a), self.owner_a, self.airport_dish.id,
            KitchenStockUpdate(out_of_stock=True),
        )
        self.assertTrue(result.out_of_stock)


if __name__ == "__main__":
    unittest.main()
