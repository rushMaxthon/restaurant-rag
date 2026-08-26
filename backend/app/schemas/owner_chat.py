"""Request and response models for the owner Q&A assistant."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ChatMessageRole


class OwnerChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: uuid.UUID | None = None
    # Accepted for owners but never trusted: the scope resolver pins an owner to
    # their own restaurant regardless of what is sent.
    restaurant_id: uuid.UUID | None = None
    restaurant_location_id: uuid.UUID | None = None


class OwnerChatResponse(BaseModel):
    session_id: uuid.UUID
    answer: str
    # Which analysis answered the question, and whether the wording came from the
    # model or the deterministic template.
    skill: str
    answer_source: str
    routed_by: str
    fallback_reason: str | None = None
    # The numbers the answer was allowed to state, so a reply can be audited.
    facts: dict[str, Any] = Field(default_factory=dict)
    # Offers and combos this answer suggests, each with the one action that
    # applies to it. Empty for the great majority of answers.
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class OwnerChatHistoryItem(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: ChatMessageRole
    message: str
    skill: str | None
    answer_source: str | None
    created_at: datetime
    # Replayed with the message so a restored conversation keeps its cards
    # instead of degrading to the bare text on the next page load.
    suggestions: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_message(cls, row: Any) -> "OwnerChatHistoryItem":
        """Build from an ORM row, lifting the cards out of the stored facts."""

        item = cls.model_validate(row)
        stored = (getattr(row, "facts", None) or {}).get("suggestions")
        if isinstance(stored, list):
            item.suggestions = stored
        return item


class SuggestionOfferActivationResponse(BaseModel):
    """The end state of an offer a chat card started."""

    offer_id: uuid.UUID
    name: str
    state: str
    # True when the offer was already running, so the client can say "already
    # active" rather than reporting a change that did not happen.
    already_active: bool
    detail: str


class OwnerChatClearResponse(BaseModel):
    deleted_count: int
    cleared_session_id: uuid.UUID | None


__all__ = [
    "OwnerChatClearResponse",
    "SuggestionOfferActivationResponse",
    "OwnerChatHistoryItem",
    "OwnerChatRequest",
    "OwnerChatResponse",
]
