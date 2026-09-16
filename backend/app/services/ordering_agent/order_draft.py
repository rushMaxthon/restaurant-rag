"""Where an order's contact details live before there is an order.

Placing an order needs a name, a phone, an email and — for delivery — an
address. A signed-in customer has most of that on their account already. A
customer on WhatsApp has only a verified phone number, and gives the rest a
sentence at a time, over several turns. Nothing can be written to `orders`
until all of it is in hand, so it accumulates here.

Redis, keyed by the chat session, with a TTL: the same store the chat's own
session memory uses, so a guest gets it too and nobody has to migrate a
table for something that is thrown away the moment the order is placed.

**The values never go back into a prompt.** `known_fields` reports which
details are held, not what they are — a customer's home address belongs on
the order and in the kitchen ticket, not in a model's context window on
every later turn of the conversation. The model passes each value through
once, to `remember`, which validates and stores it; after that it only ever
learns that the field is filled.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, fields
from typing import Any

from app.config import get_settings
from app.models.enums import OrderFulfillmentType
from app.services.auth import normalize_phone_number
from app.services.cache import cache_delete, cache_get_json, cache_set_json

settings = get_settings()

# Long enough to survive a conversation with a slow typist and a sandwich
# break; short enough that an abandoned draft does not sit in Redis holding
# someone's address for a week.
DRAFT_TTL_SECONDS = 2 * 60 * 60

# Deliberately loose. This is a sanity check against "yes please" landing in
# the email field, not an attempt to out-parse RFC 5322 — the receipt is
# Stripe's problem, and a customer who mistypes their own address knows
# sooner than any regex could tell them.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

# `OrderCreateRequest.delivery_address` takes 5 characters as its floor, and
# two stores disagreeing about what counts as an address is how a draft
# becomes an order that will not save.
_MIN_ADDRESS = 5


@dataclass(slots=True)
class OrderDraft:
    """The contact details gathered so far. Every field optional: the whole
    point is that it is incomplete until it is not."""

    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    delivery_address: str | None = None
    fulfillment_type: str | None = None

    def known_fields(self) -> list[str]:
        return [f.name for f in fields(self) if getattr(self, f.name)]

    def missing_fields(self) -> list[str]:
        """What still has to be asked for.

        Pickup needs no address, and asking for one is how a customer ends up
        typing their home address to a restaurant they are walking to.
        """

        needed = ["fulfillment_type", "contact_name", "contact_phone", "contact_email"]
        if self.fulfillment_type == OrderFulfillmentType.DELIVERY.value:
            needed.append("delivery_address")
        elif self.fulfillment_type is None:
            # Until they say, assume the address will be wanted: better to
            # have asked for it than to stall at the last step.
            needed.append("delivery_address")
        return [name for name in needed if not getattr(self, name)]

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields()


def _key(session_id: uuid.UUID | str) -> str:
    return f"ordering:draft:{session_id}"


def load(session_id: uuid.UUID | str) -> OrderDraft:
    """The draft for this conversation, or an empty one.

    Never raises: Redis being unreachable means the customer is asked for
    their details again, which is a worse conversation but a working one.
    """

    stored = cache_get_json(_key(session_id))
    if not isinstance(stored, dict):
        return OrderDraft()
    allowed = {f.name for f in fields(OrderDraft)}
    return OrderDraft(**{k: v for k, v in stored.items() if k in allowed and isinstance(v, str)})


def save(session_id: uuid.UUID | str, draft: OrderDraft) -> None:
    cache_set_json(_key(session_id), asdict(draft), ttl_seconds=DRAFT_TTL_SECONDS)


def clear(session_id: uuid.UUID | str) -> None:
    """Called once the order exists. The details are on the order from then
    on, and there is no reason for a copy to outlive it."""

    cache_delete(_key(session_id))


def seed_from_profile(draft: OrderDraft, customer: Any | None) -> OrderDraft:
    """Fill what the account already knows, without overwriting what the
    customer has just said.

    A signed-in customer should not be asked for their own name. What they
    typed into this conversation wins over what is on file, because the
    reason to type it is usually that the file is wrong — a different address
    tonight, a number they are actually holding.
    """

    if customer is None:
        return draft
    if not draft.contact_name:
        draft.contact_name = (getattr(customer, "full_name", None) or "").strip() or None
    if not draft.contact_phone:
        draft.contact_phone = normalize_phone_number(getattr(customer, "phone_number", None))
    if not draft.contact_email:
        draft.contact_email = (getattr(customer, "email", None) or "").strip() or None
    if not draft.delivery_address:
        draft.delivery_address = (getattr(customer, "default_address", None) or "").strip() or None
    return draft


def remember(draft: OrderDraft, **given: str | None) -> tuple[OrderDraft, list[str]]:
    """Take what the customer just gave, validate it, and keep what is good.

    Returns the updated draft and the reasons anything was refused. A refusal
    is fed back to the model so it can ask again for that one field rather
    than starting the whole exchange over — "that email looks wrong" is a
    normal thing for a waiter to say.
    """

    problems: list[str] = []

    name = (given.get("contact_name") or "").strip()
    if name:
        if len(name) > 255:
            problems.append("that name is too long")
        else:
            draft.contact_name = name

    phone_raw = (given.get("contact_phone") or "").strip()
    if phone_raw:
        phone = normalize_phone_number(phone_raw)
        # The order endpoint normalises the same way, so a number accepted
        # here cannot be rejected there.
        if not phone or len(re.sub(r"\D", "", phone)) < 7:
            problems.append("that does not look like a phone number")
        else:
            draft.contact_phone = phone

    email = (given.get("contact_email") or "").strip()
    if email:
        if not _EMAIL.match(email) or len(email) > 320:
            problems.append("that does not look like an email address")
        else:
            draft.contact_email = email

    address = (given.get("delivery_address") or "").strip()
    if address:
        if len(address) < _MIN_ADDRESS:
            problems.append("that address is too short to deliver to")
        elif len(address) > 2000:
            problems.append("that address is too long")
        else:
            draft.delivery_address = address

    fulfillment = (given.get("fulfillment_type") or "").strip().upper()
    if fulfillment:
        valid = {item.value for item in OrderFulfillmentType}
        if fulfillment not in valid:
            problems.append(f"fulfillment_type must be one of {sorted(valid)}")
        else:
            draft.fulfillment_type = fulfillment

    return draft, problems


__all__ = [
    "DRAFT_TTL_SECONDS",
    "OrderDraft",
    "clear",
    "load",
    "remember",
    "save",
    "seed_from_profile",
]
