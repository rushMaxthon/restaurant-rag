from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.user_preferences import UserPreferences
from app.services.bestsellers import BESTSELLER_DYNAMIC_ATTR
from app.services.menu_item_metadata import build_generic_menu_item_badge_metadata
from app.services.rag import (
    ExtractedIntent,
    RetrievedMenuCandidate,
    SessionConversationState,
    _build_safe_reply,
    _fallback_extract_intent,
    _filter_candidates,
    _suggestion_items,
)
from app.services.recommendations import (
    OrderHistoryProfile,
    OrderHistoryScoreComponents,
    _build_recommendation_metadata,
    _model_to_profile,
    _new_item_boost_score,
    _preference_signal_scores,
)


def make_restaurant(*, cuisine_type: str = "Italian", is_open: bool = True) -> Restaurant:
    return Restaurant(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name=f"{cuisine_type} House",
        slug=f"{cuisine_type.lower()}-house",
        description=None,
        cuisine_type=cuisine_type,
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
        is_open=is_open,
        is_active=True,
        logo_image_url=None,
        cover_image_url=None,
    )


def make_menu_item(
    *,
    name: str,
    category: str,
    cuisine_type: str | None = None,
    description: str | None = None,
    is_veg: bool = False,
    is_available: bool = True,
    is_bestseller: bool = False,
    is_dynamic_bestseller: bool = False,
    popularity_score: str = "0.60",
    launched_days_ago: int = 2,
    is_new_launch: bool = True,
) -> MenuItem:
    now = datetime.now(UTC)
    launched_at = now - timedelta(days=launched_days_ago)
    menu_item = MenuItem(
        id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        restaurant_location_id=uuid.uuid4(),
        name=name,
        category=category,
        cuisine_type=cuisine_type,
        description=description,
        price=Decimal("249.00"),
        is_veg=is_veg,
        is_available=is_available,
        is_bestseller=is_bestseller,
        image_url=None,
        popularity_score=Decimal(popularity_score),
        launched_at=launched_at,
        is_new_launch=is_new_launch,
        created_at=launched_at,
        updated_at=now,
    )
    setattr(menu_item, BESTSELLER_DYNAMIC_ATTR, is_dynamic_bestseller)
    return menu_item


def make_preferences(
    *,
    cuisines: list[str] | None = None,
    favorite_items: list[str] | None = None,
    spice_level: str | None = None,
    diet: list[str] | None = None,
) -> UserPreferences:
    return UserPreferences(
        user_id=uuid.uuid4(),
        favorite_cuisines=cuisines or [],
        disliked_cuisines=[],
        dietary_preferences=diet or [],
        preferred_meal_times=[],
        price_sensitivity=Decimal("1.00"),
        average_budget=Decimal("250.00"),
        cuisine_affinity_scores={},
        spice_level=spice_level,
        budget_tier="MID",
        favorite_items=favorite_items or [],
    )


