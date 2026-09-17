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

from datetime import datetime
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
# As long as the cart it belongs to. They were two hours and twenty-four, so
# a customer coming back at hour three still had their food and was asked for
# their address again. A conversation abandoned for a day starts clean, which
# is what anybody expects of a day-old chat.
DRAFT_TTL_SECONDS = 24 * 60 * 60

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
    # When the order is for, as an ISO datetime with its zone. Empty means
    # as soon as possible, which is every order until a closed kitchen makes
    # "later" the only answer.
    scheduled_at: str | None = None
    # The time the kitchen offered when it refused "now" — so that "yes" on
    # the next turn can mean that time. State, not a detail the customer gave.
    offered_scheduled_at: str | None = None
    # The choice the agent last asked for, as JSON: the dish, the quantity
    # and the ids behind each option. A turn's records do not survive it, so
    # without this "large one" was a sentence about nothing.
    pending_choice: str | None = None
    # Whether they have seen THIS order read back and said go ahead. Not
    # the same as `confirmed`, which is about their contact details: an
    # address can be right and the order still be wrong.
    order_confirmed: bool = False
    # How many times the order has been read back to them, so a yes that
    # goes astray cannot leave a customer answering the same question for
    # ever. The order is created unpaid, so the link is the confirmation
    # that actually spends money.
    place_asks: int = 0
    # The question this conversation is waiting on an answer to, as JSON:
    # what we asked in our own words, and what agreeing to it acts on. A
    # bare "yes" has no meaning by itself — live, "Which one would you like?"
    # was answered "Yes" and the turn had nothing to read it against, so the
    # reply pipeline filled the silence with prose about fulfillment types.
    awaiting: str | None = None
    # What they said they eat, kept for the conversation. Stating it on a
    # guest channel was remembered nowhere at all — `_remember_stated_diet`
    # writes to an account and every WhatsApp customer is a guest — so a
    # vegetarian was offered chicken two messages later.
    diet: str | None = None
    # Whether the customer has stood behind these details in THIS
    # conversation — by typing them, or by saying yes to them. Details that
    # came from their account have not been confirmed by anybody: an address
    # is the thing most likely to be different tonight, and using last
    # month's silently is how food arrives at the wrong door.
    confirmed: bool = False
    # How many times the confirmation has been put to them, so it is never
    # asked a third time.
    confirm_asks: int = 0
    # Set once the customer has been asked for their details. It is what
    # tells a later turn that the conversation is mid-collection, rather
    # than leaving the model to infer it from a thread it may not read.
    collecting: bool = False

    #: Not a detail, a state flag. Excluded everywhere the detail fields are
    #: counted, or "collecting" would report itself as something we hold.
    _STATE_FIELDS = (
        "collecting",
        "offered_scheduled_at",
        "pending_choice",
        "awaiting",
        "order_confirmed",
        "place_asks",
        "confirmed",
        "confirm_asks",
        "diet",
    )

    def known_fields(self) -> list[str]:
        return [
            f.name
            for f in fields(self)
            if f.name not in self._STATE_FIELDS and getattr(self, f.name)
        ]

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
    detail_fields = {f.name for f in fields(OrderDraft)} - set(OrderDraft._STATE_FIELDS)
    kept: dict[str, Any] = {
        key: value
        for key, value in stored.items()
        if key in detail_fields and isinstance(value, str)
    }
    for flag in ("collecting", "confirmed", "order_confirmed"):
        if isinstance(stored.get(flag), bool):
            kept[flag] = stored[flag]
    for counter in ("confirm_asks", "place_asks"):
        if isinstance(stored.get(counter), int):
            kept[counter] = stored[counter]
    # The other state fields are strings and round-trip as such. Live: the
    # time the kitchen offered was saved here and dropped on the very next
    # read, so "yes" on the following turn had nothing to say yes to.
    for name in OrderDraft._STATE_FIELDS:
        if name not in {
            "collecting", "confirmed", "confirm_asks", "order_confirmed", "place_asks",
        } and isinstance(stored.get(name), str):
            kept[name] = stored[name]
    return OrderDraft(**kept)


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

    # An address given is a delivery. Nobody hands over their street to
    # collect a bag themselves, and asking "delivery or pickup?" straight
    # after being told where to deliver reads as not having listened.
    if draft.delivery_address and not draft.fulfillment_type:
        draft.fulfillment_type = OrderFulfillmentType.DELIVERY.value

    # An address they typed is theirs and needs no reading back. Saying
    # "delivery" is not that: it settles how the food travels, not where to,
    # and treating it as confirmation meant an address from last month went
    # out unseen.
    if (given.get("delivery_address") or "").strip():
        draft.confirmed = True
    elif draft.fulfillment_type == OrderFulfillmentType.PICKUP.value and any(
        (given.get(field) or "").strip()
        for field in ("contact_name", "contact_email", "contact_phone")
    ):
        # Pickup has no address, so the field most likely to be stale and
        # unseen is not in play at all. Live: a customer collecting their own
        # food typed their name and email and was asked, on the very next
        # turn, whether those were the details to use.
        draft.confirmed = True

    when = (given.get("scheduled_at") or "").strip()
    if when:
        parsed = _parse_when(when)
        if parsed is None:
            problems.append("that time could not be read")
        elif parsed <= datetime.now(parsed.tzinfo):
            problems.append("that time has already passed")
        else:
            draft.scheduled_at = parsed.isoformat()
            # An offer taken up, or overridden, is no longer pending.
            draft.offered_scheduled_at = None

    return draft, problems


def _parse_when(value: str) -> datetime | None:
    """An ISO datetime with a zone, or None. Naive times are refused rather
    than guessed at: the branch, the customer and this server are not
    promised to share a clock."""

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


__all__ = [
    "DRAFT_TTL_SECONDS",
    "OrderDraft",
    "clear",
    "load",
    "remember",
    "save",
    "seed_from_profile",
]
