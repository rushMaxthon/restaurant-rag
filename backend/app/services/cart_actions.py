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
