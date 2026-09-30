"""Sending, and the things a send must never do twice.

Two of these tests exist because the behaviour they pin down was wrong when
first written, and the failure was only visible against a real database:

* **A recipient is written once per customer.** The first version looked the
  row up with a query each time it was needed. A row added to the session but
  not yet flushed is invisible to that query, so the same customer got a second
  INSERT and the unique constraint failed the entire send at commit — after
  Firebase had already been called.

* **A dispatch that raises must leave the campaign FAILED, not SENDING.**
  SENDING only leads to SENT or FAILED, both written by the dispatcher, so a
  campaign stranded there can never be retried and never be cancelled. The
  handler that puts it down has to survive a session left dirty by the very
  exception it is handling.

The dry-run split is the third thing worth pinning: with dispatch switched off
the audience is still computed and recipient rows are still written, so an
owner can inspect exactly who a send would have reached. A dry run that skipped
the work would prove nothing.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.base import Base
from app.models.enums import (
    CampaignRecipientState,
    MarketingChannel,
    MarketingSegmentKey,
    PushNotificationAudience,
    PushNotificationCampaignKind,
    PushNotificationCampaignStatus,
    UserRole,
)
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.push_notification_campaign_recipient import (
    PushNotificationCampaignRecipient,
)
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.models.user_device_token import UserDeviceToken
from app.services.marketing import campaigns as campaign_service
from app.services.marketing import dispatch as dispatch_module
from app.services.marketing.providers import push as push_provider_module
from app.services.marketing.dispatch import dispatch_campaign, render_merge_fields

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_marketing_dispatch_test"
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
    except Exception:  # noqa: BLE001
        return False
    finally:
        if engine is not None:
            engine.dispose()


class MergeFieldTests(unittest.TestCase):
    """No raw token, and no "Hi None", ever reaches a real person."""

    def test_values_are_substituted(self) -> None:
        self.assertEqual(
            render_merge_fields("Hi {first_name} at {branch}", first_name="Ada", branch="Main"),
            "Hi Ada at Main",
        )

    def test_a_missing_first_name_falls_back_rather_than_rendering_none(self) -> None:
        self.assertEqual(
            render_merge_fields("Hi {first_name}", first_name=None, branch=None),
            "Hi there",
        )

    def test_a_blank_name_is_treated_as_missing(self) -> None:
        self.assertEqual(
            render_merge_fields("Hi {first_name}", first_name="   ", branch=None),
            "Hi there",
        )

    def test_the_fallbacks_match_the_admin_apps(self) -> None:
        """The preview the owner approved has to be the message that goes out."""

        self.assertEqual(dispatch_module.MERGE_FALLBACKS["first_name"], "there")
        self.assertEqual(dispatch_module.MERGE_FALLBACKS["branch"], "our kitchen")


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class MarketingDispatchTests(unittest.TestCase):
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

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.engine is not None:
            cls.engine.dispose()
        admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin_engine.dispose()

    def setUp(self) -> None:
        self.session: Session = self.session_factory()
        for table in (
            "push_notification_campaign_recipients",
            "user_device_tokens",
            "push_notification_campaigns",
            "restaurant_locations",
            "restaurants",
            "users",
        ):
            self.session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
        self.session.commit()

        self.owner_id = uuid.uuid4()
        self.restaurant_id = uuid.uuid4()
        self.branch_id = uuid.uuid4()
        self.session.add(
            User(
                id=self.owner_id,
                app_client_id=None,
                full_name="Owner One",
                email="owner@example.com",
                hashed_password="x",
                role=UserRole.OWNER,
                is_active=True,
                is_verified=True,
            )
        )
        self.session.flush()
        self.session.add(
            Restaurant(
                id=self.restaurant_id,
                owner_id=self.owner_id,
                name="Restaurant One",
                slug="one",
                cuisine_type="Indian",
                address_line_1="1 Road",
                city="Ahmedabad",
                state="Gujarat",
                postal_code="380001",
            )
        )
        self.session.add(
            RestaurantLocation(
                id=self.branch_id,
                restaurant_id=self.restaurant_id,
                branch_name="Main",
                address_line_1="1 Road",
                city="Ahmedabad",
                state="Gujarat",
                postal_code="380001",
            )
        )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()

    def _campaign(self, status=PushNotificationCampaignStatus.SENDING):
        campaign = PushNotificationCampaign(
            id=uuid.uuid4(),
            restaurant_id=self.restaurant_id,
            kind=PushNotificationCampaignKind.MARKETING,
            audience=PushNotificationAudience.SEGMENT,
            title="Hi {first_name}",
            message="Come back to {branch}",
            status=status,
            name="Winback",
            segment_key=MarketingSegmentKey.LAPSED_REGULARS.value,
            branch_ids=[str(self.branch_id)],
            channels=[MarketingChannel.PUSH.value],
        )
        self.session.add(campaign)
        self.session.commit()
        return campaign

    def _audience(self, count: int) -> list[uuid.UUID]:
        ids = []
        for index in range(count):
            customer_id = uuid.uuid4()
            self.session.add(
                User(
                    id=customer_id,
                    app_client_id=None,
                    full_name=f"Customer {index}",
                    email=f"customer{index}@example.com",
                    hashed_password="x",
                    role=UserRole.ADMIN,
                    is_active=True,
                    is_verified=True,
                )
            )
            self.session.flush()
            self.session.add(
                UserDeviceToken(
                    id=uuid.uuid4(),
                    user_id=customer_id,
                    fcm_token=f"token-{index}",
                    installation_id=f"install-{index}",
                    platform="ANDROID",
                    is_active=True,
                )
            )
            ids.append(customer_id)
        self.session.commit()
        return ids

    # --- the dry run ------------------------------------------------------

    def test_a_dry_run_writes_real_recipients_and_calls_nothing(self) -> None:
        campaign = self._campaign()
        audience = self._audience(3)

        with mock.patch.object(dispatch_module, "_recompute_audience", return_value=audience), \
             mock.patch.object(dispatch_module.settings, "enable_marketing_dispatch", False), \
             mock.patch.object(push_provider_module, "_get_firebase_app") as firebase:
            result = dispatch_campaign(self.session, campaign=campaign, now=NOW)

        # Firebase moved into the push provider when dispatch stopped being
        # Firebase code; the assertion is unchanged in intent — a dry run runs
        # every step up to the wire and does not touch the wire.
        firebase.assert_not_called()
        self.assertTrue(result.dry_run)
        self.assertEqual(result.sent, 3)
        self.assertEqual(campaign.status, PushNotificationCampaignStatus.SENT)

        rows = self.session.scalars(
            select(PushNotificationCampaignRecipient).where(
                PushNotificationCampaignRecipient.campaign_id == campaign.id
            )
        ).all()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.state is CampaignRecipientState.SENT for row in rows))
        self.assertTrue(all(row.sent_at is not None for row in rows))

    def test_a_customer_with_no_device_is_skipped_not_failed(self) -> None:
        """Nothing was attempted and nothing went wrong."""

        campaign = self._campaign()
        no_device = uuid.uuid4()
        self.session.add(
            User(
                id=no_device,
                app_client_id=None,
                full_name="No Device",
                email="nodevice@example.com",
                hashed_password="x",
                role=UserRole.ADMIN,
                is_active=True,
                is_verified=True,
            )
        )
        self.session.commit()

        with mock.patch.object(dispatch_module, "_recompute_audience", return_value=[no_device]), \
             mock.patch.object(dispatch_module.settings, "enable_marketing_dispatch", False):
            result = dispatch_campaign(self.session, campaign=campaign, now=NOW)

        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.failed, 0)
        row = self.session.scalars(
            select(PushNotificationCampaignRecipient).where(
                PushNotificationCampaignRecipient.campaign_id == campaign.id
            )
        ).one()
        self.assertIs(row.state, CampaignRecipientState.SKIPPED)
        self.assertEqual(row.failure_reason, "No active device")

    # --- idempotency ------------------------------------------------------

    def test_one_recipient_row_per_customer_however_many_batches(self) -> None:
        """The unique constraint used to fail the whole send at commit."""

        campaign = self._campaign()
        audience = self._audience(4)

        with mock.patch.object(dispatch_module, "_recompute_audience", return_value=audience), \
             mock.patch.object(dispatch_module.settings, "enable_marketing_dispatch", False), \
             mock.patch.object(dispatch_module.settings, "marketing_dispatch_batch_size", 1):
            dispatch_campaign(self.session, campaign=campaign, now=NOW)

        count = self.session.scalar(
            select(text("count(*)")).select_from(
                text("push_notification_campaign_recipients")
            )
        )
        self.assertEqual(count, 4)

    def test_a_retry_does_not_message_people_the_first_attempt_reached(self) -> None:
        campaign = self._campaign()
        audience = self._audience(3)

        with mock.patch.object(dispatch_module, "_recompute_audience", return_value=audience), \
             mock.patch.object(dispatch_module.settings, "enable_marketing_dispatch", False):
            dispatch_campaign(self.session, campaign=campaign, now=NOW)

        # A second run over the same audience: everyone is already SENT, so
        # nothing is dispatched again and no duplicate rows appear.
        campaign.status = PushNotificationCampaignStatus.SENDING
        self.session.commit()
        with mock.patch.object(dispatch_module, "_recompute_audience", return_value=audience), \
             mock.patch.object(dispatch_module.settings, "enable_marketing_dispatch", False):
            second = dispatch_campaign(self.session, campaign=campaign, now=NOW)

        self.assertEqual(second.sent, 3)
        rows = self.session.scalars(
            select(PushNotificationCampaignRecipient).where(
                PushNotificationCampaignRecipient.campaign_id == campaign.id
            )
        ).all()
        self.assertEqual(len(rows), 3)

    # --- failure handling -------------------------------------------------

    def test_an_empty_audience_is_reported_rather_than_failed(self) -> None:
        """Nobody qualifying today is an answer, not an error to retry."""

        campaign = self._campaign()
        with mock.patch.object(dispatch_module, "_recompute_audience", return_value=[]):
            result = dispatch_campaign(self.session, campaign=campaign, now=NOW)

        self.assertEqual(result.status, PushNotificationCampaignStatus.SENT)
        self.assertEqual(result.audience, 0)
        self.assertIn("Nobody matched", campaign.last_error)

    def test_a_campaign_is_never_stranded_in_sending(self) -> None:
        campaign = self._campaign()
        campaign_service.mark_send_failed(self.session, campaign=campaign, reason="boom")

        self.assertIs(campaign.status, PushNotificationCampaignStatus.FAILED)
        self.assertEqual(campaign.last_error, "boom")
        self.assertIsNone(campaign.sending_progress)

    def test_marking_failed_survives_a_session_left_dirty_by_the_error(self) -> None:
        """The handler runs while the session is unusable — that is the point."""

        campaign = self._campaign()
        self.session.add(
            PushNotificationCampaignRecipient(
                campaign_id=campaign.id, user_id=uuid.uuid4()  # no such user: FK violation
            )
        )
        with self.assertRaises(Exception):
            self.session.commit()

        campaign_service.mark_send_failed(self.session, campaign=campaign, reason="boom")
        self.assertIs(campaign.status, PushNotificationCampaignStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
