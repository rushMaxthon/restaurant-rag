"""Task 2: the seven read-only ordering-agent tools, wired to real services.

No new business logic lives here or in the handlers under test — every
assertion checks that a handler faithfully relays what an existing service
already decided (branch scoping, hours, enabled payment methods, pricing),
never that it computed something itself. `test_price_quote_agrees_with_validate_order_draft`
is the one that matters most: it calls `orders.validate_order_draft` directly
and asserts the tool's numbers match, rather than hardcoding an expected
total, so this test cannot pass by the tool and the checkout path drifting to
the same wrong answer independently.

DB fixture mirrors `test_suggestion_cards.py`: a throwaway local Postgres
database, `Base.metadata.create_all`. `menu_embeddings` is deliberately
excluded from that create_all — its column type needs the pgvector
extension, which this checkout's local Postgres 14 does not have (see
CLAUDE.md's environment notes and the plan's verification-gate signature for
that exact error). None of these tests need it: `search_menu`/`get_dish`
patch `app.services.rag._embed_query` to `None`, the same "embedding
provider unavailable" branch `_resolve_final_candidates` already handles in
production, so retrieval falls through to the keyword tier — real code, a
real DB round-trip, just not a real network call to Ollama.
"""

from __future__ import annotations

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
from app.models.enums import OrderFulfillmentType, PaymentMethod, UserRole
from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.models.menu_item_size import MenuItemSize
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.order import OrderCreateItem, OrderCreateRequest
from app.services.orders import validate_order_draft
from app.services.ordering_agent.tools import (
    CartLineArgs,
    CheckHoursArgs,
    GetDishArgs,
    OrderingScope,
    PaymentOptionsArgs,
    PriceQuoteArgs,
    RestaurantInfoArgs,
    SearchMenuArgs,
    SelectedOptionArgs,
    TOOLS,
    ViewCartArgs,
)

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_ordering_agent_readonly_test"


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
class OrderingAgentReadonlyToolTests(unittest.TestCase):
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
            # `_fetch_fuzzy_candidates` (`rag.py`, migration `0055`) reads
            # `word_similarity`, which ships in core Postgres's `pg_trgm`
            # contrib module — unlike pgvector below, this needs no external
            # build, so it is safe to enable even where pgvector cannot be.
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            connection.commit()
        # `menu_embeddings` needs the pgvector extension, which this
        # checkout's local Postgres does not have installed for the running
        # major version. Excluded here on purpose: nothing under test reaches
        # it, since `_embed_query` is patched to `None` in every test that
        # runs retrieval, and creating every OTHER table with plain
        # `create_all` is what lets these tests execute for real instead of
        # failing at setUpClass like the rest of the suite does on this
        # machine.
        tables = [
            table
            for table in Base.metadata.sorted_tables
            if table.name != "menu_embeddings"
        ]
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
            full_name="Readonly Owner",
            email="readonly-owner@test.local",
            hashed_password="x",
            role=UserRole.OWNER,
        )
        customer = User(
            id=uuid.uuid4(),
            full_name="Readonly Customer",
            email="readonly-customer@test.local",
            hashed_password="x",
            role=UserRole.CUSTOMER,
        )
        session.add_all([owner, customer])
        session.flush()
        cls.customer = customer

        restaurant = Restaurant(
            id=uuid.uuid4(),
            owner_id=owner.id,
            name="Readonly Kitchen",
            slug="readonly-kitchen",
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

        # Branch A: open, COD only, no slots/hours configured (so
        # `get_location_fulfillment_status` reads "always available" per its
        # own fallback for a branch with neither slots nor opening/closing
        # times set).
        branch_a = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            branch_name="Branch A",
            address_line_1="10 Branch Road",
            address_line_2="Suite 1",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560010",
            phone_number="+911234500010",
            delivery_fee=Decimal("30.00"),
            minimum_order_amount=Decimal("100.00"),
            estimated_delivery_time=35,
            estimated_pickup_time=15,
            preparation_time_minutes=12,
            delivery_enabled=True,
            pickup_enabled=True,
            is_open=True,
            is_active=True,
            google_pay_enabled=False,
            razorpay_enabled=False,
            card_payment_enabled=False,
            cash_on_delivery_enabled=True,
        )
        # Branch B: a second branch of the SAME restaurant, closed, with its
        # own separate menu. Exists purely so a foreign-branch id has
        # somewhere real to belong to instead of just being nonexistent.
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

        def make_item(
            *,
            restaurant_id: uuid.UUID,
            location_id: uuid.UUID,
            name: str,
            price: str,
            category: str = "Mains",
            is_veg: bool = False,
            has_sizes: bool = False,
            has_customizations: bool = False,
        ) -> MenuItem:
            row = MenuItem(
                id=uuid.uuid4(),
                restaurant_id=restaurant_id,
                restaurant_location_id=location_id,
                name=name,
                category=category,
                price=Decimal(price),
                is_veg=is_veg,
                is_available=True,
                has_sizes=has_sizes,
                has_customizations=has_customizations,
            )
            session.add(row)
            return row

        pad_thai = make_item(
            restaurant_id=restaurant.id, location_id=branch_a.id, name="Pad Thai", price="220.00"
        )
        # Distinct from "Pad Thai" above on purpose: "pad thai" (what a
        # customer actually types) is an exact case-insensitive match for
        # THIS item's name, but only a near-miss (a substring) against a
        # dish literally named "Pad Thai (Veg)" — the fix-round-4 short
        # circuit must not fire for it, and the existing keyword-tier
        # cascade must still be the one that resolves it.
        pad_thai_veg = make_item(
            restaurant_id=restaurant.id,
            location_id=branch_a.id,
            name="Pad Thai (Veg)",
            price="210.00",
            is_veg=True,
        )
        curry = make_item(
            restaurant_id=restaurant.id,
            location_id=branch_a.id,
            name="Green Curry",
            price="260.00",
            is_veg=True,
        )
        sized_item = make_item(
            restaurant_id=restaurant.id,
            location_id=branch_a.id,
            name="Fried Rice",
            price="180.00",
            has_sizes=True,
        )
        # Mirrors the coordinator's own reproduction of the fix-round-1
        # defect: a real, sized pizza with a REQUIRED topping choice. Used to
        # come back "not on this branch's menu"; must now come back
        # `needs_choice` with both the sizes and the topping group listed.
        pizza = make_item(
            restaurant_id=restaurant.id,
            location_id=branch_a.id,
            name="Margherita Pizza",
            price="350.00",
            has_sizes=True,
            has_customizations=True,
        )
        other_branch_item = make_item(
            restaurant_id=restaurant.id, location_id=branch_b.id, name="Tom Yum Soup", price="240.00"
        )
        session.flush()

        pizza_small_id, pizza_large_id = uuid.uuid4(), uuid.uuid4()
        session.add_all(
            [
                MenuItemSize(
                    id=uuid.uuid4(),
                    menu_item_id=sized_item.id,
                    name="Regular",
                    price=Decimal("180.00"),
                ),
                MenuItemSize(id=pizza_small_id, menu_item_id=pizza.id, name="Small", price=Decimal("350.00")),
                MenuItemSize(id=pizza_large_id, menu_item_id=pizza.id, name="Large", price=Decimal("550.00")),
            ]
        )
        session.flush()

        # A REQUIRED group ("choose your base") — the one case with no
        # default, must genuinely block a price until answered.
        crust_group_id = uuid.uuid4()
        crust_group = MenuItemCustomizationGroup(
            id=crust_group_id,
            menu_item_id=pizza.id,
            title="Crust",
            is_required=True,
            min_selection=1,
            max_selection=1,
        )
        # An OPTIONAL group ("extra toppings") — rule 3: has a default (no
        # extra toppings) and must never block a price, only be offered.
        toppings_group_id = uuid.uuid4()
        toppings_group = MenuItemCustomizationGroup(
            id=toppings_group_id,
            menu_item_id=pizza.id,
            title="Extra Toppings",
            is_required=False,
            min_selection=0,
            max_selection=3,
        )
        session.add_all([crust_group, toppings_group])
        session.flush()

        crust_thin_id, crust_stuffed_id = uuid.uuid4(), uuid.uuid4()
        topping_cheese_id, topping_olives_id = uuid.uuid4(), uuid.uuid4()
        session.add_all(
            [
                # Marked `is_default=True` to mirror what migration 0061's
                # real backfill would do here: the cheapest active option in
                # a required+single-choice group.
                MenuItemCustomizationOption(
                    id=crust_thin_id,
                    group_id=crust_group_id,
                    name="Thin Crust",
                    extra_price=Decimal("0.00"),
                    is_default=True,
                ),
                MenuItemCustomizationOption(
                    id=crust_stuffed_id,
                    group_id=crust_group_id,
                    name="Stuffed Crust",
                    extra_price=Decimal("60.00"),
                ),
                MenuItemCustomizationOption(
                    id=topping_cheese_id,
                    group_id=toppings_group_id,
                    name="Extra Cheese",
                    extra_price=Decimal("40.00"),
                ),
                MenuItemCustomizationOption(
                    id=topping_olives_id, group_id=toppings_group_id, name="Olives", extra_price=Decimal("20.00")
                ),
            ]
        )
        session.flush()

        cls.pad_thai_id = pad_thai.id
        cls.pad_thai_veg_id = pad_thai_veg.id
        cls.curry_id = curry.id
        cls.sized_item_id = sized_item.id
        cls.pizza_id = pizza.id
        cls.pizza_small_id = pizza_small_id
        cls.pizza_large_id = pizza_large_id
        cls.crust_thin_id = crust_thin_id
        cls.crust_stuffed_id = crust_stuffed_id
        cls.topping_cheese_id = topping_cheese_id
        cls.topping_olives_id = topping_olives_id
        cls.other_branch_item_id = other_branch_item.id
        session.commit()

    def _session(self) -> Session:
        return self.session_factory()

    def _scope(self, *, location_id: uuid.UUID | None = None, customer=None) -> OrderingScope:
        return OrderingScope(
            restaurant_id=self.restaurant_id,
            restaurant_location_id=location_id or self.branch_a_id,
            customer=customer,
        )

    # -- search_menu ---------------------------------------------------

    def test_search_menu_is_branch_scoped(self) -> None:
        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["search_menu"].handler(
                db, self._scope(), SearchMenuArgs(query="curry")
            )
        names = {row["name"] for row in result["results"]}
        self.assertIn("Green Curry", names)
        self.assertNotIn("Tom Yum Soup", names, "branch B's item leaked into branch A's search")

    def test_search_menu_veg_filter_delegates_to_menu_item_is_veg(self) -> None:
        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["search_menu"].handler(
                db, self._scope(), SearchMenuArgs(query="Pad Thai", is_veg=True)
            )
        names = {row["name"] for row in result["results"]}
        self.assertNotIn("Pad Thai", names)

    # -- get_dish --------------------------------------------------------

    def test_get_dish_resolves_a_real_menu_row_at_this_branch(self) -> None:
        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(db, self._scope(), GetDishArgs(name="Pad Thai"))
        self.assertTrue(result["found"])
        self.assertEqual(result["menu_item_id"], self.pad_thai_id)
        self.assertEqual(result["price"], Decimal("220.00"))

    def test_get_dish_exact_name_matches_resolve_named_without_touching_the_cascade(self) -> None:
        """Fix round 4: the reported defect. An exact `MenuItem.name` value
        must resolve `found=True, confidence="named"` — never `absent`,
        never `unknown` — and must not even reach the retrieval cascade
        (patched here to raise if called), since an exact match needs no
        embedding, no keyword tier, and no guardrail distance to be sure of
        itself. Exercised over every real dish name in the fixture, not
        just one, mirroring how the coordinator found the defect (a sample
        across a whole branch, not a single lucky/unlucky name)."""

        exact_names_and_ids = {
            "Pad Thai": self.pad_thai_id,
            "Pad Thai (Veg)": self.pad_thai_veg_id,
            "Green Curry": self.curry_id,
            "Fried Rice": self.sized_item_id,
            "Margherita Pizza": self.pizza_id,
        }
        with self._session() as db, patch(
            "app.services.rag._resolve_final_candidates",
            side_effect=AssertionError("cascade should not run"),
        ):
            for name, expected_id in exact_names_and_ids.items():
                with self.subTest(name=name):
                    result = TOOLS["get_dish"].handler(db, self._scope(), GetDishArgs(name=name))
                    self.assertTrue(result["found"], msg=name)
                    self.assertEqual(result["confidence"], "named", msg=name)
                    self.assertEqual(result["menu_item_id"], expected_id, msg=name)

    def test_get_dish_exact_name_match_is_case_insensitive(self) -> None:
        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(db, self._scope(), GetDishArgs(name="pad thai"))
        self.assertTrue(result["found"])
        self.assertEqual(result["confidence"], "named")
        self.assertEqual(result["menu_item_id"], self.pad_thai_id)

    def test_get_dish_near_miss_still_uses_the_existing_cascade(self) -> None:
        """"Margherita" is not an exact match for "Margherita Pizza" — it
        must fall through to the same keyword-tier cascade this resolved
        through before fix round 4, and get the same answer it always has:
        found via keyword match, `unknown` confidence with no embedding
        available (there is no vector-sourced candidate for the guardrail to
        read a distance from, and its own fallback re-query is skipped when
        `query_embedding` is `None`). Fix round 4 adds a path in front of
        this one; it must not change what this path itself produces."""

        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(db, self._scope(), GetDishArgs(name="Margherita"))
        self.assertTrue(result["found"])
        self.assertEqual(result["menu_item_id"], self.pizza_id)
        self.assertEqual(result["confidence"], "unknown")

    def test_get_dish_genuinely_absent_dish_still_resolves_absent(self) -> None:
        """Not a new test in spirit — `test_get_dish_degrades_for_a_name_on_no_menu`
        already covers this — but named and grouped here explicitly per the
        coordinator's ask, since fix round 4 must not turn "absent" into
        "found" for a name that genuinely is not on the menu."""

        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(
                db, self._scope(), GetDishArgs(name="xyzzy nonsense dish")
            )
        self.assertFalse(result["found"])

    def test_get_dish_returns_sizes_with_their_own_prices(self) -> None:
        """Second fix round: step 1 of the flow ("which size, and what does
        it cost") must be answerable from this one call — each size's own
        absolute price, not a delta off the base `price`."""

        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(db, self._scope(), GetDishArgs(name="Margherita"))
        self.assertTrue(result["found"])
        self.assertEqual(result["menu_item_id"], self.pizza_id)
        sizes = {(size["name"], size["price"]) for size in result["sizes"]}
        self.assertEqual(sizes, {("Small", Decimal("350.00")), ("Large", Decimal("550.00"))})

    def test_get_dish_reports_no_sizes_for_an_unsized_item(self) -> None:
        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(db, self._scope(), GetDishArgs(name="Pad Thai"))
        self.assertEqual(result["sizes"], [])

    def test_get_dish_returns_customization_groups_with_real_defaults(self) -> None:
        """Fix round 3: `has_customizations: True` must come with the groups
        themselves, not nothing — both groups here are dish-wide (no size
        named), so both must appear without needing `menu_item_size_id` at
        all. Crust's real default (migration 0061: cheapest active option in
        a required+single group) shows as `is_default`; Extra Toppings, an
        optional group, marks none."""

        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(db, self._scope(), GetDishArgs(name="Margherita"))

        groups_by_title = {g["title"]: g for g in result["customization_groups"]}
        self.assertEqual(set(groups_by_title), {"Crust", "Extra Toppings"})

        crust = groups_by_title["Crust"]
        self.assertTrue(crust["is_required"])
        crust_defaults = {o["option_id"] for o in crust["options"] if o["is_default"]}
        self.assertEqual(crust_defaults, {self.crust_thin_id})

        toppings = groups_by_title["Extra Toppings"]
        self.assertFalse(toppings["is_required"])
        self.assertEqual({o["option_id"] for o in toppings["options"] if o["is_default"]}, set())
        self.assertEqual(len(toppings["options"]), 2)

    def test_get_dish_reports_no_customization_groups_for_a_plain_item(self) -> None:
        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(db, self._scope(), GetDishArgs(name="Pad Thai"))
        self.assertEqual(result["customization_groups"], [])

    def test_get_dish_defaults_compose_into_a_real_price_quote(self) -> None:
        """The coordinator's explicit ask: get_dish must not price anything
        itself, but the defaults it reports must actually compose into a
        working `price_quote` call — proving the composition works end to
        end, through the one price path, rather than asserting it in the
        abstract."""

        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            dish = TOOLS["get_dish"].handler(db, self._scope(), GetDishArgs(name="Margherita"))

        small_size_id = next(s["size_id"] for s in dish["sizes"] if s["name"] == "Small")
        crust_group = next(g for g in dish["customization_groups"] if g["title"] == "Crust")
        default_crust_option_id = next(o["option_id"] for o in crust_group["options"] if o["is_default"])

        lines = [
            CartLineArgs(
                menu_item_id=dish["menu_item_id"],
                quantity=1,
                menu_item_size_id=small_size_id,
                selected_options=[SelectedOptionArgs(option_id=default_crust_option_id)],
            )
        ]
        with self._session() as db:
            result = TOOLS["price_quote"].handler(
                db, self._scope(customer=self.customer), PriceQuoteArgs(lines=lines)
            )

        self.assertTrue(result["priced"])
        self.assertEqual(result["needs_choice"], [])
        self.assertEqual(result["subtotal"], Decimal("350.00"))

    def test_get_dish_at_the_wrong_branch_does_not_find_it(self) -> None:
        """Tom Yum Soup is real, but only at branch B — asking from branch A's
        scope must not resolve it."""

        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(
                db, self._scope(location_id=self.branch_a_id), GetDishArgs(name="Tom Yum Soup")
            )
        self.assertFalse(result["found"])

    def test_get_dish_degrades_for_a_name_on_no_menu(self) -> None:
        with self._session() as db, patch("app.services.rag._embed_query", return_value=None):
            result = TOOLS["get_dish"].handler(
                db, self._scope(), GetDishArgs(name="xyzzy nonsense dish")
            )
        self.assertFalse(result["found"])

    # -- view_cart ---------------------------------------------------------

    def test_view_cart_resolves_only_this_branchs_lines(self) -> None:
        lines = [
            CartLineArgs(menu_item_id=self.pad_thai_id, quantity=2),
            CartLineArgs(menu_item_id=self.other_branch_item_id, quantity=1),
            CartLineArgs(menu_item_id=uuid.uuid4(), quantity=1),
        ]
        with self._session() as db:
            result = TOOLS["view_cart"].handler(db, self._scope(), ViewCartArgs(lines=lines))

        self.assertEqual(len(result["lines"]), 1)
        self.assertEqual(result["lines"][0]["menu_item_id"], self.pad_thai_id)
        self.assertEqual(result["lines"][0]["total_price"], Decimal("440.00"))
        self.assertEqual(result["subtotal"], Decimal("440.00"))
        self.assertEqual(result["dropped_line_count"], 2)

    def test_view_cart_on_an_empty_cart_degrades_not_raises(self) -> None:
        with self._session() as db:
            result = TOOLS["view_cart"].handler(db, self._scope(), ViewCartArgs(lines=[]))
        self.assertEqual(result["lines"], [])
        self.assertEqual(result["subtotal"], Decimal("0.00"))

    def test_view_cart_flags_a_missing_size_as_needing_a_choice_not_absent(self) -> None:
        """Fix round 1's exact defect: a real, sized dish with no size named
        must come back `needs_choice`, listing its real sizes and prices —
        never "not on this branch's menu", and never silently dropped."""

        lines = [CartLineArgs(menu_item_id=self.pizza_id, quantity=2)]
        with self._session() as db:
            result = TOOLS["view_cart"].handler(db, self._scope(), ViewCartArgs(lines=lines))

        self.assertEqual(result["lines"], [])
        self.assertEqual(result["dropped_line_count"], 0)
        self.assertEqual(len(result["needs_choice"]), 1)
        choice = result["needs_choice"][0]
        self.assertEqual(choice["menu_item_id"], self.pizza_id)
        self.assertTrue(choice["needs_size"])
        sizes = {(size["name"], size["price"]) for size in choice["available_sizes"]}
        self.assertEqual(sizes, {("Small", Decimal("350.00")), ("Large", Decimal("550.00"))})

    def test_view_cart_reports_required_customization_groups_and_their_defaults(self) -> None:
        """Once a size resolves the pizza still has an unmet REQUIRED group
        (Crust) and a satisfied-by-default OPTIONAL one (Extra Toppings).
        The response must show both — which one blocks, and what each
        defaults to: Crust has a REAL marked default (Thin Crust) that
        nonetheless still blocks until explicitly chosen; Extra Toppings
        defaults to nothing chosen, at_default True."""

        lines = [
            CartLineArgs(menu_item_id=self.pizza_id, quantity=1, menu_item_size_id=self.pizza_small_id)
        ]
        with self._session() as db:
            result = TOOLS["view_cart"].handler(db, self._scope(), ViewCartArgs(lines=lines))

        self.assertEqual(result["lines"], [])
        self.assertEqual(len(result["needs_choice"]), 1)
        choice = result["needs_choice"][0]
        self.assertFalse(choice["needs_size"])
        self.assertTrue(choice["needs_customization"])

        groups_by_title = {g["title"]: g for g in choice["customization_groups"]}
        crust = groups_by_title["Crust"]
        toppings = groups_by_title["Extra Toppings"]
        self.assertTrue(crust["is_required"])
        self.assertTrue(crust["needs_selection"])
        # A real default exists (migration 0061's rule: cheapest active
        # option in a required+single group) but nothing has been chosen
        # yet, so it still blocks — a default narrates, it never applies
        # itself.
        self.assertEqual(crust["default_selection"], [self.crust_thin_id])
        self.assertFalse(crust["at_default"])
        self.assertFalse(toppings["is_required"])
        self.assertFalse(toppings["needs_selection"])
        self.assertEqual(toppings["default_selection"], [])
        self.assertTrue(toppings["at_default"])
        self.assertEqual(len(toppings["options"]), 2)

    def test_view_cart_prices_a_complete_pizza_line_and_shows_its_defaults(self) -> None:
        """A size AND the required crust chosen, no extra toppings: complete,
        priced from `resolve_menu_item_selection`, and still shows the
        optional group as available/at-default alongside the price — step 2
        of the flow needs the price and the defaults together."""

        lines = [
            CartLineArgs(
                menu_item_id=self.pizza_id,
                quantity=1,
                menu_item_size_id=self.pizza_small_id,
                selected_options=[SelectedOptionArgs(option_id=self.crust_thin_id)],
            )
        ]
        with self._session() as db:
            result = TOOLS["view_cart"].handler(db, self._scope(), ViewCartArgs(lines=lines))

        self.assertEqual(result["needs_choice"], [])
        self.assertEqual(len(result["lines"]), 1)
        line = result["lines"][0]
        self.assertEqual(line["unit_price"], Decimal("350.00"))
        groups_by_title = {g["title"]: g for g in line["customization_groups"]}
        self.assertEqual(groups_by_title["Crust"]["selected_option_ids"], [self.crust_thin_id])
        # The customer's explicit pick happens to be the real marked default
        # (Thin Crust) — `at_default` reads that off `is_default`, not off
        # `is_required`, so a required group can now be truthfully "at
        # default" too.
        self.assertEqual(groups_by_title["Crust"]["default_selection"], [self.crust_thin_id])
        self.assertTrue(groups_by_title["Crust"]["at_default"])
        self.assertTrue(groups_by_title["Extra Toppings"]["at_default"])

    def test_view_cart_mixed_cart_prices_complete_lines_and_flags_the_incomplete_one(self) -> None:
        """Three real lines, one of them missing a size: the three price,
        the fourth is reported as needing a choice — never a whole-cart
        refusal (rule 4)."""

        lines = [
            CartLineArgs(menu_item_id=self.pad_thai_id, quantity=1),
            CartLineArgs(menu_item_id=self.curry_id, quantity=1),
            CartLineArgs(menu_item_id=self.pizza_id, quantity=1),  # no size named
        ]
        with self._session() as db:
            result = TOOLS["view_cart"].handler(db, self._scope(), ViewCartArgs(lines=lines))

        priced_ids = {line["menu_item_id"] for line in result["lines"]}
        self.assertEqual(priced_ids, {self.pad_thai_id, self.curry_id})
        self.assertEqual(result["subtotal"], Decimal("480.00"))
        self.assertEqual(len(result["needs_choice"]), 1)
        self.assertEqual(result["needs_choice"][0]["menu_item_id"], self.pizza_id)
        self.assertEqual(result["dropped_line_count"], 0)

    def test_view_cart_still_silently_drops_a_foreign_branch_id_alongside_a_choice(self) -> None:
        """The other-branch id must not be promoted to `needs_choice` just
        because a real needs_choice line also exists in the same cart."""

        lines = [
            CartLineArgs(menu_item_id=self.pizza_id, quantity=1),  # needs a size
            CartLineArgs(menu_item_id=self.other_branch_item_id, quantity=1),  # not here at all
        ]
        with self._session() as db:
            result = TOOLS["view_cart"].handler(db, self._scope(), ViewCartArgs(lines=lines))

        self.assertEqual(result["dropped_line_count"], 1)
        self.assertEqual(len(result["needs_choice"]), 1)
        self.assertEqual(result["needs_choice"][0]["menu_item_id"], self.pizza_id)

    # -- check_hours ---------------------------------------------------

    def test_check_hours_reports_the_open_branch_available(self) -> None:
        with self._session() as db:
            result = TOOLS["check_hours"].handler(
                db, self._scope(location_id=self.branch_a_id), CheckHoursArgs()
            )
        self.assertTrue(result["branch_found"])
        self.assertTrue(result["fulfillment"][OrderFulfillmentType.DELIVERY.value]["available"])
        self.assertTrue(result["fulfillment"][OrderFulfillmentType.PICKUP.value]["available"])

    def test_check_hours_reports_the_closed_branch_unavailable(self) -> None:
        with self._session() as db:
            result = TOOLS["check_hours"].handler(
                db, self._scope(location_id=self.branch_b_id), CheckHoursArgs()
            )
        self.assertTrue(result["branch_found"])
        self.assertFalse(result["fulfillment"][OrderFulfillmentType.DELIVERY.value]["available"])

    def test_check_hours_narrows_to_the_requested_fulfillment_type(self) -> None:
        with self._session() as db:
            result = TOOLS["check_hours"].handler(
                db,
                self._scope(location_id=self.branch_a_id),
                CheckHoursArgs(fulfillment_type=OrderFulfillmentType.PICKUP),
            )
        self.assertEqual(set(result["fulfillment"]), {OrderFulfillmentType.PICKUP.value})

    # -- price_quote ---------------------------------------------------

    def test_price_quote_agrees_with_validate_order_draft(self) -> None:
        """The load-bearing test: the tool must not invent its own total. It
        is asserted equal to a direct call of the same function checkout
        uses, never to a hardcoded number.
        """

        lines = [
            CartLineArgs(menu_item_id=self.pad_thai_id, quantity=2),
            CartLineArgs(menu_item_id=self.curry_id, quantity=1),
        ]
        with self._session() as db:
            result = TOOLS["price_quote"].handler(
                db,
                self._scope(customer=self.customer),
                PriceQuoteArgs(lines=lines, fulfillment_type=OrderFulfillmentType.DELIVERY),
            )

            expected = validate_order_draft(
                db,
                self.customer,
                OrderCreateRequest(
                    restaurant_id=self.restaurant_id,
                    restaurant_location_id=self.branch_a_id,
                    fulfillment_type=OrderFulfillmentType.DELIVERY,
                    items=[
                        OrderCreateItem(menu_item_id=self.pad_thai_id, quantity=2),
                        OrderCreateItem(menu_item_id=self.curry_id, quantity=1),
                    ],
                    delivery_address="Some real address, 12345",
                ),
            )

        self.assertTrue(result["priced"])
        self.assertEqual(result["subtotal"], expected.subtotal)
        self.assertEqual(result["delivery_fee"], expected.delivery_fee)
        self.assertEqual(result["tax_amount"], expected.tax_amount)
        self.assertEqual(result["total_amount"], expected.total_amount)
        self.assertEqual(result["currency"], expected.currency)

    def test_price_quote_ignores_a_line_from_another_branch(self) -> None:
        lines = [
            CartLineArgs(menu_item_id=self.pad_thai_id, quantity=1),
            CartLineArgs(menu_item_id=self.other_branch_item_id, quantity=5),
        ]
        with self._session() as db:
            result = TOOLS["price_quote"].handler(
                db, self._scope(customer=self.customer), PriceQuoteArgs(lines=lines)
            )
            expected = validate_order_draft(
                db,
                self.customer,
                OrderCreateRequest(
                    restaurant_id=self.restaurant_id,
                    restaurant_location_id=self.branch_a_id,
                    items=[OrderCreateItem(menu_item_id=self.pad_thai_id, quantity=1)],
                    delivery_address="Some real address, 12345",
                ),
            )

        self.assertTrue(result["priced"])
        self.assertEqual(result["subtotal"], expected.subtotal)
        self.assertEqual(result["total_amount"], expected.total_amount)

    def test_price_quote_without_a_signed_in_customer_degrades(self) -> None:
        lines = [CartLineArgs(menu_item_id=self.pad_thai_id, quantity=1)]
        with self._session() as db:
            result = TOOLS["price_quote"].handler(
                db, self._scope(customer=None), PriceQuoteArgs(lines=lines)
            )
        self.assertFalse(result["priced"])

    def test_price_quote_with_only_foreign_lines_degrades_not_raises(self) -> None:
        lines = [CartLineArgs(menu_item_id=self.other_branch_item_id, quantity=1)]
        with self._session() as db:
            result = TOOLS["price_quote"].handler(
                db, self._scope(customer=self.customer), PriceQuoteArgs(lines=lines)
            )
        self.assertFalse(result["priced"])
        self.assertEqual(result["needs_choice"], [])

    def test_price_quote_prices_the_complete_lines_and_flags_the_incomplete_one(self) -> None:
        """Rule 4: a mixed cart must not refuse the whole quote. Pad Thai and
        Green Curry price; the sizeless pizza rides along in `needs_choice`
        on the SAME response."""

        lines = [
            CartLineArgs(menu_item_id=self.pad_thai_id, quantity=2),
            CartLineArgs(menu_item_id=self.pizza_id, quantity=1),  # no size named
        ]
        with self._session() as db:
            result = TOOLS["price_quote"].handler(
                db, self._scope(customer=self.customer), PriceQuoteArgs(lines=lines)
            )
            expected = validate_order_draft(
                db,
                self.customer,
                OrderCreateRequest(
                    restaurant_id=self.restaurant_id,
                    restaurant_location_id=self.branch_a_id,
                    items=[OrderCreateItem(menu_item_id=self.pad_thai_id, quantity=2)],
                    delivery_address="Some real address, 12345",
                ),
            )

        self.assertTrue(result["priced"])
        self.assertEqual(result["subtotal"], expected.subtotal)
        self.assertEqual(result["total_amount"], expected.total_amount)
        self.assertEqual(len(result["needs_choice"]), 1)
        self.assertEqual(result["needs_choice"][0]["menu_item_id"], self.pizza_id)
        self.assertTrue(result["needs_choice"][0]["needs_size"])

    def test_price_quote_with_only_a_needs_choice_line_does_not_price_but_still_reports_it(self) -> None:
        lines = [CartLineArgs(menu_item_id=self.pizza_id, quantity=1)]
        with self._session() as db:
            result = TOOLS["price_quote"].handler(
                db, self._scope(customer=self.customer), PriceQuoteArgs(lines=lines)
            )
        self.assertFalse(result["priced"])
        self.assertEqual(len(result["needs_choice"]), 1)
        self.assertEqual(result["needs_choice"][0]["menu_item_id"], self.pizza_id)

    # -- restaurant_info -------------------------------------------------

    def test_restaurant_info_reads_real_columns(self) -> None:
        with self._session() as db:
            result = TOOLS["restaurant_info"].handler(
                db, self._scope(location_id=self.branch_a_id), RestaurantInfoArgs()
            )
        self.assertTrue(result["branch_found"])
        self.assertEqual(result["branch_name"], "Branch A")
        self.assertEqual(result["phone_number"], "+911234500010")
        self.assertEqual(result["delivery_fee"], Decimal("30.00"))
        self.assertEqual(result["minimum_order_amount"], Decimal("100.00"))
        self.assertEqual(result["estimated_delivery_time_minutes"], 35)
        self.assertEqual(result["preparation_time_minutes"], 12)
        self.assertIn("10 Branch Road", result["address"])

    def test_restaurant_info_for_an_unknown_branch_degrades(self) -> None:
        with self._session() as db:
            result = TOOLS["restaurant_info"].handler(
                db,
                self._scope(location_id=uuid.uuid4()),
                RestaurantInfoArgs(),
            )
        self.assertFalse(result["branch_found"])

    # -- payment_options -------------------------------------------------

    def test_payment_options_reports_only_what_branch_a_enabled(self) -> None:
        with self._session() as db:
            result = TOOLS["payment_options"].handler(
                db, self._scope(location_id=self.branch_a_id), PaymentOptionsArgs()
            )
        self.assertEqual(result["payment_methods"], [PaymentMethod.COD.value])

    def test_payment_options_differs_for_branch_b(self) -> None:
        with self._session() as db:
            result = TOOLS["payment_options"].handler(
                db, self._scope(location_id=self.branch_b_id), PaymentOptionsArgs()
            )
        self.assertEqual(result["payment_methods"], [PaymentMethod.CARD.value])


if __name__ == "__main__":
    unittest.main()
