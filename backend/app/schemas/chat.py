from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ChatMessageRole
from app.schemas.generated_combo import GeneratedComboResponse
from app.schemas.personalized_offer import PersonalizedOfferCardResponse


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
    similarity_score: float


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    restaurant_id: uuid.UUID | None = None
    restaurant_location_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None


class ChatMessageResponse(BaseModel):
    reply: str
    session_id: uuid.UUID
    suggestions: list[ChatSuggestionItem] = Field(default_factory=list)
    combo_suggestions: list[GeneratedComboResponse] = Field(default_factory=list)
    offer_suggestions: list[PersonalizedOfferCardResponse] = Field(default_factory=list)


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
