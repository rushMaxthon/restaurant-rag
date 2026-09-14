from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ChatMessageRole
from app.schemas.generated_combo import GeneratedComboResponse
from app.schemas.personalized_offer import PersonalizedOfferCardResponse
from app.schemas.suggestions import CartLinePayload, SellSuggestionResponse


class ChatSuggestionItem(BaseModel):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    restaurant_name: str
    restaurant_location_name: str
    name: str
    category: str
    cuisine_type: str | None
    description: str | None
    price: Decimal
    is_veg: bool
    is_available: bool
    is_bestseller: bool = False
    is_featured: bool = False
    image_url: str | None
    launched_at: datetime | None = None
    is_new_launch: bool = False
    is_new: bool = False
    recommendation_label: str | None = None
    recommendation_reason: str | None = None
    new_item_reason: str | None = None
    is_favorite: bool = False
    # Whether this dish needs choices before it can be ordered.
    #
    # The customer app decides between a one-tap "+" and a "Choose" that opens
    # the dish, and a chat card had no way to know: it hardcoded both to false,
    # so a sized or customisable dish was added at its base price with no size
    # and no required options, and the server refused the order at checkout
    # ("Select a size for X") after everything else had been filled in.
    has_sizes: bool = False
    has_customizations: bool = False
    similarity_score: float


class GuestPreferencePayload(BaseModel):
    """Durable traits a browser is carrying for a visitor with no account.

    Honoured ONLY for a guest. For an authenticated user the database is the
    only source and this is ignored outright — see `resolve_chat_preferences`.
    Both values are re-normalised server-side, so anything unrecognised becomes
    None rather than reaching a query.
    """

    diet: str | None = Field(default=None, max_length=32)
    spice_level: str | None = Field(default=None, max_length=32)


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    restaurant_id: uuid.UUID | None = None
    restaurant_location_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    guest_preferences: GuestPreferencePayload | None = None
    # Both selling rules are functions of the cart, and the cart lives in the
    # browser. Untrusted: every id is re-resolved against the branch.
    cart: list[CartLinePayload] = Field(default_factory=list)


class ChatMessageResponse(BaseModel):
    reply: str
    session_id: uuid.UUID
    suggestions: list[ChatSuggestionItem] = Field(default_factory=list)
    combo_suggestions: list[GeneratedComboResponse] = Field(default_factory=list)
    offer_suggestions: list[PersonalizedOfferCardResponse] = Field(default_factory=list)
    # What this turn learned about the visitor, for a guest's browser to keep.
    # Empty for an authenticated user: their traits already have a home.
    inferred_preferences: dict[str, str] = Field(default_factory=dict)
    # Same contract as `GET /api/suggestions`: one waiter, one nudge, one
    # suppression memory, regardless of which surface asked. None on every
    # short-circuit reply (acknowledgement, greeting, a cache hit) — see
    # `handle_chat_message` for why only the fully-assembled turn computes one.
    suggestion: SellSuggestionResponse | None = None


class ChatHistoryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    restaurant_id: uuid.UUID | None
    restaurant_location_id: uuid.UUID | None
    role: ChatMessageRole
    message: str
    context_payload: dict[str, object]
    created_at: datetime
    updated_at: datetime


class ChatClearResponse(BaseModel):
    deleted_count: int
    cleared_session_id: uuid.UUID | None = None
