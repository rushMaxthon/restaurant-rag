"""The promises the Hub makes to customers and to owners' wallets.

Four groups, and three of them exist because the product was already making
the promise and not keeping it:

* **The weekly frequency cap counted nothing.** It read
  `push_notification_events` of type SENT or DELIVERED, and the only writer of
  that table records OPENED, CLICKED and UNSUBSCRIBED. The query matched zero
  rows, so the cap suppressed nobody — while the schedule screen told owners
  "anyone who already heard from you this week is left out automatically".

* **"Reply STOP to opt out" was a footer with nothing behind it.** Every SMS
  and every WhatsApp template carried the line and no inbound path read the
  replies. A customer who does exactly what they were told and keeps getting
  messages has been misled, and the restaurant answers for it.

* **Nothing capped spend.** The reach estimate showed a cost and no rule ever
  refused one. Widening a segment from 400 people to 9,000 changes one number
  on screen and multiplies the bill.

The fourth is the retry path, which the backend always allowed and the UI
never offered: FAILED -> SENDING is a legal transition and recipient rows are
what make a second attempt safe.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
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
    MarketingNoticeTone,
    PushNotificationAudience,
    PushNotificationCampaignKind,
    PushNotificationCampaignStatus,
    PushNotificationEventType,
    UserRole,
)
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.push_notification_campaign_recipient import (
    PushNotificationCampaignRecipient,
)
from app.models.push_notification_event import PushNotificationEvent
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.marketing import campaigns as campaign_service
from app.services.marketing import reach as reach_module
from app.services.marketing.optout import (
    apply_reply,
    is_start_word,
    is_stop_word,
)
from app.services.marketing.reach import (
    campaign_spend,
    recently_messaged_user_ids,
    spend_this_month,
)

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_marketing_guardrails_test"
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
    except Exception:  # noqa: BLE001
        return False
    finally:
        if engine is not None:
            engine.dispose()


class StopWordTests(unittest.TestCase):
    """What a customer types when they mean stop."""

    def test_the_words_carriers_oblige_us_to_honour(self) -> None:
        for word in ("STOP", "stop", "UNSUBSCRIBE", "cancel", "END", "QUIT"):
            self.assertTrue(is_stop_word(word), word)

    def test_punctuation_and_spacing_do_not_defeat_it(self) -> None:
        # Someone typing "Stop." on a phone keyboard means stop.
        for word in ("Stop.", "STOP!", "  stop  ", "stop all"):
            self.assertTrue(is_stop_word(word), word)

    def test_a_sentence_containing_stop_is_not_a_stop(self) -> None:
        """Left for a human or the assistant to read.

        Treating every message with "stop" in it as an opt-out would silently
        unsubscribe people asking a question.
        """

        self.assertFalse(is_stop_word("stop sending me the chicken one"))
        self.assertFalse(is_stop_word("where do I stop for pickup?"))

    def test_starting_again_is_recognised_too(self) -> None:
        # An opt-out a customer cannot reverse from the same place is a trap.
        self.assertTrue(is_start_word("START"))
        self.assertTrue(is_start_word("subscribe"))
        self.assertFalse(is_start_word("start my order"))


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class GuardrailTests(unittest.TestCase):
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
            "push_notification_events",
            "push_notification_campaign_recipients",
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

    # --- helpers ----------------------------------------------------------

    def _customer(self, *, phone: str | None = None, email: str | None = None,
                  opted_in: bool = True) -> uuid.UUID:
        customer_id = uuid.uuid4()
        self.session.add(
            User(
                id=customer_id,
                app_client_id=None,
                full_name="Customer Person",
                email=email or f"c{customer_id.hex[:8]}@example.com",
                phone_number=phone,
                hashed_password="x",
                role=UserRole.CUSTOMER,
                is_active=True,
                is_verified=True,
                marketing_opt_in=opted_in,
            )
        )
        self.session.commit()
        return customer_id

    def _campaign(
        self,
        *,
        channel: MarketingChannel = MarketingChannel.PUSH,
        status=PushNotificationCampaignStatus.SENT,
        dispatched_at: datetime | None = None,
        message: str = "Come back",
        sent_count: int = 0,
    ) -> PushNotificationCampaign:
        campaign = PushNotificationCampaign(
            id=uuid.uuid4(),
            restaurant_id=self.restaurant_id,
            created_by_user_id=self.owner_id,
            kind=PushNotificationCampaignKind.MARKETING,
            audience=PushNotificationAudience.SEGMENT,
            status=status,
            name="A campaign",
            goal="WINBACK",
            segment_key="LAPSED_REGULARS",
            branch_ids=[str(self.branch_id)],
            channels=[channel.value],
            title="Hello",
            message=message,
            timezone="Asia/Kolkata",
            dispatched_at=dispatched_at,
            sent_count=sent_count,
        )
        self.session.add(campaign)
        self.session.commit()
        return campaign

    def _received(self, campaign, user_id: uuid.UUID, *, when: datetime,
                  state=CampaignRecipientState.SENT) -> None:
        self.session.add(
            PushNotificationCampaignRecipient(
                campaign_id=campaign.id,
                user_id=user_id,
                state=state,
                sent_at=when if state is CampaignRecipientState.SENT else None,
            )
        )
        self.session.commit()

    # --- the frequency cap ------------------------------------------------

    def test_the_cap_counts_campaigns_actually_received(self) -> None:
        """The bug: it read a table nothing writes, and suppressed nobody."""

        customer = self._customer()
        for _ in range(reach_module.FREQUENCY_CAP_PER_WEEK):
            campaign = self._campaign(dispatched_at=NOW - timedelta(days=1))
            self._received(campaign, customer, when=NOW - timedelta(days=1))

        capped = recently_messaged_user_ids(
            self.session,
            restaurant_id=self.restaurant_id,
            user_ids=[customer],
            now=NOW,
        )
        self.assertIn(customer, capped)

    def test_one_short_of_the_cap_is_not_capped(self) -> None:
        customer = self._customer()
        for _ in range(reach_module.FREQUENCY_CAP_PER_WEEK - 1):
            campaign = self._campaign(dispatched_at=NOW - timedelta(days=1))
            self._received(campaign, customer, when=NOW - timedelta(days=1))

        self.assertNotIn(
            customer,
            recently_messaged_user_ids(
                self.session,
                restaurant_id=self.restaurant_id,
                user_ids=[customer],
                now=NOW,
            ),
        )

    def test_an_engagement_event_no_longer_stands_in_for_a_send(self) -> None:
        """The old query's shape, proven not to be what counts any more.

        OPENED rows are the only thing that table has ever held, and a cap
        built on them was counting nothing.
        """

        customer = self._customer()
        for _ in range(reach_module.FREQUENCY_CAP_PER_WEEK + 2):
            campaign = self._campaign(dispatched_at=NOW - timedelta(days=1))
            self.session.add(
                PushNotificationEvent(
                    campaign_id=campaign.id,
                    user_id=customer,
                    event_type=PushNotificationEventType.OPENED,
                )
            )
        self.session.commit()

        self.assertNotIn(
            customer,
            recently_messaged_user_ids(
                self.session,
                restaurant_id=self.restaurant_id,
                user_ids=[customer],
                now=NOW,
            ),
        )

    def test_a_send_that_failed_does_not_use_up_the_allowance(self) -> None:
        """Holding a message back over a delivery we never made is backwards."""

        customer = self._customer()
        for _ in range(reach_module.FREQUENCY_CAP_PER_WEEK + 1):
            campaign = self._campaign(dispatched_at=NOW - timedelta(days=1))
            self._received(
                campaign, customer, when=NOW, state=CampaignRecipientState.FAILED
            )

        self.assertNotIn(
            customer,
            recently_messaged_user_ids(
                self.session,
                restaurant_id=self.restaurant_id,
                user_ids=[customer],
                now=NOW,
            ),
        )

    def test_last_weeks_messages_have_expired(self) -> None:
        customer = self._customer()
        for _ in range(reach_module.FREQUENCY_CAP_PER_WEEK + 1):
            campaign = self._campaign(dispatched_at=NOW - timedelta(days=30))
            self._received(campaign, customer, when=NOW - timedelta(days=30))

        self.assertNotIn(
            customer,
            recently_messaged_user_ids(
                self.session,
                restaurant_id=self.restaurant_id,
                user_ids=[customer],
                now=NOW,
            ),
        )

    def test_the_cap_is_counted_across_channels_not_per_channel(self) -> None:
        """Three pushes and three texts is six messages from one restaurant."""

        customer = self._customer(phone="+919876543210")
        channels = [MarketingChannel.PUSH, MarketingChannel.SMS, MarketingChannel.EMAIL]
        for index in range(reach_module.FREQUENCY_CAP_PER_WEEK):
            campaign = self._campaign(
                channel=channels[index % len(channels)],
                dispatched_at=NOW - timedelta(days=1),
            )
            self._received(campaign, customer, when=NOW - timedelta(days=1))

        self.assertIn(
            customer,
            recently_messaged_user_ids(
                self.session,
                restaurant_id=self.restaurant_id,
                user_ids=[customer],
                now=NOW,
            ),
        )

    # --- STOP -------------------------------------------------------------

    def test_stop_opts_the_customer_out(self) -> None:
        customer = self._customer(phone="+919876543210")
        result = apply_reply(
            self.session, phone_number="+919876543210", text="STOP", source="sms", now=NOW
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.changed, 1)
        self.session.expire_all()
        self.assertFalse(self.session.get(User, customer).marketing_opt_in)

    def test_the_preference_is_stamped_so_a_consent_audit_can_see_it(self) -> None:
        customer = self._customer(phone="+919876543210")
        apply_reply(
            self.session, phone_number="+919876543210", text="stop", source="sms", now=NOW
        )
        self.session.expire_all()
        stamped = self.session.get(User, customer).marketing_opt_in_changed_at
        # Compared as instants: Postgres returns the value in the server's own
        # zone, and forcing UTC onto that wall clock would shift it by the
        # offset rather than convert it.
        self.assertEqual(stamped.astimezone(UTC), NOW)

    def test_a_number_written_differently_still_matches(self) -> None:
        """The column has been written by several paths and holds both forms."""

        customer = self._customer(phone="9876543210")
        apply_reply(
            self.session,
            phone_number="9876543210",
            text="STOP",
            source="sms",
            now=NOW,
        )
        self.session.expire_all()
        self.assertFalse(self.session.get(User, customer).marketing_opt_in)

    def test_every_account_on_that_number_is_opted_out(self) -> None:
        """A phone number identifies a person, not an account.

        `AppClient` scoping makes the same phone two customer rows. Telling
        someone who texted STOP that they are still subscribed on their other
        account would be a technicality used against them.
        """

        first = self._customer(phone="+919876543210", email="a@example.com")
        second = self._customer(phone="+919876543210", email="b@example.com")
        result = apply_reply(
            self.session, phone_number="+919876543210", text="STOP", source="sms", now=NOW
        )
        self.assertEqual(result.changed, 2)
        self.session.expire_all()
        self.assertFalse(self.session.get(User, first).marketing_opt_in)
        self.assertFalse(self.session.get(User, second).marketing_opt_in)

    def test_stopping_twice_records_one_opt_out(self) -> None:
        """Or the campaign it is attributed to is charged for it twice."""

        customer = self._customer(phone="+919876543210")
        campaign = self._campaign(dispatched_at=NOW - timedelta(days=1))
        self._received(campaign, customer, when=NOW - timedelta(days=1))

        apply_reply(self.session, phone_number="+919876543210", text="STOP",
                    source="sms", now=NOW)
        second = apply_reply(self.session, phone_number="+919876543210", text="STOP",
                             source="sms", now=NOW)
        self.assertEqual(second.changed, 0)

        events = self.session.scalars(
            select(PushNotificationEvent).where(
                PushNotificationEvent.event_type == PushNotificationEventType.UNSUBSCRIBED
            )
        ).all()
        self.assertEqual(len(events), 1)

    def test_the_opt_out_is_credited_to_the_last_campaign_they_received(self) -> None:
        """An opt-out rate per campaign is how an owner learns copy cost them."""

        customer = self._customer(phone="+919876543210")
        older = self._campaign(dispatched_at=NOW - timedelta(days=5))
        newer = self._campaign(dispatched_at=NOW - timedelta(days=1))
        self._received(older, customer, when=NOW - timedelta(days=5))
        self._received(newer, customer, when=NOW - timedelta(days=1))

        apply_reply(self.session, phone_number="+919876543210", text="STOP",
                    source="whatsapp", now=NOW)

        event = self.session.scalars(
            select(PushNotificationEvent).where(
                PushNotificationEvent.event_type == PushNotificationEventType.UNSUBSCRIBED
            )
        ).first()
        self.assertEqual(event.campaign_id, newer.id)

    def test_start_puts_them_back(self) -> None:
        customer = self._customer(phone="+919876543210", opted_in=False)
        result = apply_reply(
            self.session, phone_number="+919876543210", text="START", source="sms", now=NOW
        )
        self.assertEqual(result.changed, 1)
        self.session.expire_all()
        self.assertTrue(self.session.get(User, customer).marketing_opt_in)

    def test_an_ordinary_message_is_not_an_opt_out(self) -> None:
        """It must fall through to the assistant, not silently unsubscribe."""

        customer = self._customer(phone="+919876543210")
        self.assertIsNone(
            apply_reply(
                self.session,
                phone_number="+919876543210",
                text="what time do you close",
                source="whatsapp",
                now=NOW,
            )
        )
        self.session.expire_all()
        self.assertTrue(self.session.get(User, customer).marketing_opt_in)

    def test_stop_from_a_number_we_do_not_hold_is_not_an_error(self) -> None:
        result = apply_reply(
            self.session, phone_number="+910000000000", text="STOP", source="sms", now=NOW
        )
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.changed, 0)

    # --- spend ------------------------------------------------------------

    def test_a_free_channel_costs_nothing_however_many_it_reached(self) -> None:
        campaign = self._campaign(
            channel=MarketingChannel.PUSH,
            dispatched_at=NOW,
            sent_count=50_000,
        )
        self.assertEqual(campaign_spend(campaign), 0.0)

    def test_sms_is_charged_per_person_and_per_part(self) -> None:
        """A long text bills as two, and quoting one halves the real number."""

        short = self._campaign(
            channel=MarketingChannel.SMS, dispatched_at=NOW, message="Short", sent_count=100
        )
        long = self._campaign(
            channel=MarketingChannel.SMS,
            dispatched_at=NOW,
            message="x" * 400,
            sent_count=100,
        )
        self.assertGreater(campaign_spend(long), campaign_spend(short))
        self.assertAlmostEqual(
            campaign_spend(short), settings.marketing_sms_cost_per_message * 100, places=2
        )

    def test_only_what_was_actually_delivered_is_charged(self) -> None:
        """A send that half failed is charged for half."""

        campaign = self._campaign(
            channel=MarketingChannel.SMS, dispatched_at=NOW, message="Hi", sent_count=40
        )
        self.assertAlmostEqual(
            campaign_spend(campaign), settings.marketing_sms_cost_per_message * 40, places=2
        )

    def test_the_month_total_covers_this_calendar_month_only(self) -> None:
        self._campaign(
            channel=MarketingChannel.SMS,
            dispatched_at=NOW - timedelta(days=2),
            message="Hi",
            sent_count=100,
        )
        self._campaign(
            channel=MarketingChannel.SMS,
            dispatched_at=NOW - timedelta(days=60),
            message="Hi",
            sent_count=100,
        )
        total = spend_this_month(
            self.session, restaurant_id=self.restaurant_id, now=NOW
        )
        self.assertAlmostEqual(
            total, settings.marketing_sms_cost_per_message * 100, places=2
        )

    def test_another_restaurants_spend_is_not_counted_against_this_one(self) -> None:
        other = uuid.uuid4()
        self._campaign(
            channel=MarketingChannel.SMS, dispatched_at=NOW, message="Hi", sent_count=100
        )
        self.assertEqual(
            spend_this_month(self.session, restaurant_id=other, now=NOW), 0.0
        )

    def test_a_campaign_over_the_cap_is_blocked_not_warned(self) -> None:
        """The notice is a BLOCK, which is what dispatch refuses on.

        One rule decides both what the builder shows and what the send
        allows — a warning here would be a cap in name only.
        """

        notices = reach_module._spend_notices(
            self.session,
            restaurant_id=self.restaurant_id,
            projected=settings.marketing_campaign_spend_cap + 1,
            now=NOW,
        )
        blocking = [n for n in notices if n.tone is MarketingNoticeTone.BLOCK]
        self.assertTrue(any(n.id == "over-campaign-spend-cap" for n in blocking))

    def test_a_campaign_under_the_cap_is_allowed(self) -> None:
        self.assertEqual(
            reach_module._spend_notices(
                self.session, restaurant_id=self.restaurant_id, projected=1.0, now=NOW
            ),
            [],
        )

    def test_a_free_campaign_is_never_blocked_on_spend(self) -> None:
        # Push and the social channels cost nothing; a cap must not touch them.
        self.assertEqual(
            reach_module._spend_notices(
                self.session, restaurant_id=self.restaurant_id, projected=0.0, now=NOW
            ),
            [],
        )

    def test_the_month_to_date_is_counted_against_the_monthly_cap(self) -> None:
        """A campaign under the per-campaign cap can still break the budget."""

        spent = settings.marketing_monthly_spend_cap - 10
        people = int(spent / settings.marketing_sms_cost_per_message)
        self._campaign(
            channel=MarketingChannel.SMS,
            dispatched_at=NOW - timedelta(days=1),
            message="Hi",
            sent_count=people,
        )
        notices = reach_module._spend_notices(
            self.session, restaurant_id=self.restaurant_id, projected=100.0, now=NOW
        )
        self.assertTrue(any(n.id == "over-monthly-spend-cap" for n in notices))

    def test_a_cap_set_to_zero_is_no_cap(self) -> None:
        with mock.patch.object(reach_module.settings, "marketing_campaign_spend_cap", 0.0), \
             mock.patch.object(reach_module.settings, "marketing_monthly_spend_cap", 0.0):
            self.assertEqual(
                reach_module._spend_notices(
                    self.session,
                    restaurant_id=self.restaurant_id,
                    projected=1_000_000.0,
                    now=NOW,
                ),
                [],
            )

    # --- retrying a failed campaign ---------------------------------------

    def test_a_failed_campaign_can_be_claimed_again(self) -> None:
        """FAILED -> SENDING is legal, and recipient rows make it safe."""

        campaign = self._campaign(status=PushNotificationCampaignStatus.FAILED)
        claimed = campaign_service.claim_for_sending(
            self.session, campaign_id=campaign.id, restaurant_id=self.restaurant_id
        )
        self.assertIs(claimed.status, PushNotificationCampaignStatus.SENDING)

    def test_a_sent_campaign_cannot_be_sent_again(self) -> None:
        """The other half of the rule: SENT is terminal."""

        campaign = self._campaign(status=PushNotificationCampaignStatus.SENT)
        with self.assertRaises(campaign_service.CampaignValidationError):
            campaign_service.claim_for_sending(
                self.session, campaign_id=campaign.id, restaurant_id=self.restaurant_id
            )


if __name__ == "__main__":
    unittest.main()
