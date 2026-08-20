"""Measuring what happened after an approved recommendation ran.

The risk here is not a wrong number, it is a *misread* one: an owner who
believes an offer caused revenue will keep paying for it. So these check the
maturity gate, the verdicts, and — as much as anything — that the wording stays
observational.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # imported first to settle import order
from app.config import get_settings
from app.config.database import get_db
from app.models.action_outcome import ActionOutcome
from app.models.base import Base
from app.models.enums import (
    ActionOutcomeVerdict,
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    OwnerActionStatus,
    OwnerActionType,
    PaymentMethod,
    PaymentStatus,
    PersonalizedOfferAudience,
    PersonalizedOfferDiscountType,
    PersonalizedOfferState,
    PersonalizedOfferType,
    UserRole,
)
from app.models.order import Order
from app.models.owner_action import OwnerActionProposal
from app.models.personalized_offer import PersonalizedOffer
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.auth import get_current_user
from app.services.insights.outcomes import (
    is_mature,
    list_outcomes,
    measure_due_outcomes,
    measure_proposal,
)
from app.services.insights.scope import InsightsScope
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()
TEST_DB_NAME = os.environ.get("OUTCOMES_TEST_DB", "restaurant_rag_outcomes_test")
IST = ZoneInfo("Asia/Kolkata")


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


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class ActionOutcomeTests(unittest.TestCase):
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

        # An offer that went live ten days ago, so it has matured.
        cls.executed_at = datetime.now(UTC) - timedelta(days=10)
        cls.window_start = cls.executed_at.date()

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
        def make_owner(name, email):
            user = User(id=uuid.uuid4(), full_name=name, email=email,
                        hashed_password="x", role=UserRole.OWNER)
            session.add(user)
            return user

        owner_a = make_owner("Owner A", "out-owner-a@t.local")
        owner_b = make_owner("Owner B", "out-owner-b@t.local")
        customer = User(id=uuid.uuid4(), full_name="C", email="out-cust@t.local",
                        hashed_password="x", role=UserRole.CUSTOMER)
        session.add(customer)
        session.flush()

        def make_restaurant(owner, name, slug):
            r = Restaurant(id=uuid.uuid4(), owner_id=owner.id, name=name, slug=slug,
                           cuisine_type="Italian", address_line_1="1 St", city="BLR",
                           state="KA", postal_code="560001", is_approved=True, is_active=True)
            session.add(r)
            return r

        restaurant_a = make_restaurant(owner_a, "Out A", "out-a")
        restaurant_b = make_restaurant(owner_b, "Out B", "out-b")
        session.flush()

        def make_location(r):
            loc = RestaurantLocation(id=uuid.uuid4(), restaurant_id=r.id, branch_name="Main",
                                     address_line_1="1 St", city="BLR", state="KA",
                                     postal_code="560001")
            session.add(loc)
            return loc

        location_a = make_location(restaurant_a)
        location_b = make_location(restaurant_b)
        session.flush()

        def make_offer(r, name):
            offer = PersonalizedOffer(
                id=uuid.uuid4(), restaurant_id=r.id, name=name,
                offer_type=PersonalizedOfferType.FAVORITE_ITEM,
                audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
                state=PersonalizedOfferState.ACTIVE,
                discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
                discount_value=Decimal("10.00"), minimum_order_amount=Decimal("199.00"),
            )
            session.add(offer)
            return offer

        offer_a = make_offer(restaurant_a, "A Offer")
        offer_b = make_offer(restaurant_b, "B Offer")
        session.commit()

        cls.owner_a_id = owner_a.id
        cls.restaurant_a = restaurant_a.id
        cls.restaurant_b = restaurant_b.id
        cls.location_a = location_a.id
        cls.location_b = location_b.id
        cls.offer_a = offer_a.id
        cls.offer_b = offer_b.id
        cls.customer_id = customer.id

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)
        self.addCleanup(self._reset)
        self.scope_a = InsightsScope(restaurant_id=self.restaurant_a)
        self.now = datetime.now(UTC)

    def _reset(self) -> None:
        with self.session_factory() as session:
            session.query(ActionOutcome).delete()
            session.query(OwnerActionProposal).delete()
            session.query(Order).delete()
            session.commit()

    def _proposal(
        self,
        *,
        restaurant_id=None,
        offer_id=None,
        status=OwnerActionStatus.EXECUTED,
        executed_at=None,
        estimate: Decimal | None = Decimal("1000.00"),
    ) -> OwnerActionProposal:
        proposal = OwnerActionProposal(
            id=uuid.uuid4(),
            restaurant_id=restaurant_id or self.restaurant_a,
            action_type=OwnerActionType.PROMOTE_ITEM,
            status=status,
            dedupe_key=f"k-{uuid.uuid4()}",
            priority=Decimal("100"),
            title="Promote Margherita",
            rationale="Sales fell.",
            is_executable=True,
            expected_impact_amount=estimate,
            expected_impact_basis="Estimate only.",
            action_payload={},
            source_facts={},
            generated_at=self.executed_at,
            executed_at=executed_at if executed_at is not None else self.executed_at,
            executed_offer_id=offer_id or self.offer_a,
        )
        self.session.add(proposal)
        self.session.commit()
        return proposal

    def _order(self, *, offer_id, restaurant_id, location_id, total, discount, days_ago=5):
        placed = datetime.combine(
            (datetime.now(IST) - timedelta(days=days_ago)).date(), time(13, 0), tzinfo=IST
        )
        order = Order(
            id=uuid.uuid4(), customer_id=self.customer_id, restaurant_id=restaurant_id,
            restaurant_location_id=location_id, status=OrderStatus.DELIVERED,
            payment_status=PaymentStatus.PAID, payment_method=PaymentMethod.CARD,
            payment_provider="test", fulfillment_type=OrderFulfillmentType.DELIVERY,
            schedule_type=OrderScheduleType.ASAP, scheduled_at=placed,
            subtotal=Decimal(total), delivery_fee=Decimal("0.00"), tax_amount=Decimal("0.00"),
            discount_amount=Decimal(discount), total_amount=Decimal(total), currency="INR",
            delivery_address="1 St", placed_at=placed, applied_offer_id=offer_id,
        )
        self.session.add(order)
        self.session.commit()
        return order

    # -- maturity gate -----------------------------------------------------

    def test_immature_action_is_not_measured(self) -> None:
        # Measuring too early would report "no uptake" for an offer that simply
        # had not been shown yet.
        proposal = self._proposal(executed_at=self.now - timedelta(days=1))
        self.assertFalse(is_mature(proposal, now=self.now))
        self.assertIsNone(measure_proposal(self.session, proposal=proposal, now=self.now))

    def test_matured_action_is_measured(self) -> None:
        proposal = self._proposal()
        self.assertTrue(is_mature(proposal, now=self.now))
        self.assertIsNotNone(measure_proposal(self.session, proposal=proposal, now=self.now))

    def test_unexecuted_proposal_is_never_measured(self) -> None:
        proposal = self._proposal(status=OwnerActionStatus.PROPOSED)
        self.assertIsNone(measure_proposal(self.session, proposal=proposal, now=self.now))

    # -- verdicts ----------------------------------------------------------

    def test_no_orders_reads_as_no_uptake(self) -> None:
        proposal = self._proposal()
        outcome = measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()

        self.assertEqual(outcome.verdict, ActionOutcomeVerdict.NO_UPTAKE)
        self.assertEqual(outcome.attributed_orders, 0)
        self.assertIn("No orders used this offer", outcome.summary)

    def test_revenue_above_the_estimate(self) -> None:
        proposal = self._proposal(estimate=Decimal("1000.00"))
        for _ in range(4):
            self._order(offer_id=self.offer_a, restaurant_id=self.restaurant_a,
                        location_id=self.location_a, total="900.00", discount="100.00")

        outcome = measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()

        self.assertEqual(outcome.attributed_orders, 4)
        self.assertEqual(outcome.attributed_revenue, Decimal("3600.00"))
        self.assertEqual(outcome.discount_cost, Decimal("400.00"))
        self.assertEqual(outcome.verdict, ActionOutcomeVerdict.ABOVE_ESTIMATE)

    def test_revenue_below_the_estimate(self) -> None:
        proposal = self._proposal(estimate=Decimal("5000.00"))
        self._order(offer_id=self.offer_a, restaurant_id=self.restaurant_a,
                    location_id=self.location_a, total="450.00", discount="50.00")

        outcome = measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()
        self.assertEqual(outcome.verdict, ActionOutcomeVerdict.BELOW_ESTIMATE)

    def test_revenue_within_tolerance_meets_the_estimate(self) -> None:
        proposal = self._proposal(estimate=Decimal("900.00"))
        self._order(offer_id=self.offer_a, restaurant_id=self.restaurant_a,
                    location_id=self.location_a, total="900.00", discount="100.00")

        outcome = measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()
        self.assertEqual(outcome.verdict, ActionOutcomeVerdict.MET_ESTIMATE)

    def test_uptake_without_an_estimate_is_not_measurable(self) -> None:
        proposal = self._proposal(estimate=None)
        self._order(offer_id=self.offer_a, restaurant_id=self.restaurant_a,
                    location_id=self.location_a, total="450.00", discount="50.00")

        outcome = measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()
        self.assertEqual(outcome.verdict, ActionOutcomeVerdict.NOT_MEASURABLE)
        self.assertIn("no estimate to compare", outcome.summary)

    # -- honesty of wording ------------------------------------------------

    def test_summary_never_claims_the_offer_caused_the_revenue(self) -> None:
        # There is no holdout group, so causal language would be a lie an owner
        # would spend money on.
        proposal = self._proposal()
        self._order(offer_id=self.offer_a, restaurant_id=self.restaurant_a,
                    location_id=self.location_a, total="900.00", discount="100.00")
        outcome = measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()

        lowered = outcome.summary.lower()
        # Causal *claims* are banned. The word "caused" is allowed only inside
        # the disclaimer that denies causation, which is checked below.
        for claim in (
            "this offer caused",
            "the offer generated",
            "the offer produced",
            "thanks to this offer",
            "because of this offer",
            "earned you",
            "lift",
        ):
            self.assertNotIn(claim, lowered)
        self.assertIn("used this offer", lowered)
        self.assertIn("not proof the offer caused", lowered)

    # -- idempotency and isolation ----------------------------------------

    def test_remeasuring_updates_rather_than_appends(self) -> None:
        proposal = self._proposal()
        measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()

        self._order(offer_id=self.offer_a, restaurant_id=self.restaurant_a,
                    location_id=self.location_a, total="900.00", discount="100.00")
        measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()

        rows = self.session.scalars(select(ActionOutcome)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].attributed_orders, 1)

    def test_another_restaurants_orders_are_never_attributed(self) -> None:
        proposal = self._proposal()
        # Restaurant B takes a lot of money on its own offer in the same window.
        for _ in range(5):
            self._order(offer_id=self.offer_b, restaurant_id=self.restaurant_b,
                        location_id=self.location_b, total="5000.00", discount="500.00")

        outcome = measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()
        self.assertEqual(outcome.attributed_orders, 0)
        self.assertEqual(outcome.attributed_revenue, Decimal("0.00"))

    def test_orders_using_a_different_offer_are_not_counted(self) -> None:
        proposal = self._proposal()
        self._order(offer_id=None, restaurant_id=self.restaurant_a,
                    location_id=self.location_a, total="900.00", discount="0.00")
        outcome = measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()
        self.assertEqual(outcome.attributed_orders, 0)

    # -- batch run ---------------------------------------------------------

    def test_batch_run_measures_matured_and_skips_the_rest(self) -> None:
        self._proposal()
        self._proposal(executed_at=self.now - timedelta(days=1))

        summary = measure_due_outcomes(self.session, now=self.now)
        self.assertEqual(summary.proposals_examined, 2)
        self.assertEqual(summary.outcomes_written, 1)
        self.assertEqual(summary.not_yet_mature, 1)

    def test_batch_run_is_scoped_when_asked(self) -> None:
        self._proposal(restaurant_id=self.restaurant_a)
        self._proposal(restaurant_id=self.restaurant_b, offer_id=self.offer_b)

        summary = measure_due_outcomes(
            self.session, restaurant_id=self.restaurant_a, now=self.now
        )
        self.assertEqual(summary.proposals_examined, 1)

    def test_listing_is_restaurant_scoped(self) -> None:
        self._proposal(restaurant_id=self.restaurant_a)
        self._proposal(restaurant_id=self.restaurant_b, offer_id=self.offer_b)
        measure_due_outcomes(self.session, now=self.now)

        rows_a = list_outcomes(self.session, scope=self.scope_a)
        self.assertEqual(len(rows_a), 1)
        self.assertEqual(rows_a[0].restaurant_id, self.restaurant_a)

    # -- endpoints ---------------------------------------------------------

    def _client(self) -> TestClient:
        factory = self.session_factory
        owner_id = self.owner_a_id

        def override_db():
            with factory() as session:
                yield session

        def override_user() -> User:
            with factory() as session:
                return session.get(User, owner_id)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def test_outcomes_endpoint_returns_measured_results(self) -> None:
        proposal = self._proposal()
        self._order(offer_id=self.offer_a, restaurant_id=self.restaurant_a,
                    location_id=self.location_a, total="900.00", discount="100.00")
        measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()

        response = self._client().get("/api/owner/insights/outcomes")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["attributed_orders"], 1)
        self.assertIn("used this offer", body[0]["summary"])

    def test_recommendations_carry_their_outcome(self) -> None:
        proposal = self._proposal()
        self._order(offer_id=self.offer_a, restaurant_id=self.restaurant_a,
                    location_id=self.location_a, total="900.00", discount="100.00")
        measure_proposal(self.session, proposal=proposal, now=self.now)
        self.session.commit()

        body = self._client().get(
            "/api/owner/insights/recommendations", params={"action_status": ["EXECUTED"]}
        ).json()
        self.assertEqual(len(body), 1)
        self.assertIsNotNone(body[0]["outcome"])
        self.assertEqual(body[0]["outcome"]["attributed_orders"], 1)

    def test_unmeasured_recommendation_has_no_outcome(self) -> None:
        self._proposal(status=OwnerActionStatus.PROPOSED)
        body = self._client().get("/api/owner/insights/recommendations").json()
        self.assertEqual(len(body), 1)
        self.assertIsNone(body[0]["outcome"])


if __name__ == "__main__":
    unittest.main()
