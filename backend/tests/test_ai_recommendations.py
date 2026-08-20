from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.recommendation import (
    RecommendationItemResponse,
    RecommendationLocationSummary,
    RecommendationRestaurantSummary,
    RecommendationScoreBreakdown,
)
from app.services import ai_recommendations


def make_recommendation(
    *,
    name: str,
    restaurant_name: str,
    cuisine_type: str,
    category: str,
    score: float,
    is_veg: bool = True,
) -> RecommendationItemResponse:
    restaurant_id = uuid.uuid5(uuid.NAMESPACE_DNS, restaurant_name)
    location_id = uuid.uuid5(
        uuid.NAMESPACE_DNS,
        f"{restaurant_name}:{name}:location",
    )
    menu_item_id = uuid.uuid5(
        uuid.NAMESPACE_DNS,
        f"{restaurant_name}:{name}:menu-item",
    )
    now = datetime.now(UTC)
    return RecommendationItemResponse(
        id=menu_item_id,
        restaurant_id=restaurant_id,
        restaurant_location_id=location_id,
        restaurant=RecommendationRestaurantSummary(
            id=restaurant_id,
            name=restaurant_name,
            slug=restaurant_name.lower().replace(" ", "-"),
            cuisine_type=cuisine_type,
            city="Ahmedabad",
            is_open=True,
        ),
        restaurant_location=RecommendationLocationSummary(
            id=location_id,
            branch_name=f"{restaurant_name} Main",
            city="Ahmedabad",
            latitude=Decimal("23.0225"),
            longitude=Decimal("72.5714"),
            is_open=True,
            is_active=True,
            delivery_fee=Decimal("20.00"),
            minimum_order_amount=Decimal("99.00"),
            estimated_delivery_time=25,
        ),
        name=name,
        category=category,
        cuisine_type=cuisine_type,
        description=f"{name} description",
        price=Decimal("149.00"),
        is_available=True,
        is_veg=is_veg,
        is_bestseller=False,
        is_featured=False,
        image_url=None,
        popularity_score=Decimal("90.00"),
        launched_at=now,
        created_at=now,
        updated_at=now,
        is_new_launch=False,
        is_new=False,
        recommendation_label="Recommended for You",
        recommendation_reason=f"Because you like {cuisine_type}.",
        new_item_reason=None,
        score=score,
        score_breakdown=RecommendationScoreBreakdown(
            cuisine_match=0.8,
            order_history=0.7,
            popularity=0.9,
            budget_fit=0.8,
            novelty=0.2,
        ),
    )


