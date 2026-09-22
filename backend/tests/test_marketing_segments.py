"""Who ends up in a marketing segment, and who must never.

Three questions this file exists to answer, each of which was a real design
decision rather than an implementation detail:

1. **Does each segment select the people its owner-facing sentence promises?**
   "Ordered 3 or more times, but nothing in the last 30 days" is a contract
   with the owner. A customer with two orders, or one who ordered last week,
   appearing in a winback campaign is a wrong message to a real person.

2. **Can a campaign ever reach another app's customers?** The same phone in the
   Marketplace app and in a single-restaurant app are two accounts
   (`docs/per-app-identity.md`). A segment that ignored `app_client_id` would
   push one restaurant's promotion into the platform app's users.

3. **Does opting out remove someone from a segment?** It must not. Consent is
   applied at the reach step so the owner can be shown where their audience
   went. Folding it into membership makes people vanish with no explanation —
   see `consent.audience_base_conditions`.

Cancelled orders are seeded deliberately throughout: they must never make
someone a regular.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.app_client import AppClient
from app.models.base import Base
from app.models.enums import (
    AppMode,
    MarketingSegmentKey,
    OrderStatus,
    UserRole,
)
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.marketing.segments import (
    SegmentUnavailable,
    list_segment_member_ids,
    resolve_marketing_app_client_id,
)

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_marketing_segments_test"
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


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
class MarketingSegmentTests(unittest.TestCase):
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

    # --- seeding ----------------------------------------------------------

    @classmethod
    def _seed(cls, session: Session) -> None:
        owner = User(
            id=uuid.uuid4(),
            app_client_id=None,
            full_name="Owner",
            email="owner@example.com",
            hashed_password="x",
            role=UserRole.OWNER,
            is_active=True,
            is_verified=True,
        )
        session.add(owner)
        session.flush()

        cls.restaurant_id = uuid.uuid4()
        session.add(
            Restaurant(
                id=cls.restaurant_id,
                owner_id=owner.id,
                name="Test Kitchen",
                slug="test-kitchen",
                cuisine_type="Indian",
                address_line_1="1 Road",
                city="Ahmedabad",
                state="Gujarat",
                postal_code="380001",
            )
        )

        # The restaurant's own app, and the platform marketplace app. The
        # marketplace client exists purely so the scoping assertion has
        # something real to fail against.
        cls.app_client_id = uuid.uuid4()
        cls.marketplace_id = uuid.uuid4()
        session.add_all(
            [
                AppClient(
                    id=cls.app_client_id,
                    key="test_kitchen",
                    display_name="Test Kitchen",
                    app_mode=AppMode.SINGLE_RESTAURANT,
                    restaurant_id=cls.restaurant_id,
                    order_number_prefix="TK",
                ),
                AppClient(
                    id=cls.marketplace_id,
                    key="marketplace",
                    display_name="QuickBite",
                    app_mode=AppMode.MARKETPLACE,
                    restaurant_id=None,
                    order_number_prefix="MP",
                ),
            ]
        )

        cls.branch_a = uuid.uuid4()
        cls.branch_b = uuid.uuid4()
        for branch_id, name in ((cls.branch_a, "Branch A"), (cls.branch_b, "Branch B")):
            session.add(
                RestaurantLocation(
                    id=branch_id,
                    restaurant_id=cls.restaurant_id,
                    branch_name=name,
                    address_line_1="1 Road",
                    city="Ahmedabad",
                    state="Gujarat",
                    postal_code="380001",
                )
            )
        session.flush()

        cls.users: dict[str, uuid.UUID] = {}

        def make_customer(
            label: str,
            *,
            app_client_id: uuid.UUID | None = None,
            opted_in: bool = True,
            verified: bool = True,
            active: bool = True,
        ) -> uuid.UUID:
            user_id = uuid.uuid4()
            session.add(
                User(
                    id=user_id,
                    app_client_id=app_client_id or cls.app_client_id,
                    full_name=label,
                    email=f"{label}@example.com",
                    hashed_password="x",
                    role=UserRole.CUSTOMER,
                    is_active=active,
                    is_verified=verified,
                    marketing_opt_in=opted_in,
                )
            )
            cls.users[label] = user_id
            return user_id

        def order(
            customer_id: uuid.UUID,
            *,
            days_ago: float,
            amount: str = "100.00",
            branch_id: uuid.UUID | None = None,
            status: OrderStatus = OrderStatus.DELIVERED,
        ) -> None:
            session.add(
                Order(
                    id=uuid.uuid4(),
                    customer_id=customer_id,
                    restaurant_id=cls.restaurant_id,
                    restaurant_location_id=branch_id or cls.branch_a,
                    subtotal=Decimal(amount),
                    total_amount=Decimal(amount),
                    delivery_address="1 Road",
                    status=status,
                    placed_at=NOW - timedelta(days=days_ago),
                )
            )

        # lapsed: 3 orders, none inside 30 days
        lapsed = make_customer("lapsed")
        for days in (95, 80, 65):
            order(lapsed, days_ago=days)

        # not lapsed: 3 orders but one is recent
        recent_regular = make_customer("recent_regular")
        for days in (95, 80, 3):
            order(recent_regular, days_ago=days)

        # two orders only: below the "regular" threshold even though quiet
        quiet_pair = make_customer("quiet_pair")
        for days in (95, 80):
            order(quiet_pair, days_ago=days)

        # three CANCELLED orders: must not count as a regular at all
        cancelled_only = make_customer("cancelled_only")
        for days in (95, 80, 65):
            order(cancelled_only, days_ago=days, status=OrderStatus.CANCELLED)

        # exactly one order, inside 60 days
        first_timer = make_customer("first_timer")
        order(first_timer, days_ago=10)

        # exactly one order, too old to be a first-time buyer
        old_first_timer = make_customer("old_first_timer")
        order(old_first_timer, days_ago=200)

        # big spender: high AOV, recent, also the VIP by 90-day spend
        whale = make_customer("whale")
        for days in (5, 15, 25):
            order(whale, days_ago=days, amount="900.00")

        # weekend-only: every order on a Saturday (NOW is a Saturday)
        weekender = make_customer("weekender")
        for days in (7, 14, 21):
            order(weekender, days_ago=days, amount="50.00")

        # weekday diner: orders spread across the week
        weekdayer = make_customer("weekdayer")
        for days in (9, 10, 11):
            order(weekdayer, days_ago=days, amount="50.00")

        # branch B only
        branch_b_customer = make_customer("branch_b_customer")
        order(branch_b_customer, days_ago=12, branch_id=cls.branch_b)

        # registered, never ordered
        make_customer("never_ordered")

        # opted out, but otherwise a textbook lapsed regular
        opted_out = make_customer("opted_out", opted_in=False)
        for days in (95, 80, 65):
            order(opted_out, days_ago=days)

        # unverified, otherwise a lapsed regular
        unverified = make_customer("unverified", verified=False)
        for days in (95, 80, 65):
            order(unverified, days_ago=days)

        # another app's customer, otherwise a textbook lapsed regular
        other_app = make_customer("other_app", app_client_id=cls.marketplace_id)
        for days in (95, 80, 65):
            order(other_app, days_ago=days)

        session.commit()

    # --- helpers ----------------------------------------------------------

    def members(
        self,
        key: MarketingSegmentKey,
        *,
        branch_ids: list[uuid.UUID] | None = None,
    ) -> set[str]:
        with self.session_factory() as session:
            ids = list_segment_member_ids(
                session,
                key=key,
                restaurant_id=self.restaurant_id,
                app_client_id=self.app_client_id,
                branch_ids=branch_ids,
                now=NOW,
            )
        by_id = {user_id: label for label, user_id in self.users.items()}
        return {by_id[user_id] for user_id in ids if user_id in by_id}

    # --- tenancy ----------------------------------------------------------

    def test_another_apps_customer_is_never_in_a_segment(self) -> None:
        """The whole per-app identity rule, as one assertion.

        `other_app` is seeded to match LAPSED_REGULARS perfectly and differs
        from `lapsed` in exactly one column: `app_client_id`.
        """

        for key in MarketingSegmentKey:
            with self.subTest(segment=key.value):
                self.assertNotIn("other_app", self.members(key))

    def test_app_client_resolves_to_the_restaurants_own_app(self) -> None:
        with self.session_factory() as session:
            resolved = resolve_marketing_app_client_id(session, self.restaurant_id)
        self.assertEqual(resolved, self.app_client_id)
        self.assertNotEqual(resolved, self.marketplace_id)

    def test_restaurant_without_its_own_app_raises(self) -> None:
        """Explicitly unavailable, not silently empty.

        An owner whose restaurant has no app needs to be told that, not shown
        an audience of zero they will try to fix by picking another segment.
        """

        with self.session_factory() as session:
            with self.assertRaises(SegmentUnavailable):
                resolve_marketing_app_client_id(session, uuid.uuid4())

    # --- consent ----------------------------------------------------------

    def test_opting_out_does_not_remove_someone_from_their_segment(self) -> None:
        """Consent belongs to reach, not to membership.

        If this ever flips, the Hub's reach breakdown loses the "not opted in
        to marketing" line — the number would simply be smaller, with nothing
        to explain it.
        """

        self.assertIn("opted_out", self.members(MarketingSegmentKey.LAPSED_REGULARS))

    def test_unverified_customer_is_excluded(self) -> None:
        self.assertNotIn("unverified", self.members(MarketingSegmentKey.LAPSED_REGULARS))

    # --- individual segments ----------------------------------------------

    def test_lapsed_regulars(self) -> None:
        members = self.members(MarketingSegmentKey.LAPSED_REGULARS)
        self.assertIn("lapsed", members)
        # Ordered recently, so not lapsed however many orders they have.
        self.assertNotIn("recent_regular", members)
        # Quiet, but two orders is not a regular.
        self.assertNotIn("quiet_pair", members)
        # Three cancelled orders is not three orders.
        self.assertNotIn("cancelled_only", members)

    def test_first_time_buyers(self) -> None:
        members = self.members(MarketingSegmentKey.FIRST_TIME_BUYERS)
        self.assertIn("first_timer", members)
        self.assertNotIn("old_first_timer", members)
        self.assertNotIn("lapsed", members)

    def test_vips_are_the_top_of_the_ninety_day_spend(self) -> None:
        members = self.members(MarketingSegmentKey.VIPS)
        self.assertIn("whale", members)
        self.assertNotIn("weekender", members)

    def test_big_spenders_beat_the_median_average_order_value(self) -> None:
        members = self.members(MarketingSegmentKey.BIG_SPENDERS)
        self.assertIn("whale", members)
        self.assertNotIn("weekender", members)

    def test_weekend_diners_are_concentrated_not_merely_present(self) -> None:
        members = self.members(MarketingSegmentKey.WEEKEND_DINERS)
        self.assertIn("weekender", members)
        self.assertNotIn("weekdayer", members)

    def test_branch_customers_respects_branch_filtering(self) -> None:
        only_b = self.members(
            MarketingSegmentKey.BRANCH_CUSTOMERS, branch_ids=[self.branch_b]
        )
        self.assertIn("branch_b_customer", only_b)
        self.assertNotIn("lapsed", only_b)

        both = self.members(
            MarketingSegmentKey.BRANCH_CUSTOMERS,
            branch_ids=[self.branch_a, self.branch_b],
        )
        self.assertIn("branch_b_customer", both)
        self.assertIn("lapsed", both)

    def test_never_ordered_ignores_branch_filtering(self) -> None:
        """The one segment where branch filtering must not apply.

        Filtering it would mean "never ordered from Branch B", which includes
        every loyal Branch A regular — the opposite of who the owner means.
        """

        filtered = self.members(
            MarketingSegmentKey.NEVER_ORDERED, branch_ids=[self.branch_b]
        )
        self.assertIn("never_ordered", filtered)
        self.assertNotIn("lapsed", filtered)
        self.assertNotIn("branch_b_customer", filtered)

    def test_never_ordered_excludes_anyone_with_a_counted_order(self) -> None:
        members = self.members(MarketingSegmentKey.NEVER_ORDERED)
        self.assertIn("never_ordered", members)
        # Only ever cancelled, so they have never actually bought anything.
        self.assertIn("cancelled_only", members)
        self.assertNotIn("first_timer", members)


if __name__ == "__main__":
    unittest.main()
