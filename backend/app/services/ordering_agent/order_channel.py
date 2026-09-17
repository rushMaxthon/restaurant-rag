"""Which conversation an order was placed from, if it was placed in one.

An order's own phone number is not the answer. A customer who ordered on
the web typed a number into a form; messaging it because a payment
succeeded would be sending WhatsApp to somebody who never opened a chat.
What matters is that THIS order came out of THIS conversation, and only the
turn that placed it knows that.

So the placing turn writes it down here and the payment webhook reads it
back. Kept in Redis beside the draft and the cart rather than on the order,
because it is a fact about a conversation rather than about an order, and
it stops mattering once the food has arrived.
"""

from __future__ import annotations

import logging
import uuid

from app.services.cache import cache_delete, cache_get_json, cache_set_json

logger = logging.getLogger(__name__)

# Long enough for a payment, a kitchen and a delivery, and for a customer
# who pays the next morning. Short enough that a number is not kept against
# an order nobody remembers.
CHANNEL_TTL_SECONDS = 7 * 24 * 60 * 60


def _key(order_id: uuid.UUID | str) -> str:
    return f"ordering:channel:{order_id}"


def remember(order_id: uuid.UUID | str, *, phone_number: str) -> None:
    """Note that this order came out of a chat with this number."""

    if not phone_number:
        return
    cache_set_json(_key(order_id), {"phone_number": phone_number}, ttl_seconds=CHANNEL_TTL_SECONDS)


def phone_for(order_id: uuid.UUID | str) -> str | None:
    """The number to talk to about this order, or None to stay quiet.

    None is the common answer and the safe one: every web order, and any
    chat order old enough to have expired. Never raises — Redis being
    unreachable costs a customer their confirmation, which is worse than it
    working and much better than a webhook failing and Stripe retrying a
    payment that was recorded perfectly well.
    """

    stored = cache_get_json(_key(order_id))
    if not isinstance(stored, dict):
        return None
    phone = stored.get("phone_number")
    return phone if isinstance(phone, str) and phone else None


def forget(order_id: uuid.UUID | str) -> None:
    cache_delete(_key(order_id))


__all__ = ["CHANNEL_TTL_SECONDS", "forget", "phone_for", "remember"]