class AIRecommendationsTests(unittest.TestCase):
    def test_apply_diversity_limits_dominant_restaurant_when_alternatives_exist(
        self,
    ) -> None:
        items = [
            make_recommendation(
                name="Pad Thai Veg",
                restaurant_name="Bangkok Bowl",
                cuisine_type="Thai",
                category="Noodles",
                score=0.98,
            ),
            make_recommendation(
                name="Thai Iced Tea",
                restaurant_name="Bangkok Bowl",
                cuisine_type="Thai",
                category="Beverages",
                score=0.96,
            ),
            make_recommendation(
                name="Red Curry Tofu",
                restaurant_name="Bangkok Bowl",
                cuisine_type="Thai",
                category="Curry",
                score=0.95,
            ),
            make_recommendation(
                name="Margherita Pizza",
                restaurant_name="Luigi's Italian Trattoria",
                cuisine_type="Italian",
                category="Pizza",
                score=0.92,
            ),
            make_recommendation(
                name="Veg Momos",
                restaurant_name="Momo Mountain",
                cuisine_type="Tibetan",
                category="Momos",
                score=0.91,
            ),
        ]

        with (
            patch.object(
                ai_recommendations.settings,
                "ai_recommendation_max_same_restaurant",
                1,
            ),
            patch.object(
                ai_recommendations.settings,
                "ai_recommendation_max_same_cuisine",
                2,
            ),
            patch.object(
                ai_recommendations.settings,
                "ai_recommendation_max_same_category",
                2,
            ),
        ):
            selected = ai_recommendations._apply_diversity(items, limit=3)

        self.assertEqual(len(selected), 3)
        selected_restaurants = [item.restaurant.name for item in selected]
        self.assertEqual(selected_restaurants.count("Bangkok Bowl"), 1)
        self.assertIn("Luigi's Italian Trattoria", selected_restaurants)
        self.assertIn("Momo Mountain", selected_restaurants)

    def test_apply_diversity_keeps_items_when_no_alternatives_exist(self) -> None:
        items = [
            make_recommendation(
                name="Pad Thai Veg",
                restaurant_name="Bangkok Bowl",
                cuisine_type="Thai",
                category="Noodles",
                score=0.98,
            ),
            make_recommendation(
                name="Thai Iced Tea",
                restaurant_name="Bangkok Bowl",
                cuisine_type="Thai",
                category="Beverages",
                score=0.96,
            ),
            make_recommendation(
                name="Red Curry Tofu",
                restaurant_name="Bangkok Bowl",
                cuisine_type="Thai",
                category="Curry",
                score=0.95,
            ),
        ]

        with patch.object(
            ai_recommendations.settings,
            "ai_recommendation_max_same_restaurant",
            1,
        ):
            selected = ai_recommendations._apply_diversity(items, limit=3)

        self.assertEqual([item.name for item in selected], [item.name for item in items])

    def test_apply_cached_ai_recommendations_uses_snapshot_order_and_metadata(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        first = make_recommendation(
            name="Pad Thai Veg",
            restaurant_name="Bangkok Bowl",
            cuisine_type="Thai",
            category="Noodles",
            score=0.97,
        )
        second = make_recommendation(
            name="Thai Iced Tea",
            restaurant_name="Bangkok Bowl",
            cuisine_type="Thai",
            category="Beverages",
            score=0.93,
        )
        items = [first, second]
        first_key = ai_recommendations._candidate_group_key(first)
        second_key = ai_recommendations._candidate_group_key(second)
        snapshot = SimpleNamespace(
            candidate_snapshot_hash="snapshot-hash",
            generation_status=ai_recommendations.STATUS_READY,
            ranked_recommendation_keys=[second_key, first_key],
            item_metadata={
                second_key: {
                    "ai_badge": "Because You Like Thai",
                    "ai_reason": "Frequently paired with meals you enjoy.",
                }
            },
            updated_at=datetime.now(UTC),
        )

        with (
            patch.object(
                ai_recommendations.settings,
                "enable_ai_recommendation_reranking",
                True,
            ),
            patch.object(
                ai_recommendations.settings,
                "ai_recommendation_min_candidate_count",
                2,
            ),
            patch.object(
                ai_recommendations.settings,
                "ai_recommendation_final_limit",
                20,
            ),
            patch.object(
                ai_recommendations,
                "_build_candidate_pool",
                return_value=items,
            ),
            patch.object(
                ai_recommendations,
                "_candidate_snapshot_hash",
                return_value="snapshot-hash",
            ),
            patch.object(
                ai_recommendations,
                "_load_snapshot_record",
                return_value=snapshot,
            ),
            patch.object(
                ai_recommendations,
                "_build_current_deduped_items",
                return_value=items,
            ),
        ):
            ordered = ai_recommendations.apply_cached_ai_recommendations(
                SimpleNamespace(),
                user=user,
                items=items,
                location_context=None,
            )

        self.assertEqual([item.name for item in ordered], [second.name, first.name])
        self.assertEqual(ordered[0].ai_badge, "Because You Like Thai")
        self.assertEqual(
            ordered[0].ai_reason,
            "Frequently paired with meals you enjoy.",
        )


if __name__ == "__main__":
    unittest.main()
