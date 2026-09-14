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

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.generated_combo import GeneratedCombo
from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.models.menu_item_size import MenuItemSize
from app.services.bestsellers import get_dynamic_bestseller_ids_by_location
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
class CategoryFallbackItem:
    """A candidate for the category-default rung's own fallback.

    Carries price and name only because those are what the ordering below
    needs to break ties — the DB read that produces these lives in the
    orchestrator, not here.
    """

    menu_item_id: uuid.UUID
    price: Decimal
    name: str


def order_category_fallback(items: list[CategoryFallbackItem]) -> list[uuid.UUID]:
    """A total, stable order for offering something from a category that has
    no bestseller yet.

    `record_offer`/`is_suppressed` key suppression memory on the id this list
    hands to `choose_category_default` first, so the same cart must produce
    the same leading candidate on every call — a tie-break that could vary
    between calls (dict/set iteration order, an unstable sort) would let the
    "same" cart quietly offer a different item each time, which breaks the
    decline-limit bookkeeping instead of genuinely exhausting it. Cheapest
    item first, since this rung exists for a low-friction nudge rather than
    the highest ticket; name then id break any remaining ties so two
    identically-priced items still sort the same way every time.
    """

    ordered = sorted(items, key=lambda item: (item.price, item.name, item.menu_item_id))
    return [item.menu_item_id for item in ordered]


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


# `MenuItem.category` is a plain string column, and a null or blank value is
# indistinguishable from "no categories" if we simply omit it when building
# cart_categories. choose_category_default's contract (see its docstring)
# treats an empty set as "the cart is empty" — so an uncategorised item must
# still occupy a slot in the set, under a value that can never collide with a
# real category or appear in COMPLEMENT_CATEGORIES.
UNCATEGORISED = "\x00uncategorised"


def _load_visible_combos(db: Session, location_id: uuid.UUID) -> list[GeneratedCombo]:
    """Combos this branch can show — AND mined from real orders.

    `choose_pairing`'s `co_occurrence` basis says "Often ordered with what
    you've got", which is only true because every row reaching it today
    happens to have been mined from order history — the single construction
    site (`generated_combos.py`) hardcodes `generated_from_orders=True`. That
    is an accident of what exists, not a rule this query enforces, and
    `GeneratedCombo.generated_from_orders` exists precisely to distinguish
    mined rows from an owner-authored one. Filtering on it here makes the
    claim true by construction: the day a hand-built combo lands with the
    flag correctly set to False, this query — not luck — is what keeps it out
    of a sentence that says people ordered it together.
    """

    return list(
        db.scalars(
            select(GeneratedCombo)
            .where(
                GeneratedCombo.restaurant_location_id == location_id,
                GeneratedCombo.is_active.is_(True),
                GeneratedCombo.is_customer_visible.is_(True),
                GeneratedCombo.generated_from_orders.is_(True),
            )
            .options(selectinload(GeneratedCombo.combo_items))
        ).all()
    )


