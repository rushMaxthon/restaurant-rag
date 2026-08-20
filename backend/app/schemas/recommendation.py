from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class RecommendationRestaurantSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    cuisine_type: str
    city: str
    is_open: bool


class RecommendationLocationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    branch_name: str
    city: str
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    is_open: bool
    is_active: bool
    delivery_fee: Decimal
    minimum_order_amount: Decimal
    estimated_delivery_time: int


class RecommendationScoreBreakdown(BaseModel):
    cuisine_match: float
    order_history: float
    popularity: float
    budget_fit: float
    novelty: float


class RecommendationLocationVariantSummary(BaseModel):
    menu_item_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    branch_name: str
    city: str
    price: Decimal
    is_open: bool
    is_active: bool


class RecommendationItemResponse(BaseModel):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    restaurant_location_name: str | None = None
    restaurant_location_city: str | None = None
    restaurant: RecommendationRestaurantSummary
    restaurant_location: RecommendationLocationSummary
    name: str
    category: str
    cuisine_type: str | None
    description: str | None
    price: Decimal
    is_available: bool
    is_veg: bool
    is_bestseller: bool
    is_featured: bool = False
    image_url: str | None
    popularity_score: Decimal
    launched_at: datetime
    created_at: datetime
    updated_at: datetime
    is_new_launch: bool = False
    is_new: bool = False
    recommendation_label: str | None = None
    recommendation_reason: str | None = None
    new_item_reason: str | None = None
    ai_badge: str | None = None
    ai_reason: str | None = None
    is_favorite: bool = False
    score: float
    score_breakdown: RecommendationScoreBreakdown
    display_price: Decimal | None = None
    price_label: str | None = None
    available_locations_count: int = 1
    preferred_menu_item_id: uuid.UUID | None = None
    preferred_location_id: uuid.UUID | None = None
    preferred_location_name: str | None = None
    requires_location_selection: bool = False
    location_variants: list[RecommendationLocationVariantSummary] = []


class PersonalizedRecommendationContextResponse(BaseModel):
    ai_collection_title: str | None = None
    ai_insight: str | None = None
    generated_at: datetime | None = None
    model_name: str | None = None
    candidate_count: int = 0
