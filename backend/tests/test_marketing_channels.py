"""Channel connections, the providers behind them, and posting to a platform.

Everything here covers the step between "the flow asks where you want to run
this" and "something actually leaves the building". Four groups, each pinning
a decision that would fail silently rather than loudly:

* **A credential goes in and never comes out.** Connecting splits secrets from
  configuration into two columns, and only one of them is ever serialised. The
  test that matters most is the re-save: a connect form cannot display a
  stored token, so an owner correcting their sender name leaves that field
  empty — and if that blanked the key, nothing would say so until the next
  send failed.

* **Availability is a fact about the restaurant, not about the build.** It
  used to be a constant that could only say "not connected yet", so a channel
  that HAD been connected still rendered as unavailable and still refused.

* **A social campaign is a different path, not a different branch.** It has no
  audience, writes no recipient rows, and must not be reported as a send with
  an audience of zero.

* **A post is attributed by a typed code, and that claim is weaker.** These
  tests fix what it counts — and, just as importantly, what it does not: no
  baseline, nothing outside the window, nothing with the wrong code.
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
    ChannelConnectionStatus,
    MarketingChannel,
    MarketingChannelFamily,
    OrderStatus,
    PushNotificationAudience,
    PushNotificationCampaignKind,
    PushNotificationCampaignStatus,
    UserRole,
    channel_family,
)
from app.models.order import Order
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.push_notification_campaign_recipient import (
    PushNotificationCampaignRecipient,
)
from app.models.restaurant import Restaurant
from app.models.restaurant_channel_connection import RestaurantChannelConnection
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.marketing import connections as connection_service
from app.services.marketing import dispatch as dispatch_module
from app.services.marketing.attribution import build_social_attribution, promo_code_for
from app.services.marketing.dispatch import DispatchError, dispatch_campaign
from app.services.marketing.providers import ProviderError, provider_for
from app.services.marketing.providers.base import PublishResult, SocialContent
from app.services.marketing.providers.sms import compose as sms_compose
from app.services.marketing.providers.sms import parts as sms_parts
from app.services.marketing.providers.whatsapp import WhatsAppProvider

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_marketing_channels_test"
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


# --- things that need no database -----------------------------------------


class ChannelFamilyTests(unittest.TestCase):
    """The split the whole Hub branches on."""

    def test_social_is_exactly_instagram_and_facebook(self) -> None:
        social = {
            channel
            for channel in MarketingChannel
            if channel_family(channel) is MarketingChannelFamily.SOCIAL
        }
        self.assertEqual(social, {MarketingChannel.INSTAGRAM, MarketingChannel.FACEBOOK})

    def test_an_unmapped_channel_is_direct_rather_than_an_exception(self) -> None:
        """A channel added to the enum and forgotten must not crash a send.

        DIRECT means it fails the "no provider for this channel" check, which
        is a sentence an owner can read, instead of raising a KeyError from
        inside the dispatcher.
        """

        with mock.patch.dict(
            "app.models.enums.CHANNEL_FAMILY", {}, clear=True
        ):
            self.assertIs(
                channel_family(MarketingChannel.INSTAGRAM),
                MarketingChannelFamily.DIRECT,
            )


class SmsCostTests(unittest.TestCase):
    """What the owner was quoted has to be what the operator bills."""

    def test_the_opt_out_line_is_appended_and_counted(self) -> None:
        composed = sms_compose("Tonight only")
        self.assertTrue(composed.endswith("Reply STOP to opt out"))

    def test_an_owner_who_types_the_footer_is_not_charged_twice(self) -> None:
        text_with_footer = "Tonight only. Reply STOP to opt out"
        self.assertEqual(sms_compose(text_with_footer), text_with_footer)

    def test_the_footer_can_push_a_message_into_a_second_part(self) -> None:
        """The case that was wrong: length costed without the footer.

        One character short of the boundary before the footer is added, and
        over it once the footer is counted — which is what the operator does.
        """

        footer_length = len("Reply STOP to opt out") + 1
        body = "x" * (160 - footer_length + 1)
        self.assertEqual(sms_parts(body), 2)

    def test_an_empty_message_is_one_part_not_zero(self) -> None:
        # "0 messages, free" would read as "SMS costs nothing" to an owner
        # who has not typed yet.
        self.assertEqual(sms_parts(""), 1)


class WhatsAppAddressTests(unittest.TestCase):
    """Meta wants E.164 without the plus; the kitchen prints it with."""

    def _provider(self) -> WhatsAppProvider:
        return WhatsAppProvider(
            config={"phone_number_id": "123"}, credentials={"access_token": "t"}
        )

    def test_a_formatted_number_is_reduced_to_digits(self) -> None:
        user = mock.Mock(phone_number="+91 80 4718-2203")
        self.assertEqual(self._provider().addresses_for(user), ["918047182203"])

    def test_a_customer_with_no_number_has_no_address(self) -> None:
        # Not a failure: nothing was attempted, which is why dispatch records
        # these people SKIPPED rather than FAILED.
        self.assertEqual(self._provider().addresses_for(mock.Mock(phone_number=None)), [])

    def test_an_obviously_short_number_is_refused_rather_than_sent(self) -> None:
        self.assertEqual(self._provider().addresses_for(mock.Mock(phone_number="123")), [])

    def test_a_half_configured_connection_refuses_to_construct(self) -> None:
        """The error names what is missing, because the owner has to fix it."""

        with self.assertRaises(ProviderError) as caught:
            WhatsAppProvider(config={}, credentials={})
        self.assertIn("access token", str(caught.exception))


# --- everything that needs a database --------------------------------------


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class ChannelConnectionTests(unittest.TestCase):
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
            "restaurant_channel_connections",
            "push_notification_campaign_recipients",
            "push_notification_campaigns",
            "orders",
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

    def _connect_sms(self, **overrides):
        values = {
            "sender_id": "SPICER",
            "api_url": "https://gateway.test/send",
            "api_key": "secret-one",
        }
        values.update(overrides)
        return connection_service.connect(
            self.session,
            restaurant_id=self.restaurant_id,
            channel=MarketingChannel.SMS,
            values=values,
        )

    # --- credentials ------------------------------------------------------

    def test_secrets_and_configuration_land_in_different_columns(self) -> None:
        connection = self._connect_sms()

        self.assertEqual(connection.config["sender_id"], "SPICER")
        self.assertEqual(connection.credentials["api_key"], "secret-one")
        # The half an API response is allowed to carry must not contain it.
        self.assertNotIn("api_key", connection.config)

    def test_the_serialised_view_never_carries_a_credential(self) -> None:
        connection = self._connect_sms()
        view = connection_service.view_for(MarketingChannel.SMS, connection)

        self.assertNotIn("api_key", view.config)
        self.assertEqual(view.identity, "SPICER")

    def test_re_saving_without_the_secret_keeps_the_stored_one(self) -> None:
        """The bug this exists for: a blanked key nothing reports until a send.

        A connect form cannot display a stored token, so an owner correcting
        their sender name leaves that field empty. Treating empty as "clear
        it" would break the channel silently.
        """

        self._connect_sms()
        updated = self._connect_sms(sender_id="SPICE2", api_key="")

        self.assertEqual(updated.config["sender_id"], "SPICE2")
        self.assertEqual(updated.credentials["api_key"], "secret-one")

    def test_a_missing_required_field_is_refused_by_name(self) -> None:
        with self.assertRaises(connection_service.ConnectionError_) as caught:
            connection_service.connect(
                self.session,
                restaurant_id=self.restaurant_id,
                channel=MarketingChannel.SMS,
                values={"sender_id": "SPICER"},
            )
        # Named, not "invalid input": the owner has to know which box to fill.
        self.assertIn("API key", str(caught.exception))

    def test_push_cannot_be_connected_because_it_is_never_disconnected(self) -> None:
        with self.assertRaises(connection_service.ConnectionError_):
            connection_service.connect(
                self.session,
                restaurant_id=self.restaurant_id,
                channel=MarketingChannel.PUSH,
                values={},
            )

    # --- availability -----------------------------------------------------

    def test_push_is_live_with_no_row_at_all(self) -> None:
        self.assertTrue(
            connection_service.is_live(
                self.session,
                restaurant_id=self.restaurant_id,
                channel=MarketingChannel.PUSH,
            )
        )

    def test_a_channel_with_no_row_is_not_live(self) -> None:
        self.assertFalse(
            connection_service.is_live(
                self.session,
                restaurant_id=self.restaurant_id,
                channel=MarketingChannel.WHATSAPP,
            )
        )

    def test_connecting_makes_a_channel_live(self) -> None:
        self._connect_sms()
        self.assertIn(
            MarketingChannel.SMS,
            connection_service.live_channels(
                self.session, restaurant_id=self.restaurant_id
            ),
        )

    def test_pausing_keeps_the_setup_and_stops_the_sending(self) -> None:
        """Distinct from disconnecting, and the distinction is the feature.

        An owner pausing WhatsApp for a month should not have to re-authorise
        Meta afterwards.
        """

        self._connect_sms()
        connection_service.set_enabled(
            self.session,
            restaurant_id=self.restaurant_id,
            channel=MarketingChannel.SMS,
            enabled=False,
        )

        row = connection_service.get_connection(
            self.session, restaurant_id=self.restaurant_id, channel=MarketingChannel.SMS
        )
        self.assertIs(row.status, ChannelConnectionStatus.DISABLED)
        self.assertEqual(row.credentials["api_key"], "secret-one")
        self.assertNotIn(
            MarketingChannel.SMS,
            connection_service.live_channels(
                self.session, restaurant_id=self.restaurant_id
            ),
        )

    def test_a_channel_in_error_can_still_send(self) -> None:
        """The error may describe a problem that has since gone away.

        Refusing the send would leave the owner no way to find out other than
        disconnecting and reconnecting. The send itself will fail loudly.
        """

        self._connect_sms()
        connection_service.record_failure(
            self.session,
            restaurant_id=self.restaurant_id,
            channel=MarketingChannel.SMS,
            reason="Gateway refused the key",
        )
        row = connection_service.get_connection(
            self.session, restaurant_id=self.restaurant_id, channel=MarketingChannel.SMS
        )
        self.assertIs(row.status, ChannelConnectionStatus.ERROR)
        self.assertTrue(row.is_sendable())

    def test_disconnecting_forgets_the_credentials(self) -> None:
        self._connect_sms()
        connection_service.disconnect(
            self.session, restaurant_id=self.restaurant_id, channel=MarketingChannel.SMS
        )
        self.assertIsNone(
            connection_service.get_connection(
                self.session,
                restaurant_id=self.restaurant_id,
                channel=MarketingChannel.SMS,
            )
        )

    def test_disconnecting_something_never_connected_is_not_an_error(self) -> None:
        # The owner asked for it to be gone and it is gone.
        connection_service.disconnect(
            self.session,
            restaurant_id=self.restaurant_id,
            channel=MarketingChannel.EMAIL,
        )

    def test_one_restaurants_connection_is_not_anothers(self) -> None:
        self._connect_sms()
        other_restaurant = uuid.uuid4()
        self.assertNotIn(
            MarketingChannel.SMS,
            connection_service.live_channels(
                self.session, restaurant_id=other_restaurant
            ),
        )

    # --- the provider factory --------------------------------------------

    def test_an_unconnected_channel_explains_itself_rather_than_crashing(self) -> None:
        with self.assertRaises(ProviderError) as caught:
            provider_for(MarketingChannel.WHATSAPP, None)
        self.assertIn("not connected", str(caught.exception).lower())

    def test_a_paused_channel_says_it_is_paused(self) -> None:
        self._connect_sms()
        connection_service.set_enabled(
            self.session,
            restaurant_id=self.restaurant_id,
            channel=MarketingChannel.SMS,
            enabled=False,
        )
        row = connection_service.get_connection(
            self.session, restaurant_id=self.restaurant_id, channel=MarketingChannel.SMS
        )
        with self.assertRaises(ProviderError) as caught:
            provider_for(MarketingChannel.SMS, row)
        self.assertIn("switched off", str(caught.exception))

    def test_push_needs_no_connection_row(self) -> None:
        self.assertIsNotNone(provider_for(MarketingChannel.PUSH, None))

    # --- publishing a post ------------------------------------------------

    def _social_campaign(self, *, promo_code: str | None = "INSTA20"):
        campaign = PushNotificationCampaign(
            id=uuid.uuid4(),
            restaurant_id=self.restaurant_id,
            created_by_user_id=self.owner_id,
            kind=PushNotificationCampaignKind.MARKETING,
            audience=PushNotificationAudience.SEGMENT,
            status=PushNotificationCampaignStatus.SENDING,
            name="Launch post",
            goal="NEW_ITEM",
            segment_key="BRANCH_CUSTOMERS",
            branch_ids=[str(self.branch_id)],
            channels=[MarketingChannel.INSTAGRAM.value],
            title="Back on the menu",
            message="Eight hours, every morning.",
            timezone="Asia/Kolkata",
            data_payload={
                "content_extra": {
                    "image_url": "https://example.test/a.jpg",
                    **({"promo_code": promo_code} if promo_code else {}),
                }
            },
        )
        self.session.add(campaign)
        self.session.commit()
        return campaign

    def _connect_instagram(self):
        return connection_service.connect(
            self.session,
            restaurant_id=self.restaurant_id,
            channel=MarketingChannel.INSTAGRAM,
            values={"ig_user_id": "17841400000000000", "access_token": "tok"},
        )

    def test_a_social_campaign_publishes_and_writes_no_recipient_rows(self) -> None:
        """The whole reason it is a separate path.

        Running a post through the direct path with the people-shaped parts
        skipped would report a campaign with an audience of zero as a failed
        send.
        """

        self._connect_instagram()
        campaign = self._social_campaign()

        published = PublishResult(post_id="ig-1", permalink="https://instagram.test/p/1")
        with mock.patch.object(dispatch_module.settings, "enable_marketing_dispatch", True), \
             mock.patch(
                 "app.services.marketing.providers.meta_social.InstagramProvider.publish",
                 return_value=published,
             ) as publish:
            result = dispatch_campaign(self.session, campaign=campaign, now=NOW)

        publish.assert_called_once()
        content = publish.call_args.args[0]
        self.assertIsInstance(content, SocialContent)
        self.assertEqual(content.image_url, "https://example.test/a.jpg")

        self.assertIs(result.status, PushNotificationCampaignStatus.SENT)
        self.assertEqual(result.audience, 0)
        self.assertEqual(
            self.session.scalars(
                select(PushNotificationCampaignRecipient).where(
                    PushNotificationCampaignRecipient.campaign_id == campaign.id
                )
            ).all(),
            [],
        )
        post = campaign.data_payload["social_post"]
        self.assertEqual(post["post_id"], "ig-1")
        self.assertEqual(post["permalink"], "https://instagram.test/p/1")

    def test_publishing_to_an_unconnected_account_fails_with_a_readable_reason(self) -> None:
        campaign = self._social_campaign()
        with self.assertRaises(DispatchError) as caught:
            dispatch_campaign(self.session, campaign=campaign, now=NOW)
        self.assertIn("not connected", str(caught.exception).lower())

    def test_a_refused_post_is_recorded_and_the_channel_is_flagged(self) -> None:
        """The picker should say the channel is in trouble, not leave the
        owner to infer it from a campaign that went red."""

        self._connect_instagram()
        campaign = self._social_campaign()

        with mock.patch.object(dispatch_module.settings, "enable_marketing_dispatch", True), \
             mock.patch(
                 "app.services.marketing.providers.meta_social.InstagramProvider.publish",
                 side_effect=ProviderError("Meta rejected your access token"),
             ):
            with self.assertRaises(DispatchError):
                dispatch_campaign(self.session, campaign=campaign, now=NOW)

        self.session.refresh(campaign)
        self.assertEqual(campaign.data_payload["social_post"]["state"], "FAILED")
        row = connection_service.get_connection(
            self.session,
            restaurant_id=self.restaurant_id,
            channel=MarketingChannel.INSTAGRAM,
        )
        self.assertIs(row.status, ChannelConnectionStatus.ERROR)

    def test_a_dry_run_posts_nothing_and_says_so(self) -> None:
        self._connect_instagram()
        campaign = self._social_campaign()

        with mock.patch.object(dispatch_module.settings, "enable_marketing_dispatch", False), \
             mock.patch(
                 "app.services.marketing.providers.meta_social.InstagramProvider.publish",
             ) as publish:
            result = dispatch_campaign(self.session, campaign=campaign, now=NOW)

        publish.assert_not_called()
        self.assertTrue(result.dry_run)
        self.assertTrue(campaign.data_payload["social_post"]["dry_run"])
        self.assertIn("switched off", campaign.last_error)

    # --- attribution by promo code ---------------------------------------

    def _customer(self, email: str) -> uuid.UUID:
        customer_id = uuid.uuid4()
        self.session.add(
            User(
                id=customer_id,
                app_client_id=None,
                full_name="Customer",
                email=email,
                hashed_password="x",
                role=UserRole.ADMIN,
                is_active=True,
                is_verified=True,
            )
        )
        self.session.commit()
        return customer_id

    def _order(self, customer_id: uuid.UUID, *, code: str | None, when: datetime,
               status=OrderStatus.DELIVERED, total="500.00") -> Order:
        order = Order(
            id=uuid.uuid4(),
            customer_id=customer_id,
            restaurant_id=self.restaurant_id,
            restaurant_location_id=self.branch_id,
            status=status,
            subtotal=Decimal(total),
            delivery_fee=Decimal("0"),
            tax_amount=Decimal("0"),
            discount_amount=Decimal("0"),
            total_amount=Decimal(total),
            currency="INR",
            delivery_address="1 Road",
            marketing_promo_code=code,
        )
        self.session.add(order)
        self.session.commit()
        self.session.execute(
            text("UPDATE orders SET created_at = :when WHERE id = :id"),
            {"when": when, "id": order.id},
        )
        self.session.commit()
        self.session.refresh(order)
        return order

    def _published(self, campaign, *, at: datetime) -> None:
        campaign.status = PushNotificationCampaignStatus.SENT
        campaign.dispatched_at = at
        campaign.data_payload = {
            **(campaign.data_payload or {}),
            "social_post": {
                "state": "PUBLISHED",
                "post_id": "ig-1",
                "permalink": None,
                "published_at": at.isoformat(),
                "dry_run": False,
            },
        }
        self.session.add(campaign)
        self.session.commit()

    def test_an_order_with_the_code_inside_the_window_counts(self) -> None:
        campaign = self._social_campaign()
        self._published(campaign, at=NOW)
        customer = self._customer("a@example.com")
        self._order(customer, code="INSTA20", when=NOW + timedelta(days=1))

        report = build_social_attribution(
            self.session, campaign, now=NOW + timedelta(days=2)
        )
        self.assertEqual(report.orders, 1)
        self.assertEqual(report.revenue, 500.0)

    def test_an_order_with_a_different_code_is_not_this_campaigns(self) -> None:
        campaign = self._social_campaign()
        self._published(campaign, at=NOW)
        customer = self._customer("b@example.com")
        self._order(customer, code="OTHER", when=NOW + timedelta(days=1))

        report = build_social_attribution(
            self.session, campaign, now=NOW + timedelta(days=2)
        )
        self.assertEqual(report.orders, 0)

    def test_an_order_before_the_post_went_up_is_not_caused_by_it(self) -> None:
        campaign = self._social_campaign()
        self._published(campaign, at=NOW)
        customer = self._customer("c@example.com")
        self._order(customer, code="INSTA20", when=NOW - timedelta(days=1))

        report = build_social_attribution(
            self.session, campaign, now=NOW + timedelta(days=2)
        )
        self.assertEqual(report.orders, 0)

    def test_an_order_past_the_window_is_not_counted(self) -> None:
        campaign = self._social_campaign()
        self._published(campaign, at=NOW)
        customer = self._customer("d@example.com")
        self._order(customer, code="INSTA20", when=NOW + timedelta(days=30))

        report = build_social_attribution(
            self.session, campaign, now=NOW + timedelta(days=40)
        )
        self.assertEqual(report.orders, 0)

    def test_a_cancelled_order_is_not_revenue(self) -> None:
        """The same rule every other revenue figure in this product uses."""

        campaign = self._social_campaign()
        self._published(campaign, at=NOW)
        customer = self._customer("e@example.com")
        self._order(
            customer,
            code="INSTA20",
            when=NOW + timedelta(days=1),
            status=OrderStatus.CANCELLED,
        )

        report = build_social_attribution(
            self.session, campaign, now=NOW + timedelta(days=2)
        )
        self.assertEqual(report.orders, 0)

    def test_a_post_reports_no_baseline_rather_than_a_made_up_one(self) -> None:
        """There is no "these same customers before the send" for a post.

        A fabricated denominator next to a real numerator is worse than none,
        so the report carries zero and the UI does not draw it.
        """

        campaign = self._social_campaign()
        self._published(campaign, at=NOW)
        customer = self._customer("f@example.com")
        self._order(customer, code="INSTA20", when=NOW + timedelta(days=1))

        report = build_social_attribution(
            self.session, campaign, now=NOW + timedelta(days=2)
        )
        self.assertEqual(report.baseline_orders, 0)

    def test_a_post_with_no_code_has_nothing_to_attribute(self) -> None:
        campaign = self._social_campaign(promo_code=None)
        self._published(campaign, at=NOW)

        self.assertIsNone(promo_code_for(campaign))
        self.assertIsNone(
            build_social_attribution(self.session, campaign, now=NOW + timedelta(days=1))
        )

    def test_a_code_is_matched_regardless_of_how_it_was_typed(self) -> None:
        """The customer is copying it off a phone screen and will get the
        case wrong. Both sides normalise to upper case."""

        campaign = self._social_campaign(promo_code="insta20")
        self._published(campaign, at=NOW)
        customer = self._customer("g@example.com")
        self._order(customer, code="INSTA20", when=NOW + timedelta(days=1))

        report = build_social_attribution(
            self.session, campaign, now=NOW + timedelta(days=2)
        )
        self.assertEqual(report.orders, 1)


if __name__ == "__main__":
    unittest.main()
