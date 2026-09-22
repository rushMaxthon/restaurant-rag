"""Did the campaign cause the order, and can the answer be trusted?

The number this module produces is one an owner may spend money on, so the
tests are about what it must NOT count as much as what it must.

* **The window is per recipient, not per campaign.** A send spanning minutes
  must not shorten the last customer's window by the first customer's clock.
  Attributing from `campaigns.dispatched_at` would do exactly that, and the
  error grows with the size of the audience — invisible in a test with one
  recipient, material for a real send.

* **Only customers who actually received it count.** SKIPPED (no device) and
  FAILED (Firebase refused) recipients were never reached, and crediting their
  orders would make a campaign that delivered to nobody look successful.

* **Only counted statuses are revenue.** A cancelled order is not money, and a
  campaign must not be paid for one. Same rule as the rest of the product's
  revenue figures, deliberately.

* **Baseline is what makes the headline honest.** A campaign to regulars
  reports a big number that means nothing on its own; the same customers'
  rate in the window immediately before the send is what turns it into lift.
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
from app.models.base import Base
from app.models.enums import (
    CampaignRecipientState,
    OrderStatus,
    PushNotificationAudience,
    PushNotificationCampaignKind,
    PushNotificationCampaignStatus,
    UserRole,
)
from app.models.order import Order
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.push_notification_campaign_recipient import (
    PushNotificationCampaignRecipient,
)
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.marketing.attribution import build_attribution, failure_reason_view
from app.services.marketing.dashboard import build_dashboard

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_marketing_attribution_test"
SENT_AT = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
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
class MarketingAttributionTests(unittest.TestCase):
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
            "orders",
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

    def _customer(self, name: str) -> uuid.UUID:
        customer_id = uuid.uuid4()
        self.session.add(
            User(
                id=customer_id,
                app_client_id=None,
                full_name=name,
                email=f"{name.lower().replace(' ', '')}@example.com",
                hashed_password="x",
                role=UserRole.ADMIN,  # role is irrelevant here; app_client_id must be null
                is_active=True,
                is_verified=True,
            )
        )
        self.session.commit()
        return customer_id

    def _campaign(self, *, window_days: int = 7, status=PushNotificationCampaignStatus.SENT):
        campaign = PushNotificationCampaign(
            id=uuid.uuid4(),
            restaurant_id=self.restaurant_id,
            kind=PushNotificationCampaignKind.MARKETING,
            audience=PushNotificationAudience.SEGMENT,
            title="Hi",
            message="Come back",
            status=status,
            name="Winback",
            attribution_window_days=window_days,
            dispatched_at=SENT_AT,
        )
        self.session.add(campaign)
        self.session.commit()
        return campaign

    def _recipient(
        self,
        campaign,
        customer_id: uuid.UUID,
        *,
        state=CampaignRecipientState.SENT,
        sent_at: datetime | None = None,
        failure_reason: str | None = None,
    ):
        recipient = PushNotificationCampaignRecipient(
            campaign_id=campaign.id,
            user_id=customer_id,
            state=state,
            sent_at=sent_at if sent_at is not None else (SENT_AT if state is CampaignRecipientState.SENT else None),
            failure_reason=failure_reason,
        )
        self.session.add(recipient)
        self.session.commit()
        return recipient

    def _order(
        self,
        customer_id: uuid.UUID,
        *,
        created_at: datetime,
        total: str = "100.00",
        discount: str = "0.00",
        status=OrderStatus.DELIVERED,
    ):
        order = Order(
            id=uuid.uuid4(),
            customer_id=customer_id,
            restaurant_id=self.restaurant_id,
            restaurant_location_id=self.branch_id,
            subtotal=Decimal(total),
            total_amount=Decimal(total),
            discount_amount=Decimal(discount),
            delivery_address="1 Road",
            status=status,
            created_at=created_at,
        )
        self.session.add(order)
        self.session.commit()
        return order

    # --- the window -------------------------------------------------------

    def test_an_order_inside_the_window_is_attributed(self) -> None:
        campaign = self._campaign()
        customer = self._customer("Ada")
        self._recipient(campaign, customer)
        self._order(customer, created_at=SENT_AT + timedelta(days=2), total="250.00")

        report = build_attribution(self.session, campaign, now=NOW)

        self.assertEqual(report.orders, 1)
        self.assertEqual(report.revenue, 250.0)
        self.assertEqual(report.net_revenue, 250.0)
        self.assertEqual(report.average_order_value, 250.0)

    def test_an_order_before_the_send_is_not_attributed(self) -> None:
        campaign = self._campaign()
        customer = self._customer("Bob")
        self._recipient(campaign, customer)
        self._order(customer, created_at=SENT_AT - timedelta(hours=1))

        report = build_attribution(self.session, campaign, now=NOW)

        self.assertEqual(report.orders, 0)
        # It is the baseline instead, which is the whole point of having one.
        self.assertEqual(report.baseline_orders, 1)

    def test_an_order_after_the_window_closes_is_not_attributed(self) -> None:
        campaign = self._campaign(window_days=7)
        customer = self._customer("Cleo")
        self._recipient(campaign, customer)
        self._order(customer, created_at=SENT_AT + timedelta(days=8))

        report = build_attribution(self.session, campaign, now=NOW)

        self.assertEqual(report.orders, 0)

    def test_the_window_is_measured_from_each_recipients_own_send(self) -> None:
        """The design decision this table exists for.

        Two customers, messaged three days apart by one long send. The second
        customer's order is inside *their* window and outside a window measured
        from the campaign's own timestamp — so a per-campaign window would
        silently lose it.
        """

        campaign = self._campaign(window_days=7)
        early = self._customer("Early")
        late = self._customer("Late")
        self._recipient(campaign, early, sent_at=SENT_AT)
        self._recipient(campaign, late, sent_at=SENT_AT + timedelta(days=3))

        # Nine days after the campaign started, but six days after Late got it.
        self._order(late, created_at=SENT_AT + timedelta(days=9), total="80.00")

        report = build_attribution(self.session, campaign, now=NOW + timedelta(days=30))

        self.assertEqual(report.orders, 1)
        self.assertEqual(report.revenue, 80.0)

    # --- who counts -------------------------------------------------------

    def test_a_skipped_recipient_does_not_attribute(self) -> None:
        campaign = self._campaign()
        customer = self._customer("Dee")
        self._recipient(
            campaign, customer, state=CampaignRecipientState.SKIPPED, failure_reason="No active device"
        )
        self._order(customer, created_at=SENT_AT + timedelta(days=1))

        report = build_attribution(self.session, campaign, now=NOW)

        self.assertEqual(report.orders, 0)

    def test_a_failed_recipient_does_not_attribute(self) -> None:
        campaign = self._campaign()
        customer = self._customer("Eve")
        self._recipient(
            campaign, customer, state=CampaignRecipientState.FAILED, failure_reason="Unregistered"
        )
        self._order(customer, created_at=SENT_AT + timedelta(days=1))

        report = build_attribution(self.session, campaign, now=NOW)

        self.assertEqual(report.orders, 0)

    def test_a_cancelled_order_is_not_revenue(self) -> None:
        campaign = self._campaign()
        customer = self._customer("Fay")
        self._recipient(campaign, customer)
        self._order(
            customer,
            created_at=SENT_AT + timedelta(days=1),
            status=OrderStatus.CANCELLED,
        )

        report = build_attribution(self.session, campaign, now=NOW)

        self.assertEqual(report.orders, 0)
        self.assertEqual(report.revenue, 0.0)

    # --- the shape of the report -----------------------------------------

    def test_discount_is_subtracted_from_net_revenue(self) -> None:
        campaign = self._campaign()
        customer = self._customer("Gus")
        self._recipient(campaign, customer)
        self._order(
            customer, created_at=SENT_AT + timedelta(days=1), total="100.00", discount="30.00"
        )

        report = build_attribution(self.session, campaign, now=NOW)

        self.assertEqual(report.revenue, 100.0)
        self.assertEqual(report.discount_given, 30.0)
        self.assertEqual(report.net_revenue, 70.0)

    def test_returning_and_new_customers_are_split_by_prior_history(self) -> None:
        campaign = self._campaign()
        returning = self._customer("Hana")
        brand_new = self._customer("Ivan")
        self._recipient(campaign, returning)
        self._recipient(campaign, brand_new)

        # Hana ordered long before the campaign; Ivan never had.
        self._order(returning, created_at=SENT_AT - timedelta(days=90))
        self._order(returning, created_at=SENT_AT + timedelta(days=1))
        self._order(brand_new, created_at=SENT_AT + timedelta(days=1))

        report = build_attribution(self.session, campaign, now=NOW)

        self.assertEqual(report.orders, 2)
        self.assertEqual(report.returning_customers, 1)
        self.assertEqual(report.new_customers, 1)

    def test_the_window_reports_itself_as_open_while_it_is_still_collecting(self) -> None:
        campaign = self._campaign(window_days=7)
        self.assertTrue(
            build_attribution(self.session, campaign, now=SENT_AT + timedelta(days=2)).window_open
        )
        self.assertFalse(
            build_attribution(self.session, campaign, now=SENT_AT + timedelta(days=8)).window_open
        )

    def test_a_campaign_that_has_not_sent_has_no_report(self) -> None:
        campaign = self._campaign(status=PushNotificationCampaignStatus.DRAFT)
        self.assertIsNone(build_attribution(self.session, campaign, now=NOW))

    def test_the_daily_series_does_not_run_into_the_future(self) -> None:
        """A window still open shows the days that happened, not a run of zeroes."""

        campaign = self._campaign(window_days=7)
        report = build_attribution(self.session, campaign, now=SENT_AT + timedelta(days=2))
        self.assertEqual(len(report.daily), 3)

    def test_failure_reasons_are_counted_by_reason(self) -> None:
        campaign = self._campaign()
        for index in range(3):
            self._recipient(
                campaign,
                self._customer(f"NoDevice{index}"),
                state=CampaignRecipientState.SKIPPED,
                failure_reason="No active device",
            )
        self._recipient(
            campaign,
            self._customer("Dead"),
            state=CampaignRecipientState.FAILED,
            failure_reason="Unregistered",
        )

        reasons = failure_reason_view(self.session, campaign)

        self.assertEqual(reasons[0], {"reason": "No active device", "count": 3})
        self.assertEqual(reasons[1], {"reason": "Unregistered", "count": 1})

    # --- the dashboard ----------------------------------------------------

    def test_the_dashboard_totals_only_what_was_attributed(self) -> None:
        campaign = self._campaign()
        customer = self._customer("Jo")
        self._recipient(campaign, customer)
        self._order(customer, created_at=SENT_AT + timedelta(days=1), total="120.00")

        view = build_dashboard(self.session, restaurant_id=self.restaurant_id, now=NOW)

        self.assertEqual(view.campaigns_sent_30d, 1)
        self.assertEqual(view.attributed_orders_30d, 1)
        self.assertEqual(view.attributed_revenue_30d, 120.0)
        self.assertIsNotNone(view.best_campaign)
        self.assertEqual(view.best_campaign.net_revenue, 120.0)
        # Zero-filled across the window, so the chart cannot imply trade on a
        # day that had none.
        self.assertEqual(len(view.revenue_trend), 30)

    def test_an_empty_workspace_reports_zero_rather_than_a_mock(self) -> None:
        view = build_dashboard(self.session, restaurant_id=self.restaurant_id, now=NOW)

        self.assertEqual(view.campaigns_sent_30d, 0)
        self.assertEqual(view.attributed_revenue_30d, 0.0)
        self.assertIsNone(view.best_campaign)

    def test_a_failed_campaign_is_raised_for_attention(self) -> None:
        campaign = self._campaign(status=PushNotificationCampaignStatus.FAILED)
        campaign.last_error = "All notification deliveries failed"
        self.session.commit()

        view = build_dashboard(self.session, restaurant_id=self.restaurant_id, now=NOW)

        self.assertEqual(len(view.attention), 1)
        self.assertEqual(view.attention[0].tone, "critical")
        self.assertEqual(view.attention[0].campaign_id, campaign.id)


if __name__ == "__main__":
    unittest.main()
