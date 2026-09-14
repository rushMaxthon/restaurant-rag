"""Transport for the pages that have no message to send.

`POST /chat` needs something to say; a home page or a cart drawer does not, so
it cannot ask the concierge for guidance. This endpoint is the same rule
engine and the same suppression memory, reached without starting a
conversation — see `backend/app/services/suggestions.py` for the rules
themselves and `docs/superpowers/specs/2026-09-14-waiter-agentic-cart-design.md`
for why one suggestion per page-render is the contract.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AppScopeDep, ensure_restaurant_readable
from app.config.database import get_db
from app.models.restaurant_location import RestaurantLocation
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

# A real cart is small: even a generous order of a few dozen lines, each with
# a size and a handful of customization option ids, serializes to well under
# 2000 characters of JSON. 4096 leaves headroom for that without leaving the
# query param open to a payload built purely to be large. Enforced by hand in
# `_parse_cart`, BEFORE `json.loads` runs, rather than via FastAPI's
# `Query(max_length=...)` — that path raises a 422, and an oversized `cart` on
# this endpoint must answer like every other malformed value: 200, no
# suggestion.
MAX_CART_QUERY_LENGTH = 4096


def _restaurant_id_for_location(db: Session, restaurant_location_id: uuid.UUID) -> uuid.UUID | None:
    """Resolve the owning restaurant so the scope guard has something to check.

    This endpoint only ever receives a `restaurant_location_id`, not the
    `restaurant_id` `ensure_restaurant_readable` expects — every sibling
    customer-facing read (`generated_combos.py`, `menu_items.py`, `chat.py`)
    already has the restaurant id in hand. A location id that does not exist
    resolves to None, which `AppScope.allows_restaurant` treats as out of
    scope for a single-restaurant app (matching a real cross-restaurant id)
    and as allowed for the unscoped marketplace scope — either way nothing
    downstream can leak, since the menu-item query below is scoped to the
    same (possibly nonexistent) location regardless.
    """

    return db.scalar(
        select(RestaurantLocation.restaurant_id).where(RestaurantLocation.id == restaurant_location_id)
    )


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

    The length check runs BEFORE `json.loads` on purpose, not after: the
    attack this closes is a string of thousands of nested `[` characters
    (`"[" * 5000 + "]" * 5000`, ~10KB), which is cheap to construct and blows
    Python's recursion limit inside the JSON decoder itself — the crash
    happens while parsing, so no amount of validating the *parsed result*
    would ever run. Rejecting on raw length keeps that string away from
    `json.loads` entirely. This is done manually here rather than via
    FastAPI's `Query(max_length=...)`, which would raise a 422 on the exact
    input requirement 1 says must answer with a null suggestion instead.
    """

    if not cart:
        return []
    if len(cart) > MAX_CART_QUERY_LENGTH:
        logger.info("Suggestions: oversized cart parameter, treating as empty")
        return []
    try:
        raw_lines = json.loads(cart)
        if not isinstance(raw_lines, list):
            return []
        parsed = [CartLinePayload.model_validate(entry) for entry in raw_lines]
    except (ValueError, TypeError):
        logger.info("Suggestions: malformed cart parameter, treating as empty")
        return []
    except RecursionError:
        # Belt to the length bound's braces: nesting depth is cheap per byte
        # (`[[[[...]]]]` costs 2 bytes per level), so a bound generous enough
        # for a real cart's JSON does not, by itself, guarantee every string
        # under that bound stays inside the interpreter's recursion limit.
        # Do NOT collapse this into the tuple above — RecursionError is a
        # RuntimeError, not a ValueError, and merging it with a bare
        # `except Exception` would also swallow genuine bugs in this function
        # behind a silent null suggestion.
        logger.info("Suggestions: cart parameter too deeply nested, treating as empty")
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
    app_scope: AppScopeDep,
    restaurant_location_id: uuid.UUID,
    session_id: uuid.UUID,
    cart: Annotated[
        str | None,
        Query(
            description=(
                "JSON array of cart lines. Oversized or malformed values are "
                f"ignored, not rejected — see `_parse_cart` (cap: "
                f"{MAX_CART_QUERY_LENGTH} characters)."
            )
        ),
    ] = None,
) -> SuggestionEnvelope:
    """One suggestion for a page that has nothing to say, or none at all.

    An absent or empty cart is the ordinary case — someone landing on the home
    page — not an error, so it always answers 200 with `suggestion: null`
    rather than 4xx.
    """

    # Same guard every sibling customer-facing read applies (see
    # `generated_combos.py`'s `/cart/upsell-suggestions`): without it, an
    # unauthenticated caller could name any restaurant_location_id on the
    # platform and get back an item id and a price delta from a restaurant
    # their app client has no business seeing. 404, not 403 — same reasoning
    # as `ensure_restaurant_readable` itself: a single-restaurant app must not
    # be able to use this to probe which locations exist elsewhere.
    ensure_restaurant_readable(app_scope, _restaurant_id_for_location(db, restaurant_location_id))

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
    app_scope: AppScopeDep,
) -> SuggestionEnvelope:
    """Dismissing a prompt is a decline wherever it happened.

    Without this, an in-page prompt could be dismissed forever while the chat
    kept offering the same item on the same identity — which reads to a
    customer as not listening. `menu_item_id` here is a real menu item id from
    the caller, so `record_decline`'s parameter name is accurate at this call
    site even though the suppression key it stores can also be a combo id or a
    customization option id (see `_suggestion_identity` in
    `services/suggestions.py`).

    `app_scope` is declared (matching `get_suggestion`) so a suspended app is
    refused here too, but there is no `ensure_restaurant_readable` call to go
    with it: this endpoint never reads a restaurant-scoped row — it only
    mutates the caller's OWN suppression memory, keyed by their own principal
    id, and `menu_item_id` is stored opaquely, never resolved against the DB.
    There is nothing here for a scoped app to see that it does not already own.
    """

    user_id = _principal_id(current_user, payload.session_id)
    memory = load_memory(user_id, payload.session_id)
    store_memory(user_id, payload.session_id, record_decline(memory, payload.menu_item_id))
    return SuggestionEnvelope()
