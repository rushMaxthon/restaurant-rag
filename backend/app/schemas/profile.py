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
    #: Where this address is, found once when it was saved. Present means every
    #: future order to it is priced with no lookup at all.
    latitude: float | None = None
    longitude: float | None = None
    #: How precise that point is. EMPTY WITH COORDINATES means the customer
    #: picked the address from the autocomplete, so it is the map provider's own
    #: record of that building — the best source there is.
    geocode_confidence: str = ""
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
    """A PATCH, and now it behaves like one.

    **Every field used to be written unconditionally**, so a field left out of
    the body was stored as NULL. `api.updateProfile` sends only `full_name` and
    `phone_number` — so a customer who edited their name on the account screen
    silently lost their saved delivery address, every time. It was found
    because a test fixture's address kept disappearing between runs.

    The rule is the one `services/restaurant_storefront.py` already uses for
    the same reason: **only the keys actually present in the body change.**
    Pydantic records which those were in `model_fields_set`, which is the only
    way to tell "not mentioned" from "sent as null" — the two had the same
    representation here, and conflating them is the bug.

    So: absent leaves a field alone, and an explicit `null` clears it. The
    account screen already sends `phone_number: null` when the customer empties
    that box, so it means exactly what it did before; it simply no longer takes
    the address with it.

    `full_name` is optional because a PATCH should not demand a field you are
    not changing — but it cannot be CLEARED, because the column is NOT NULL and
    an account with no name is not a thing this product has. Sending it as null
    or blank is refused rather than ignored, since a client that asks to erase
    a name should hear that it did not happen.
    """

    full_name: str | None = Field(default=None, max_length=255)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    default_address: str | None = Field(default=None, max_length=2000)
