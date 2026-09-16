"""Migration 0061: `menu_item_customization_options.is_default`.

Two things under test, both load-bearing for the "comes with X, that's $N"
step of the ordering flow:

1. The migration's own backfill SQL (`_BACKFILL_SQL`, loaded straight from
   the migration module rather than re-typed here, so this test would catch
   the migration itself being edited into something different from what ran
   against the real database) — every required+single-choice group ends
   with exactly one default, it is the cheapest ACTIVE option, ties go to the
   lowest `sort_order`, and no optional or multi-select group gets one.

2. `get_dish`'s `customization_groups` — the tool-facing read of that column.

   Fix round 3 (2026-09-16) superseded the original shape here:
   `_describe_defaults_for_size` used to compute a size-plus-defaults PRICE
   inside `get_dish` via `resolve_menu_item_selection`, gated behind an
   explicit `menu_item_size_id` argument, and reported nothing about
   customization groups at all when that argument was omitted — which left a
   dish with `has_customizations=True` reporting no group information
   whatsoever until a size was named. `get_dish` now always returns
   `customization_groups` (dish-wide groups, plus a given size's own once
   `menu_item_size_id` narrows it), each option carrying its real
   `is_default`, and prices nothing itself — see
   `test_ordering_agent_readonly.py::test_get_dish_defaults_compose_into_a_real_price_quote`
   for proof that those defaults compose into a working `price_quote` call
   instead.

DB fixture mirrors `test_ordering_agent_readonly.py`: a throwaway local
Postgres database via `Base.metadata.create_all`, skipped outright if
Postgres is not reachable. `menu_embeddings` is excluded for the same reason
it is there — its column needs pgvector, and nothing here touches it.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.main import app  # noqa: F401 - imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import MenuItemCustomizationSelectionType, UserRole
from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.models.menu_item_size import MenuItemSize
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.ordering_agent.tools import GetDishArgs, OrderingScope, TOOLS

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_customization_defaults_test"

MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "0061_customization_option_defaults.py"
)


def _load_backfill_sql() -> str:
    """Imports the migration file directly by path (its filename is not a
    valid dotted module name) so this test runs the exact SQL string the
    migration applies, rather than a hand-copied lookalike that could drift
    from it.
    """

    spec = importlib.util.spec_from_file_location("migration_0061", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._BACKFILL_SQL


BACKFILL_SQL = _load_backfill_sql()


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
class BackfillSqlTests(unittest.TestCase):
    """Runs migration 0061's own `_BACKFILL_SQL` against synthetic groups
    covering every case the brief called out, set-based, the same way it ran
    against the real 1,199-row table.
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
        tables = [table for table in Base.metadata.sorted_tables if table.name != "menu_embeddings"]
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
            full_name="Backfill Owner",
            email="backfill-owner@test.local",
            hashed_password="x",
            role=UserRole.OWNER,
        )
        session.add(owner)
        session.flush()

        restaurant = Restaurant(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name="Backfill Kitchen",
            slug="backfill-kitchen",
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

        location = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            branch_name="Branch A",
            address_line_1="10 Branch Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560010",
            is_open=True,
            is_active=True,
        )
        session.add(location)
        session.flush()

        dish = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            name="Backfill Bowl",
            category="Mains",
            price=Decimal("100.00"),
            is_available=True,
        )
        session.add(dish)
        session.flush()

        def group(*, title: str, is_required: bool, selection_type, sort_order: int) -> MenuItemCustomizationGroup:
            row = MenuItemCustomizationGroup(
                id=uuid.uuid4(),
                menu_item_id=dish.id,
                title=title,
                is_required=is_required,
                selection_type=selection_type,
                min_selection=1 if is_required else 0,
                max_selection=1 if selection_type == MenuItemCustomizationSelectionType.SINGLE else 3,
                sort_order=sort_order,
            )
            session.add(row)
            return row

        # Case A: required + single, one option strictly cheapest — no tie
        # to resolve, the plain case.
        clear_winner_group = group(
            title="Spice Level",
            is_required=True,
            selection_type=MenuItemCustomizationSelectionType.SINGLE,
            sort_order=1,
        )
        # Case B: required + single, two options tied at the SAME cheapest
        # price — the tie must go to the lower `sort_order`, not to
        # insertion order or id.
        tie_group = group(
            title="Crust",
            is_required=True,
            selection_type=MenuItemCustomizationSelectionType.SINGLE,
            sort_order=2,
        )
        # Case C: optional + single — free choice, must get NO default even
        # though it has a clear cheapest option, per the customer's own rule
        # that a free choice is never pre-decided for them.
        optional_group = group(
            title="Sauce",
            is_required=False,
            selection_type=MenuItemCustomizationSelectionType.SINGLE,
            sort_order=3,
        )
        # Case D: required + MULTI — the customer must pick something, but
        # not exactly one thing, so there is no single option to call "the"
        # default either.
        required_multi_group = group(
            title="Toppings",
            is_required=True,
            selection_type=MenuItemCustomizationSelectionType.MULTI,
            sort_order=4,
        )
        session.flush()

        def option(
            *,
            group_id: uuid.UUID,
            name: str,
            extra_price: str,
            sort_order: int,
            is_active: bool = True,
        ) -> MenuItemCustomizationOption:
            row = MenuItemCustomizationOption(
                id=uuid.uuid4(),
                group_id=group_id,
                name=name,
                extra_price=Decimal(extra_price),
                sort_order=sort_order,
                is_active=is_active,
            )
            session.add(row)
            return row

        # Case A options: Mild is the only $0.00 one.
        mild = option(group_id=clear_winner_group.id, name="Mild", extra_price="0.00", sort_order=1)
        option(group_id=clear_winner_group.id, name="Hot", extra_price="0.50", sort_order=2)
        # An inactive option cheaper than everything else — must be ignored,
        # never chosen as a default a customer could not actually select.
        option(
            group_id=clear_winner_group.id,
            name="Retired Free Sample",
            extra_price="-5.00",
            sort_order=0,
            is_active=False,
        )

        # Case B options: Thin Crust and Classic both $0.00; Classic has the
        # lower sort_order and must win the tie.
        option(group_id=tie_group.id, name="Thin Crust", extra_price="0.00", sort_order=2)
        classic = option(group_id=tie_group.id, name="Classic", extra_price="0.00", sort_order=1)
        option(group_id=tie_group.id, name="Stuffed Crust", extra_price="60.00", sort_order=3)

        # Case C: a clear cheapest option that must NOT become a default.
        option(group_id=optional_group.id, name="Ketchup", extra_price="0.00", sort_order=1)
        option(group_id=optional_group.id, name="Chilli Mayo", extra_price="0.50", sort_order=2)

        # Case D: likewise must get no default.
        option(group_id=required_multi_group.id, name="Cheese", extra_price="0.00", sort_order=1)
        option(group_id=required_multi_group.id, name="Olives", extra_price="0.50", sort_order=2)

        session.flush()

        cls.clear_winner_group_id = clear_winner_group.id
        cls.tie_group_id = tie_group.id
        cls.optional_group_id = optional_group.id
        cls.required_multi_group_id = required_multi_group.id
        cls.mild_id = mild.id
        cls.classic_id = classic.id
        session.commit()

    def _default_option_ids(self, connection, group_id: uuid.UUID) -> set[uuid.UUID]:
        rows = connection.execute(
            text(
                "SELECT id FROM menu_item_customization_options "
                "WHERE group_id = :group_id AND is_default = true"
            ),
            {"group_id": group_id},
        ).fetchall()
        return {row[0] for row in rows}

    def test_required_single_group_defaults_to_its_one_cheapest_active_option(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text(BACKFILL_SQL))
            connection.commit()
            defaults = self._default_option_ids(connection, self.clear_winner_group_id)
        self.assertEqual(defaults, {self.mild_id})

    def test_required_single_group_ties_go_to_the_lower_sort_order(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text(BACKFILL_SQL))
            connection.commit()
            defaults = self._default_option_ids(connection, self.tie_group_id)
        self.assertEqual(defaults, {self.classic_id})

    def test_optional_group_gets_no_default_even_with_a_clear_cheapest_option(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text(BACKFILL_SQL))
            connection.commit()
            defaults = self._default_option_ids(connection, self.optional_group_id)
        self.assertEqual(defaults, set())

    def test_required_multi_select_group_gets_no_default(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text(BACKFILL_SQL))
            connection.commit()
            defaults = self._default_option_ids(connection, self.required_multi_group_id)
        self.assertEqual(defaults, set())

    def test_every_required_single_group_ends_with_exactly_one_default(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text(BACKFILL_SQL))
            connection.commit()
            rows = connection.execute(
                text(
                    """
                    SELECT g.id, count(o.id)
                    FROM menu_item_customization_groups g
                    JOIN menu_item_customization_options o
                        ON o.group_id = g.id AND o.is_default
                    WHERE g.is_required = true AND g.selection_type = 'SINGLE'
                    GROUP BY g.id
                    """
                )
            ).fetchall()
        self.assertEqual(len(rows), 2)  # clear_winner_group and tie_group only
        for _group_id, default_count in rows:
            self.assertEqual(default_count, 1)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class GetDishCustomizationGroupsTests(unittest.TestCase):
    """`get_dish`'s `customization_groups` — the tool-facing read of the real
    `is_default` column, exercised through the registry the ordering agent
    actually calls, exactly like `test_ordering_agent_readonly.py`.
    """

    engine = None
    session_factory = None

    @classmethod
    def setUpClass(cls) -> None:
        admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}_tool" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}_tool"'))
        admin_engine.dispose()

        cls.engine = create_engine(
            f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_server}:{settings.postgres_port}/{TEST_DB_NAME}_tool"
        )
        with cls.engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            connection.commit()
        tables = [table for table in Base.metadata.sorted_tables if table.name != "menu_embeddings"]
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
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}_tool" WITH (FORCE)'))
        admin_engine.dispose()

    @classmethod
    def _seed(cls, session: Session) -> None:
        owner = User(
            id=uuid.uuid4(),
            full_name="Tool Owner",
            email="tool-owner@test.local",
            hashed_password="x",
            role=UserRole.OWNER,
        )
        session.add(owner)
        session.flush()

        restaurant = Restaurant(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name="Tool Kitchen",
            slug="tool-kitchen",
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

        location = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            branch_name="Branch A",
            address_line_1="10 Branch Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560010",
            is_open=True,
            is_active=True,
        )
        session.add(location)
        session.flush()
        cls.location_id = location.id

        pizza = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            name="Default Pizza",
            category="Mains",
            price=Decimal("300.00"),
            is_available=True,
            has_sizes=True,
            has_customizations=True,
        )
        session.add(pizza)
        session.flush()

        small = MenuItemSize(id=uuid.uuid4(), menu_item_id=pizza.id, name="Small", price=Decimal("300.00"))
        large = MenuItemSize(id=uuid.uuid4(), menu_item_id=pizza.id, name="Large", price=Decimal("450.00"))
        session.add_all([small, large])
        session.flush()
        cls.pizza_id = pizza.id
        cls.small_id = small.id
        cls.large_id = large.id

        # A group the SCHEMA scopes to one specific size
        # (`menu_item_size_id` set) rather than the dish — only meaningful
        # once Large is chosen, and must not appear for Small or for no size
        # at all.
        large_only_group = MenuItemCustomizationGroup(
            id=uuid.uuid4(),
            menu_item_id=pizza.id,
            menu_item_size_id=large.id,
            title="Stuffed Crust Filling",
            is_required=False,
            selection_type=MenuItemCustomizationSelectionType.SINGLE,
            min_selection=0,
            max_selection=1,
        )
        session.add(large_only_group)
        session.flush()
        session.add(
            MenuItemCustomizationOption(
                id=uuid.uuid4(),
                group_id=large_only_group.id,
                name="Cheese Stuffed",
                extra_price=Decimal("70.00"),
                is_default=False,
                sort_order=1,
            )
        )
        session.flush()
        cls.large_only_group_id = large_only_group.id

        # A required, single-choice group WITH a default already marked —
        # simulating the state migration 0061 leaves a real group in.
        crust_group = MenuItemCustomizationGroup(
            id=uuid.uuid4(),
            menu_item_id=pizza.id,
            title="Crust",
            is_required=True,
            selection_type=MenuItemCustomizationSelectionType.SINGLE,
            min_selection=1,
            max_selection=1,
        )
        session.add(crust_group)
        session.flush()

        thin = MenuItemCustomizationOption(
            id=uuid.uuid4(),
            group_id=crust_group.id,
            name="Thin Crust",
            extra_price=Decimal("0.00"),
            is_default=True,
            sort_order=1,
        )
        stuffed = MenuItemCustomizationOption(
            id=uuid.uuid4(),
            group_id=crust_group.id,
            name="Stuffed Crust",
            extra_price=Decimal("60.00"),
            is_default=False,
            sort_order=2,
        )
        session.add_all([thin, stuffed])

        # An optional group — no default marked, per the backfill rule.
        toppings_group = MenuItemCustomizationGroup(
            id=uuid.uuid4(),
            menu_item_id=pizza.id,
            title="Extra Toppings",
            is_required=False,
            selection_type=MenuItemCustomizationSelectionType.MULTI,
            min_selection=0,
            max_selection=3,
        )
        session.add(toppings_group)
        session.flush()

        olives = MenuItemCustomizationOption(
            id=uuid.uuid4(),
            group_id=toppings_group.id,
            name="Olives",
            extra_price=Decimal("20.00"),
            is_default=False,
            sort_order=1,
        )
        session.add(olives)

        # A second pizza whose required group was never backfilled with a
        # default at all (e.g. added after the migration ran) — the tool
        # must refuse to invent a price rather than guess one.
        undefaulted_pizza = MenuItem(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            name="Undefaulted Pizza",
            category="Mains",
            price=Decimal("280.00"),
            is_available=True,
            has_sizes=True,
            has_customizations=True,
        )
        session.add(undefaulted_pizza)
        session.flush()

        undefaulted_size = MenuItemSize(
            id=uuid.uuid4(), menu_item_id=undefaulted_pizza.id, name="Small", price=Decimal("280.00")
        )
        session.add(undefaulted_size)
        session.flush()

        no_default_group = MenuItemCustomizationGroup(
            id=uuid.uuid4(),
            menu_item_id=undefaulted_pizza.id,
            title="Crust",
            is_required=True,
            selection_type=MenuItemCustomizationSelectionType.SINGLE,
            min_selection=1,
            max_selection=1,
        )
        session.add(no_default_group)
        session.flush()
        session.add(
            MenuItemCustomizationOption(
                id=uuid.uuid4(),
                group_id=no_default_group.id,
                name="Thin Crust",
                extra_price=Decimal("0.00"),
                is_default=False,
                sort_order=1,
            )
        )
        session.flush()

        cls.undefaulted_pizza_id = undefaulted_pizza.id
        cls.undefaulted_size_id = undefaulted_size.id
        cls.thin_id = thin.id
        cls.stuffed_id = stuffed.id
        cls.olives_id = olives.id
        session.commit()

    def _session(self) -> Session:
        return self.session_factory()

    def _scope(self) -> OrderingScope:
        return OrderingScope(restaurant_id=self.restaurant_id, restaurant_location_id=self.location_id)

    def test_get_dish_without_a_size_reports_the_dish_wide_groups_and_their_defaults(self) -> None:
        """The reported gap, reproduced directly: `has_customizations: True`
        must come with the groups themselves even with no size named — the
        dish-wide ones (Crust, Extra Toppings; both have no
        `menu_item_size_id`) do not depend on a size to be knowable."""

        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(db, self._scope(), GetDishArgs(name="Default Pizza"))

        self.assertTrue(result["found"])
        groups_by_title = {group["title"]: group for group in result["customization_groups"]}
        self.assertEqual(set(groups_by_title), {"Crust", "Extra Toppings"})

        crust = groups_by_title["Crust"]
        self.assertTrue(crust["is_required"])
        self.assertIsNone(crust["menu_item_size_id"])
        crust_defaults = {o["option_id"] for o in crust["options"] if o["is_default"]}
        self.assertEqual(crust_defaults, {self.thin_id})
        self.assertEqual({o["option_id"] for o in crust["options"]}, {self.thin_id, self.stuffed_id})

        toppings = groups_by_title["Extra Toppings"]
        self.assertFalse(toppings["is_required"])
        # Offered but not pre-picked — nothing on this group has is_default.
        self.assertEqual({o["option_id"] for o in toppings["options"] if o["is_default"]}, set())

    def test_get_dish_never_computes_a_price(self) -> None:
        """The coordinator's explicit instruction: get_dish answers "what
        could this be", never "what would this cost" — no price-shaped key
        anywhere in the response."""

        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(
                db, self._scope(), GetDishArgs(name="Default Pizza", menu_item_size_id=self.small_id)
            )

        self.assertNotIn("defaults", result)
        self.assertNotIn("price_with_defaults", result)
        for group in result["customization_groups"]:
            self.assertNotIn("price", group)
            for option in group["options"]:
                self.assertNotIn("price", option)

    def test_get_dish_scopes_a_size_specific_group_to_the_right_size(self) -> None:
        """`Stuffed Crust Filling` is scoped to Large via the group's own
        `menu_item_size_id` — it must be absent with no size given, absent
        for Small, and present for Large."""

        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            no_size = TOOLS["get_dish"].handler(db, self._scope(), GetDishArgs(name="Default Pizza"))
            small = TOOLS["get_dish"].handler(
                db, self._scope(), GetDishArgs(name="Default Pizza", menu_item_size_id=self.small_id)
            )
            large = TOOLS["get_dish"].handler(
                db, self._scope(), GetDishArgs(name="Default Pizza", menu_item_size_id=self.large_id)
            )

        self.assertNotIn("Stuffed Crust Filling", {g["title"] for g in no_size["customization_groups"]})
        self.assertNotIn("Stuffed Crust Filling", {g["title"] for g in small["customization_groups"]})

        large_group = next(
            g for g in large["customization_groups"] if g["title"] == "Stuffed Crust Filling"
        )
        self.assertEqual(large_group["menu_item_size_id"], self.large_id)
        # The dish-wide groups are still there too — narrowing to a size
        # adds that size's own groups, it does not drop the dish's others.
        self.assertIn("Crust", {g["title"] for g in large["customization_groups"]})

    def test_get_dish_reports_no_default_for_a_group_nobody_backfilled(self) -> None:
        """A required group nobody ever ran the backfill against (or added
        after it ran) must not get an invented default — every option in it
        honestly reports `is_default: False`, same as an optional group."""

        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(
                db,
                self._scope(),
                GetDishArgs(name="Undefaulted Pizza", menu_item_size_id=self.undefaulted_size_id),
            )

        self.assertTrue(result["found"])
        crust_group = next(g for g in result["customization_groups"] if g["title"] == "Crust")
        self.assertTrue(crust_group["is_required"])
        self.assertEqual({o["option_id"] for o in crust_group["options"] if o["is_default"]}, set())


if __name__ == "__main__":
    unittest.main()
