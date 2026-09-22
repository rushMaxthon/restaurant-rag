"""Campaign persistence, lifecycle and tenancy.

What is actually being pinned down here:

* **A draft saves half-finished.** The wizard has six steps and saves on each
  one. If an incomplete draft were rejected, the owner would lose their work
  every time they stepped away mid-flow — so the permissiveness is the feature,
  and validation of whether a campaign may *go out* belongs at send time.

* **A sent campaign is immutable.** Its report describes a message real people
  received. Editing it afterwards would silently rewrite what the report is
  about, which is the sort of bug nobody notices until an owner disputes a
  number.

* **A campaign belongs to exactly one restaurant.** Another tenant's campaign
  id must 404, not 403 — a 403 confirms the id exists and turns the endpoint
  into a way of enumerating the platform's campaigns.

* **Transactional pushes stay out of the Hub.** The Hub reads the same table
  the order-placed path writes to. Without the `kind` filter an owner would
  open Marketing and find every order notification the platform ever sent.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.base import Base
from app.models.enums import (
    MarketingCampaignGoal,
    MarketingChannel,
    MarketingDeepLink,
    MarketingSegmentKey,
    PushNotificationAudience,
    PushNotificationCampaignKind,
    PushNotificationCampaignStatus,
    UserRole,
)
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.marketing import (
    CampaignContentSchema,
    CampaignDraftRequest,
    CampaignScheduleSchema,
)
from app.services.marketing import campaigns as campaign_service

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_marketing_campaigns_test"
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
Status = PushNotificationCampaignStatus


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
class MarketingCampaignTests(unittest.TestCase):
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
        cls.restaurant_id = uuid.uuid4()
        cls.other_restaurant_id = uuid.uuid4()
        cls.owner_id = uuid.uuid4()

        session.add(
            User(
                id=cls.owner_id,
                app_client_id=None,
                full_name="Owner One",
                email="owner1@example.com",
                hashed_password="x",
                role=UserRole.OWNER,
                is_active=True,
                is_verified=True,
            )
        )
        other_owner_id = uuid.uuid4()
        session.add(
            User(
                id=other_owner_id,
                app_client_id=None,
                full_name="Owner Two",
                email="owner2@example.com",
                hashed_password="x",
                role=UserRole.OWNER,
                is_active=True,
                is_verified=True,
            )
        )
        session.flush()

        for restaurant_id, owner_id, slug in (
            (cls.restaurant_id, cls.owner_id, "one"),
            (cls.other_restaurant_id, other_owner_id, "two"),
        ):
            session.add(
                Restaurant(
                    id=restaurant_id,
                    owner_id=owner_id,
                    name=f"Restaurant {slug}",
                    slug=slug,
                    cuisine_type="Indian",
                    address_line_1="1 Road",
                    city="Ahmedabad",
                    state="Gujarat",
                    postal_code="380001",
                )
            )

        cls.branch_id = uuid.uuid4()
        cls.other_branch_id = uuid.uuid4()
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
        session.add(
            RestaurantLocation(
                id=cls.other_branch_id,
                restaurant_id=cls.other_restaurant_id,
                branch_name="Theirs",
                address_line_1="2 Road",
                city="Ahmedabad",
                state="Gujarat",
                postal_code="380002",
            )
        )
        session.commit()

    # --- helpers ----------------------------------------------------------

    def draft_payload(self, **overrides) -> CampaignDraftRequest:
        base = {
            "name": "May winback",
            "goal": MarketingCampaignGoal.WINBACK,
            "segment_key": MarketingSegmentKey.LAPSED_REGULARS,
            "branch_ids": [self.branch_id],
            "offer_id": None,
            "channels": [MarketingChannel.PUSH],
            "content": CampaignContentSchema(
                title="We miss you",
                body="Come back for something good.",
                deep_link=MarketingDeepLink.RESTAURANT_HOME,
                template_id=None,
            ),
            "schedule": CampaignScheduleSchema(
                mode="NOW", send_at=None, timezone="Asia/Kolkata"
            ),
            "last_step": 3,
        }
        base.update(overrides)
        return CampaignDraftRequest(**base)

    def save(self, session: Session, **overrides) -> PushNotificationCampaign:
        return campaign_service.save_draft(
            session,
            payload=self.draft_payload(**overrides),
            restaurant_id=self.restaurant_id,
            created_by_user_id=self.owner_id,
        )

    # --- creating and updating --------------------------------------------

    def test_a_new_draft_is_marketing_and_segment_scoped(self) -> None:
        with self.session_factory() as session:
            campaign = self.save(session, name="Kind check")

            self.assertEqual(campaign.kind, PushNotificationCampaignKind.MARKETING)
            self.assertEqual(campaign.audience, PushNotificationAudience.SEGMENT)
            self.assertEqual(campaign.status, Status.DRAFT)
            self.assertEqual(campaign.restaurant_id, self.restaurant_id)

    def test_saving_again_updates_in_place_rather_than_forking(self) -> None:
        """The wizard saves the same draft five times; it must stay one row."""

        with self.session_factory() as session:
            first = self.save(session, name="Step one")
            second = campaign_service.save_draft(
                session,
                payload=self.draft_payload(
                    id=first.id, name="Step two", last_step=4
                ),
                restaurant_id=self.restaurant_id,
                created_by_user_id=self.owner_id,
            )

            self.assertEqual(first.id, second.id)
            self.assertEqual(second.name, "Step two")
            self.assertEqual(second.last_step, 4)

    def test_a_branch_from_another_restaurant_is_refused(self) -> None:
        """A UI guard is not a rule.

        The picker only offers this restaurant's branches, which is precisely
        why the server checks: a crafted request could otherwise scope a
        campaign to a competitor's branch and read its customer count back out
        of the reach estimate.
        """

        with self.session_factory() as session:
            with self.assertRaises(HTTPException) as caught:
                self.save(session, branch_ids=[self.other_branch_id])
            self.assertEqual(caught.exception.status_code, 404)

    # --- lifecycle --------------------------------------------------------

    def test_a_sent_campaign_cannot_be_edited(self) -> None:
        with self.session_factory() as session:
            campaign = self.save(session, name="Already sent")
            campaign.status = Status.SENT
            session.add(campaign)
            session.commit()

            with self.assertRaises(campaign_service.CampaignValidationError):
                campaign_service.save_draft(
                    session,
                    payload=self.draft_payload(id=campaign.id, name="Rewrite"),
                    restaurant_id=self.restaurant_id,
                    created_by_user_id=self.owner_id,
                )

    def test_only_a_draft_can_be_deleted(self) -> None:
        with self.session_factory() as session:
            campaign = self.save(session, name="Scheduled, not deletable")
            campaign.status = Status.SCHEDULED
            session.add(campaign)
            session.commit()

            with self.assertRaises(campaign_service.CampaignValidationError):
                campaign_service.delete_draft(
                    session,
                    campaign_id=campaign.id,
                    restaurant_id=self.restaurant_id,
                )

    def test_a_draft_is_deleted(self) -> None:
        with self.session_factory() as session:
            campaign = self.save(session, name="Disposable")
            campaign_service.delete_draft(
                session,
                campaign_id=campaign.id,
                restaurant_id=self.restaurant_id,
            )
            with self.assertRaises(HTTPException):
                campaign_service.get_campaign(
                    session,
                    campaign_id=campaign.id,
                    restaurant_id=self.restaurant_id,
                )

    def test_a_sent_campaign_cannot_be_cancelled(self) -> None:
        """Some customers already have it on their phone.

        A status claiming the campaign was cancelled would be a lie about what
        happened, so SENT is terminal.
        """

        with self.session_factory() as session:
            campaign = self.save(session, name="Gone out")
            campaign.status = Status.SENT
            session.add(campaign)
            session.commit()

            with self.assertRaises(campaign_service.CampaignValidationError):
                campaign_service.cancel_campaign(
                    session,
                    campaign_id=campaign.id,
                    restaurant_id=self.restaurant_id,
                )

    def test_a_sending_campaign_cannot_be_cancelled(self) -> None:
        with self.session_factory() as session:
            campaign = self.save(session, name="Mid flight")
            campaign.status = Status.SENDING
            session.add(campaign)
            session.commit()

            with self.assertRaises(campaign_service.CampaignValidationError):
                campaign_service.cancel_campaign(
                    session,
                    campaign_id=campaign.id,
                    restaurant_id=self.restaurant_id,
                )

    def test_scheduling_in_the_past_is_refused(self) -> None:
        with self.session_factory() as session:
            campaign = self.save(session, name="Backwards")
            with self.assertRaises(campaign_service.CampaignValidationError):
                campaign_service.schedule_campaign(
                    session,
                    campaign_id=campaign.id,
                    restaurant_id=self.restaurant_id,
                    send_at=NOW - timedelta(hours=1),
                    now=NOW,
                )

    def test_scheduling_moves_a_draft_to_scheduled(self) -> None:
        with self.session_factory() as session:
            campaign = self.save(session, name="Friday push")
            scheduled = campaign_service.schedule_campaign(
                session,
                campaign_id=campaign.id,
                restaurant_id=self.restaurant_id,
                send_at=NOW + timedelta(days=2),
                now=NOW,
            )
            self.assertEqual(scheduled.status, Status.SCHEDULED)
            self.assertIsNotNone(scheduled.scheduled_for)

    def test_editing_a_failed_campaign_clears_the_error(self) -> None:
        """A fixed campaign should stop looking broken in the list."""

        with self.session_factory() as session:
            campaign = self.save(session, name="Failed once")
            campaign.status = Status.FAILED
            campaign.last_error = "No device tokens"
            session.add(campaign)
            session.commit()

            updated = campaign_service.save_draft(
                session,
                payload=self.draft_payload(id=campaign.id, name="Fixed"),
                restaurant_id=self.restaurant_id,
                created_by_user_id=self.owner_id,
            )
            self.assertEqual(updated.status, Status.DRAFT)
            self.assertIsNone(updated.last_error)

    # --- duplication ------------------------------------------------------

    def test_duplicate_copies_content_but_not_results(self) -> None:
        with self.session_factory() as session:
            original = self.save(session, name="Original")
            original.status = Status.SENT
            original.sent_count = 300
            original.delivered_count = 280
            original.last_error = "some error"
            session.add(original)
            session.commit()

            copy = campaign_service.duplicate_campaign(
                session,
                campaign_id=original.id,
                restaurant_id=self.restaurant_id,
                created_by_user_id=self.owner_id,
            )

            self.assertEqual(copy.title, original.title)
            self.assertEqual(copy.segment_key, original.segment_key)
            self.assertEqual(copy.status, Status.DRAFT)
            self.assertEqual(copy.sent_count, 0)
            self.assertEqual(copy.delivered_count, 0)
            self.assertIsNone(copy.last_error)
            self.assertNotEqual(copy.name, original.name)

    # --- per-channel content ----------------------------------------------

    def test_channel_content_survives_a_round_trip(self) -> None:
        """The bag the channel-first wizard fills is stored and handed back.

        `content.extra` holds everything one channel needs and the others do
        not - the photo an Instagram post cannot exist without, the promo code
        a public post is attributed by. It rides in `data_payload` rather than
        in columns, so nothing type-checks it on the way through and a dropped
        key looks exactly like an owner who did not fill the field in. This is
        the test that would catch that.
        """

        with self.session_factory() as session:
            extra = {
                "image_url": "https://example.test/biryani.jpg",
                "hashtags": "#biryani",
                "promo_code": "INSTA20",
                "boost_budget": 500,
            }
            campaign = self.save(
                session,
                name="Instagram launch",
                channels=[MarketingChannel.INSTAGRAM],
                content=CampaignContentSchema(
                    title="Back on the menu",
                    body="Slow-cooked, eight hours, every morning.",
                    deep_link=MarketingDeepLink.RESTAURANT_HOME,
                    template_id=None,
                    extra=extra,
                ),
            )

            view = campaign_service.campaign_view(campaign)
            self.assertEqual(view["content"]["extra"], extra)
            self.assertEqual(view["channels"], [MarketingChannel.INSTAGRAM])

    def test_content_extra_is_namespaced_not_assigned_over(self) -> None:
        """`data_payload` is shared with the transactional push path.

        A marketing campaign has never written anything else into that column,
        but it is the same column, and clobbering it would make this feature
        the reason an unrelated push lost its payload.
        """

        with self.session_factory() as session:
            campaign = self.save(session, name="Namespacing")
            campaign.data_payload = {**(campaign.data_payload or {}), "other": "keep me"}
            session.add(campaign)
            session.commit()

            campaign_service.save_draft(
                session,
                payload=self.draft_payload(
                    id=campaign.id,
                    name="Namespacing",
                    content=CampaignContentSchema(
                        title="We miss you",
                        body="Come back.",
                        deep_link=MarketingDeepLink.RESTAURANT_HOME,
                        template_id=None,
                        extra={"promo_code": "BACK10"},
                    ),
                ),
                restaurant_id=self.restaurant_id,
                created_by_user_id=self.owner_id,
            )
            session.refresh(campaign)

            self.assertEqual(campaign.data_payload["other"], "keep me")
            self.assertEqual(
                campaign.data_payload["content_extra"], {"promo_code": "BACK10"}
            )

    def test_a_draft_with_no_channel_content_reads_back_as_an_empty_bag(self) -> None:
        """Never None. Every editor reads `content.extra.image_url` directly."""

        with self.session_factory() as session:
            campaign = self.save(session, name="Plain push")
            campaign.data_payload = None
            session.add(campaign)
            session.commit()

            view = campaign_service.campaign_view(campaign)
            self.assertEqual(view["content"]["extra"], {})

    def test_duplicate_carries_the_photo_with_the_caption(self) -> None:
        """A copy with the caption and no image is not a post at all."""

        with self.session_factory() as session:
            original = self.save(
                session,
                name="Original post",
                channels=[MarketingChannel.INSTAGRAM],
                content=CampaignContentSchema(
                    title="Back on the menu",
                    body="Eight hours, every morning.",
                    deep_link=MarketingDeepLink.RESTAURANT_HOME,
                    template_id=None,
                    extra={"image_url": "https://example.test/a.jpg"},
                ),
            )

            copy = campaign_service.duplicate_campaign(
                session,
                campaign_id=original.id,
                restaurant_id=self.restaurant_id,
                created_by_user_id=self.owner_id,
            )

            self.assertEqual(
                campaign_service.campaign_view(copy)["content"]["extra"],
                {"image_url": "https://example.test/a.jpg"},
            )

    # --- tenancy ----------------------------------------------------------

    def test_another_restaurants_campaign_is_not_found(self) -> None:
        with self.session_factory() as session:
            campaign = self.save(session, name="Mine")
            with self.assertRaises(HTTPException) as caught:
                campaign_service.get_campaign(
                    session,
                    campaign_id=campaign.id,
                    restaurant_id=self.other_restaurant_id,
                )
            # 404, not 403: a 403 would confirm the id exists.
            self.assertEqual(caught.exception.status_code, 404)

    def test_transactional_pushes_never_appear_in_the_hub(self) -> None:
        """The order-placed path writes to this table too."""

        with self.session_factory() as session:
            session.add(
                PushNotificationCampaign(
                    id=uuid.uuid4(),
                    restaurant_id=self.restaurant_id,
                    audience=PushNotificationAudience.SPECIFIC_USER,
                    kind=PushNotificationCampaignKind.TRANSACTIONAL,
                    title="Order placed",
                    message="Your order is on its way",
                )
            )
            session.commit()

            listed = campaign_service.list_campaigns(
                session, restaurant_id=self.restaurant_id
            )
            self.assertTrue(listed)
            for campaign in listed:
                self.assertEqual(campaign.kind, PushNotificationCampaignKind.MARKETING)

    # --- presentation -----------------------------------------------------

    def test_a_draft_reports_no_delivery_figures(self) -> None:
        """Null, not a row of zeros — the UI's empty state depends on it."""

        with self.session_factory() as session:
            campaign = self.save(session, name="Never sent")
            view = campaign_service.campaign_view(campaign)
            self.assertIsNone(view["delivery"])
            self.assertIsNone(view["attribution"])

    def test_a_sent_campaign_reports_delivery_figures(self) -> None:
        with self.session_factory() as session:
            campaign = self.save(session, name="Has figures")
            campaign.status = Status.SENT
            campaign.sent_count = 120
            campaign.delivered_count = 110
            session.add(campaign)
            session.commit()

            view = campaign_service.campaign_view(campaign)
            self.assertIsNotNone(view["delivery"])
            self.assertEqual(view["delivery"]["sent"], 120)
            self.assertEqual(view["delivery"]["delivered"], 110)


if __name__ == "__main__":
    unittest.main()
