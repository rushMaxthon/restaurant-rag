"""What the waiter offers next, and why it is allowed to.

Every rule here is pure over plain dataclasses. The DB-backed orchestrator that
loads those dataclasses lives at the bottom of the file, so a change to a
selling rule never requires a database to re-check.

The `basis` field on a suggestion is load-bearing, not decoration: it is what
lets the client say "often ordered with your curry" for mined evidence and
"most people add a drink" for a category default. Rendering them alike would
present a guess as a measurement.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

# A pairing must leave exactly one item unaccounted for. Two missing items is a
# menu, not a nudge, and the customer cannot act on it with one tap.
PAIRING_MISSING_ITEM_COUNT = 1


@dataclass(frozen=True)
class PairingPattern:
    """A set of items real customers ordered together, with its mined score."""

    item_ids: tuple[uuid.UUID, ...]
    confidence_score: Decimal


@dataclass(frozen=True)
class CandidateItem:
    """The facts a selling rule is allowed to filter on."""

    menu_item_id: uuid.UUID
    category: str | None
    is_veg: bool
    is_available: bool


@dataclass(frozen=True)
class SellSuggestion:
    kind: str
    basis: str
    menu_item_id: uuid.UUID | None = None
    combo_id: uuid.UUID | None = None
    size_id: uuid.UUID | None = None
    customization_option_id: uuid.UUID | None = None
    saving: Decimal | None = None
    extra_cost: Decimal | None = None


def _is_offerable(candidate: CandidateItem | None, *, diet: str | None) -> bool:
    if candidate is None or not candidate.is_available:
        return False
    # A VEG customer being shown a non-veg pairing is the kind of mistake that
    # loses the account, not just the order.
    if diet == "VEG" and not candidate.is_veg:
        return False
    return True


def choose_pairing(
    patterns: list[PairingPattern],
    cart_item_ids: set[uuid.UUID],
    *,
    candidates: dict[uuid.UUID, CandidateItem],
    diet: str | None,
) -> SellSuggestion | None:
    """The strongest mined pattern this cart is one item short of."""

    if not cart_item_ids:
        return None

    best: tuple[Decimal, uuid.UUID] | None = None
    for pattern in patterns:
        missing = [item_id for item_id in pattern.item_ids if item_id not in cart_item_ids]
        # A pairing must leave exactly one item unaccounted for. Two or more missing
        # means the pattern is mostly about a meal this cart is not having; zero means
        # the cart already covers it.
        if len(missing) != PAIRING_MISSING_ITEM_COUNT:
            continue
        candidate_id = missing[0]
        if not _is_offerable(candidates.get(candidate_id), diet=diet):
            continue
        if best is None or pattern.confidence_score > best[0]:
            best = (pattern.confidence_score, candidate_id)

    if best is None:
        return None
    return SellSuggestion(kind="cross_sell", basis="co_occurrence", menu_item_id=best[1])


# Ordered by how naturally a waiter raises them. A drink is a normal thing to
# offer with a main; a soup is not, which is why this list is short rather than
# "every category the branch sells".
COMPLEMENT_CATEGORIES = ("Beverages", "Dessert")


def choose_category_default(
    cart_categories: set[str],
    *,
    bestsellers: dict[str, list[uuid.UUID]],
    candidates: dict[uuid.UUID, CandidateItem],
    diet: str | None,
) -> SellSuggestion | None:
    """The branch bestseller from a category this cart has nothing from.

    Weaker than a mined pairing and labelled as such. It exists because mined
    evidence is thin until order volume grows, and a waiter who says nothing
    for the first thousand orders is not a waiter.
    """

    # Empty cart_categories means the cart has no items with resolvable
    # categories — not that the cart is empty. The caller must represent
    # uncategorised items (with a sentinel or similar) so this never fires
    # on an actual cart. The truly-empty-cart case is filtered by the caller.
    if not cart_categories:
        return None

    for category in COMPLEMENT_CATEGORIES:
        if category in cart_categories:
            continue
        for candidate_id in bestsellers.get(category, []):
            if _is_offerable(candidates.get(candidate_id), diet=diet):
                return SellSuggestion(
                    kind="cross_sell",
                    basis="category_default",
                    menu_item_id=candidate_id,
                )
    return None
