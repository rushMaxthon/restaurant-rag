from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class FavoriteStatusResponse(BaseModel):
    menu_item_id: uuid.UUID
    is_favorite: bool


class FavoriteItemResponse(BaseModel):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    restaurant_name: str
    restaurant_location_name: str
    restaurant_slug: str
    restaurant_is_active: bool
    restaurant_is_approved: bool
    restaurant_is_open: bool
    name: str
    category: str
    cuisine_type: str | None
    description: str | None
    price: Decimal
    is_available: bool
    is_orderable: bool
    is_veg: bool
    is_bestseller: bool
    is_featured: bool = False
    image_url: str | None
    popularity_score: Decimal
    rating: Decimal | None = None
    rating_count: int = 0
    is_favorite: bool = True
    favorited_at: datetime
    created_at: datetime
    updated_at: datetime
