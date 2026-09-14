"""Transport for the pages that have no message to send.

`POST /chat` needs something to say; a home page or a cart drawer does not, so
it cannot ask the concierge for guidance. This endpoint is the same rule
engine and the same suppression memory, reached without starting a
conversation — see `backend/app/services/suggestions.py` for the rules
themselves and `docs` for why one suggestion per page-render is the contract.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.schemas.suggestions import (
    CartLinePayload,
    SellSuggestionResponse,
    SuggestionDeclineRequest,
    SuggestionEnvelope,
)
from app.services.auth import get_current_user_optional
from app.services.chat_principal import guest_principal_for_session
from app.services.recommendations import get_user_preferences_response
from app.services.suggestions import (
    CartLineFacts,
    load_memory,
    record_decline,
    store_memory,
    suggestion_for_cart,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/suggestions", tags=["Suggestions"])


def _principal_id(current_user: User | None, session_id: uuid.UUID) -> uuid.UUID:
    """Same identity rule `app/api/chat.py` uses, so a decline made on a page
    suppresses the same suggestion the concierge would otherwise repeat."""

    if current_user is not None:
        return current_user.id
    return guest_principal_for_session(session_id).id


def _parse_cart(cart: str | None) -> list[CartLineFacts]:
    """Turn the browser's cart into facts, or nothing.

    `cart` is a JSON string in a query parameter, and this is called on every
    page render — a malformed value (bad JSON, wrong shape, a stray string
    where an id belongs) must degrade to "no lines" rather than a 422 or a
    traceback, because guidance must never be the reason a page fails to load.
    `suggestion_for_cart` re-resolves every id against the branch regardless,
    so nothing here needs to validate correctness beyond "is this shape usable
    at all".
    """

    if not cart:
        return []
    try:
        raw_lines = json.loads(cart)
        if not isinstance(raw_lines, list):
            return []
        parsed = [CartLinePayload.model_validate(entry) for entry in raw_lines]
    except (ValueError, TypeError):
        logger.info("Suggestions: malformed cart parameter, treating as empty")
        return []
    return [
        CartLineFacts(
            menu_item_id=line.menu_item_id,
            size_id=line.size_id,
            customization_option_ids=frozenset(line.customization_option_ids),
        )
        for line in parsed
    ]


@router.get("", response_model=SuggestionEnvelope)
def get_suggestion(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    restaurant_location_id: uuid.UUID,
    session_id: uuid.UUID,
    cart: Annotated[str | None, Query(description="JSON array of cart lines")] = None,
) -> SuggestionEnvelope:
    """One suggestion for a page that has nothing to say, or none at all.

    An absent or empty cart is the ordinary case — someone landing on the home
    page — not an error, so it always answers 200 with `suggestion: null`
    rather than 4xx.
    """

    lines = _parse_cart(cart)

    # Takes the User, not an id — the same helper the recommendation scorer
    # reads diet from, so a suggestion respects the diet everything else does.
    preferences = get_user_preferences_response(db, current_user) if current_user else None
    suggestion = suggestion_for_cart(
        db,
        cart_lines=lines,
        restaurant_location_id=restaurant_location_id,
        user_id=_principal_id(current_user, session_id),
        session_id=session_id,
        diet=getattr(preferences, "diet", None),
    )
    if suggestion is None:
        return SuggestionEnvelope()
    return SuggestionEnvelope(suggestion=SellSuggestionResponse(**suggestion.__dict__))


@router.post("/decline", response_model=SuggestionEnvelope)
def decline_suggestion(
    payload: SuggestionDeclineRequest,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> SuggestionEnvelope:
    """Dismissing a prompt is a decline wherever it happened.

    Without this, an in-page prompt could be dismissed forever while the chat
    kept offering the same item on the same identity — which reads to a
    customer as not listening. `menu_item_id` here is a real menu item id from
    the caller, so `record_decline`'s parameter name is accurate at this call
    site even though the suppression key it stores can also be a combo id or a
    customization option id (see `_suggestion_identity` in
    `services/suggestions.py`).
    """

    user_id = _principal_id(current_user, payload.session_id)
    memory = load_memory(user_id, payload.session_id)
    store_memory(user_id, payload.session_id, record_decline(memory, payload.menu_item_id))
    return SuggestionEnvelope()
