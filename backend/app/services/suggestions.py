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

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.services.cache import cache_get_json, cache_set_json

logger = logging.getLogger(__name__)

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


@dataclass(frozen=True)
class CartLineFacts:
    menu_item_id: uuid.UUID
    size_id: uuid.UUID | None
    customization_option_ids: frozenset[uuid.UUID]


@dataclass(frozen=True)
class ComboUpgrade:
    combo_id: uuid.UUID
    item_ids: tuple[uuid.UUID, ...]
    saving: Decimal


@dataclass(frozen=True)
class SizeOption:
    menu_item_id: uuid.UUID
    size_id: uuid.UUID
    extra_cost: Decimal


@dataclass(frozen=True)
class AddOnOption:
    menu_item_id: uuid.UUID
    option_id: uuid.UUID
    extra_cost: Decimal


def choose_upsell(
    lines: list[CartLineFacts],
    *,
    combos: list[ComboUpgrade],
    sizes: list[SizeOption],
    add_ons: list[AddOnOption],
) -> SellSuggestion | None:
    """First rung that fires wins, and the rungs descend in customer value.

    Add-on options already chosen are pooled across every cart line, not tracked
    per line. So a pizza ordered twice with different extras can lose an otherwise-
    valid add-on offer on one of the lines. This is accepted: the failure direction
    is a missed suggestion rather than a wrong one. A per-line answer would require
    the suggestion to carry a line identity, which this phase's contract does not
    have. Phase 2 introduces cart actions with line identity; that is the right
    moment to revisit per-line tracking.
    """

    if not lines:
        return None

    cart_item_ids = {line.menu_item_id for line in lines}

    for combo in combos:
        if set(combo.item_ids) <= cart_item_ids:
            return SellSuggestion(
                kind="up_sell",
                basis="combo_upgrade",
                combo_id=combo.combo_id,
                saving=combo.saving,
            )

    for size in sizes:
        if size.menu_item_id in cart_item_ids:
            return SellSuggestion(
                kind="up_sell",
                basis="size_upgrade",
                menu_item_id=size.menu_item_id,
                size_id=size.size_id,
                extra_cost=size.extra_cost,
            )

    chosen_options = {option for line in lines for option in line.customization_option_ids}
    for add_on in add_ons:
        if add_on.menu_item_id in cart_item_ids and add_on.option_id not in chosen_options:
            return SellSuggestion(
                kind="up_sell",
                basis="add_on",
                menu_item_id=add_on.menu_item_id,
                customization_option_id=add_on.option_id,
                extra_cost=add_on.extra_cost,
            )

    return None


# Two noes is the whole budget. A third ask does not convert; it teaches the
# customer that the prompts are noise and costs every future suggestion.
DECLINE_LIMIT = 2

# Long enough to outlive a browsing session, short enough that tomorrow is a
# fresh conversation.
SUGGESTION_MEMORY_TTL_SECONDS = 60 * 60 * 6


@dataclass(frozen=True)
class SuggestionMemory:
    offered_item_ids: frozenset[uuid.UUID] = frozenset()
    declined_item_ids: frozenset[uuid.UUID] = frozenset()
    decline_count: int = 0


def _suggestion_identity(suggestion: SellSuggestion) -> uuid.UUID | None:
    """The one field that names this suggestion, for suppression purposes.

    menu_item_id is not set on every suggestion: combo_upgrade carries only
    combo_id, because a combo is several items, not one. Falling through
    menu_item_id -> combo_id -> customization_option_id means a combo is
    still remembered by combo_id even though it has no menu_item_id.
    is_suppressed and record_offer both call this so the two can never
    disagree about what "the same suggestion" means.

    menu_item_id wins whenever it is set, which includes add_on suggestions
    (they carry both menu_item_id and customization_option_id). Two different
    add-ons offered on the same item therefore collide under one identity —
    the same missed-suggestion-over-wrong-suggestion trade-off choose_upsell
    already accepts for pooling add-on options across cart lines.
    """

    return suggestion.menu_item_id or suggestion.combo_id or suggestion.customization_option_id


def is_suppressed(
    suggestion: SellSuggestion,
    *,
    memory: SuggestionMemory,
    cart_item_ids: set[uuid.UUID],
) -> bool:
    if memory.decline_count >= DECLINE_LIMIT:
        return True

    # Only cross-sell offers a genuinely new item, so only cross-sell can be
    # made redundant by something already sitting in the cart. up_sell's two
    # rungs (size_upgrade, add_on) set menu_item_id to the item being
    # upgraded, which is in the cart by definition — applying this check to
    # them would suppress every up-sell choose_upsell could ever produce.
    if suggestion.kind == "cross_sell" and suggestion.menu_item_id in cart_item_ids:
        return True

    identity = _suggestion_identity(suggestion)
    if identity is None:
        return False
    return identity in memory.offered_item_ids or identity in memory.declined_item_ids


def record_offer(memory: SuggestionMemory, suggestion: SellSuggestion) -> SuggestionMemory:
    identity = _suggestion_identity(suggestion)
    if identity is None:
        # Nothing to key the memory on, so this offer cannot be recognised
        # again later. It is offered once and forgotten rather than raising —
        # a suggestion the rules produced is still worth showing even if this
        # module can't yet remember it.
        return memory
    return SuggestionMemory(
        offered_item_ids=memory.offered_item_ids | {identity},
        declined_item_ids=memory.declined_item_ids,
        decline_count=memory.decline_count,
    )


def record_decline(memory: SuggestionMemory, menu_item_id: uuid.UUID) -> SuggestionMemory:
    return SuggestionMemory(
        offered_item_ids=memory.offered_item_ids,
        declined_item_ids=memory.declined_item_ids | {menu_item_id},
        decline_count=memory.decline_count + 1,
    )


def _memory_cache_key(user_id: uuid.UUID, session_id: uuid.UUID) -> str:
    return f"suggestions:memory:{user_id}:{session_id}"


def load_memory(user_id: uuid.UUID, session_id: uuid.UUID | None) -> SuggestionMemory:
    """Owned here rather than riding on the RAG session state.

    `GET /api/suggestions` must work with no conversation at all, and reaching
    into `rag.py` for its dataclass would couple a page render to the whole
    retrieval module — and make the import cycle real once rag.py calls this
    service.
    """

    if session_id is None:
        return SuggestionMemory()
    payload = cache_get_json(_memory_cache_key(user_id, session_id))
    if not isinstance(payload, dict):
        return SuggestionMemory()
    try:
        return SuggestionMemory(
            offered_item_ids=frozenset(
                uuid.UUID(value) for value in payload.get("offered", []) if isinstance(value, str)
            ),
            declined_item_ids=frozenset(
                uuid.UUID(value) for value in payload.get("declined", []) if isinstance(value, str)
            ),
            decline_count=int(payload.get("decline_count", 0)),
        )
    except (TypeError, ValueError):
        logger.warning("Suggestion memory payload validation failed; starting fresh")
        return SuggestionMemory()


def store_memory(
    user_id: uuid.UUID,
    session_id: uuid.UUID | None,
    memory: SuggestionMemory,
) -> None:
    if session_id is None:
        return
    cache_set_json(
        _memory_cache_key(user_id, session_id),
        {
            "offered": sorted(str(value) for value in memory.offered_item_ids),
            "declined": sorted(str(value) for value in memory.declined_item_ids),
            "decline_count": memory.decline_count,
        },
        ttl_seconds=SUGGESTION_MEMORY_TTL_SECONDS,
    )
