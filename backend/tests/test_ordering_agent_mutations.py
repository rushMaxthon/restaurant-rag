"""Task 3: the four cart-mutating tools.

These tools return *actions* for the browser to apply — nothing here writes
to the database. `clear_cart` needs no DB at all; `remove_from_cart`/
`set_quantity` only need the DB to identify a scoped menu item's provenance
is irrelevant to them (they work purely off the cart lines the browser
already sent); `add_to_cart` is the one handler that must consult the real
branch menu, via `_load_branch_menu_items`/`_resolve_cart_lines` exactly the
way `view_cart`/`price_quote` already do (Task 2) — reused, not
reimplemented.

DB fixture mirrors `test_ordering_agent_readonly.py`: a throwaway local
Postgres database, `Base.metadata.create_all` excluding `menu_embeddings`
(needs pgvector, nothing here touches it).
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.main import app  # noqa: F401 - imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import UserRole
from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.models.menu_item_size import MenuItemSize
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.ordering_agent.tools import (
    AddToCartArgs,
    ClearCartArgs,
    OrderingScope,
    RemoveFromCartArgs,
    SelectedOptionArgs,
    SetQuantityArgs,
    TOOLS,
    CartLineArgs,
)

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_ordering_agent_mutations_test"


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
class OrderingAgentMutationToolTests(unittest.TestCase):
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
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            connection.commit()
        tables = [t for t in Base.metadata.sorted_tables if t.name != "menu_embeddings"]
        Base.metadata.create_all(cls.engine, tables=tables)
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
            id=uuid.uuid4(),
            full_name="Mutation Owner",
            email="mutation-owner@test.local",
            hashed_password="x",
            role=UserRole.OWNER,
        )
        session.add(owner)
        session.flush()

        restaurant = Restaurant(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name="Mutation Kitchen",
            slug="mutation-kitchen",
            cuisine_type="Thai",
            address_line_1="1 Test Street",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            is_approved=True,
            is_active=True,
            is_open=True,
        )
        session.add(restaurant)
        session.flush()
        cls.restaurant_id = restaurant.id

        branch_a = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            branch_name="Branch A",
            address_line_1="10 Branch Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560010",
            is_open=True,
            is_active=True,
            google_pay_enabled=False,
            razorpay_enabled=False,
            card_payment_enabled=False,
            cash_on_delivery_enabled=True,
        )
        branch_b = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            branch_name="Branch B",
            address_line_1="20 Branch Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560020",
            is_open=False,
            is_active=True,
            google_pay_enabled=False,
            razorpay_enabled=False,
            card_payment_enabled=True,
            cash_on_delivery_enabled=False,
        )
        session.add_all([branch_a, branch_b])
        session.flush()
        cls.branch_a_id = branch_a.id
        cls.branch_b_id = branch_b.id

        pad_thai = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            restaurant_location_id=branch_a.id,
            name="Pad Thai",
            category="Mains",
            price=Decimal("220.00"),
            is_veg=False,
            is_available=True,
        )
        pizza = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            restaurant_location_id=branch_a.id,
            name="Margherita Pizza",
            category="Mains",
            price=Decimal("350.00"),
            is_veg=True,
            is_available=True,
            has_sizes=True,
            has_customizations=True,
        )
        other_branch_item = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            restaurant_location_id=branch_b.id,
            name="Tom Yum Soup",
            category="Soups",
            price=Decimal("240.00"),
            is_veg=False,
            is_available=True,
        )
        session.add_all([pad_thai, pizza, other_branch_item])
        session.flush()

        pizza_small_id = uuid.uuid4()
        session.add(
            MenuItemSize(id=pizza_small_id, menu_item_id=pizza.id, name="Small", price=Decimal("350.00"))
        )
        session.flush()

        crust_group_id = uuid.uuid4()
        session.add(
            MenuItemCustomizationGroup(
                id=crust_group_id,
                menu_item_id=pizza.id,
                title="Crust",
                is_required=True,
                min_selection=1,
                max_selection=1,
            )
        )
        session.flush()
        session.add(
            MenuItemCustomizationOption(
                id=uuid.uuid4(),
                group_id=crust_group_id,
                name="Thin Crust",
                extra_price=Decimal("0.00"),
                is_default=True,
            )
        )
        session.flush()

        cls.pad_thai_id = pad_thai.id
        cls.pizza_id = pizza.id
        cls.pizza_small_id = pizza_small_id
        cls.other_branch_item_id = other_branch_item.id
        session.commit()

    def _session(self) -> Session:
        return self.session_factory()

    def _scope(self) -> OrderingScope:
        return OrderingScope(restaurant_id=self.restaurant_id, restaurant_location_id=self.branch_a_id)

    def _pad_thai_line(self, size_id=None) -> CartLineArgs:
        return CartLineArgs(menu_item_id=self.pad_thai_id, quantity=1, menu_item_size_id=size_id)

    # -- clear_cart ------------------------------------------------------

    def test_clear_cart_always_proposed(self) -> None:
        with self._session() as db:
            result = TOOLS["clear_cart"].handler(db, self._scope(), ClearCartArgs())
        self.assertEqual(result["action"]["status"], "proposed")
        self.assertEqual(result["action"]["reason"], "destructive")
        self.assertEqual(result["action"]["kind"], "clear")

    def test_clear_cart_extra_arg_rejected(self) -> None:
        with self.assertRaises(Exception):
            ClearCartArgs(quantity=2)

    # -- remove_from_cart --------------------------------------------------

    def test_remove_matching_one_line_may_be_applied(self) -> None:
        args = RemoveFromCartArgs(menu_item_id=self.pad_thai_id, existing_lines=[self._pad_thai_line()])
        with self._session() as db:
            result = TOOLS["remove_from_cart"].handler(db, self._scope(), args)
        self.assertEqual(result["outcome"], "action")
        self.assertEqual(result["action"]["status"], "applied")
        self.assertEqual(result["action"]["kind"], "remove")
        self.assertEqual(result["action"]["menu_item_id"], self.pad_thai_id)

    def test_remove_matching_two_lines_is_proposed(self) -> None:
        args = RemoveFromCartArgs(
            menu_item_id=self.pizza_id,
            existing_lines=[
                CartLineArgs(menu_item_id=self.pizza_id, quantity=1, menu_item_size_id=self.pizza_small_id),
                CartLineArgs(menu_item_id=self.pizza_id, quantity=2, menu_item_size_id=self.pizza_small_id),
            ],
        )
        with self._session() as db:
            result = TOOLS["remove_from_cart"].handler(db, self._scope(), args)
        self.assertEqual(result["outcome"], "action")
        self.assertEqual(result["action"]["status"], "proposed")
        self.assertEqual(result["action"]["reason"], "destructive")

    def test_remove_matching_nothing_produces_nothing(self) -> None:
        args = RemoveFromCartArgs(menu_item_id=self.pad_thai_id, existing_lines=[])
        with self._session() as db:
            result = TOOLS["remove_from_cart"].handler(db, self._scope(), args)
        self.assertEqual(result["outcome"], "not_found")
        self.assertNotIn("action", result)

    # -- set_quantity ------------------------------------------------------

    def test_set_quantity_matching_one_line_may_be_applied(self) -> None:
        args = SetQuantityArgs(
            menu_item_id=self.pad_thai_id, quantity=3, existing_lines=[self._pad_thai_line()]
        )
        with self._session() as db:
            result = TOOLS["set_quantity"].handler(db, self._scope(), args)
        self.assertEqual(result["action"]["status"], "applied")
        self.assertEqual(result["action"]["quantity"], 3)

    def test_set_quantity_matching_two_lines_is_proposed(self) -> None:
        args = SetQuantityArgs(
            menu_item_id=self.pizza_id,
            quantity=2,
            existing_lines=[
                CartLineArgs(menu_item_id=self.pizza_id, quantity=1, menu_item_size_id=self.pizza_small_id),
                CartLineArgs(menu_item_id=self.pizza_id, quantity=1, menu_item_size_id=self.pizza_small_id),
            ],
        )
        with self._session() as db:
            result = TOOLS["set_quantity"].handler(db, self._scope(), args)
        self.assertEqual(result["action"]["status"], "proposed")
        self.assertEqual(result["action"]["reason"], "ambiguous")

    # -- add_to_cart ---------------------------------------------------------

    def test_add_simple_dish_is_applied(self) -> None:
        args = AddToCartArgs(menu_item_id=self.pad_thai_id, quantity=2)
        with self._session() as db:
            result = TOOLS["add_to_cart"].handler(db, self._scope(), args)
        self.assertEqual(result["outcome"], "action")
        self.assertEqual(result["action"]["status"], "applied")
        self.assertEqual(result["action"]["reason"], "named")
        self.assertEqual(result["action"]["quantity"], 2)
        self.assertEqual(result["action"]["menu_item_id"], self.pad_thai_id)

    def test_add_dish_with_sizes_never_applied_without_size(self) -> None:
        args = AddToCartArgs(menu_item_id=self.pizza_id, quantity=1)
        with self._session() as db:
            result = TOOLS["add_to_cart"].handler(db, self._scope(), args)
        self.assertEqual(result["outcome"], "needs_choice")
        self.assertTrue(result["needs_size"])
        self.assertTrue(result["available_sizes"], "sizes must be carried so the agent can ask")
        size_ids = {s["size_id"] for s in result["available_sizes"]}
        self.assertIn(self.pizza_small_id, size_ids)

    def test_add_dish_with_required_customization_never_applied(self) -> None:
        args = AddToCartArgs(menu_item_id=self.pizza_id, quantity=1, menu_item_size_id=self.pizza_small_id)
        with self._session() as db:
            result = TOOLS["add_to_cart"].handler(db, self._scope(), args)
        self.assertEqual(result["outcome"], "needs_choice")
        self.assertFalse(result["needs_size"])
        self.assertTrue(result["needs_customization"])
        self.assertTrue(result["customization_groups"])

    def test_add_foreign_branch_item_produces_nothing(self) -> None:
        args = AddToCartArgs(menu_item_id=self.other_branch_item_id, quantity=1)
        with self._session() as db:
            result = TOOLS["add_to_cart"].handler(db, self._scope(), args)
        self.assertEqual(result["outcome"], "not_on_menu")
        self.assertNotIn("action", result)

    # -- no name or price on any action --------------------------------

    def test_no_action_carries_a_name_or_price(self) -> None:
        with self._session() as db:
            add_result = TOOLS["add_to_cart"].handler(
                db, self._scope(), AddToCartArgs(menu_item_id=self.pad_thai_id, quantity=1)
            )
            remove_result = TOOLS["remove_from_cart"].handler(
                db,
                self._scope(),
                RemoveFromCartArgs(menu_item_id=self.pad_thai_id, existing_lines=[self._pad_thai_line()]),
            )
            clear_result = TOOLS["clear_cart"].handler(db, self._scope(), ClearCartArgs())
        for result in (add_result, remove_result, clear_result):
            action = result["action"]
            self.assertNotIn("name", action)
            self.assertNotIn("price", action)
            self.assertNotIn("total_price", action)
            self.assertNotIn("unit_price", action)


if __name__ == "__main__":
    unittest.main()
