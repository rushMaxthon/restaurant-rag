"""Offer and combo suggestion cards, and the actions attached to them.

The cards are the surface an owner clicks to create or start something real, so
the rules that matter here are about what a card *offers*: a Create button on a
proposal approval would refuse is worse than no button, and an Activate button
on an offer somebody deliberately retired is worse still.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

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
from app.models.generated_combo import GeneratedCombo, GeneratedComboItem
from app.models.menu_item import MenuItem
from app.models.owner_action import OwnerActionProposal
from app.models.personalized_offer import PersonalizedOffer
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.auth import get_current_user
from app.services.insights.actions import list_proposals
from app.services.insights.scope import InsightsScope
from app.services.insights.suggestion_cards import (
    combo_cards,
    offer_cards_from_catalogue,
    offer_cards_from_proposals,
)

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_suggestion_cards_test"


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
class SuggestionCardTests(unittest.TestCase):
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
            full_name="Card Owner",
            email="cards-owner@test.local",
            hashed_password="x",
            role=UserRole.OWNER,
        )
        stranger = User(
            id=uuid.uuid4(),
            app_client_id=None,
            full_name="Other Owner",
            email="cards-other@test.local",
            hashed_password="x",
            role=UserRole.OWNER,
        )
        session.add_all([owner, stranger])
        session.flush()
        cls.owner_id = owner.id
        cls.stranger_id = stranger.id

        def make_restaurant(user: User, name: str, slug: str) -> Restaurant:
            row = Restaurant(
                id=uuid.uuid4(),
                owner_id=user.id,
                name=name,
                slug=slug,
                cuisine_type="Thai",
                address_line_1="1 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                is_approved=True,
                is_active=True,
            )
            session.add(row)
            return row

        restaurant = make_restaurant(owner, "Card Kitchen", "card-kitchen")
        other = make_restaurant(stranger, "Other Kitchen", "other-kitchen")
        session.flush()
        cls.restaurant_id = restaurant.id
        cls.other_restaurant_id = other.id

        location = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            branch_name="Main",
            address_line_1="1 Test Street",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
        )
        session.add(location)
        session.flush()
        cls.location_id = location.id

        def make_item(name: str, price: str) -> MenuItem:
            row = MenuItem(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                restaurant_location_id=location.id,
                name=name,
                category="Mains",
                price=Decimal(price),
            )
            session.add(row)
            return row

        noodles = make_item("Pad Thai", "220.00")
        tea = make_item("Iced Tea", "80.00")
        session.flush()
        cls.noodles_id = noodles.id

        # -- proposals, one per status that matters -------------------------
        def make_proposal(
            status: OwnerActionStatus,
            title: str,
            *,
            executable: bool = True,
            expires_at: datetime | None = None,
        ) -> OwnerActionProposal:
            row = OwnerActionProposal(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                action_type=OwnerActionType.PROMOTE_ITEM,
                status=status,
                dedupe_key=f"card-{title}",
                priority=Decimal("1.0"),
                title=title,
                rationale="Sales fell and a short discount should recover part of it.",
                is_executable=executable,
                expected_impact_amount=Decimal("664.26"),
                expected_impact_basis="Estimate only.",
                action_payload={
                    "name": f"{title} offer",
                    "offer_type": PersonalizedOfferType.FAVORITE_ITEM.value,
                    "discount_type": PersonalizedOfferDiscountType.PERCENTAGE.value,
                    "discount_value": "10.00",
                    "minimum_order_amount": "199.00",
                    "valid_for_days": 7,
                    "applicable_item_id": str(noodles.id),
                },
                source_facts={},
                generated_at=datetime.now(UTC),
                expires_at=expires_at,
            )
            session.add(row)
            return row

        cls.proposed_id = make_proposal(OwnerActionStatus.PROPOSED, "Promote Pad Thai").id
        make_proposal(OwnerActionStatus.REJECTED, "Rejected idea")
        make_proposal(OwnerActionStatus.EXPIRED, "Expired idea")
        make_proposal(
            OwnerActionStatus.PROPOSED,
            "Stale idea",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        make_proposal(OwnerActionStatus.PROPOSED, "Advisory only", executable=False)

        # -- offers, one per state ------------------------------------------
        def make_offer(state: PersonalizedOfferState, name: str) -> PersonalizedOffer:
            row = PersonalizedOffer(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                restaurant_location_id=None,
                applicable_item_id=noodles.id,
                name=name,
                offer_type=PersonalizedOfferType.FAVORITE_ITEM,
                audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
                state=state,
                discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
                discount_value=Decimal("15.00"),
                minimum_order_amount=Decimal("199.00"),
            )
            session.add(row)
            return row

        cls.draft_offer_id = make_offer(PersonalizedOfferState.DRAFT, "Draft offer").id
        # The activation test mutates its target, and these tests share one
        # seeded database. Without a row of its own it would flip "Draft offer"
        # to ACTIVE and the catalogue test would fail depending on run order.
        cls.activation_target_id = make_offer(
            PersonalizedOfferState.DRAFT, "Activation target"
        ).id
        cls.paused_offer_id = make_offer(PersonalizedOfferState.PAUSED, "Paused offer").id
        cls.active_offer_id = make_offer(PersonalizedOfferState.ACTIVE, "Active offer").id
        cls.disabled_offer_id = make_offer(
            PersonalizedOfferState.DISABLED, "Disabled offer"
        ).id

        # An offer belonging to somebody else, to prove the scope holds.
        foreign = PersonalizedOffer(
            id=uuid.uuid4(),
            restaurant_id=other.id,
            name="Foreign offer",
            offer_type=PersonalizedOfferType.FAVORITE_ITEM,
            audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
            state=PersonalizedOfferState.DRAFT,
            discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
            discount_value=Decimal("15.00"),
            minimum_order_amount=Decimal("0.00"),
        )
        session.add(foreign)
        session.flush()
        cls.foreign_offer_id = foreign.id

        # -- combos ----------------------------------------------------------
        def make_combo(
            name: str, status: str, *, active: bool, original: str, offered: str
        ) -> GeneratedCombo:
            row = GeneratedCombo(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                restaurant_location_id=location.id,
                signature=f"sig-{name}",
                combo_name=name,
                description=None,
                order_count=4,
                unique_user_count=2,
                confidence_score=Decimal("0.8"),
                status=status,
                is_customer_visible=active,
                original_total_price=Decimal(original),
                suggested_combo_price=Decimal(offered),
                is_active=active,
                generated_from_orders=True,
                last_seen_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            for index, item in enumerate((noodles, tea)):
                session.add(
                    GeneratedComboItem(
                        id=uuid.uuid4(),
                        combo_id=row.id,
                        menu_item_id=item.id,
                        quantity=1,
                        sort_order=index,
                    )
                )
            return row

        cls.draft_combo_id = make_combo(
            "Pad Thai + Iced Tea", "DRAFT", active=False, original="300.00", offered="270.00"
        ).id
        cls.live_combo_id = make_combo(
            "Live combo", "LIVE", active=True, original="300.00", offered="280.00"
        ).id
        session.commit()

    def _scope(self) -> InsightsScope:
        return InsightsScope(restaurant_id=self.restaurant_id, restaurant_location_id=None)

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

    # -- which proposals earn a card ---------------------------------------

    def test_only_proposals_approval_accepts_get_a_create_card(self) -> None:
        # The regression this guards: a REJECTED proposal is still "executable"
        # in the column sense, so it used to render a Create button - and
        # approving a rejected proposal raises, so the button could only fail.
        with self.session_factory() as session:
            proposals = list_proposals(session, scope=self._scope(), limit=50)
            cards = offer_cards_from_proposals(session, proposals, limit=10)

        titles = {card["title"] for card in cards}
        self.assertIn("Promote Pad Thai offer", titles)
        for refused in ("Rejected idea offer", "Expired idea offer", "Stale idea offer"):
            self.assertNotIn(refused, titles)

    def test_an_advisory_proposal_gets_no_card(self) -> None:
        # Nothing is created by approving it, so there is nothing to offer.
        with self.session_factory() as session:
            proposals = list_proposals(session, scope=self._scope(), limit=50)
            cards = offer_cards_from_proposals(session, proposals, limit=10)
        self.assertNotIn("Advisory only offer", {card["title"] for card in cards})

    def test_a_create_card_names_the_dish_not_its_id(self) -> None:
        with self.session_factory() as session:
            proposals = list_proposals(session, scope=self._scope(), limit=50)
            card = offer_cards_from_proposals(session, proposals, limit=10)[0]

        self.assertEqual(card["state"], "creatable")
        self.assertEqual(card["action"], "create")
        self.assertEqual(card["details"][0], {"label": "Applies to", "value": "Pad Thai"})
        self.assertEqual(card["discount"], {"type": "PERCENTAGE", "value": 10.0})
        self.assertEqual(card["minimum_order_amount"], 199.0)
        self.assertEqual(card["valid_for_days"], 7)

    # -- the offer catalogue ------------------------------------------------

    def test_only_reversible_offer_states_are_offered_for_activation(self) -> None:
        # DISABLED and ACTIVE are both excluded, for opposite reasons: one is a
        # deliberate end state, the other is already running.
        with self.session_factory() as session:
            cards = offer_cards_from_catalogue(session, self._scope(), limit=10)

        names = {card["title"] for card in cards}
        # Asserted by inclusion/exclusion rather than equality: "Activation
        # target" is the row the activation test flips, so whether it is still
        # DRAFT here depends on test order.
        self.assertIn("Draft offer", names)
        self.assertIn("Paused offer", names)
        self.assertNotIn("Active offer", names)
        self.assertNotIn("Disabled offer", names)
        for card in cards:
            self.assertEqual(card["action"], "activate")
            self.assertEqual(card["state"], "activatable")

    def test_the_catalogue_is_scoped_to_the_callers_restaurant(self) -> None:
        with self.session_factory() as session:
            cards = offer_cards_from_catalogue(session, self._scope(), limit=10)
        self.assertNotIn("Foreign offer", {card["title"] for card in cards})

    # -- combos --------------------------------------------------------------

    def test_a_draft_combo_offers_activation_and_a_live_one_does_not(self) -> None:
        with self.session_factory() as session:
            cards = {card["title"]: card for card in combo_cards(session, self._scope(), limit=10)}

        draft = cards["Pad Thai + Iced Tea"]
        self.assertEqual(draft["state"], "activatable")
        self.assertEqual(draft["action"], "activate")

        live = cards["Live combo"]
        self.assertEqual(live["state"], "active")
        self.assertIsNone(live["action"])

    def test_a_combo_card_carries_both_prices_and_the_saving(self) -> None:
        with self.session_factory() as session:
            cards = {card["title"]: card for card in combo_cards(session, self._scope(), limit=10)}

        pricing = cards["Pad Thai + Iced Tea"]["pricing"]
        self.assertEqual(pricing["original"], 300.0)
        self.assertEqual(pricing["offered"], 270.0)
        # Sent, not derived on the client, so the three figures always agree.
        self.assertEqual(pricing["saving"], 30.0)

    def test_a_combo_card_lists_its_items_by_name(self) -> None:
        with self.session_factory() as session:
            cards = {card["title"]: card for card in combo_cards(session, self._scope(), limit=10)}
        labels = [row["label"] for row in cards["Pad Thai + Iced Tea"]["details"]]
        self.assertEqual(labels, ["Pad Thai", "Iced Tea"])

    def test_actionable_combos_are_ranked_above_live_ones(self) -> None:
        with self.session_factory() as session:
            cards = combo_cards(session, self._scope(), limit=10)
        self.assertEqual(cards[0]["title"], "Pad Thai + Iced Tea")

    # -- the activation endpoint --------------------------------------------

    def test_activating_a_draft_offer_starts_it(self) -> None:
        response = self._client_as(self.owner_id).post(
            f"/api/owner/insights/suggestions/offers/{self.activation_target_id}/activate"
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["state"], "ACTIVE")
        self.assertFalse(body["already_active"])

        with self.session_factory() as session:
            offer = session.get(PersonalizedOffer, self.activation_target_id)
            self.assertEqual(offer.state, PersonalizedOfferState.ACTIVE)

    def test_activating_a_running_offer_is_idempotent(self) -> None:
        # A stale card, or a double click, reports the end state rather than
        # failing the second call.
        response = self._client_as(self.owner_id).post(
            f"/api/owner/insights/suggestions/offers/{self.active_offer_id}/activate"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["already_active"])

    def test_a_disabled_offer_cannot_be_revived_from_a_card(self) -> None:
        response = self._client_as(self.owner_id).post(
            f"/api/owner/insights/suggestions/offers/{self.disabled_offer_id}/activate"
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("Offers screen", response.json()["detail"])

    def test_another_restaurants_offer_is_not_found(self) -> None:
        # A 404 rather than a 403: a 403 would confirm the offer exists.
        response = self._client_as(self.owner_id).post(
            f"/api/owner/insights/suggestions/offers/{self.foreign_offer_id}/activate"
        )
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
