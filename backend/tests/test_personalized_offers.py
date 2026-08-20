from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.enums import (
    OrderFulfillmentType,
    PersonalizedOfferAudience,
    PersonalizedOfferDiscountType,
    PersonalizedOfferGenerationReason,
    PersonalizedOfferSource,
    PersonalizedOfferState,
    PersonalizedOfferType,
    UserRole,
)
from app.models.personalized_offer import GeneratedOffer, GeneratedOfferUserMatch, PersonalizedOffer
from app.models.restaurant import Restaurant
from app.schemas.personalized_offer import GeneratedOfferUpdateRequest
from app.schemas.personalized_offer import PersonalizedOfferCardResponse, PersonalizedOfferPreviewRequest
from app.models.user_preferences import UserPreferences
from app.services.personalized_offers import (
    OfferSelection,
    UserOrderInsights,
    _apply_generated_offer_manual_overrides,
    _build_selection_for_offer,
    _compute_discount_amount,
    _descriptor_for_offer,
    _discount_label,
    _effective_state,
    _is_supported_manual_offer,
    _quantize,
    _serialize_generated_match_card,
    _terms_label,
    delete_restaurant_offer,
    ensure_global_welcome_offer,
    get_personalized_offers_for_user,
    preview_personalized_offer_for_user,
    sync_global_welcome_offer_for_user,
    update_generated_offer,
)


def make_restaurant(name: str = "Bangkok Bowl", cuisine: str = "Thai") -> Restaurant:
    return Restaurant(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name=name,
        slug=name.lower().replace(" ", "-"),
        description=None,
        cuisine_type=cuisine,
        address_line_1="123 Main St",
        address_line_2=None,
        city="Ahmedabad",
        state="Gujarat",
        country="India",
        postal_code="380001",
        phone_number=None,
        minimum_order_amount=Decimal("99.00"),
        delivery_fee=Decimal("20.00"),
        is_approved=True,
        is_open=True,
        is_active=True,
        logo_image_url=None,
        cover_image_url=None,
    )


