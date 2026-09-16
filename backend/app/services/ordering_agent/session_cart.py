"""A cart for a customer who has no browser.

The cart lives in `localStorage` and travels with every request — that is the
whole shape of this feature on the web, and it is why no cart table exists.
WhatsApp has no localStorage and nothing to send. So for those channels the
cart is kept here, against the conversation, in the same Redis the order
draft uses.

This is deliberately the *only* difference between the two channels. The
agent still returns actions and never writes a cart itself; the web client
applies them to its own cart, and for a channel with no client this applies
the same actions to the stored one. One set of rules about what an action
means, two places that carry it out.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.schemas.suggestions import CartLinePayload
from app.services.cache import cache_delete, cache_get_json, cache_set_json

logger = logging.getLogger(__name__)

# A cart someone is building over a chat, not a cart they abandoned last
# month. Long enough to eat lunch around, short enough that a stale one does
# not surprise them a week later.
CART_TTL_SECONDS = 24 * 60 * 60


def _key(session_id: uuid.UUID | str) -> str:
    return f"ordering:cart:{session_id}"


def load(session_id: uuid.UUID | str) -> list[CartLinePayload]:
    """The cart this conversation is holding.

    Never raises. Redis being unreachable means an empty cart and a customer
    who has to say it again, which is worse than it working and better than
    an error where an answer should be.
    """

    stored = cache_get_json(_key(session_id))
    if not isinstance(stored, list):
        return []
    lines: list[CartLinePayload] = []
    for row in stored:
        try:
            lines.append(CartLinePayload.model_validate(row))
        except Exception:  # noqa: BLE001 - one bad row must not empty a cart
            logger.warning("Dropping an unreadable stored cart line", exc_info=True)
    return lines


def save(session_id: uuid.UUID | str, lines: list[CartLinePayload]) -> None:
    cache_set_json(
        _key(session_id),
        [line.model_dump(mode="json") for line in lines],
        ttl_seconds=CART_TTL_SECONDS,
    )


def clear(session_id: uuid.UUID | str) -> None:
    cache_delete(_key(session_id))


def _same_line(line: CartLinePayload, action: dict[str, Any]) -> bool:
    """Whether an action is about this line.

    Matched on the dish alone, exactly as `cart_actions._matching_lines` does
    on the other side of the wire: "remove the pizza" means the pizza,
    whichever size it turned out to be, and two sizes of one dish are an
    ambiguity the server has already resolved by proposing rather than
    applying.
    """

    return str(line.menu_item_id) == str(action.get("menu_item_id"))


def apply_actions(
    lines: list[CartLinePayload], actions: list[dict[str, Any]]
) -> tuple[list[CartLinePayload], list[dict[str, Any]]]:
    """Carry out the applied actions; hand back the ones needing confirmation.

    Only `applied` changes anything. A `proposed` action is a question for the
    customer — clearing a cart, or a removal that matched more than one line —
    and answering it on their behalf is the one thing this agent may never do.
    Anything with a missing or unrecognised status is treated as proposed,
    because a drifted shape must fail towards asking.
    """

    current = list(lines)
    proposed: list[dict[str, Any]] = []

    for action in actions:
        kind = action.get("kind")
        if action.get("status") != "applied" or kind in {"clear", "checkout", "place_order"}:
            proposed.append(action)
            continue

        if kind == "add":
            menu_item_id = action.get("menu_item_id")
            if not menu_item_id:
                continue
            quantity = int(action.get("quantity") or 1)
            size_id = action.get("menu_item_size_id")
            options = [str(o) for o in (action.get("selected_option_ids") or [])]
            # The same dish at the same size with the same options is one
            # line with a bigger number, not two lines — which is what the
            # web store does, and a cart that disagrees with itself across
            # channels is a bug waiting for a customer to find.
            for existing in current:
                if (
                    str(existing.menu_item_id) == str(menu_item_id)
                    and str(existing.size_id or "") == str(size_id or "")
                    and sorted(str(o) for o in existing.customization_option_ids) == sorted(options)
                ):
                    existing.quantity += quantity
                    break
            else:
                current.append(
                    CartLinePayload(
                        menu_item_id=menu_item_id,
                        quantity=quantity,
                        size_id=size_id,
                        customization_option_ids=options,
                    )
                )
        elif kind == "remove":
            current = [line for line in current if not _same_line(line, action)]
        elif kind == "set_quantity":
            quantity = int(action.get("quantity") or 1)
            for line in current:
                if _same_line(line, action):
                    line.quantity = quantity
        else:
            # A kind this build does not know how to carry out. Reported
            # rather than guessed at.
            proposed.append(action)

    return current, proposed


__all__ = ["CART_TTL_SECONDS", "apply_actions", "clear", "load", "save"]
