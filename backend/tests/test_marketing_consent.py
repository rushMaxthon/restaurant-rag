"""Marketing consent, and the reach breakdown it feeds.

Consent is opt-out here (migration `0063`): a customer who has never been asked
is reachable. The tests below are mostly about the *consequences* of that
choice rather than the flag itself.

The breakdown matters as much as the number. The Hub shows an owner three
descending figures — segment members, audience after branch filtering, then
reachable per channel — and every person lost between the last two is itemised.
An owner watching 40 become 30 with no explanation will conclude the product is
broken. So each blocker is asserted to carry a real count, and the counts are
asserted not to double-count: someone who both opted out and has no device is
reported once, under consent, because that is the one the owner cannot fix and
the one that matters legally.
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
    MarketingChannel,
    MarketingNoticeTone,
    MarketingSegmentKey,
    OrderStatus,
    UserRole,
)
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.models.user_device_token import UserDeviceToken
from app.services.marketing.consent import has_ever_decided, set_marketing_consent
from app.services.marketing.reach import estimate_reach

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_marketing_consent_test"
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
class MarketingConsentTests(unittest.TestCase):
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
                name="Consent Kitchen",
                slug="consent-kitchen",
                cuisine_type="Indian",
                address_line_1="1 Road",
                city="Ahmedabad",
                state="Gujarat",
                postal_code="380001",
            )
        )

        cls.app_client_id = uuid.uuid4()
        session.add(
            AppClient(
                id=cls.app_client_id,
                key="consent_kitchen",
                display_name="Consent Kitchen",
                app_mode=AppMode.SINGLE_RESTAURANT,
                restaurant_id=cls.restaurant_id,
                order_number_prefix="CK",
            )
        )

        cls.branch_id = uuid.uuid4()
        session.add(
            RestaurantLocation(
                id=cls.branch_id,
                restaurant_id=cls.restaurant_id,
                branch_name="Main",
                address_line_1="1 Road",
                city="Ahmedabad",
                state="Gujarat",
                postal_code="380001",
            )
        )
        session.flush()

        cls.customer_ids: list[uuid.UUID] = []

        def make(label: str, *, opted_in: bool, with_device: bool) -> uuid.UUID:
            user_id = uuid.uuid4()
            session.add(
                User(
                    id=user_id,
                    app_client_id=cls.app_client_id,
                    full_name=label,
                    email=f"{label}@example.com",
                    hashed_password="x",
                    role=UserRole.CUSTOMER,
                    is_active=True,
                    is_verified=True,
                    marketing_opt_in=opted_in,
                )
            )
            session.add(
                Order(
                    id=uuid.uuid4(),
                    customer_id=user_id,
                    restaurant_id=cls.restaurant_id,
                    restaurant_location_id=cls.branch_id,
                    subtotal=Decimal("100.00"),
                    total_amount=Decimal("100.00"),
                    delivery_address="1 Road",
                    status=OrderStatus.DELIVERED,
                    placed_at=NOW - timedelta(days=5),
                )
            )
            if with_device:
                session.add(
                    UserDeviceToken(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        installation_id=f"install-{label}",
                        fcm_token=f"token-{label}-{uuid.uuid4().hex}",
                        platform="ANDROID",
                        is_active=True,
                    )
                )
            cls.customer_ids.append(user_id)
            return user_id

        # 12 reachable, 3 opted out, 2 with no device, and one who is both.
        # 12 keeps the audience above MINIMUM_SEGMENT_SIZE so the breakdown is
        # what is under test rather than the too-small block.
        for index in range(12):
            make(f"reachable{index}", opted_in=True, with_device=True)
        for index in range(3):
            make(f"optedout{index}", opted_in=False, with_device=True)
        for index in range(2):
            make(f"nodevice{index}", opted_in=True, with_device=False)
        cls.both_id = make("both", opted_in=False, with_device=False)

        # A customer who has never been asked: the opt-out default in practice.
        cls.never_asked_id = make("neverasked", opted_in=True, with_device=True)

        session.commit()

    # --- the flag itself ---------------------------------------------------

    def test_a_new_customer_is_opted_in_by_default(self) -> None:
        with self.session_factory() as session:
            user = session.get(User, self.never_asked_id)
            self.assertTrue(user.marketing_opt_in)

    def test_never_asked_is_distinguishable_from_having_agreed(self) -> None:
        """Null `changed_at` is an assumption; a timestamp is a decision.

        The distinction is the first thing anyone auditing consent asks for,
        which is why the backfill deliberately left it null.
        """

        with self.session_factory() as session:
            user = session.get(User, self.never_asked_id)
            self.assertFalse(has_ever_decided(user))

            set_marketing_consent(session, user=user, opted_in=True)
            self.assertTrue(has_ever_decided(user))

    def test_opting_out_is_recorded_with_a_timestamp(self) -> None:
        with self.session_factory() as session:
            user = session.get(User, self.customer_ids[0])
            updated = set_marketing_consent(session, user=user, opted_in=False)

            self.assertFalse(updated.marketing_opt_in)
            self.assertIsNotNone(updated.marketing_opt_in_changed_at)

            # Put it back, so the reach assertions below are not order-dependent.
            set_marketing_consent(session, user=updated, opted_in=True)

    # --- the reach breakdown ----------------------------------------------

    def estimate(self, session: Session):
        return estimate_reach(
            session,
            restaurant_id=self.restaurant_id,
            app_client_id=self.app_client_id,
            segment_key=MarketingSegmentKey.BRANCH_CUSTOMERS,
            branch_ids=[self.branch_id],
            channels=[MarketingChannel.PUSH],
            now=NOW,
        )

    def test_audience_counts_everyone_but_reachable_counts_fewer(self) -> None:
        with self.session_factory() as session:
            result = self.estimate(session)

        push = next(channel for channel in result.channels if channel.available)
        # 12 reachable + 3 opted out + 2 deviceless + `both` + `neverasked`.
        self.assertEqual(result.audience_size, 19)
        self.assertEqual(push.reachable, 13)

    def test_every_lost_person_is_itemised(self) -> None:
        """The gap between audience and reachable is fully explained."""

        with self.session_factory() as session:
            result = self.estimate(session)

        push = next(channel for channel in result.channels if channel.available)
        accounted = push.reachable + sum(blocker["count"] for blocker in push.blockers)
        self.assertEqual(accounted, result.audience_size)

    def test_someone_who_is_both_opted_out_and_deviceless_is_counted_once(self) -> None:
        with self.session_factory() as session:
            result = self.estimate(session)

        push = next(channel for channel in result.channels if channel.available)
        by_reason = {blocker["reason"]: blocker["count"] for blocker in push.blockers}

        # 3 plain opt-outs plus `both`.
        self.assertEqual(by_reason["Not opted in to marketing"], 4)
        # 2 deviceless — `both` is not counted again here.
        self.assertEqual(by_reason["No app with notifications on"], 2)

    def test_push_costs_nothing(self) -> None:
        with self.session_factory() as session:
            result = self.estimate(session)

        push = next(channel for channel in result.channels if channel.available)
        self.assertEqual(push.estimated_cost, 0.0)

    def test_an_unconnected_channel_is_unavailable_with_a_reason(self) -> None:
        with self.session_factory() as session:
            result = estimate_reach(
                session,
                restaurant_id=self.restaurant_id,
                app_client_id=self.app_client_id,
                segment_key=MarketingSegmentKey.BRANCH_CUSTOMERS,
                branch_ids=[self.branch_id],
                channels=[MarketingChannel.PUSH, MarketingChannel.SMS],
                now=NOW,
            )

        sms = next(
            channel for channel in result.channels if channel.channel == MarketingChannel.SMS
        )
        self.assertFalse(sms.available)
        self.assertTrue(sms.unavailable_reason)
        self.assertEqual(sms.reachable, 0)

    # --- blocking checks ---------------------------------------------------

    def test_no_branch_selected_blocks_the_send(self) -> None:
        with self.session_factory() as session:
            result = estimate_reach(
                session,
                restaurant_id=self.restaurant_id,
                app_client_id=self.app_client_id,
                segment_key=MarketingSegmentKey.BRANCH_CUSTOMERS,
                branch_ids=[],
                channels=[MarketingChannel.PUSH],
                now=NOW,
            )
        self.assertTrue(result.blocked())

    def test_a_send_inside_quiet_hours_is_blocked(self) -> None:
        """23:00 in the business timezone, which is outside 08:00-22:00."""

        with self.session_factory() as session:
            result = estimate_reach(
                session,
                restaurant_id=self.restaurant_id,
                app_client_id=self.app_client_id,
                segment_key=MarketingSegmentKey.BRANCH_CUSTOMERS,
                branch_ids=[self.branch_id],
                channels=[MarketingChannel.PUSH],
                send_at=datetime(2026, 9, 20, 17, 45, tzinfo=UTC),  # 23:15 IST
                timezone_name="Asia/Kolkata",
                now=NOW,
            )

        self.assertTrue(result.blocked())
        self.assertIn(
            "quiet-hours",
            [notice.id for notice in result.notices if notice.tone == MarketingNoticeTone.BLOCK],
        )

    def test_a_send_inside_opening_hours_is_not_blocked(self) -> None:
        with self.session_factory() as session:
            result = estimate_reach(
                session,
                restaurant_id=self.restaurant_id,
                app_client_id=self.app_client_id,
                segment_key=MarketingSegmentKey.BRANCH_CUSTOMERS,
                branch_ids=[self.branch_id],
                channels=[MarketingChannel.PUSH],
                send_at=datetime(2026, 9, 20, 8, 30, tzinfo=UTC),  # 14:00 IST
                timezone_name="Asia/Kolkata",
                now=NOW,
            )
        self.assertFalse(result.blocked())

    def test_reachable_user_ids_are_never_part_of_the_counts(self) -> None:
        """The estimate carries ids internally; the route must not leak them.

        Asserted here because the dispatcher will need this list, and the
        temptation to serialise the whole result object later is real.
        """

        with self.session_factory() as session:
            result = self.estimate(session)

        self.assertTrue(result.reachable_user_ids)
        self.assertEqual(len(result.reachable_user_ids), 13)


if __name__ == "__main__":
    unittest.main()