def make_offer(
    *,
    offer_type: PersonalizedOfferType,
    state: PersonalizedOfferState = PersonalizedOfferState.ACTIVE,
    audience_type: PersonalizedOfferAudience = PersonalizedOfferAudience.ALL_CUSTOMERS,
    discount_type: PersonalizedOfferDiscountType = PersonalizedOfferDiscountType.NONE,
    discount_value: str = "0.00",
    max_discount_amount: str | None = None,
    minimum_order_amount: str = "299.00",
    inactivity_days: int = 14,
    valid_for_days: int = 3,
    applicable_cuisine: str | None = None,
) -> PersonalizedOffer:
    restaurant = make_restaurant()
    offer = PersonalizedOffer(
        id=uuid.uuid4(),
        restaurant_id=restaurant.id,
        name="Welcome Back",
        offer_type=offer_type,
        audience_type=audience_type,
        state=state,
        discount_type=discount_type,
        discount_value=Decimal(discount_value),
        max_discount_amount=Decimal(max_discount_amount) if max_discount_amount is not None else None,
        minimum_order_amount=Decimal(minimum_order_amount),
        inactivity_days=inactivity_days,
        cooldown_hours=48,
        valid_for_days=valid_for_days,
        applicable_cuisine=applicable_cuisine,
        business_rules={},
        starts_at=datetime.now(UTC) - timedelta(days=1),
        expires_at=datetime.now(UTC) + timedelta(days=2),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    offer.restaurant = restaurant
    offer.restaurant_location = None
    offer.applicable_item = None
    return offer


def make_preferences() -> UserPreferences:
    return UserPreferences(
        user_id=uuid.uuid4(),
        favorite_cuisines=["Thai"],
        disliked_cuisines=[],
        dietary_preferences=["VEG"],
        preferred_meal_times=[],
        price_sensitivity=Decimal("1.00"),
        average_budget=Decimal("250.00"),
        cuisine_affinity_scores={},
        spice_level="HIGH",
        budget_tier="MID",
        favorite_items=["Pad Thai Veg"],
    )


class PersonalizedOffersTests(unittest.TestCase):
    def test_update_generated_offer_tracks_manual_override_metadata(self) -> None:
        db = Mock()
        editor = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")
        generated_offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=None,
            generated_for_user_id=uuid.uuid4(),
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=None,
            applicable_item_id=None,
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.REPEATED_ORDER,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.FAVORITE_ITEM,
            audience_type=PersonalizedOfferAudience.ACTIVE_USERS,
            generated_title="Original title",
            generated_subtitle="Original subtitle",
            generated_badge="10% OFF",
            generated_cta_label="Order now",
            discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
            discount_value=Decimal("10.00"),
            minimum_order_amount=Decimal("99.00"),
            valid_for_days=7,
            score=Decimal("900.00"),
            eligible_user_count=1,
            business_metadata={"model": "qwen3:8b"},
            starts_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) + timedelta(days=2),
        )

        payload = GeneratedOfferUpdateRequest(
            title="Edited title",
            subtitle="Edited subtitle",
            badge="Limited Time",
            cta_label="Try again",
            state=PersonalizedOfferState.PAUSED,
        )

        updated = update_generated_offer(
            db,
            generated_offer=generated_offer,
            payload=payload,
            edited_by_user=editor,
        )

        self.assertEqual(updated.generated_title, "Edited title")
        self.assertEqual(updated.generated_subtitle, "Edited subtitle")
        self.assertEqual(updated.generated_badge, "Limited Time")
        self.assertEqual(updated.generated_cta_label, "Try again")
        self.assertEqual(updated.state, PersonalizedOfferState.PAUSED)
        self.assertTrue(updated.business_metadata["manually_edited"])
        self.assertEqual(updated.business_metadata["edited_by"], "admin@example.com")
        self.assertEqual(updated.business_metadata["manual_override"]["title"], "Edited title")
        self.assertEqual(updated.business_metadata["original_generated_offer_snapshot"]["title"], "Original title")
        db.add.assert_called_once_with(generated_offer)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(generated_offer)

    def test_update_generated_offer_rejects_invalid_state(self) -> None:
        db = Mock()
        editor = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")
        generated_offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=None,
            generated_for_user_id=uuid.uuid4(),
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=None,
            applicable_item_id=None,
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.REPEATED_ORDER,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.FAVORITE_ITEM,
            audience_type=PersonalizedOfferAudience.ACTIVE_USERS,
            generated_title="Original title",
            generated_subtitle="Original subtitle",
            generated_badge="10% OFF",
            generated_cta_label="Order now",
            discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
            discount_value=Decimal("10.00"),
            minimum_order_amount=Decimal("99.00"),
            valid_for_days=7,
            score=Decimal("900.00"),
            eligible_user_count=1,
            business_metadata={},
            starts_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) + timedelta(days=2),
        )

        with self.assertRaises(HTTPException):
            update_generated_offer(
                db,
                generated_offer=generated_offer,
                payload=GeneratedOfferUpdateRequest(state=PersonalizedOfferState.EXPIRED),
                edited_by_user=editor,
            )

    def test_apply_generated_offer_manual_overrides_restores_admin_copy(self) -> None:
        generated_offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=uuid.uuid4(),
            generated_for_user_id=None,
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=None,
            applicable_item_id=None,
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.REPEATED_ORDER,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.FAVORITE_ITEM,
            audience_type=PersonalizedOfferAudience.ACTIVE_USERS,
            generated_title="AI title",
            generated_subtitle="AI subtitle",
            generated_badge="AI badge",
            generated_cta_label="AI CTA",
            discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
            discount_value=Decimal("10.00"),
            minimum_order_amount=Decimal("99.00"),
            valid_for_days=7,
            score=Decimal("900.00"),
            eligible_user_count=1,
            business_metadata={
                "manually_edited": True,
                "manual_override": {
                    "title": "Admin title",
                    "subtitle": "Admin subtitle",
                    "badge": "Admin badge",
                    "cta_label": "Admin CTA",
                    "state": "PAUSED",
                },
            },
            starts_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) + timedelta(days=2),
        )

        _apply_generated_offer_manual_overrides(generated_offer)

        self.assertEqual(generated_offer.generated_title, "Admin title")
        self.assertEqual(generated_offer.generated_subtitle, "Admin subtitle")
        self.assertEqual(generated_offer.generated_badge, "Admin badge")
        self.assertEqual(generated_offer.generated_cta_label, "Admin CTA")
        self.assertEqual(generated_offer.state, PersonalizedOfferState.PAUSED)

    def test_percentage_discount_label_with_cap(self) -> None:
        offer = make_offer(
            offer_type=PersonalizedOfferType.FAVORITE_ITEM,
            discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
            discount_value="10.00",
            max_discount_amount="80.00",
        )
        self.assertEqual(_discount_label(offer), "10% OFF up to Rs 80")

    def test_discount_amount_respects_percentage_cap(self) -> None:
        offer = make_offer(
            offer_type=PersonalizedOfferType.FAVORITE_ITEM,
            discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
            discount_value="25.00",
            max_discount_amount="80.00",
        )
        self.assertEqual(_compute_discount_amount(offer, Decimal("500.00")), Decimal("80.00"))

    def test_discount_amount_respects_flat_total_ceiling(self) -> None:
        offer = make_offer(
            offer_type=PersonalizedOfferType.FAVORITE_ITEM,
            discount_type=PersonalizedOfferDiscountType.FLAT,
            discount_value="90.00",
        )
        self.assertEqual(_compute_discount_amount(offer, Decimal("60.00")), Decimal("60.00"))

    def test_terms_label_includes_inactivity_minimum_and_validity(self) -> None:
        offer = make_offer(offer_type=PersonalizedOfferType.FAVORITE_RESTAURANT)
        self.assertEqual(_terms_label(offer), "Inactive 14 days · Min Rs 299 · Valid 3 days")

    def test_effective_state_marks_expired_offer(self) -> None:
        offer = make_offer(offer_type=PersonalizedOfferType.FAVORITE_RESTAURANT)
        offer.expires_at = datetime.now(UTC) - timedelta(hours=1)
        self.assertEqual(_effective_state(offer), PersonalizedOfferState.EXPIRED)

    def test_cuisine_affinity_offer_picks_matching_restaurant(self) -> None:
        offer = make_offer(
            offer_type=PersonalizedOfferType.CUISINE_AFFINITY,
            applicable_cuisine="Thai",
        )
        recommendation = SimpleNamespace(
            id=uuid.uuid4(),
            restaurant_id=offer.restaurant_id,
            restaurant_location_id=uuid.uuid4(),
            name="Pad Thai Veg",
            category="Noodles",
            cuisine_type="Thai",
            recommendation_label="Recommended for You",
            restaurant=SimpleNamespace(
                name="Bangkok Bowl",
                slug="bangkok-bowl",
                cuisine_type="Thai",
            ),
            restaurant_location=SimpleNamespace(branch_name="Ellisbridge"),
        )
        selection = _build_selection_for_offer(
            None,  # type: ignore[arg-type]
            offer=offer,
            recommendations=[recommendation],
            preferences=make_preferences(),
            insights=UserOrderInsights(
                latest_order_at=datetime.now(UTC) - timedelta(days=20),
                average_order_value=Decimal("250.00"),
                favorite_restaurant_id=offer.restaurant_id,
                favorite_restaurant_name="Bangkok Bowl",
                favorite_restaurant_slug="bangkok-bowl",
                favorite_restaurant_cuisine="Thai",
                favorite_location_id=None,
                favorite_location_name=None,
                favorite_item_id=None,
                favorite_item_name=None,
                favorite_item_category=None,
                favorite_item_cuisine=None,
                top_cuisine="Thai",
            ),
        )
        self.assertIsInstance(selection, OfferSelection)
        assert selection is not None
        self.assertEqual(selection.target_type, "RESTAURANT")
        self.assertIn("Thai", selection.title)

    def test_custom_offer_type_is_supported_for_manual_and_generated_flows(self) -> None:
        offer = make_offer(offer_type=PersonalizedOfferType.CUSTOM)
        self.assertTrue(_is_supported_manual_offer(offer))

        descriptor = _descriptor_for_offer(None, offer)  # type: ignore[arg-type]
        self.assertIsNotNone(descriptor)
        assert descriptor is not None
        self.assertEqual(descriptor.restaurant_id, offer.restaurant_id)
        self.assertEqual(descriptor.generated_cta_label, "Explore now")

    def test_generated_match_card_uses_generated_offer_id_for_offer_id(self) -> None:
        restaurant = make_restaurant(name="Spice Route Indian Kitchen", cuisine="Indian")
        generated_offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=uuid.uuid4(),
            generated_for_user_id=None,
            restaurant_id=restaurant.id,
            restaurant_location_id=None,
            applicable_item_id=None,
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.FAVORITE_RESTAURANT,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.FAVORITE_RESTAURANT,
            audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
            generated_title="Recommended from Spice Route Indian Kitchen",
            generated_subtitle="Restaurant-wide campaign",
            generated_badge="Rs 15 OFF",
            generated_cta_label="Go go",
            discount_type=PersonalizedOfferDiscountType.FLAT,
            discount_value=Decimal("15.00"),
            minimum_order_amount=Decimal("45.00"),
            valid_for_days=7,
            score=Decimal("500.00"),
            eligible_user_count=1,
            business_metadata={},
            starts_at=datetime.now(UTC) - timedelta(minutes=5),
            expires_at=datetime.now(UTC) + timedelta(days=2),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        generated_offer.restaurant = restaurant
        match = GeneratedOfferUserMatch(
            id=uuid.uuid4(),
            generated_offer_id=generated_offer.id,
            user_id=uuid.uuid4(),
            matched_reason=PersonalizedOfferGenerationReason.FAVORITE_RESTAURANT,
            score=Decimal("500.00"),
            rank=1,
            is_current=True,
            target_type="RESTAURANT",
            target_id=str(restaurant.id),
            match_metadata={},
        )
        match.generated_offer = generated_offer

        card = _serialize_generated_match_card(match)

        self.assertIsNotNone(card)
        assert card is not None
        self.assertEqual(card.offer_id, generated_offer.id)
        self.assertEqual(card.generated_offer_id, generated_offer.id)

    @patch("app.services.personalized_offers._sync_generated_offer_matches_for_user")
    @patch("app.services.personalized_offers._load_live_manual_offer_cards_for_user")
    @patch("app.services.personalized_offers._ensure_generated_offers_bootstrapped")
    @patch("app.services.personalized_offers.cache_set_json")
    @patch("app.services.personalized_offers.cache_get_json")
    def test_custom_manual_offers_are_returned_from_customer_feed(
        self,
        mock_cache_get_json: Mock,
        mock_cache_set_json: Mock,
        mock_bootstrap: Mock,
        mock_load_manual_cards: Mock,
        mock_sync_matches: Mock,
    ) -> None:
        restaurant = make_restaurant(name="Spice Route Indian Kitchen", cuisine="Indian")
        custom_offer = make_offer(
            offer_type=PersonalizedOfferType.CUSTOM,
            discount_type=PersonalizedOfferDiscountType.FLAT,
            discount_value="15.00",
            minimum_order_amount="45.00",
        )
        custom_offer.name = "Diwali Special"
        custom_offer.restaurant = restaurant
        custom_offer.notes = "Flat Rs 15 off on orders above Rs 45."
        custom_offer.created_at = datetime.now(UTC)
        manual_card = PersonalizedOfferCardResponse(
            id=f"{custom_offer.id}:RESTAURANT:{restaurant.id}",
            generated_offer_id=None,
            generated_offer_user_match_id=None,
            offer_id=custom_offer.id,
            offer_name=custom_offer.name,
            offer_type=custom_offer.offer_type,
            audience_type=custom_offer.audience_type,
            badge="Rs 15 OFF",
            title=custom_offer.name,
            subtitle=custom_offer.notes,
            cta_label="View offer",
            target_type="RESTAURANT",
            restaurant_id=restaurant.id,
            restaurant_name=restaurant.name,
            restaurant_slug=restaurant.slug,
            restaurant_location_id=None,
            restaurant_location_name=None,
            offer_restaurant_location_id=None,
            menu_item_id=None,
            menu_item_name=None,
            generated_combo_id=None,
            generated_combo_name=None,
            cuisine_type=restaurant.cuisine_type,
            discount_type=PersonalizedOfferDiscountType.FLAT,
            discount_value=Decimal("15.00"),
            discount_label="Rs 15 OFF",
            max_discount_amount=None,
            minimum_order_amount=Decimal("45.00"),
            terms_label="Min Rs 45",
            valid_for_days=3,
            expires_at=custom_offer.expires_at,
            created_at=custom_offer.created_at,
        )
        user = SimpleNamespace(id=uuid.uuid4(), email="customer@example.com")

        mock_cache_get_json.return_value = None
        mock_load_manual_cards.return_value = [manual_card]
        mock_sync_matches.return_value = []

        cards = get_personalized_offers_for_user(
            Mock(),
            user=user,  # type: ignore[arg-type]
            limit=4,
        )

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].offer_name, "Diwali Special")
        self.assertEqual(cards[0].generated_offer_id, None)
        mock_bootstrap.assert_called()
        mock_cache_set_json.assert_called_once()

    def test_delete_restaurant_offer_detaches_generated_offers_before_template_delete(self) -> None:
        restaurant = make_restaurant(name="Spice Route Indian Kitchen", cuisine="Indian")
        offer = make_offer(offer_type=PersonalizedOfferType.CUSTOM)
        offer.restaurant_id = restaurant.id
        offer.business_rules = {"demo_target_emails": ["customer@example.com"]}

        generated_offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=offer.id,
            generated_for_user_id=None,
            restaurant_id=restaurant.id,
            restaurant_location_id=None,
            applicable_item_id=None,
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.FAVORITE_RESTAURANT,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.FAVORITE_RESTAURANT,
            audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
            generated_title="Recommended from Spice Route Indian Kitchen",
            generated_subtitle="Restaurant-wide campaign",
            generated_badge="Rs 15 OFF",
            generated_cta_label="Go go",
            discount_type=PersonalizedOfferDiscountType.FLAT,
            discount_value=Decimal("15.00"),
            minimum_order_amount=Decimal("45.00"),
            valid_for_days=7,
            score=Decimal("500.00"),
            eligible_user_count=1,
            business_metadata={},
            starts_at=datetime.now(UTC) - timedelta(minutes=5),
            expires_at=datetime.now(UTC) + timedelta(days=2),
        )

        linked_offers = Mock()
        linked_offers.all.return_value = [generated_offer]
        db = Mock()
        db.scalars.return_value = linked_offers

        with patch("app.services.personalized_offers.rebuild_generated_offers") as mock_rebuild, patch(
            "app.services.personalized_offers.invalidate_all_personalized_offer_caches"
        ) as mock_invalidate:
            delete_restaurant_offer(
                db,
                offer=offer,
            )

        self.assertIsNone(generated_offer.template_offer_id)
        self.assertEqual(
            generated_offer.business_metadata["template_provenance"]["detached_reason"],
            "template_deleted_by_admin",
        )
        db.delete.assert_called_once_with(offer)
        self.assertEqual(db.commit.call_count, 2)
        mock_rebuild.assert_called_once_with(db, restaurant_id=offer.restaurant_id)
        mock_invalidate.assert_called_once()

    @patch("app.services.personalized_offers.validate_generated_offer_for_order")
    @patch("app.services.personalized_offers._load_cart_preview_menu_items")
    def test_preview_generated_offer_uses_generated_ids(
        self,
        mock_load_cart_preview_menu_items: Mock,
        mock_validate_generated_offer_for_order: Mock,
    ) -> None:
        generated_offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=None,
            generated_for_user_id=uuid.uuid4(),
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=uuid.uuid4(),
            applicable_item_id=uuid.uuid4(),
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.REPEATED_ORDER,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.FAVORITE_ITEM,
            audience_type=PersonalizedOfferAudience.ACTIVE_USERS,
            generated_title="Save on Margherita Pizza",
            generated_subtitle="Built around your repeat pizza orders.",
            generated_badge="10% OFF",
            generated_cta_label="Try Again",
            discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
            discount_value=Decimal("10.00"),
            max_discount_amount=Decimal("100.00"),
            minimum_order_amount=Decimal("99.00"),
            valid_for_days=7,
            score=Decimal("900.00"),
            eligible_user_count=1,
            business_metadata={},
            starts_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) + timedelta(days=2),
        )
        user = SimpleNamespace(id=generated_offer.generated_for_user_id)
        payload = PersonalizedOfferPreviewRequest(
            offer_id=generated_offer.id,
            generated_offer_id=generated_offer.id,
            generated_offer_user_match_id=uuid.uuid4(),
            restaurant_id=generated_offer.restaurant_id,
            restaurant_location_id=generated_offer.restaurant_location_id,
            fulfillment_type=OrderFulfillmentType.DELIVERY,
            items=[
                {
                    "menu_item_id": generated_offer.applicable_item_id,
                    "quantity": 1,
                }
            ],
        )
        db = Mock()
        db.scalar.side_effect = [generated_offer, None]
        mock_load_cart_preview_menu_items.return_value = ([], Decimal("120.00"))
        mock_validate_generated_offer_for_order.return_value = (
            generated_offer,
            Decimal("12.00"),
        )

        preview = preview_personalized_offer_for_user(
            db,
            user=user,  # type: ignore[arg-type]
            payload=payload,
        )

        self.assertTrue(preview.eligible)
        self.assertEqual(preview.offer_name, "Save on Margherita Pizza")
        self.assertEqual(preview.discount_amount, _quantize(Decimal("12.00")))
        mock_validate_generated_offer_for_order.assert_called_once()
        self.assertEqual(
            mock_validate_generated_offer_for_order.call_args.kwargs[
                "generated_offer_id"
            ],
            generated_offer.id,
        )
        self.assertEqual(
            mock_validate_generated_offer_for_order.call_args.kwargs[
                "generated_offer_user_match_id"
            ],
            payload.generated_offer_user_match_id,
        )

    @patch("app.services.personalized_offers._pick_default_generated_offer_restaurant")
    def test_ensure_global_welcome_offer_creates_single_reusable_offer(
        self,
        mock_pick_default_restaurant: Mock,
    ) -> None:
        restaurant = make_restaurant()
        db = Mock()
        existing_offers = Mock()
        existing_offers.all.return_value = []
        db.scalars.return_value = existing_offers
        mock_pick_default_restaurant.return_value = restaurant

        offer = ensure_global_welcome_offer(db)

        self.assertIsNotNone(offer)
        assert offer is not None
        self.assertIsNone(offer.generated_for_user_id)
        self.assertEqual(offer.offer_type, PersonalizedOfferType.WELCOME_FIRST_ORDER)
        self.assertEqual(offer.discount_type, PersonalizedOfferDiscountType.PERCENTAGE)
        self.assertEqual(offer.discount_value, Decimal("15.00"))
        self.assertEqual(offer.minimum_order_amount, Decimal("149.00"))
        self.assertEqual(offer.business_metadata["offer_strategy"], "global_welcome")
        db.add.assert_called_once()
        db.flush.assert_called_once()

    @patch("app.services.personalized_offers._refresh_generated_offer_eligible_counts")
    @patch("app.services.personalized_offers.ensure_global_welcome_offer")
    @patch("app.services.personalized_offers._latest_paid_order_at")
    def test_sync_global_welcome_offer_for_user_attaches_reusable_match_for_new_user(
        self,
        mock_latest_paid_order_at: Mock,
        mock_ensure_global_welcome_offer: Mock,
        mock_refresh_counts: Mock,
    ) -> None:
        user = SimpleNamespace(
            id=uuid.uuid4(),
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        welcome_offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=None,
            generated_for_user_id=None,
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=None,
            applicable_item_id=None,
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.FIRST_ORDER,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.WELCOME_FIRST_ORDER,
            audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
            generated_title="Welcome offer",
            generated_subtitle="First-order offer",
            generated_badge="15% OFF",
            generated_cta_label="Start Here",
            discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
            discount_value=Decimal("15.00"),
            max_discount_amount=Decimal("100.00"),
            minimum_order_amount=Decimal("149.00"),
            valid_for_days=0,
            score=Decimal("980.00"),
            eligible_user_count=0,
            business_metadata={},
            starts_at=datetime.now(UTC) - timedelta(minutes=5),
            expires_at=None,
        )
        db = Mock()
        welcome_matches = Mock()
        welcome_matches.all.return_value = []
        legacy_offers = Mock()
        legacy_offers.all.return_value = []
        db.scalars.side_effect = [welcome_matches, legacy_offers]
        db.scalar.return_value = None
        mock_latest_paid_order_at.return_value = None
        mock_ensure_global_welcome_offer.return_value = welcome_offer

        attached = sync_global_welcome_offer_for_user(db, user=user)  # type: ignore[arg-type]

        self.assertTrue(attached)
        added_match = db.add.call_args.args[0]
        self.assertIsInstance(added_match, GeneratedOfferUserMatch)
        self.assertEqual(added_match.generated_offer_id, welcome_offer.id)
        self.assertEqual(added_match.user_id, user.id)
        self.assertTrue(added_match.is_current)
        mock_refresh_counts.assert_called_once()

    @patch("app.services.personalized_offers._refresh_generated_offer_eligible_counts")
    @patch("app.services.personalized_offers.ensure_global_welcome_offer")
    @patch("app.services.personalized_offers._latest_paid_order_at")
    def test_sync_global_welcome_offer_for_user_deactivates_match_after_first_paid_order(
        self,
        mock_latest_paid_order_at: Mock,
        mock_ensure_global_welcome_offer: Mock,
        mock_refresh_counts: Mock,
    ) -> None:
        user = SimpleNamespace(
            id=uuid.uuid4(),
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        welcome_offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=None,
            generated_for_user_id=None,
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=None,
            applicable_item_id=None,
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.FIRST_ORDER,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.WELCOME_FIRST_ORDER,
            audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
            generated_title="Welcome offer",
            generated_subtitle="First-order offer",
            generated_badge="15% OFF",
            generated_cta_label="Start Here",
            discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
            discount_value=Decimal("15.00"),
            minimum_order_amount=Decimal("149.00"),
            valid_for_days=0,
            score=Decimal("980.00"),
            eligible_user_count=1,
            business_metadata={},
            starts_at=datetime.now(UTC) - timedelta(minutes=5),
            expires_at=None,
        )
        match = GeneratedOfferUserMatch(
            generated_offer_id=welcome_offer.id,
            user_id=user.id,
            matched_reason=PersonalizedOfferGenerationReason.FIRST_ORDER,
            score=Decimal("500.00"),
            rank=1,
            is_current=True,
            match_metadata={},
        )
        match.generated_offer = welcome_offer
        db = Mock()
        welcome_matches = Mock()
        welcome_matches.all.return_value = [match]
        legacy_offers = Mock()
        legacy_offers.all.return_value = []
        db.scalars.side_effect = [welcome_matches, legacy_offers]
        mock_latest_paid_order_at.return_value = datetime.now(UTC)

        attached = sync_global_welcome_offer_for_user(db, user=user)  # type: ignore[arg-type]

        self.assertFalse(attached)
        self.assertFalse(match.is_current)
        mock_ensure_global_welcome_offer.assert_not_called()
        mock_refresh_counts.assert_called_once()


if __name__ == "__main__":
    unittest.main()
