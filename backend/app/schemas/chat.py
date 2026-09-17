from __future__ import annotations

import uuid
from typing import Any, Literal
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


class ChatThreadLine(BaseModel):
    """One line of the thread as the customer saw it. Text only, capped: it
    feeds a prompt, never a database row."""

    role: Literal["customer", "assistant"]
    text: str = Field(min_length=1, max_length=600)


class ChatPlaceOrderRequest(BaseModel):
    """Place the order this conversation has been building.

    Carries no contact details: those were collected and validated over the
    conversation and live in the draft this session owns. All that is needed
    here is which conversation, which branch, and the cart the browser is
    holding — the same cart every other ordering call sends.
    """

    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    session_id: uuid.UUID
    cart: list[CartLinePayload] = Field(default_factory=list)


class ChatPlaceOrderResponse(BaseModel):
    outcome: str
    order_id: uuid.UUID | None = None
    total: Decimal | None = None
    currency: str | None = None
    payment_url: str | None = None
    missing: list[str] = Field(default_factory=list)
    reason: str | None = None


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    restaurant_id: uuid.UUID | None = None
    restaurant_location_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    guest_preferences: GuestPreferencePayload | None = None
    # Both selling rules are functions of the cart, and the cart lives in the
    # browser. Untrusted: every id is re-resolved against the branch.
    cart: list[CartLinePayload] = Field(default_factory=list)
    # The assistant's last line as the customer saw it, so the ordering
    # agent can read "yes" or "not yet" against what it just offered. The
    # client holds the thread; sending one line back is cheaper and more
    # honest than re-deriving it from stored history, which may carry a
    # different rendering than the one on screen.
    previous_reply: str | None = Field(default=None, max_length=2000)
    # The tail of the thread, newest last, so the ordering agent reads an
    # answer against the question it answers. Capped at 8 lines.
    recent_history: list[ChatThreadLine] = Field(default_factory=list, max_length=8)


class CartActionResponse(BaseModel):
    """One cart change the ordering agent decided on, as the wire sees it.

    Identifiers and a quantity, and deliberately nothing else: the client
    already has the branch menu loaded and renders the name and the price from
    that, so putting either here would create a second source for them that can
    disagree with the menu the customer is looking at. `status` is the field
    that matters most — `proposed` means the client must ASK before changing
    anything, and every destructive change is proposed by construction.
    """

    kind: str
    status: str
    reason: str
    menu_item_id: uuid.UUID | None = None
    menu_item_size_id: uuid.UUID | None = None
    selected_option_ids: list[uuid.UUID] = Field(default_factory=list)
    quantity: int | None = None


class ChatMessageResponse(BaseModel):
    reply: str
    session_id: uuid.UUID
    suggestions: list[ChatSuggestionItem] = Field(default_factory=list)
    combo_suggestions: list[GeneratedComboResponse] = Field(default_factory=list)
    offer_suggestions: list[PersonalizedOfferCardResponse] = Field(default_factory=list)
    # What this turn learned about the visitor, for a guest's browser to keep.
    # Empty for an authenticated user: their traits already have a home.
    inferred_preferences: dict[str, str] = Field(default_factory=dict)
    # Same rules and the same suppression memory as `GET /api/suggestions`,
    # but populated only on THIS route (`POST /chat/message`), and only once
    # `handle_chat_message` reaches the fully-assembled turn — every
    # short-circuit reply (acknowledgement, greeting, a cache hit) leaves it
    # null. `POST /chat/message/stream`, which is the route the web concierge
    # and mobile actually call, never computes a suggestion at all — its SSE
    # `meta` frame carries `suggestions`/`combo_suggestions`/`offer_suggestions`
    # only, so this field is always null on that path. In practice this field
    # is always null today for another reason too: `cart` above is populated
    # by no shipped client, so even a `/chat/message` caller earns nothing to
    # suggest against. The concierge UI gets its suggestion by mounting
    # `WaiterPrompt` alongside the transcript instead, which calls
    # `GET /api/suggestions` directly. Kept, not dead: Phase 2 is expected to
    # start sending `cart` on this route, at which point this stops being
    # theoretical.
    suggestion: SellSuggestionResponse | None = None
    # Whether the agent's answer is the one to show, everything an order
    # needs is gathered, and what was placed if anything. Absent from the
    # streaming route's own model — it speaks in frames — but the same
    # fields, so a channel reading either gets one contract.
    agent_asks: bool = False
    order_ready: bool = False
    placed_order: dict[str, Any] | None = None
    # The ordering agent's three additions, all of them empty here today: the
    # agent is wired into `POST /chat/message/stream` only (Task 6), because
    # the concierge streams and wiring the non-streaming route as well would
    # mean two seams to keep honest for a surface nobody calls. They are
    # declared on this model anyway so the two routes describe the same turn —
    # a client reading the OpenAPI schema should not have to learn that the
    # streamed `done` frame carries fields the response model denies exist.
    turn_id: uuid.UUID | None = None
    cart_actions: list[CartActionResponse] = Field(default_factory=list)
    # The agent's own sentence, kept separate from `reply` on purpose: `reply`
    # is what the existing pipeline said and streams unchanged, and this never
    # substitutes for it.
    agent_reply: str | None = None


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
