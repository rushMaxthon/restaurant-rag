from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class GeneratedComboItemSummary(BaseModel):
    menu_item_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None = None
    restaurant_location_name: str | None = None
    name: str
    category: str
    price: Decimal
    quantity: int
    image_url: str | None
    is_veg: bool
    is_available: bool
    is_favorite: bool = False


class GeneratedComboResponse(BaseModel):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    restaurant_name: str
    restaurant_location_name: str
    combo_name: str
    description: str | None
    items: list[GeneratedComboItemSummary]
    order_count: int
    unique_user_count: int
    confidence_score: Decimal
    status: str
    manual_status_override: str | None = None
    is_customer_visible: bool
    remaining_unique_users_to_publish: int
    original_total_price: Decimal
    suggested_combo_price: Decimal
    savings_amount: Decimal
    image_url: str | None
    is_active: bool
    generated_from_orders: bool
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class GeneratedComboStatusUpdate(BaseModel):
    status: Literal["DRAFT", "LIVE", "ARCHIVED"]


class GeneratedComboRebuildResponse(BaseModel):
    created_count: int
    updated_count: int
    deactivated_count: int
    scanned_order_count: int
    eligible_pattern_count: int


class ComboUpsellSuggestionResponse(BaseModel):
    combo_id: uuid.UUID
    combo_name: str
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    restaurant_name: str
    restaurant_location_name: str
    confidence_score: Decimal
    suggested_combo_price: Decimal
    missing_items: list[GeneratedComboItemSummary]
    message: str


class GeneratedComboQuery(BaseModel):
    restaurant_id: uuid.UUID | None = None
    limit: int = Field(default=12, ge=1, le=50)
