from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class CartLinePayload(BaseModel):
    """What the browser says is in the cart.

    Identifiers only, and treated as untrusted: the service re-resolves every
    id against the selected branch and ignores whatever does not belong there.
    Names and prices are never taken from here.
    """

    menu_item_id: uuid.UUID
    # Same bounds as an order line (`OrderCreateItem`): past them the order
    # path refused the cart with a 500 instead of a 422 (2026-10-07 review).
    quantity: int = Field(default=1, ge=1, le=99)
    size_id: uuid.UUID | None = None
    customization_option_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class SellSuggestionResponse(BaseModel):
    kind: str
    basis: str
    menu_item_id: uuid.UUID | None = None
    combo_id: uuid.UUID | None = None
    size_id: uuid.UUID | None = None
    customization_option_id: uuid.UUID | None = None
    saving: Decimal | None = None
    extra_cost: Decimal | None = None


class SuggestionEnvelope(BaseModel):
    suggestion: SellSuggestionResponse | None = None


class SuggestionDeclineRequest(BaseModel):
    session_id: uuid.UUID
    menu_item_id: uuid.UUID
