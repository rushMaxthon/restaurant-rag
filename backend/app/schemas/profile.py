from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.auth import UserResponse
from app.schemas.order import OrderResponse
from app.schemas.preferences import UserPreferencesResponse

SavedAddressLabel = Literal["HOME", "WORK", "OTHER"]


class SavedAddressBase(BaseModel):
    label: SavedAddressLabel = "OTHER"
    address_line_1: str = Field(min_length=3, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    landmark: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=2, max_length=120)
    state: str = Field(min_length=2, max_length=120)
    postal_code: str = Field(min_length=4, max_length=20)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    is_default: bool = False


class SavedAddressCreateRequest(SavedAddressBase):
    pass


class SavedAddressUpdateRequest(BaseModel):
    label: SavedAddressLabel | None = None
    address_line_1: str | None = Field(default=None, min_length=3, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    landmark: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, min_length=2, max_length=120)
    state: str | None = Field(default=None, min_length=2, max_length=120)
    postal_code: str | None = Field(default=None, min_length=4, max_length=20)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    is_default: bool | None = None


class SavedAddressResponse(BaseModel):
    id: uuid.UUID
    label: SavedAddressLabel
    address_line_1: str
    address_line_2: str | None = None
    landmark: str | None = None
    city: str
    state: str
    postal_code: str
    phone_number: str | None = None
    is_default: bool
    formatted_address: str
    created_at: datetime
    updated_at: datetime


class UserProfileStatsResponse(BaseModel):
    total_orders: int = 0
    delivered_orders: int = 0
    saved_places: int = 0
    favorites_count: int = 0


class UserProfileSummaryResponse(BaseModel):
    user: UserResponse
    stats: UserProfileStatsResponse
    preferences: UserPreferencesResponse | None = None
    recent_orders: list[OrderResponse]
    saved_addresses: list[SavedAddressResponse] = []


class UserProfileUpdateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    default_address: str | None = Field(default=None, max_length=2000)
