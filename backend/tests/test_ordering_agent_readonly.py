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
            )
            session.add(row)
            return row

        pad_thai = make_item(
            restaurant_id=restaurant.id, location_id=branch_a.id, name="Pad Thai", price="220.00"
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
        other_branch_item = make_item(
            restaurant_id=restaurant.id, location_id=branch_b.id, name="Tom Yum Soup", price="240.00"
        )
        session.flush()
        session.add(
            MenuItemSize(
                id=uuid.uuid4(),
                menu_item_id=sized_item.id,
                name="Regular",
                price=Decimal("180.00"),
            )
        )
        session.flush()

        cls.pad_thai_id = pad_thai.id
        cls.curry_id = curry.id
        cls.sized_item_id = sized_item.id
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

    def test_view_cart_drops_a_line_missing_a_required_size(self) -> None:
        """Fried Rice `has_sizes=True`; a line naming it with no size cannot
        be priced and must be dropped, not raise."""

        lines = [CartLineArgs(menu_item_id=self.sized_item_id, quantity=1)]
        with self._session() as db:
            result = TOOLS["view_cart"].handler(db, self._scope(), ViewCartArgs(lines=lines))
        self.assertEqual(result["lines"], [])
        self.assertEqual(result["dropped_line_count"], 1)

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