def suggestion_for_cart(
    db: Session,
    *,
    cart_lines: list[CartLineFacts],
    restaurant_location_id: uuid.UUID | None,
    user_id: uuid.UUID,
    session_id: uuid.UUID | None,
    diet: str | None,
) -> SellSuggestion | None:
    """The single suggestion this cart earns, or nothing.

    Nothing is a perfectly good answer and the common one early on: mined
    evidence is thin, and the alternative to silence is inventing a reason.
    """

    if restaurant_location_id is None or not cart_lines:
        return None

    memory = load_memory(user_id, session_id)
    if memory.decline_count >= DECLINE_LIMIT:
        return None

    combos = _load_visible_combos(db, restaurant_location_id)

    # Every candidate the rules may look at, loaded once and scoped to the
    # branch. An id that does not resolve HERE is simply absent, which is what
    # makes an untrusted cart payload safe to accept.
    menu_items = {
        item.id: item
        for item in db.scalars(
            select(MenuItem).where(
                MenuItem.restaurant_location_id == restaurant_location_id,
                MenuItem.is_available.is_(True),
            )
        ).all()
    }

    # cart_lines is the browser's word about its own cart, not a query result —
    # nothing stops a request from naming a menu_item_id that belongs to a
    # different restaurant or a different branch of this one. The cross-sell
    # rules already can't be fooled by that: they only ever propose ids drawn
    # from `candidates`, which is scoped to this branch. The up-sell ladder is
    # different — it reads sizes and add-ons keyed off the *cart's* ids, so an
    # unresolved line would otherwise earn a real offer for a dish this
    # kitchen doesn't serve. Dropping unresolved lines here, before anything
    # downstream sees them, closes that gap at the one place it can be closed
    # for good instead of trusting every future caller to have done it first.
    cart_lines = [line for line in cart_lines if line.menu_item_id in menu_items]
    if not cart_lines:
        return None

    cart_item_ids = {line.menu_item_id for line in cart_lines}
    candidates = {
        item_id: CandidateItem(
            menu_item_id=item.id,
            category=item.category,
            is_veg=item.is_veg,
            is_available=item.is_available,
        )
        for item_id, item in menu_items.items()
    }

    patterns = [
        PairingPattern(
            item_ids=tuple(entry.menu_item_id for entry in combo.combo_items),
            confidence_score=combo.confidence_score,
        )
        for combo in combos
    ]

    cart_categories = {
        menu_items[item_id].category or UNCATEGORISED
        for item_id in cart_item_ids
        if item_id in menu_items
    }
    bestsellers_by_category = _bestsellers_by_category(db, restaurant_location_id, menu_items)

    # Order matters: an upgrade to something already in the cart is more
    # relevant than a new item, and mined evidence outranks a category guess.
    #
    # combos=[], sizes=[], add_ons=[] here (not the branch's loaded combos,
    # sizes and add-ons): every rung of choose_upsell answers with something
    # this phase's renderer cannot honour.
    #
    #   - combo_upgrade carries only a combo_id, and the client resolves
    #     suggestion names through a menu-item lookup with no typed way to
    #     fetch a combo by id.
    #   - size_upgrade names the cart's OWN menu_item_id as the subject (the
    #     suggestion IS the size change), but Phase 1 has no way to mutate an
    #     existing cart line — "Choose" lands on the dish page, where adding
    #     produces a second, separate line beside the one already there. The
    #     prompt would promise an upgrade and deliver a duplicate.
    #   - add_on names the cart's OWN menu_item_id too, while the actual
    #     subject is a customization_option_id the client has no typed way to
    #     resolve to a name — so a cart holding a dish with an unselected
    #     paid extra would render "Add <dish already in the cart>?" next to a
    #     button that cannot add the extra.
    #
    # For combos, passing them through would record the offer as made while
    # the client rendered nothing — a wasted rung. For sizes and add-ons the
    # failure is worse: the client CAN render something, just something that
    # names the wrong subject or promises a mutation it cannot perform, and a
    # confidently wrong prompt is worse than a silent one. All three rungs are
    # disabled for the same reason, one of them just costs more to leave on.
    # Temporary — Phase 2 adds cart-line mutation and Phase 3 adds the combo
    # renderer, and each becomes real again once its client-side counterpart
    # exists. The pairing and category-default rungs below still see every
    # loaded combo, since those paths only ever need a menu_item_id.
    for candidate in (
        choose_upsell(cart_lines, combos=[], sizes=[], add_ons=[]),
        choose_pairing(patterns, cart_item_ids, candidates=candidates, diet=diet),
        choose_category_default(
            cart_categories,
            bestsellers=bestsellers_by_category,
            candidates=candidates,
            diet=diet,
        ),
    ):
        if candidate is None:
            continue
        if is_suppressed(candidate, memory=memory, cart_item_ids=cart_item_ids):
            continue
        store_memory(user_id, session_id, record_offer(memory, candidate))
        return candidate

    return None


