"""What a customer's sentence does to their cart, and whether it is safe to
apply without asking.

Every rule here is pure over plain inputs and dataclasses, the same
discipline `suggestions.py` uses for the selling rules. This module does NOT
import from `rag.py` — `rag.py` imports from here — for the identical reason
`suggestions.py` keeps its own `SuggestionMemory` rather than reaching into
`rag.py`'s session dataclass: importing the other direction would risk a
circular import once `rag.py` calls this module, and would couple a small,
independently-testable file to the whole retrieval pipeline.

`DishReferenceVerdict` below intentionally mirrors `rag.DishReference`'s three
values rather than importing it, for that same reason.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Literal

DishReferenceVerdict = Literal["named", "absent", "unknown"]

# Longest phrase first: "a couple of" must be tried before "a" or it would
# match "a" and return 1 for "a couple of spring rolls".
_NUMBER_WORDS: dict[str, int] = {
    "a couple of": 2,
    "a couple": 2,
    "couple of": 2,
    "couple": 2,
    "a few": 3,
    "few": 3,
    "single": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "a": 1,
    "an": 1,
}
_NUMBER_WORD_ORDER = sorted(_NUMBER_WORDS, key=len, reverse=True)

# "2x" / "x2" only — a bare digit elsewhere in the sentence is as likely to be
# a price ("under $15"), a phone-style quantity ("for 2 people") or a size, and
# this parser has no grammar to tell those apart. Known gap: bare digits
# immediately before a food-sounding word ("add 3 chicken satay") ARE
# supported below via a narrower, currency-guarded pattern; anything looser is
# left unread rather than guessed.
_MULTIPLIER_PATTERN = re.compile(r"\b(\d{1,2})\s*x\b|\bx\s*(\d{1,2})\b", re.IGNORECASE)

# A bare digit is read as a quantity only when it is not adjacent to a
# currency mark or a unit that means it was never a quantity of DISHES.
_BARE_DIGIT_PATTERN = re.compile(
    r"(?<![\$\d])\b(\d{1,2})\b(?!\s*(?:am|pm|rupees?|rs\.?|dollars?|percent|%|people|mins?|minutes?))",
    re.IGNORECASE,
)

# Currency markers that indicate a number is a price, not a quantity of dishes.
# Windowed check (below) applies this, not message-global.
_CURRENCY_MARK_PATTERN = re.compile(
    r"[\$₹]|\bunder\b|\bover\b|\bbudget\b|\bdollars?\b|\brupees?\b", re.IGNORECASE
)
_CURRENCY_WINDOW = 15  # characters of context on each side treated as "nearby"


def _has_nearby_currency_mark(lowered: str, start: int, end: int) -> bool:
    """Whether a currency word or symbol sits close enough to this match to
    mean the match is a price, not a quantity of dishes.

    Windowed rather than message-global: "add 2 chicken satay, under $15
    budget" must still read 2 as the quantity — the currency mention is
    about a DIFFERENT number in the same sentence. A global check dropped
    that legitimate quantity outright.
    """
    window_start = max(0, start - _CURRENCY_WINDOW)
    window_end = min(len(lowered), end + _CURRENCY_WINDOW)
    return bool(_CURRENCY_MARK_PATTERN.search(lowered[window_start:window_end]))


def extract_requested_quantity(message: str) -> int | None:
    """How many the customer asked for, or `None` if nothing said so.

    `None`, not a default of 1: whether silence means "one" or "not this
    field's job to decide" is a business decision that belongs to the caller
    (`resolve_cart_actions`), not to the parser. Collapsing that choice in
    here would make the parser lie about what it actually read.
    """

    lowered = message.lower()

    multiplier = _MULTIPLIER_PATTERN.search(lowered)
    if multiplier:
        digits = multiplier.group(1) or multiplier.group(2)
        return int(digits)

    for phrase in _NUMBER_WORD_ORDER:
        match = re.search(rf"\b{re.escape(phrase)}\b", lowered)
        if match:
            if _has_nearby_currency_mark(lowered, match.start(), match.end()):
                # This number-word is near a currency mark, so it's likely a price.
                # Skip it and try the next phrase, or fall through to bare digits.
                continue
            return _NUMBER_WORDS[phrase]

    bare = _BARE_DIGIT_PATTERN.search(lowered)
    if bare:
        if not _has_nearby_currency_mark(lowered, bare.start(), bare.end()):
            return int(bare.group(1))

    return None


CartVerb = Literal["add", "remove", "set_quantity", "clear"]

# Fix round 1 (review, 2026-09-15): the first version of this classifier
# matched bare keywords — "order", "clear", "take ... out", "i want" — with no
# requirement that the sentence be ABOUT the cart. That fired on ordinary
# restaurant conversation: "cancel my order" (a status question) read as
# "add", "do you do take out?" (a fulfillment-type question) read as
# "remove", and a bare "never mind" read as "clear" — the most destructive
# verb — with nothing to do with a cart anywhere in the sentence. The rule
# from the review: cues must be scoped to the cart, and ambiguity must return
# `None` rather than guess. Below, `_has_nearby_cart_word` gates the
# destructive `clear` cues on an actual cart/order/basket word nearby (the
# same windowed-proximity idea `_has_nearby_currency_mark` above uses for
# prices), `_matches_add` narrows "order", "i want" and "get me" so they only
# fire on item requests, and `_REMOVE_PATTERN`'s take-out cue requires an
# object between "take" and "out" so it no longer matches the fulfillment
# type. See `classify_cart_verb` for how multiple matches are resolved.
_CLEAR_CUE_PATTERN = re.compile(r"\bclear\b|\bstart over\b|\bnever ?mind\b", re.IGNORECASE)
_CART_WORD_PATTERN = re.compile(r"\b(cart|order|basket)\b", re.IGNORECASE)
_CART_WORD_WINDOW = 20  # chars of context each side — enough to bridge "start over with my order"

_SET_QUANTITY_PATTERN = re.compile(
    r"\bmake it\b|\bchange (?:it|the (?:quantity|order))? ?to\b|\bset (?:it|the quantity)? ?to\b",
    re.IGNORECASE,
)

# "take ... out" used to be `r"\btake .* out\b"`, whose `.*` matches zero
# characters — so it matched the bare phrase "take out" itself, and every
# "do you do take out?" / "is this for take out or delivery?" question read
# as removing an item. Take-out is a fulfillment type on this site, not a
# cart action. Requiring at least one token between "take" and "out" keeps
# "take the rice out" (an object sits between them) while dropping the
# adjacent noun phrase.
_REMOVE_PATTERN = re.compile(
    r"\bremove\b|\bdelete\b|\btake\s+(?:\S+\s+)+out\b|\bget rid of\b|\bdon'?t want\b",
    re.IGNORECASE,
)

_ADD_SIMPLE_PATTERN = re.compile(
    r"\badd\b|\bi'?ll have\b|\bgive me\b|\bput in\b|\banother\b", re.IGNORECASE
)
# "order" as a verb ("order two spring rolls") is an add cue; "order" as a
# noun referring to an existing order ("my order", "cancel my order", "the
# status of my order") is not, and the noun usage is the far more common one
# in a chat that already has an order in flight. The two are indistinguishable
# by the word itself, but the noun form is reliably preceded by a determiner
# and the imperative form isn't — so exclude "order" immediately preceded by
# one of these rather than matching it bare.
_ORDER_VERB_PATTERN = re.compile(
    r"(?<!my )(?<!the )(?<!your )(?<!this )(?<!that )(?<!an )\border\b", re.IGNORECASE
)
# "i want to <verb>" asks staff to DO something ("i want to speak to a
# manager"); only "i want <a thing>" is a request for a dish. Whether what
# follows "want" is an infinitive is the cheapest signal available without a
# real parse.
_WANT_ITEM_PATTERN = re.compile(r"\bi want\b(?!\s+to\b)", re.IGNORECASE)
# "get me" is a general fetch-something phrase, and most of what customers
# ask staff to fetch outside the menu falls into a small, known set. Not
# exhaustive — a deterministic tier never is — but it removes the concrete
# false positive the review found ("can you get me the wifi password").
_GET_ME_PATTERN = re.compile(r"\bget me\b", re.IGNORECASE)
_GET_ME_NON_ITEM_PATTERN = re.compile(
    r"\bget me\b\s*(?:the\s+)?(?:wifi|wi-fi|password|manager|bill|check|receipt)\b", re.IGNORECASE
)


def _has_nearby_cart_word(message: str, start: int, end: int) -> bool:
    """Whether a cart/order/basket word sits close enough to a destructive cue
    to mean the sentence is actually about the cart.

    Windowed rather than message-global for the same reason
    `_has_nearby_currency_mark` above is windowed: a global check would also
    accept a cart word anywhere in an unrelated sentence, which is exactly
    the false-positive shape the review flagged for bare "never mind" and
    "start over".
    """

    window_start = max(0, start - _CART_WORD_WINDOW)
    window_end = min(len(message), end + _CART_WORD_WINDOW)
    return bool(_CART_WORD_PATTERN.search(message[window_start:window_end]))


def _matches_add(message: str) -> bool:
    if _ADD_SIMPLE_PATTERN.search(message):
        return True
    if _ORDER_VERB_PATTERN.search(message):
        return True
    if _WANT_ITEM_PATTERN.search(message):
        return True
    if _GET_ME_PATTERN.search(message) and not _GET_ME_NON_ITEM_PATTERN.search(message):
        return True
    return False


def classify_cart_verb(message: str) -> CartVerb | None:
    """Which kind of cart mutation this sentence asks for, if any.

    Independent of `ExtractedIntent.intent` — that field is a menu-discovery
    taxonomy (`recommendation`, `menu_question`, ...) with no cart-mutation
    value in it, and adding one there would touch every `intent.intent == ...`
    branch already in `rag.py`. This classifier is additive: `None` means "not
    a cart-action message", and every existing reply path is unaffected.

    When more than one category matches — "remove the pizza and add a
    coke" — this returns `None` rather than picking one by a fixed priority
    order. An earlier version prioritised by destructiveness, but silently
    acting on (or dropping) half of a two-part request is a worse failure
    than asking; a later tier can still resolve it by asking which change
    the customer meant, or by handling both in sequence.
    """

    clear_cue = _CLEAR_CUE_PATTERN.search(message)
    is_clear = bool(clear_cue and _has_nearby_cart_word(message, clear_cue.start(), clear_cue.end()))
    is_set_quantity = bool(_SET_QUANTITY_PATTERN.search(message))
    is_remove = bool(_REMOVE_PATTERN.search(message))
    is_add = _matches_add(message)

    matched: list[CartVerb] = []
    if is_clear:
        matched.append("clear")
    if is_set_quantity:
        matched.append("set_quantity")
    if is_remove:
        matched.append("remove")
    if is_add:
        matched.append("add")

    if len(matched) == 1:
        return matched[0]
    return None


ActionKind = Literal["add", "remove", "set_quantity", "clear"]
ActionStatus = Literal["applied", "proposed"]
# `needs_choice` is not in the design spec's draft enum (`named` / `ambiguous`
# / `destructive`) — added because "the dish was named confidently but has
# sizes or customizations" is a different failure from "which item?" or
# "should this really happen?", and the client needs to tell them apart to
# render the right affordance (a link to the dish page, not a confirm button).
ActionReason = Literal["named", "ambiguous", "destructive", "needs_choice"]


@dataclass(frozen=True)
class ExistingCartLine:
    """The only fact about an existing cart line the resolver needs."""

    menu_item_id: uuid.UUID


@dataclass(frozen=True)
class ResolvedDish:
    """The single item this turn's retrieval landed on, if any.

    Deliberately just these three fields: they are exactly what
    `ChatSuggestionItem` already carries for the top retrieved candidate, so
    the caller in `rag.py` builds this from data already computed for the
    reply rather than a second database read.
    """

    menu_item_id: uuid.UUID
    has_sizes: bool
    has_customizations: bool


@dataclass(frozen=True)
class CartAction:
    kind: ActionKind
    status: ActionStatus
    reason: ActionReason
    menu_item_id: uuid.UUID | None = None
    quantity: int | None = None


def _matching_lines(existing_lines: list[ExistingCartLine], menu_item_id: uuid.UUID) -> list[ExistingCartLine]:
    return [line for line in existing_lines if line.menu_item_id == menu_item_id]


def resolve_cart_actions(
    message: str,
    *,
    dish_reference: DishReferenceVerdict,
    resolved_dish: ResolvedDish | None,
    existing_lines: list[ExistingCartLine],
) -> list[CartAction]:
    """One customer sentence, at most one cart action.

    A list, per the design's `cart_actions: list[CartAction] # ordered, may be
    empty` — this phase only ever returns 0 or 1, because multi-item parsing
    ("two pad thai and a curry") is the phrasing tier-2 (an LLM planner, not
    built) exists for. Returning a list rather than `CartAction | None` keeps
    the contract stable for when that seam is filled in.
    """

    verb = classify_cart_verb(message)
    if verb is None:
        return []

    if verb == "clear":
        # Proposed ALWAYS, whatever the confidence — the spec is explicit that
        # `clear` never applies itself.
        return [CartAction(kind="clear", status="proposed", reason="destructive")]

    # Every remaining verb needs a dish to act on. `absent` (menu doesn't have
    # it) and `unknown` (no distance to judge by) both mean "not this
    # resolver's job to guess" — silence beats a guess, the same rule
    # `classify_dish_reference` states for the reply itself.
    if resolved_dish is None or dish_reference != "named":
        return []

    matches = _matching_lines(existing_lines, resolved_dish.menu_item_id)
    quantity = extract_requested_quantity(message)

    if verb == "add":
        if resolved_dish.has_sizes or resolved_dish.has_customizations:
            return [
                CartAction(
                    kind="add",
                    status="proposed",
                    reason="needs_choice",
                    menu_item_id=resolved_dish.menu_item_id,
                    quantity=quantity or 1,
                )
            ]
        return [
            CartAction(
                kind="add",
                status="applied",
                reason="named",
                menu_item_id=resolved_dish.menu_item_id,
                quantity=quantity or 1,
            )
        ]

    if verb == "remove":
        if not matches:
            # Nothing to remove is not a destructive act on nothing — silence.
            return []
        if len(matches) > 1:
            return [
                CartAction(kind="remove", status="proposed", reason="destructive", menu_item_id=resolved_dish.menu_item_id)
            ]
        return [CartAction(kind="remove", status="applied", reason="named", menu_item_id=resolved_dish.menu_item_id)]

    if verb == "set_quantity":
        if quantity is None or not matches:
            return []
        if len(matches) > 1:
            return [
                CartAction(
                    kind="set_quantity",
                    status="proposed",
                    reason="ambiguous",
                    menu_item_id=resolved_dish.menu_item_id,
                    quantity=quantity,
                )
            ]
        return [
            CartAction(
                kind="set_quantity",
                status="applied",
                reason="named",
                menu_item_id=resolved_dish.menu_item_id,
                quantity=quantity,
            )
        ]

    return []  # pragma: no cover - exhaustive over CartVerb
