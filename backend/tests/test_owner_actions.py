"""Integration tests for the action proposal lifecycle.

Approving a proposal creates a real offer and can cost real money, so these
cover the safety properties as much as the happy path: caps re-checked at
execution, idempotency, failures recorded rather than swallowed, and no
cross-restaurant reach.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # imported first to settle import order
from app.config import get_settings
from app.config.database import get_db
from app.models.base import Base
from app.models.enums import (
    OwnerActionStatus,
    OwnerActionType,
    PersonalizedOfferAudience,
    PersonalizedOfferDiscountType,
    PersonalizedOfferState,
    PersonalizedOfferType,
    UserRole,
)
from app.models.owner_action import OwnerActionProposal
from app.models.personalized_offer import PersonalizedOffer
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.auth import get_current_user
from app.services.insights import actions as actions_module
from app.services.insights.actions import (
    ActionValidationError,
    approve_proposal,
    default_expiry,
    expire_stale_proposals,
    is_expired,
    list_proposals,
    reject_proposal,
    validate_payload,
)
from app.services.insights.scope import InsightsScope
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()

TEST_DB_NAME = os.environ.get("ACTIONS_TEST_DB", "restaurant_rag_actions_test")


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


def offer_payload(**overrides) -> dict:
    payload = {
        "name": "Margherita Pizza boost",
        "offer_type": PersonalizedOfferType.FAVORITE_ITEM.value,
        "audience_type": PersonalizedOfferAudience.ALL_CUSTOMERS.value,
        "state": PersonalizedOfferState.ACTIVE.value,
        "discount_type": PersonalizedOfferDiscountType.PERCENTAGE.value,
        "discount_value": "10.00",
        "minimum_order_amount": "199.00",
        "valid_for_days": 7,
        "cta_label": "Order now",
        "notes": "Proposed by tests.",
        "business_rules": {},
    }
    payload.update(overrides)
    return payload


class PayloadValidationTests(unittest.TestCase):
    """Caps are re-checked at execution, not only when a proposal is written."""

    def test_valid_payload_passes(self) -> None:
        parsed = validate_payload(offer_payload())
        self.assertEqual(parsed.discount_value, Decimal("10.00"))

    def test_percentage_over_the_cap_is_refused(self) -> None:
        with self.assertRaises(ActionValidationError) as raised:
            validate_payload(offer_payload(discount_value="90.00"))
        self.assertIn("exceeds the maximum", str(raised.exception))

    def test_flat_discount_over_the_cap_is_refused(self) -> None:
        with self.assertRaises(ActionValidationError):
            validate_payload(
                offer_payload(
                    discount_type=PersonalizedOfferDiscountType.FLAT.value,
                    discount_value="99999.00",
                )
            )

    def test_minimum_order_below_the_threshold_is_refused(self) -> None:
        with self.assertRaises(ActionValidationError) as raised:
            validate_payload(offer_payload(minimum_order_amount="1.00"))
        self.assertIn("below the threshold", str(raised.exception))

    def test_malformed_payload_is_refused(self) -> None:
        with self.assertRaises(ActionValidationError) as raised:
            validate_payload({"name": "x"})
        self.assertIn("not a valid offer", str(raised.exception))

    def test_a_tightened_cap_invalidates_an_existing_payload(self) -> None:
        # A proposal can sit for days. If policy tightens underneath it, the
        # stored payload must stop being executable.
        payload = offer_payload(discount_value="25.00")
        validate_payload(payload)

        previous = settings.ai_max_percentage_discount
        try:
            settings.ai_max_percentage_discount = Decimal("15.00")
            with self.assertRaises(ActionValidationError):
                validate_payload(payload)
        finally:
            settings.ai_max_percentage_discount = previous


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class ActionLifecycleTests(unittest.TestCase):
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
        def make_owner(name: str, email: str) -> User:
            user = User(
                id=uuid.uuid4(),
                app_client_id=None,
                full_name=name,
                email=email,
                hashed_password="x",
                role=UserRole.OWNER,
            )
            session.add(user)
            return user

        owner_a = make_owner("Owner A", "act-owner-a@test.local")
        owner_b = make_owner("Owner B", "act-owner-b@test.local")
        session.flush()

        def make_restaurant(owner: User, name: str, slug: str) -> Restaurant:
            restaurant = Restaurant(
                id=uuid.uuid4(),
                owner_id=owner.id,
                name=name,
                slug=slug,
                cuisine_type="Italian",
                address_line_1="1 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                is_approved=True,
                is_active=True,
            )
            session.add(restaurant)
            return restaurant

        restaurant_a = make_restaurant(owner_a, "Action Restaurant A", "action-restaurant-a")
        restaurant_b = make_restaurant(owner_b, "Action Restaurant B", "action-restaurant-b")
        session.flush()

        for restaurant, branch in ((restaurant_a, "A Main"), (restaurant_b, "B Main")):
            session.add(
                RestaurantLocation(
                    id=uuid.uuid4(),
                    restaurant_id=restaurant.id,
                    branch_name=branch,
                    address_line_1="1 Test Street",
                    city="Bengaluru",
                    state="Karnataka",
                    postal_code="560001",
                )
            )

        session.commit()
        cls.restaurant_a = restaurant_a.id
        cls.restaurant_b = restaurant_b.id
        cls.owner_a_id = owner_a.id
        cls.owner_b_id = owner_b.id

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)
        self.addCleanup(self._reset)
        self.scope_a = InsightsScope(restaurant_id=self.restaurant_a)
        self.scope_b = InsightsScope(restaurant_id=self.restaurant_b)
        self.now = datetime(2026, 3, 16, 4, 30, tzinfo=UTC)

    def _reset(self) -> None:
        with self.session_factory() as session:
            session.query(OwnerActionProposal).delete()
            session.query(PersonalizedOffer).delete()
            session.commit()

    def _proposal(
        self,
        *,
        restaurant_id: uuid.UUID | None = None,
        executable: bool = True,
        payload: dict | None = None,
        status: OwnerActionStatus = OwnerActionStatus.PROPOSED,
        expires_at: datetime | None = None,
        action_type: OwnerActionType = OwnerActionType.PROMOTE_ITEM,
    ) -> OwnerActionProposal:
        proposal = OwnerActionProposal(
            id=uuid.uuid4(),
            restaurant_id=restaurant_id or self.restaurant_a,
            action_type=action_type,
            status=status,
            dedupe_key=f"{action_type.value}:{uuid.uuid4()}",
            priority=Decimal("1000"),
            title="Promote Margherita Pizza",
            rationale="Sales fell.",
            is_executable=executable,
            expected_impact_amount=Decimal("500.00"),
            expected_impact_basis="Estimate only.",
            action_payload=payload if payload is not None else (offer_payload() if executable else {}),
            source_facts={"absolute_change": -1000.0},
            generated_at=self.now,
            # Default to an expiry relative to the real clock, since the
            # endpoint path resolves "now" itself and the seeded scenario date
            # is deliberately historical.
            expires_at=(
                expires_at
                if expires_at is not None
                else default_expiry(datetime.now(UTC))
            ),
        )
        self.session.add(proposal)
        self.session.commit()
        return proposal

    # -- approval ----------------------------------------------------------

    def test_approving_an_executable_proposal_creates_an_offer(self) -> None:
        proposal = self._proposal()
        result = approve_proposal(
            self.session, proposal=proposal, decided_by_user_id=self.owner_a_id, now=self.now
        )

        self.assertIsNotNone(result.offer_id)
        self.assertEqual(result.proposal.status, OwnerActionStatus.EXECUTED)
        self.assertEqual(result.proposal.executed_offer_id, result.offer_id)

        offer = self.session.get(PersonalizedOffer, result.offer_id)
        self.assertEqual(offer.restaurant_id, self.restaurant_a)
        self.assertEqual(offer.discount_value, Decimal("10.00"))
        self.assertEqual(offer.state, PersonalizedOfferState.ACTIVE)

    def test_approving_an_advisory_creates_nothing(self) -> None:
        proposal = self._proposal(
            executable=False, action_type=OwnerActionType.OPERATIONAL_REVIEW
        )
        result = approve_proposal(
            self.session, proposal=proposal, decided_by_user_id=self.owner_a_id, now=self.now
        )

        self.assertIsNone(result.offer_id)
        self.assertEqual(result.proposal.status, OwnerActionStatus.APPROVED)
        self.assertEqual(self.session.query(PersonalizedOffer).count(), 0)

    def test_approving_twice_does_not_create_a_second_offer(self) -> None:
        # A double-click must not double-spend.
        proposal = self._proposal()
        first = approve_proposal(self.session, proposal=proposal, now=self.now)
        second = approve_proposal(self.session, proposal=proposal, now=self.now)

        self.assertFalse(first.already_executed)
        self.assertTrue(second.already_executed)
        self.assertEqual(first.offer_id, second.offer_id)
        self.assertEqual(self.session.query(PersonalizedOffer).count(), 1)

    def test_payload_over_the_cap_fails_without_creating_an_offer(self) -> None:
        proposal = self._proposal(payload=offer_payload(discount_value="95.00"))
        with self.assertRaises(ActionValidationError):
            approve_proposal(self.session, proposal=proposal, now=self.now)

        self.session.refresh(proposal)
        self.assertEqual(proposal.status, OwnerActionStatus.FAILED)
        self.assertIn("exceeds the maximum", proposal.failure_reason)
        self.assertEqual(self.session.query(PersonalizedOffer).count(), 0)

    def test_offer_creation_failure_is_recorded_not_swallowed(self) -> None:
        proposal = self._proposal()
        with patch(
            "app.services.personalized_offers.create_restaurant_offer",
            side_effect=RuntimeError("database exploded"),
        ):
            with self.assertRaises(ActionValidationError):
                approve_proposal(self.session, proposal=proposal, now=self.now)

        refreshed = self.session.get(OwnerActionProposal, proposal.id)
        self.session.refresh(refreshed)
        self.assertEqual(refreshed.status, OwnerActionStatus.FAILED)
        self.assertIn("database exploded", refreshed.failure_reason)
        self.assertEqual(self.session.query(PersonalizedOffer).count(), 0)

    def test_rejected_proposal_cannot_be_approved(self) -> None:
        proposal = self._proposal()
        reject_proposal(self.session, proposal=proposal, now=self.now)
        with self.assertRaises(ActionValidationError):
            approve_proposal(self.session, proposal=proposal, now=self.now)
        self.assertEqual(self.session.query(PersonalizedOffer).count(), 0)

    # -- expiry ------------------------------------------------------------

    def test_expired_proposal_is_refused_and_marked(self) -> None:
        proposal = self._proposal(expires_at=self.now - timedelta(days=1))
        with self.assertRaises(ActionValidationError) as raised:
            approve_proposal(self.session, proposal=proposal, now=self.now)

        self.assertIn("expired", str(raised.exception))
        self.session.refresh(proposal)
        self.assertEqual(proposal.status, OwnerActionStatus.EXPIRED)
        self.assertEqual(self.session.query(PersonalizedOffer).count(), 0)

    def test_expire_stale_proposals_sweeps_undecided_rows(self) -> None:
        self._proposal(expires_at=self.now - timedelta(days=1))
        self._proposal(expires_at=self.now + timedelta(days=1))

        swept = expire_stale_proposals(
            self.session, restaurant_id=self.restaurant_a, now=self.now
        )
        self.session.commit()

        self.assertEqual(swept, 1)
        statuses = {
            row.status
            for row in self.session.scalars(
                select(OwnerActionProposal).where(
                    OwnerActionProposal.restaurant_id == self.restaurant_a
                )
            ).all()
        }
        self.assertEqual(statuses, {OwnerActionStatus.EXPIRED, OwnerActionStatus.PROPOSED})

    def test_is_expired_handles_a_proposal_without_an_expiry(self) -> None:
        proposal = self._proposal()
        proposal.expires_at = None
        self.assertFalse(is_expired(proposal, now=self.now))

    # -- isolation ---------------------------------------------------------

    def test_listing_is_scoped_to_one_restaurant(self) -> None:
        self._proposal(restaurant_id=self.restaurant_a)
        self._proposal(restaurant_id=self.restaurant_b)

        rows_a = list_proposals(self.session, scope=self.scope_a)
        rows_b = list_proposals(self.session, scope=self.scope_b)

        self.assertEqual(len(rows_a), 1)
        self.assertEqual(len(rows_b), 1)
        self.assertEqual(rows_a[0].restaurant_id, self.restaurant_a)

    def test_executed_offer_belongs_to_the_proposals_restaurant(self) -> None:
        # The payload never carries a restaurant id; it comes from the proposal,
        # so an offer cannot be created against someone else's restaurant.
        proposal = self._proposal(restaurant_id=self.restaurant_b)
        result = approve_proposal(self.session, proposal=proposal, now=self.now)
        offer = self.session.get(PersonalizedOffer, result.offer_id)
        self.assertEqual(offer.restaurant_id, self.restaurant_b)

    # -- endpoints ---------------------------------------------------------

    def _client_as(self, user_id: uuid.UUID) -> TestClient:
        session_factory = self.session_factory

        def override_db():
            with session_factory() as session:
                yield session

        def override_current_user() -> User:
            with session_factory() as session:
                return session.get(User, user_id)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_current_user
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def test_recommendations_endpoint_lists_only_own_proposals(self) -> None:
        self._proposal(restaurant_id=self.restaurant_a)
        self._proposal(restaurant_id=self.restaurant_b)

        body = self._client_as(self.owner_a_id).get(
            "/api/owner/insights/recommendations"
        ).json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["restaurant_id"], str(self.restaurant_a))
        self.assertIn("Estimate only", body[0]["expected_impact_basis"])

    def test_approve_endpoint_creates_the_offer(self) -> None:
        proposal = self._proposal()
        response = self._client_as(self.owner_a_id).post(
            f"/api/owner/insights/recommendations/{proposal.id}/approve"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNotNone(body["offer_id"])
        self.assertEqual(body["proposal"]["status"], "EXECUTED")
        self.assertEqual(body["detail"], "Offer created.")

    def test_approve_endpoint_reports_a_cap_breach_as_422(self) -> None:
        proposal = self._proposal(payload=offer_payload(discount_value="95.00"))
        response = self._client_as(self.owner_a_id).post(
            f"/api/owner/insights/recommendations/{proposal.id}/approve"
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("exceeds the maximum", response.json()["detail"])

    def test_reject_endpoint_marks_the_proposal(self) -> None:
        proposal = self._proposal()
        response = self._client_as(self.owner_a_id).post(
            f"/api/owner/insights/recommendations/{proposal.id}/reject"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "REJECTED")

    def test_cannot_approve_another_restaurants_proposal(self) -> None:
        proposal = self._proposal(restaurant_id=self.restaurant_b)
        response = self._client_as(self.owner_a_id).post(
            f"/api/owner/insights/recommendations/{proposal.id}/approve"
        )
        # Scoped lookup, so it is indistinguishable from a missing row.
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.session.query(PersonalizedOffer).count(), 0)

    def test_cannot_reject_another_restaurants_proposal(self) -> None:
        proposal = self._proposal(restaurant_id=self.restaurant_b)
        response = self._client_as(self.owner_a_id).post(
            f"/api/owner/insights/recommendations/{proposal.id}/reject"
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