def _larger_sizes(db: Session, cart_lines: list[CartLineFacts]) -> list[SizeOption]:
    """The next size up for any line not already on the largest."""

    item_ids = {line.menu_item_id for line in cart_lines}
    if not item_ids:
        return []
    rows = list(
        db.scalars(
            select(MenuItemSize)
            .where(MenuItemSize.menu_item_id.in_(item_ids), MenuItemSize.is_active.is_(True))
            .order_by(MenuItemSize.menu_item_id, MenuItemSize.price)
        ).all()
    )
    by_item: dict[uuid.UUID, list[MenuItemSize]] = {}
    for row in rows:
        by_item.setdefault(row.menu_item_id, []).append(row)

    options: list[SizeOption] = []
    for line in cart_lines:
        sizes = by_item.get(line.menu_item_id, [])
        if len(sizes) < 2 or line.size_id is None:
            continue
        current = next((index for index, row in enumerate(sizes) if row.id == line.size_id), None)
        if current is None or current == len(sizes) - 1:
            continue
        nxt = sizes[current + 1]
        options.append(
            SizeOption(
                menu_item_id=line.menu_item_id,
                size_id=nxt.id,
                extra_cost=nxt.price - sizes[current].price,
            )
        )
    return options


def _unchosen_add_ons(db: Session, cart_lines: list[CartLineFacts]) -> list[AddOnOption]:
    """Paid options in groups the line has not filled, in the owner's order.

    Ranked by `sort_order` because how often each option is actually chosen is
    not recorded yet. When it is, this ordering should become popularity — the
    owner's preferred order is a stand-in, not the intended answer.
    """

    item_ids = {line.menu_item_id for line in cart_lines}
    if not item_ids:
        return []
    rows = list(
        db.scalars(
            select(MenuItemCustomizationOption)
            .join(
                MenuItemCustomizationGroup,
                MenuItemCustomizationOption.group_id == MenuItemCustomizationGroup.id,
            )
            .where(
                MenuItemCustomizationGroup.menu_item_id.in_(item_ids),
                MenuItemCustomizationOption.is_active.is_(True),
                MenuItemCustomizationOption.extra_price > 0,
            )
            .options(selectinload(MenuItemCustomizationOption.group))
            .order_by(MenuItemCustomizationOption.sort_order)
        ).all()
    )
    return [
        AddOnOption(
            menu_item_id=row.group.menu_item_id,
            option_id=row.id,
            extra_cost=row.extra_price,
        )
        for row in rows
    ]


def _bestsellers_by_category(
    db: Session,
    location_id: uuid.UUID,
    menu_items: dict[uuid.UUID, MenuItem],
) -> dict[str, list[uuid.UUID]]:
    """Real bestseller ids per category first; the branch's own menu beneath that.

    `bestseller_min_valid_orders` (25 orders in the trailing
    `bestseller_window_days`) is a volume floor calibrated for the admin's
    "bestseller" badge elsewhere — a claim worth making only once a branch has
    real traffic behind it. This rung was built to rescue thin mined pairing
    evidence, then wired straight to that badge's source, which carries a
    HIGHER floor than the thing it exists to rescue: a branch with fewer than
    25 qualifying orders (a new launch, or just a quiet one) gets an empty
    bestseller set here, and with it silence from every suggestion path at
    once — the exact case this rung exists for. Falling through to the
    category's own available items, deterministically ordered (see
    `order_category_fallback`), keeps the rung able to speak without touching
    `bestseller_min_valid_orders` itself, which other surfaces (menu badges)
    also read and which should not move just to make this feature visible.
    The `category_default` basis was already a claim about the CATEGORY, not
    about any specific item, so which item wins here changes nothing about
    what the label promises.
    """

    bestseller_ids = get_dynamic_bestseller_ids_by_location(db, [location_id]).get(location_id, set())
    grouped: dict[str, list[uuid.UUID]] = {}
    for item_id in bestseller_ids:
        item = menu_items.get(item_id)
        if item is None or not item.category:
            continue
        grouped.setdefault(item.category, []).append(item_id)

    # Only categories with no bestseller at all fall through — where real
    # popularity data exists it still wins, unconditionally.
    fallback_candidates: dict[str, list[CategoryFallbackItem]] = {}
    for item in menu_items.values():
        if not item.category or item.category in grouped:
            continue
        fallback_candidates.setdefault(item.category, []).append(
            CategoryFallbackItem(menu_item_id=item.id, price=item.price, name=item.name)
        )
    for category, candidates in fallback_candidates.items():
        grouped[category] = order_category_fallback(candidates)

    return grouped