class RecommendedNewItemsTests(unittest.TestCase):
    def test_new_spicy_item_for_high_spice_user_gets_spicy_label(self) -> None:
        restaurant = make_restaurant(cuisine_type="Indian")
        menu_item = make_menu_item(
            name="Peri-Peri Chicken Bowl",
            category="Bowls",
            cuisine_type="Indian",
            description="A spicy peri peri chicken bowl with hot chilli sauce.",
        )
        preferences = _model_to_profile(
            make_preferences(
                cuisines=["Indian"],
                favorite_items=["spicy chicken"],
                spice_level="HIGH",
            )
        )
        self.assertIsNotNone(preferences)
        boost, components = _new_item_boost_score(
            menu_item,
            restaurant,
            preferences=preferences,
            history_profile=None,
            historical_cuisine_scores={},
            popularity=0.65,
            preference_signal_scores=_preference_signal_scores(preferences),
            history_signal_scores={},
            order_history_components=None,
        )
        label, reason, _ = _build_recommendation_metadata(
            menu_item,
            restaurant,
            preferences=preferences,
            history_profile=None,
            preference_match=0.88,
            order_history=0.0,
            popularity=0.65,
            new_item_components=components,
        )

        self.assertGreater(boost, 0.0)
        self.assertEqual(label, "Matches Your Taste")
        self.assertEqual(reason, "Aligned with your spice and taste preferences.")

    def test_new_cuisine_item_for_cuisine_pref_user_gets_cuisine_label(self) -> None:
        restaurant = make_restaurant(cuisine_type="Italian")
        menu_item = make_menu_item(
            name="Truffle Ravioli",
            category="Pasta",
            cuisine_type="Italian",
            description="Fresh ravioli finished with truffle cream.",
            is_veg=True,
        )
        preferences = _model_to_profile(
            make_preferences(
                cuisines=["Italian"],
                favorite_items=["pasta"],
                spice_level="LOW",
                diet=["veg"],
            )
        )
        self.assertIsNotNone(preferences)
        _, components = _new_item_boost_score(
            menu_item,
            restaurant,
            preferences=preferences,
            history_profile=None,
            historical_cuisine_scores={},
            popularity=0.55,
            preference_signal_scores=_preference_signal_scores(preferences),
            history_signal_scores={},
            order_history_components=None,
        )
        label, reason, _ = _build_recommendation_metadata(
            menu_item,
            restaurant,
            preferences=preferences,
            history_profile=None,
            preference_match=0.81,
            order_history=0.0,
            popularity=0.55,
            new_item_components=components,
        )

        self.assertEqual(label, "Matches Your Taste")
        self.assertEqual(reason, "A strong match for your saved tastes and profile.")

    def test_repeated_order_affinity_gets_based_on_your_orders_label(self) -> None:
        restaurant = make_restaurant(cuisine_type="American")
        menu_item = make_menu_item(
            name="Cheese Burger Deluxe",
            category="Burgers",
            cuisine_type="American",
            description="Loaded burger with cheese and grilled onions.",
        )
        history_profile = OrderHistoryProfile(
            item_scores={"cheese burger deluxe": 1.0},
            item_term_scores={"cheese": 1.0, "burger": 1.0},
            category_scores={"burgers": 1.0},
            cuisine_scores={"american": 1.0},
            restaurant_scores={"american house": 1.0},
            eligible_order_count=4,
            status_counts={"PLACED": 4},
        )
        order_components = OrderHistoryScoreComponents(
            direct_item=1.0,
            item_term=1.0,
            category=1.0,
            cuisine=1.0,
            restaurant=0.8,
        )
        boost, components = _new_item_boost_score(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=history_profile,
            historical_cuisine_scores=history_profile.cuisine_scores,
            popularity=0.52,
            preference_signal_scores={},
            history_signal_scores={"burger": 1.0},
            order_history_components=order_components,
        )
        label, reason, _ = _build_recommendation_metadata(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=history_profile,
            preference_match=0.0,
            order_history=order_components.total,
            popularity=0.52,
            new_item_components=components,
        )

        self.assertGreater(boost, 0.0)
        self.assertGreaterEqual(components["order_affinity"], 0.55)
        self.assertEqual(label, "Based on Your Orders")
        self.assertEqual(reason, "Similar to dishes you order often.")

    def test_user_with_no_preferences_still_gets_new_item_boost(self) -> None:
        restaurant = make_restaurant(cuisine_type="Chinese")
        menu_item = make_menu_item(
            name="Crispy Chilli Tofu",
            category="Starters",
            cuisine_type="Chinese",
            description="A just-launched tofu starter with a crisp finish.",
            is_veg=True,
        )
        boost, components = _new_item_boost_score(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=None,
            historical_cuisine_scores={},
            popularity=0.7,
            preference_signal_scores={},
            history_signal_scores={},
            order_history_components=None,
        )

        self.assertGreater(boost, 0.0)
        self.assertGreater(components["freshness"], 0.0)

    def test_old_item_has_no_new_metadata(self) -> None:
        restaurant = make_restaurant(cuisine_type="Indian")
        menu_item = make_menu_item(
            name="Paneer Tikka",
            category="Starters",
            cuisine_type="Indian",
            description="Classic paneer tikka.",
            is_veg=True,
            launched_days_ago=45,
        )
        boost, components = _new_item_boost_score(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=None,
            historical_cuisine_scores={},
            popularity=0.45,
            preference_signal_scores={},
            history_signal_scores={},
            order_history_components=None,
        )
        label, reason, new_item_reason = _build_recommendation_metadata(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=None,
            preference_match=0.0,
            order_history=0.0,
            popularity=0.45,
            new_item_components=components,
        )

        self.assertEqual(boost, 0.0)
        self.assertEqual(label, None)
        self.assertEqual(reason, None)
        self.assertEqual(new_item_reason, None)

    def test_recent_item_without_manual_new_launch_flag_has_no_new_boost(self) -> None:
        restaurant = make_restaurant(cuisine_type="Indian")
        menu_item = make_menu_item(
            name="Fresh Paneer Wrap",
            category="Wraps",
            cuisine_type="Indian",
            description="A fresh wrap that should not show as just launched.",
            is_new_launch=False,
            launched_days_ago=1,
        )
        boost, components = _new_item_boost_score(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=None,
            historical_cuisine_scores={},
            popularity=0.82,
            preference_signal_scores={},
            history_signal_scores={},
            order_history_components=None,
        )
        label, reason, new_item_reason = _build_recommendation_metadata(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=None,
            preference_match=0.0,
            order_history=0.0,
            popularity=0.82,
            new_item_components=components,
        )

        self.assertEqual(boost, 0.0)
        self.assertEqual(label, None)
        self.assertEqual(reason, None)
        self.assertEqual(new_item_reason, None)

    def test_high_popularity_manual_launch_gets_trending_now_label(self) -> None:
        restaurant = make_restaurant(cuisine_type="Italian")
        menu_item = make_menu_item(
            name="Hot Burrata Pizza",
            category="Pizza",
            cuisine_type="Italian",
            description="A new pizza taking off quickly.",
            popularity_score="92.00",
        )
        boost, components = _new_item_boost_score(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=None,
            historical_cuisine_scores={},
            popularity=0.92,
            preference_signal_scores={},
            history_signal_scores={},
            order_history_components=None,
        )
        label, reason, _ = _build_recommendation_metadata(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=None,
            preference_match=0.0,
            order_history=0.0,
            popularity=0.92,
            new_item_components=components,
        )

        self.assertGreater(boost, 0.0)
        self.assertEqual(label, "Trending Now")
        self.assertEqual(reason, "A just-launched item gaining strong customer demand.")

    def test_dynamic_bestseller_badge_beats_just_launched_when_not_trending(self) -> None:
        restaurant = make_restaurant(cuisine_type="Chinese")
        menu_item = make_menu_item(
            name="Signature Fried Rice",
            category="Rice",
            cuisine_type="Chinese",
            description="A freshly launched rice bowl with strong recent sales.",
            popularity_score="62.00",
            is_dynamic_bestseller=True,
        )
        _, components = _new_item_boost_score(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=None,
            historical_cuisine_scores={},
            popularity=0.62,
            preference_signal_scores={},
            history_signal_scores={},
            order_history_components=None,
        )
        label, reason, _ = _build_recommendation_metadata(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=None,
            preference_match=0.0,
            order_history=0.0,
            popularity=0.62,
            new_item_components=components,
        )

        self.assertEqual(label, "Best Seller")
        self.assertEqual(reason, "One of the most-ordered items at this branch recently.")

    def test_generic_badge_metadata_uses_best_seller_before_just_launched(self) -> None:
        menu_item = make_menu_item(
            name="Branch Favorite Soup",
            category="Soup",
            cuisine_type="Chinese",
            description="A branch-level favorite.",
            is_dynamic_bestseller=True,
        )
        label, reason = build_generic_menu_item_badge_metadata(menu_item)

        self.assertEqual(label, "Best Seller")
        self.assertEqual(reason, "One of the most-ordered items at this branch recently.")

    def test_unavailable_new_item_is_filtered_out(self) -> None:
        restaurant = make_restaurant(cuisine_type="Thai")
        unavailable_item = make_menu_item(
            name="New Thai Basil Rice",
            category="Rice",
            cuisine_type="Thai",
            description="Freshly launched basil rice.",
            is_available=False,
        )
        candidate = RetrievedMenuCandidate(
            menu_item=unavailable_item,
            restaurant=restaurant,
            distance=0.1,
        )
        filtered = _filter_candidates(
            [candidate],
            None,
            strict_budget=False,
            intent=ExtractedIntent(intent="recommendation", new_only=True),
            exclude_item_ids=None,
        )

        self.assertEqual(filtered, [])

    def test_chat_whats_new_intent_and_reply_use_new_item_language(self) -> None:
        intent = _fallback_extract_intent(
            "what's new spicy food for me",
            SessionConversationState(),
        )
        self.assertTrue(intent.new_only)
        self.assertTrue(intent.spicy)

        reply = _build_safe_reply(
            "what's new spicy food for me",
            [],
            "new_item_no_match",
            extracted_intent=intent,
        )
        self.assertIn("new", reply.lower())

    def test_chat_suggestion_items_include_new_spicy_label(self) -> None:
        restaurant = make_restaurant(cuisine_type="Indian")
        menu_item = make_menu_item(
            name="Schezwan Chicken Wrap",
            category="Wraps",
            cuisine_type="Indian",
            description="A spicy schezwan chicken wrap.",
        )
        candidate = RetrievedMenuCandidate(
            menu_item=menu_item,
            restaurant=restaurant,
            distance=0.08,
        )
        suggestions = _suggestion_items(
            [candidate],
            intent=ExtractedIntent(intent="recommendation", spicy=True, new_only=True),
            uses_personal_context=True,
        )

        self.assertEqual(len(suggestions), 1)
        self.assertTrue(suggestions[0].is_new)
        self.assertFalse(suggestions[0].is_bestseller)
        self.assertEqual(suggestions[0].recommendation_label, "Matches Your Taste")


if __name__ == "__main__":
    unittest.main()
