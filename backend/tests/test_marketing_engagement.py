"""What the customer did with a campaign, and how they stop receiving them.

Two halves of the same gap. `opened_count` and `clicked_count` were read by the
campaign report and written by nothing, so every campaign appeared to lose its
whole audience between "delivered" and "opened" — the one number an owner uses
to judge their copy. And a marketing push had no way out of it at all.

The assertions here are mostly about the two ways this goes wrong quietly:

* **Double counting.** The counters summarise distinct people. A phone that
  reports the same open twice — which phones do — must not make a campaign look
  twice as engaging as it was.
* **Counting strangers.** The endpoint takes a campaign id, so without a
  recipient check any signed-in customer could move any restaurant's numbers by
  posting ids at it.

The unsubscribe tests pin the thing that is easy to get wrong for a whole
different reason: a GET that opts someone out is silently triggered by mail
clients and link scanners, which is why the mutation lives on POST.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.app_client import AppClient
from app.models.base import Base
from app.models.enums import (
    AppMode,
    CampaignRecipientState,
    PushNotificationAudience,
    PushNotificationCampaignKind,
    PushNotificationEventType,
    UserRole,
)
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.push_notification_campaign_recipient import (
    PushNotificationCampaignRecipient,
)
from app.models.push_notification_event import PushNotificationEvent
from app.models.user import User
from app.services.marketing import unsubscribe as unsubscribe_service
from app.services.marketing.engagement import EngagementRefused, record_engagement

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_marketing_engagement_test"
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


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
class MarketingEngagementTests(unittest.TestCase):
    engine = None
    session_factory = None
    campaign_id: uuid.UUID
    recipient_id: uuid.UUID
    stranger_id: uuid.UUID

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
        # A fresh campaign per test: the counters are the subject, so they must
        # not carry over.
        with self.session_factory() as session:
            session.execute(text("DELETE FROM push_notification_events"))
            session.execute(text("DELETE FROM push_notification_campaign_recipients"))
            session.execute(text("DELETE FROM push_notification_campaigns"))
            session.execute(text("DELETE FROM users"))
            session.execute(text("DELETE FROM app_clients"))
            session.commit()
            self._seed(session)

    def _seed(self, session: Session) -> None:
        app_client = AppClient(
            id=uuid.uuid4(),
            key="engagement-test",
            display_name="Engagement Test",
            app_mode=AppMode.SINGLE_RESTAURANT,
        )
        session.add(app_client)

        recipient = User(
            id=uuid.uuid4(),
            app_client_id=app_client.id,
            full_name="Reachable Customer",
            email="reachable@example.com",
            hashed_password="x",
            role=UserRole.CUSTOMER,
            marketing_opt_in=True,
        )
        stranger = User(
            id=uuid.uuid4(),
            app_client_id=app_client.id,
            full_name="Someone Else",
            email="stranger@example.com",
            hashed_password="x",
            role=UserRole.CUSTOMER,
            marketing_opt_in=True,
        )
        session.add_all([recipient, stranger])

        campaign = PushNotificationCampaign(
            id=uuid.uuid4(),
            audience=PushNotificationAudience.SEGMENT,
            kind=PushNotificationCampaignKind.MARKETING,
            title="We miss you",
            message="Come back",
        )
        session.add(campaign)
        session.flush()

        session.add(
            PushNotificationCampaignRecipient(
                campaign_id=campaign.id,
                user_id=recipient.id,
                state=CampaignRecipientState.SENT,
                sent_at=NOW,
                device_token_count=1,
            )
        )
        session.commit()

        self.campaign_id = campaign.id
        self.recipient_id = recipient.id
        self.stranger_id = stranger.id

    def _user(self, session: Session, user_id: uuid.UUID) -> User:
        return session.get(User, user_id)

    def _campaign(self, session: Session) -> PushNotificationCampaign:
        return session.get(PushNotificationCampaign, self.campaign_id)

    # --- counting ---------------------------------------------------------

    def test_an_open_is_counted_once(self) -> None:
        with self.session_factory() as session:
            counted = record_engagement(
                session,
                campaign_id=self.campaign_id,
                user=self._user(session, self.recipient_id),
                event_type=PushNotificationEventType.OPENED,
            )
            self.assertTrue(counted)
            self.assertEqual(self._campaign(session).opened_count, 1)

    def test_reopening_does_not_inflate_the_count(self) -> None:
        """Phones re-report opens. A summary of distinct people must not move."""

        with self.session_factory() as session:
            user = self._user(session, self.recipient_id)
            record_engagement(
                session,
                campaign_id=self.campaign_id,
                user=user,
                event_type=PushNotificationEventType.OPENED,
            )
            again = record_engagement(
                session,
                campaign_id=self.campaign_id,
                user=user,
                event_type=PushNotificationEventType.OPENED,
            )
            self.assertFalse(again)
            self.assertEqual(self._campaign(session).opened_count, 1)

    def test_open_and_click_are_counted_separately(self) -> None:
        with self.session_factory() as session:
            user = self._user(session, self.recipient_id)
            for event in (
                PushNotificationEventType.OPENED,
                PushNotificationEventType.CLICKED,
            ):
                record_engagement(
                    session,
                    campaign_id=self.campaign_id,
                    user=user,
                    event_type=event,
                )
            campaign = self._campaign(session)
            self.assertEqual(campaign.opened_count, 1)
            self.assertEqual(campaign.clicked_count, 1)

    def test_someone_who_never_received_it_is_refused(self) -> None:
        """Otherwise any signed-in customer could move any campaign's numbers."""

        with self.session_factory() as session:
            with self.assertRaises(EngagementRefused):
                record_engagement(
                    session,
                    campaign_id=self.campaign_id,
                    user=self._user(session, self.stranger_id),
                    event_type=PushNotificationEventType.OPENED,
                )
            self.assertEqual(self._campaign(session).opened_count, 0)

    def test_a_device_cannot_claim_a_delivery(self) -> None:
        """SENT and DELIVERED are the server's own record, not a client's."""

        with self.session_factory() as session:
            with self.assertRaises(EngagementRefused):
                record_engagement(
                    session,
                    campaign_id=self.campaign_id,
                    user=self._user(session, self.recipient_id),
                    event_type=PushNotificationEventType.DELIVERED,
                )

    def test_an_unsubscribe_is_attributed_to_its_campaign(self) -> None:
        """An opt-out rate per campaign is how copy is judged to have cost the list."""

        with self.session_factory() as session:
            record_engagement(
                session,
                campaign_id=self.campaign_id,
                user=self._user(session, self.recipient_id),
                event_type=PushNotificationEventType.UNSUBSCRIBED,
            )
            event = session.scalar(
                select(PushNotificationEvent).where(
                    PushNotificationEvent.campaign_id == self.campaign_id,
                    PushNotificationEvent.event_type
                    == PushNotificationEventType.UNSUBSCRIBED,
                )
            )
            self.assertIsNotNone(event)
            self.assertEqual(event.user_id, self.recipient_id)
            # It has no counter of its own; the opt-out lives on the user.
            campaign = self._campaign(session)
            self.assertEqual(campaign.opened_count, 0)
            self.assertEqual(campaign.clicked_count, 0)

    # --- the unsubscribe token -------------------------------------------

    def test_a_token_round_trips(self) -> None:
        token = unsubscribe_service.make_token(self.recipient_id, self.campaign_id)
        self.assertEqual(
            unsubscribe_service.read_token(token),
            (self.recipient_id, self.campaign_id),
        )

    def test_a_tampered_token_is_refused(self) -> None:
        """The signature is the whole credential — swapping the user must fail."""

        token = unsubscribe_service.make_token(self.recipient_id, self.campaign_id)
        forged = unsubscribe_service.make_token(self.stranger_id, self.campaign_id)
        # Someone else's body with this token's signature.
        spliced = f"{forged.split('.')[0]}.{forged.split('.')[1]}.{token.split('.')[2]}"
        self.assertIsNone(unsubscribe_service.read_token(spliced))

    def test_rubbish_is_refused_rather_than_raising(self) -> None:
        for value in ("", "not-a-token", "a.b.c", "x" * 400):
            self.assertIsNone(unsubscribe_service.read_token(value))

    def test_no_public_base_url_means_no_link_rather_than_a_broken_one(self) -> None:
        """A link to a host nobody can reach looks like an opt-out that failed."""

        original = unsubscribe_service.settings.public_base_url
        try:
            unsubscribe_service.settings.public_base_url = ""
            self.assertIsNone(
                unsubscribe_service.unsubscribe_url(self.recipient_id, self.campaign_id)
            )
            unsubscribe_service.settings.public_base_url = "https://example.test"
            url = unsubscribe_service.unsubscribe_url(
                self.recipient_id, self.campaign_id
            )
            self.assertIsNotNone(url)
            self.assertIn("/marketing/unsubscribe/", url)
        finally:
            unsubscribe_service.settings.public_base_url = original


if __name__ == "__main__":
    unittest.main()
