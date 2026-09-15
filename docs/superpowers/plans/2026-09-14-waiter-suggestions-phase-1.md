# Waiter Phase 1 — Evidence-Backed Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the customer site feel like someone is guiding the order — one cross-sell or up-sell suggestion, derived from real order evidence, rendered through the pages that already exist.

**Architecture:** A new backend service `suggestions.py` holds every selling rule as pure functions over plain dataclasses, with a thin DB-backed orchestrator on top. Two transports carry the same `SellSuggestion`: the existing chat response, and a new `GET /api/suggestions` for pages that have no message to send. The client renders it as in-place UI — a strip under the home hero, a nudge in the cart — never as a transcript.

**Tech Stack:** FastAPI 0.115, SQLAlchemy 2.0, Pydantic v2, Redis via `app/services/cache.py`, `unittest` (NOT pytest); TanStack Start + React 19, vitest with `environment: "node"`.

**Spec:** `docs/superpowers/specs/2026-09-14-waiter-agentic-cart-design.md`

## Global Constraints

- **Tests are `unittest`, not pytest.** Every backend test file inserts `backend/` on `sys.path` itself and imports `app.main` first to settle import order. Copy the header from `backend/tests/test_time_word_topics.py`.
- **No new runtime dependencies** in either project.
- **Comments explain *why*, not what.** Match the density of `backend/app/config/settings.py`. Terse "what" comments read as foreign in this repo.
- **The LLM never invents data.** Every suggestion in this phase is a database row selected by a deterministic rule. No model is called anywhere in this plan.
- **Backend enforces, UI only hides.** The client re-checks nothing it is handed, but the backend must never trust the `cart` in a request: re-resolve every id against the selected branch.
- **Labels come from scoring, never handcrafted in a client.** The client picks copy from the `basis` field; it must not invent its own reason text.
- **`basis` must not overclaim.** `co_occurrence` copy says "often ordered with…"; `category_default` copy says "most people add…". Wording them alike is the failure the field exists to prevent.
- **At most ONE suggestion per response, ever.**
- **Verification:** `cd backend && ./.venv/bin/python -m unittest discover -s tests` and `./.venv/bin/python -m compileall app`; `cd frontend-customer && ./node_modules/.bin/tsc --noEmit && npx vitest run`.
- **No agentic cart actions in this phase.** `cart_actions`, `turn_id` and `applyCartActions` belong to Phase 2. Do not add them.

### Deliberate refinement from the spec

The spec put suppression state in `SessionConversationState`. This plan gives
`suggestions.py` its **own** Redis record instead, keyed the same way. Reason:
`GET /api/suggestions` must work without the chat pipeline, and importing
`rag.py` for its session dataclass would both couple the endpoint to the whole
RAG module and risk a circular import once `rag.py` imports `suggestions.py`.
The behaviour the spec specified is unchanged — same `session_id`, declines
shared across both transports.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/suggestions.py` (create) | every selling rule; pure functions plus one DB orchestrator |
| `backend/app/schemas/suggestions.py` (create) | `SellSuggestionResponse`, `CartLinePayload` |
| `backend/app/api/suggestions.py` (create) | `GET /api/suggestions` |
| `backend/app/api/__init__.py` (modify) | register the router |
| `backend/app/schemas/chat.py` (modify) | `cart` on the request, `suggestion` on the response |
| `backend/app/services/rag.py` (modify) | call the service; refuse to cache a reply carrying one |
| `backend/tests/test_suggestion_rules.py` (create) | the pure rules |
| `backend/tests/test_suggestion_suppression.py` (create) | memory and suppression |
| `frontend-customer/src/lib/suggestions.ts` (create) | types, `suggestionCopy`, `cartLinesForRequest` |
| `frontend-customer/src/lib/suggestions.test.ts` (create) | the pure client logic |
| `frontend-customer/src/components/bangkok/waiter-prompt.tsx` (create) | the one renderer |
| `frontend-customer/src/routes/index.tsx`, `cart.tsx`, `menu.index.tsx`, `concierge.tsx` (modify) | mount it |

---

## Task 1: The cross-sell pairing rule

**Files:**
- Create: `backend/app/services/suggestions.py`
- Test: `backend/tests/test_suggestion_rules.py`

**Interfaces:**
- Consumes: nothing
- Produces: `PairingPattern`, `CandidateItem`, `SellSuggestion`, `choose_pairing(patterns, cart_item_ids, *, candidates, diet) -> SellSuggestion | None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_suggestion_rules.py`:

```python
"""The rules that decide what a waiter offers next.

Pure over their inputs on purpose. The selling rules are the part most likely
to be argued about later, and a rule that needs a database and a session to
exercise is a rule nobody re-checks after changing it.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.suggestions import (
    CandidateItem,
    PairingPattern,
    choose_pairing,
)

CURRY = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
TEA = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
RICE = uuid.UUID("00000000-0000-0000-0000-0000000000b1")


def _candidate(item_id: uuid.UUID, *, is_veg: bool = True, available: bool = True) -> CandidateItem:
    return CandidateItem(
        menu_item_id=item_id,
        category="Beverages",
        is_veg=is_veg,
        is_available=available,
    )


class PairingRuleTests(unittest.TestCase):
    def test_a_pattern_missing_exactly_one_item_yields_that_item(self) -> None:
        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("9"))

        result = choose_pairing(
            [pattern],
            {CURRY},
            candidates={TEA: _candidate(TEA)},
            diet=None,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.menu_item_id, TEA)
        self.assertEqual(result.basis, "co_occurrence")
        self.assertEqual(result.kind, "cross_sell")

    def test_a_pattern_missing_two_items_is_not_a_pairing(self) -> None:
        """Suggesting two things at once is a menu, not a waiter's nudge."""

        pattern = PairingPattern(item_ids=(CURRY, TEA, RICE), confidence_score=Decimal("9"))

        self.assertIsNone(
            choose_pairing(
                [pattern],
                {CURRY},
                candidates={TEA: _candidate(TEA), RICE: _candidate(RICE)},
                diet=None,
            )
        )

    def test_a_pattern_that_does_not_touch_the_cart_is_ignored(self) -> None:
        pattern = PairingPattern(item_ids=(TEA, RICE), confidence_score=Decimal("9"))

        self.assertIsNone(
            choose_pairing([pattern], {CURRY}, candidates={TEA: _candidate(TEA)}, diet=None)
        )

    def test_the_highest_confidence_pattern_wins(self) -> None:
        weak = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("3"))
        strong = PairingPattern(item_ids=(CURRY, RICE), confidence_score=Decimal("11"))

        result = choose_pairing(
            [weak, strong],
            {CURRY},
            candidates={TEA: _candidate(TEA), RICE: _candidate(RICE)},
            diet=None,
        )

        self.assertEqual(result.menu_item_id, RICE)

    def test_a_veg_customer_is_never_offered_a_non_veg_pairing(self) -> None:
        """The business-rule filter runs BEFORE ranking, everywhere in this repo."""

        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("99"))

        self.assertIsNone(
            choose_pairing(
                [pattern],
                {CURRY},
                candidates={TEA: _candidate(TEA, is_veg=False)},
                diet="VEG",
            )
        )

    def test_an_unavailable_item_is_never_offered(self) -> None:
        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("99"))

        self.assertIsNone(
            choose_pairing(
                [pattern],
                {CURRY},
                candidates={TEA: _candidate(TEA, available=False)},
                diet=None,
            )
        )

    def test_an_empty_cart_yields_nothing(self) -> None:
        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("9"))

        self.assertIsNone(
            choose_pairing([pattern], set(), candidates={TEA: _candidate(TEA)}, diet=None)
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_rules -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.suggestions'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/suggestions.py`:

```python
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
        if len(missing) != PAIRING_MISSING_ITEM_COUNT:
            continue
        if len(missing) == len(pattern.item_ids):
            # Touches nothing in the cart; it is evidence about someone else's meal.
            continue
        candidate_id = missing[0]
        if not _is_offerable(candidates.get(candidate_id), diet=diet):
            continue
        if best is None or pattern.confidence_score > best[0]:
            best = (pattern.confidence_score, candidate_id)

    if best is None:
        return None
    return SellSuggestion(kind="cross_sell", basis="co_occurrence", menu_item_id=best[1])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_rules -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/suggestions.py backend/tests/test_suggestion_rules.py
git commit -m "feat(suggestions): offer the one item a mined pattern is short of"
```

---

## Task 2: The category fallback

**Files:**
- Modify: `backend/app/services/suggestions.py`
- Test: `backend/tests/test_suggestion_rules.py`

**Interfaces:**
- Consumes: `CandidateItem`, `SellSuggestion`, `_is_offerable` from Task 1
- Produces: `COMPLEMENT_CATEGORIES`, `choose_category_default(cart_categories, *, bestsellers, candidates, diet) -> SellSuggestion | None`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_suggestion_rules.py` (and add `choose_category_default` to the import list at the top):

```python
class CategoryFallbackTests(unittest.TestCase):
    """The honest gap-filler.

    Measured on 2026-09-14: 7 visible combos mined from 17 multi-item delivered
    orders. Six pairs cannot cover a 117-item menu, so without this the
    evidence-backed rule is silent nearly always. It earns its place ONLY
    because `basis` forces the copy to admit which one fired.
    """

    def test_a_cart_with_no_drink_is_offered_the_bestselling_drink(self) -> None:
        result = choose_category_default(
            {"Main Course"},
            bestsellers={"Beverages": [TEA]},
            candidates={TEA: _candidate(TEA)},
            diet=None,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.menu_item_id, TEA)
        self.assertEqual(result.basis, "category_default")
        self.assertEqual(result.kind, "cross_sell")

    def test_a_category_the_cart_already_has_is_not_offered(self) -> None:
        self.assertIsNone(
            choose_category_default(
                {"Main Course", "Beverages"},
                bestsellers={"Beverages": [TEA]},
                candidates={TEA: _candidate(TEA)},
                diet=None,
            )
        )

    def test_the_diet_filter_applies_to_the_fallback_too(self) -> None:
        self.assertIsNone(
            choose_category_default(
                {"Main Course"},
                bestsellers={"Beverages": [TEA]},
                candidates={TEA: _candidate(TEA, is_veg=False)},
                diet="VEG",
            )
        )

    def test_no_bestseller_for_the_missing_category_yields_silence(self) -> None:
        self.assertIsNone(
            choose_category_default(
                {"Main Course"},
                bestsellers={},
                candidates={},
                diet=None,
            )
        )

    def test_an_empty_cart_yields_nothing(self) -> None:
        """Nothing in the cart means nothing is missing from it."""

        self.assertIsNone(
            choose_category_default(
                set(),
                bestsellers={"Beverages": [TEA]},
                candidates={TEA: _candidate(TEA)},
                diet=None,
            )
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_rules -v`
Expected: FAIL — `ImportError: cannot import name 'choose_category_default'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/suggestions.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_rules -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/suggestions.py backend/tests/test_suggestion_rules.py
git commit -m "feat(suggestions): fall back to a category default, labelled as one"
```

---

## Task 3: The up-sell ladder

**Files:**
- Modify: `backend/app/services/suggestions.py`
- Test: `backend/tests/test_suggestion_rules.py`

**Interfaces:**
- Consumes: `SellSuggestion` from Task 1
- Produces: `CartLineFacts`, `ComboUpgrade`, `SizeOption`, `AddOnOption`, `choose_upsell(lines, *, combos, sizes, add_ons) -> SellSuggestion | None`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_suggestion_rules.py` (add the four new names to the import list):

```python
PIZZA = uuid.UUID("00000000-0000-0000-0000-0000000000ef")


class UpsellLadderTests(unittest.TestCase):
    """Ordered by value to the CUSTOMER, not margin to the restaurant.

    A combo saves money, a size gives more food, an add-on only costs more. A
    waiter who opens with the most profitable add-on gets tuned out, and then
    none of the three rungs work.
    """

    def _line(self, item_id=PIZZA, *, size_id=None, option_ids=()):
        return CartLineFacts(
            menu_item_id=item_id,
            size_id=size_id,
            customization_option_ids=frozenset(option_ids),
        )

    def test_a_combo_upgrade_beats_a_size_upgrade(self) -> None:
        combo_id = uuid.uuid4()
        larger = uuid.uuid4()

        result = choose_upsell(
            [self._line(size_id=uuid.uuid4())],
            combos=[ComboUpgrade(combo_id=combo_id, item_ids=(PIZZA,), saving=Decimal("4.00"))],
            sizes=[SizeOption(menu_item_id=PIZZA, size_id=larger, extra_cost=Decimal("3.00"))],
            add_ons=[],
        )

        self.assertEqual(result.basis, "combo_upgrade")
        self.assertEqual(result.combo_id, combo_id)
        self.assertEqual(result.saving, Decimal("4.00"))
        self.assertEqual(result.kind, "up_sell")

    def test_a_size_upgrade_beats_an_add_on(self) -> None:
        larger = uuid.uuid4()
        option = uuid.uuid4()

        result = choose_upsell(
            [self._line(size_id=uuid.uuid4())],
            combos=[],
            sizes=[SizeOption(menu_item_id=PIZZA, size_id=larger, extra_cost=Decimal("3.00"))],
            add_ons=[AddOnOption(menu_item_id=PIZZA, option_id=option, extra_cost=Decimal("1.00"))],
        )

        self.assertEqual(result.basis, "size_upgrade")
        self.assertEqual(result.size_id, larger)
        self.assertEqual(result.extra_cost, Decimal("3.00"))

    def test_an_add_on_is_the_last_resort(self) -> None:
        option = uuid.uuid4()

        result = choose_upsell(
            [self._line()],
            combos=[],
            sizes=[],
            add_ons=[AddOnOption(menu_item_id=PIZZA, option_id=option, extra_cost=Decimal("1.00"))],
        )

        self.assertEqual(result.basis, "add_on")
        self.assertEqual(result.customization_option_id, option)

    def test_a_combo_the_cart_does_not_fully_contain_is_not_offered(self) -> None:
        """A combo upgrade is only an upgrade if the cart already holds it."""

        other = uuid.uuid4()

        self.assertIsNone(
            choose_upsell(
                [self._line()],
                combos=[ComboUpgrade(combo_id=uuid.uuid4(), item_ids=(PIZZA, other), saving=Decimal("4.00"))],
                sizes=[],
                add_ons=[],
            )
        )

    def test_an_add_on_already_chosen_is_not_offered_again(self) -> None:
        option = uuid.uuid4()

        self.assertIsNone(
            choose_upsell(
                [self._line(option_ids=(option,))],
                combos=[],
                sizes=[],
                add_ons=[AddOnOption(menu_item_id=PIZZA, option_id=option, extra_cost=Decimal("1.00"))],
            )
        )

    def test_an_empty_cart_yields_nothing(self) -> None:
        self.assertIsNone(choose_upsell([], combos=[], sizes=[], add_ons=[]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_rules -v`
Expected: FAIL — `ImportError: cannot import name 'CartLineFacts'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/suggestions.py`:

```python
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
    """First rung that fires wins, and the rungs descend in customer value."""

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_rules -v`
Expected: PASS, 18 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/suggestions.py backend/tests/test_suggestion_rules.py
git commit -m "feat(suggestions): up-sell ladder ordered by value to the customer"
```

---

## Task 4: Suppression memory

**Files:**
- Modify: `backend/app/services/suggestions.py`
- Test: `backend/tests/test_suggestion_suppression.py`

**Interfaces:**
- Consumes: `SellSuggestion` from Task 1
- Produces: `SuggestionMemory`, `DECLINE_LIMIT`, `is_suppressed(suggestion, *, memory, cart_item_ids) -> bool`, `record_offer(memory, suggestion) -> SuggestionMemory`, `record_decline(memory, menu_item_id) -> SuggestionMemory`, `load_memory(user_id, session_id)`, `store_memory(user_id, session_id, memory)`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_suggestion_suppression.py`:

```python
"""When the waiter stops talking.

The cadence was a product decision, not an implementation detail: one
suggestion per reply, never the same item twice, and silence after two
declines. A waiter who asks a third time after two noes is the reason people
stop reading suggestions at all.

Memory is keyed by session and shared by BOTH transports. A prompt dismissed
on the home page must not reappear in the chat — that is the same session and
the same customer, and being asked twice reads as not listening.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.suggestions import (
    DECLINE_LIMIT,
    SellSuggestion,
    SuggestionMemory,
    is_suppressed,
    record_decline,
    record_offer,
)

TEA = uuid.uuid4()
RICE = uuid.uuid4()


def _suggestion(item_id=TEA) -> SellSuggestion:
    return SellSuggestion(kind="cross_sell", basis="co_occurrence", menu_item_id=item_id)


class SuppressionTests(unittest.TestCase):
    def test_a_fresh_session_suppresses_nothing(self) -> None:
        self.assertFalse(
            is_suppressed(_suggestion(), memory=SuggestionMemory(), cart_item_ids=set())
        )

    def test_an_item_already_offered_is_not_offered_again(self) -> None:
        memory = record_offer(SuggestionMemory(), _suggestion())

        self.assertTrue(is_suppressed(_suggestion(), memory=memory, cart_item_ids=set()))

    def test_an_item_already_in_the_cart_is_never_offered(self) -> None:
        self.assertTrue(
            is_suppressed(_suggestion(), memory=SuggestionMemory(), cart_item_ids={TEA})
        )

    def test_two_declines_silence_everything(self) -> None:
        memory = record_decline(record_decline(SuggestionMemory(), TEA), RICE)

        self.assertEqual(DECLINE_LIMIT, 2)
        # Even an item never offered before is suppressed once the session is done.
        self.assertTrue(
            is_suppressed(
                _suggestion(uuid.uuid4()), memory=memory, cart_item_ids=set()
            )
        )

    def test_one_decline_does_not_silence_a_different_item(self) -> None:
        memory = record_decline(SuggestionMemory(), RICE)

        self.assertFalse(is_suppressed(_suggestion(TEA), memory=memory, cart_item_ids=set()))

    def test_a_declined_item_stays_declined(self) -> None:
        memory = record_decline(SuggestionMemory(), TEA)

        self.assertTrue(is_suppressed(_suggestion(TEA), memory=memory, cart_item_ids=set()))

    def test_recording_is_pure(self) -> None:
        """The caller decides whether to persist; the rule never mutates in place."""

        original = SuggestionMemory()
        record_offer(original, _suggestion())

        self.assertEqual(original.offered_item_ids, frozenset())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_suppression -v`
Expected: FAIL — `ImportError: cannot import name 'DECLINE_LIMIT'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/suggestions.py`:

```python
from app.services.cache import cache_get_json, cache_set_json

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


def is_suppressed(
    suggestion: SellSuggestion,
    *,
    memory: SuggestionMemory,
    cart_item_ids: set[uuid.UUID],
) -> bool:
    if memory.decline_count >= DECLINE_LIMIT:
        return True
    item_id = suggestion.menu_item_id
    if item_id is None:
        return False
    if item_id in cart_item_ids:
        return True
    return item_id in memory.offered_item_ids or item_id in memory.declined_item_ids


def record_offer(memory: SuggestionMemory, suggestion: SellSuggestion) -> SuggestionMemory:
    if suggestion.menu_item_id is None:
        return memory
    return SuggestionMemory(
        offered_item_ids=memory.offered_item_ids | {suggestion.menu_item_id},
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
```

Add at the top of the file, after the existing imports:

```python
import logging

logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_suppression -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/suggestions.py backend/tests/test_suggestion_suppression.py
git commit -m "feat(suggestions): stop asking after two noes, and never ask twice"
```

---

## Task 5: The DB orchestrator

**Files:**
- Modify: `backend/app/services/suggestions.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4; `get_dynamic_bestseller_ids_by_location` from `app.services.bestsellers`
- Produces: `suggestion_for_cart(db, *, cart_lines, restaurant_location_id, user_id, session_id, diet) -> SellSuggestion | None`

**Why no unit test here:** this function is wiring — it loads rows and hands
them to rules that are already tested. Testing it would require DB fixtures for
combos, sizes and options, and would re-assert Task 1–4 behaviour through a
slower path. Its correctness is checked by the endpoint test in Task 6 and by
the manual verification at the end of Task 9.

- [ ] **Step 1: Write the implementation**

Append to `backend/app/services/suggestions.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.generated_combo import GeneratedCombo, GeneratedComboItem
from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.models.menu_item_size import MenuItemSize
from app.services.bestsellers import get_dynamic_bestseller_ids_by_location


def _load_visible_combos(db: Session, location_id: uuid.UUID) -> list[GeneratedCombo]:
    return list(
        db.scalars(
            select(GeneratedCombo)
            .where(
                GeneratedCombo.restaurant_location_id == location_id,
                GeneratedCombo.is_active.is_(True),
                GeneratedCombo.is_customer_visible.is_(True),
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

    cart_item_ids = {line.menu_item_id for line in cart_lines}
    combos = _load_visible_combos(db, restaurant_location_id)

    # Every candidate the rules may look at, loaded once and scoped to the
    # branch. An id that does not resolve HERE is simply absent, which is what
    # makes an untrusted cart payload safe to accept.
    pattern_item_ids = {entry.menu_item_id for combo in combos for entry in combo.combo_items}
    menu_items = {
        item.id: item
        for item in db.scalars(
            select(MenuItem).where(
                MenuItem.restaurant_location_id == restaurant_location_id,
                MenuItem.is_available.is_(True),
            )
        ).all()
    }
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

    upgrades = [
        ComboUpgrade(
            combo_id=combo.id,
            item_ids=tuple(entry.menu_item_id for entry in combo.combo_items),
            saving=combo.original_total_price - combo.suggested_combo_price,
        )
        for combo in combos
        if combo.original_total_price > combo.suggested_combo_price
    ]

    sizes = _larger_sizes(db, cart_lines)
    add_ons = _unchosen_add_ons(db, cart_lines)

    cart_categories = {
        menu_items[item_id].category
        for item_id in cart_item_ids
        if item_id in menu_items and menu_items[item_id].category
    }
    bestsellers_by_category = _bestsellers_by_category(db, restaurant_location_id, menu_items)

    # Order matters: an upgrade to something already in the cart is more
    # relevant than a new item, and mined evidence outranks a category guess.
    for candidate in (
        choose_upsell(cart_lines, combos=upgrades, sizes=sizes, add_ons=add_ons),
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
    bestseller_ids = get_dynamic_bestseller_ids_by_location(db, [location_id]).get(location_id, set())
    grouped: dict[str, list[uuid.UUID]] = {}
    for item_id in bestseller_ids:
        item = menu_items.get(item_id)
        if item is None or not item.category:
            continue
        grouped.setdefault(item.category, []).append(item_id)
    return grouped
```

Verified: `MenuItemCustomizationGroup` has both `menu_item_id` and a nullable
`menu_item_size_id`, so the join above is correct as written. A group scoped to
a size still carries its dish's `menu_item_id`, which is the id the suggestion
needs.

- [ ] **Step 2: Verify it compiles and nothing regressed**

Run: `cd backend && ./.venv/bin/python -m compileall app/services/suggestions.py && ./.venv/bin/python -m unittest discover -s tests`
Expected: compiles; full suite passes

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/suggestions.py
git commit -m "feat(suggestions): load the rows the rules need, scoped to the branch"
```

---

## Task 6: Schemas and the `GET /api/suggestions` endpoint

**Files:**
- Create: `backend/app/schemas/suggestions.py`, `backend/app/api/suggestions.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_suggestions_endpoint.py`

**Interfaces:**
- Consumes: `suggestion_for_cart`, `SellSuggestion` from Task 5
- Produces: `CartLinePayload`, `SellSuggestionResponse`, `GET /api/suggestions`, `POST /api/suggestions/decline`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_suggestions_endpoint.py`:

```python
"""The transport a page uses when it has nothing to say.

A home page cannot ask the chat endpoint for guidance: that endpoint needs a
message, and there is no message here. Without this route the only way to feel
guided is to start a conversation, which is exactly the chat-screen-everywhere
outcome the design rules out.

These tests pin the contract, not the rules — the rules have their own tests
and do not need a database to exercise.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.suggestions import CartLinePayload, SellSuggestionResponse


class SuggestionContractTests(unittest.TestCase):
    def test_the_response_carries_a_basis(self) -> None:
        """`basis` is what stops a category guess being worded as evidence."""

        payload = SellSuggestionResponse(
            kind="cross_sell",
            basis="category_default",
            menu_item_id=uuid.uuid4(),
        )

        self.assertEqual(payload.basis, "category_default")

    def test_a_cart_line_needs_only_identifiers(self) -> None:
        """No prices and no names cross the wire, so there is one price path."""

        line = CartLinePayload(menu_item_id=uuid.uuid4(), quantity=2)

        self.assertEqual(line.quantity, 2)
        self.assertIsNone(line.size_id)
        self.assertEqual(line.customization_option_ids, [])

    def test_an_empty_cart_is_answered_with_no_suggestion_not_an_error(self) -> None:
        """Arriving on the home page with nothing in the cart is the common case."""

        client = TestClient(app)
        response = client.get(
            "/api/suggestions",
            params={"restaurant_location_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4())},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["suggestion"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestions_endpoint -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.schemas.suggestions'`

- [ ] **Step 3: Write the schemas**

Create `backend/app/schemas/suggestions.py`:

```python
from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class CartLinePayload(BaseModel):
    """What the browser says is in the cart.

    Identifiers only, and treated as untrusted: the service re-resolves every
    id against the selected branch and ignores whatever does not belong there.
    Names and prices are never taken from here.
    """

    menu_item_id: uuid.UUID
    quantity: int = Field(default=1, ge=1)
    size_id: uuid.UUID | None = None
    customization_option_ids: list[uuid.UUID] = Field(default_factory=list)


class SellSuggestionResponse(BaseModel):
    kind: str
    basis: str
    menu_item_id: uuid.UUID | None = None
    combo_id: uuid.UUID | None = None
    size_id: uuid.UUID | None = None
    customization_option_id: uuid.UUID | None = None
    saving: Decimal | None = None
    extra_cost: Decimal | None = None


class SuggestionEnvelope(BaseModel):
    suggestion: SellSuggestionResponse | None = None


class SuggestionDeclineRequest(BaseModel):
    session_id: uuid.UUID
    menu_item_id: uuid.UUID
```

- [ ] **Step 4: Write the endpoint**

Create `backend/app/api/suggestions.py`:

```python
from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_optional, get_db
from app.models.user import User
from app.schemas.suggestions import (
    CartLinePayload,
    SellSuggestionResponse,
    SuggestionDeclineRequest,
    SuggestionEnvelope,
)
from app.services.chat_principal import guest_principal_for_session
from app.services.recommendations import get_user_preferences_response
from app.services.suggestions import (
    CartLineFacts,
    load_memory,
    record_decline,
    store_memory,
    suggestion_for_cart,
)

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


def _principal_id(current_user: User | None, session_id: uuid.UUID) -> uuid.UUID:
    """Same identity rule the chat uses, so declines are shared across both."""

    if current_user is not None:
        return current_user.id
    return guest_principal_for_session(session_id).id


@router.get("", response_model=SuggestionEnvelope)
def get_suggestion(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    restaurant_location_id: uuid.UUID,
    session_id: uuid.UUID,
    cart: Annotated[str | None, Query(description="JSON array of cart lines")] = None,
) -> SuggestionEnvelope:
    """One suggestion for a page that has no message to send.

    The cart arrives as a JSON query parameter rather than a body because this
    is a GET and pages call it on render; a malformed value yields no
    suggestion rather than a 422, since guidance must never break a page load.
    """

    lines: list[CartLineFacts] = []
    if cart:
        try:
            parsed = [CartLinePayload.model_validate(entry) for entry in json.loads(cart)]
        except (ValueError, TypeError):
            parsed = []
        lines = [
            CartLineFacts(
                menu_item_id=line.menu_item_id,
                size_id=line.size_id,
                customization_option_ids=frozenset(line.customization_option_ids),
            )
            for line in parsed
        ]

    # Takes the User, not an id — the same helper the recommendation scorer uses,
    # so the diet a suggestion respects is the diet everything else respects.
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
) -> SuggestionEnvelope:
    """Dismissing a prompt is a decline, wherever it was dismissed.

    Without this the in-page strip could be dismissed forever and the chat
    would keep offering the same item, which reads as not listening.
    """

    user_id = _principal_id(current_user, payload.session_id)
    memory = load_memory(user_id, payload.session_id)
    store_memory(user_id, payload.session_id, record_decline(memory, payload.menu_item_id))
    return SuggestionEnvelope()
```

Verify the two imported helpers exist and match these names before writing:
`grep -n "def guest_principal_for_session" backend/app/services/chat_principal.py`.
`get_user_preferences_response(db, user) -> UserPreferencesResponse | None` is
verified to exist in `app/services/recommendations.py:1636`.

- [ ] **Step 5: Register the router**

In `backend/app/api/__init__.py`, follow the existing registration pattern
exactly — find the line registering `preferences` and add a sibling line for
`suggestions`.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestions_endpoint -v`
Expected: PASS, 3 tests

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/suggestions.py backend/app/api/suggestions.py backend/app/api/__init__.py backend/tests/test_suggestions_endpoint.py
git commit -m "feat(suggestions): a transport for pages that have no message to send"
```

---

## Task 7: Chat carries the same suggestion

**Files:**
- Modify: `backend/app/schemas/chat.py`, `backend/app/services/rag.py`, `backend/app/api/chat.py`
- Test: `backend/tests/test_suggestion_cache_refusal.py`

**Interfaces:**
- Consumes: `suggestion_for_cart`, `SellSuggestionResponse`
- Produces: `ChatMessageRequest.cart`, `ChatMessageResponse.suggestion`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_suggestion_cache_refusal.py`:

```python
"""A reply carrying a suggestion may never be cached globally.

This is the same class of bug `may_cache_globally` already exists to catch, and
it has slipped through twice: once because the guard checked history but not
the session summary, and once because guests have no history rows at all.

A suggestion is a function of THIS customer's cart. Cached under a key that
does not include the cart, it would be replayed to the next person asking the
same question — telling them a drink goes with a curry they never ordered.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.rag import may_cache_globally


class CacheRefusalTests(unittest.TestCase):
    def test_a_reply_with_a_suggestion_is_never_globally_cached(self) -> None:
        self.assertFalse(
            may_cache_globally(
                cacheable=True,
                history_messages=[],
                session_summary="none",
                has_suggestion=True,
            )
        )

    def test_a_plain_reply_is_still_cacheable(self) -> None:
        """The guard must not become "never cache anything"."""

        self.assertTrue(
            may_cache_globally(
                cacheable=True,
                history_messages=[],
                session_summary="none",
                has_suggestion=False,
            )
        )

    def test_the_existing_session_guards_still_apply(self) -> None:
        self.assertFalse(
            may_cache_globally(
                cacheable=True,
                history_messages=[],
                session_summary="diet=VEG",
                has_suggestion=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_cache_refusal -v`
Expected: FAIL — `TypeError: may_cache_globally() got an unexpected keyword argument 'has_suggestion'`

- [ ] **Step 3: Add the cache guard**

In `backend/app/services/rag.py`, find `may_cache_globally` and add the
parameter, defaulting to `False` so no existing call site breaks:

```python
def may_cache_globally(
    *,
    cacheable: bool,
    history_messages: list[ChatHistory],
    session_summary: str = "none",
    has_suggestion: bool = False,
) -> bool:
    # A suggestion is computed from THIS cart. The cache key has no cart in it,
    # so a cached suggestion would be served to a different basket entirely.
    if has_suggestion:
        return False
    ...existing body unchanged...
```

Then update the call site inside the chat pipeline to pass
`has_suggestion=suggestion is not None`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_cache_refusal -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Add `cart` to the request and `suggestion` to the response**

In `backend/app/schemas/chat.py`:

```python
from app.schemas.suggestions import CartLinePayload, SellSuggestionResponse
```

On `ChatMessageRequest`:

```python
    # Both selling rules are functions of the cart, and the cart lives in the
    # browser. Untrusted: every id is re-resolved against the branch.
    cart: list[CartLinePayload] = Field(default_factory=list)
```

On `ChatMessageResponse`:

```python
    suggestion: SellSuggestionResponse | None = None
```

- [ ] **Step 6: Wire it into the pipeline**

In `backend/app/api/chat.py`, pass the cart through to `handle_chat_message`,
and in `rag.py` call `suggestion_for_cart` once the reply is otherwise built,
mapping the result onto `ChatMessageResponse.suggestion`. Convert the payload
with the same shape Task 6 uses:

```python
    cart_lines = [
        CartLineFacts(
            menu_item_id=line.menu_item_id,
            size_id=line.size_id,
            customization_option_ids=frozenset(line.customization_option_ids),
        )
        for line in cart
    ]
```

- [ ] **Step 7: Verify the whole backend suite**

Run: `cd backend && ./.venv/bin/python -m unittest discover -s tests`
Expected: all tests pass, including the 42 pre-existing files

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/chat.py backend/app/services/rag.py backend/app/api/chat.py backend/tests/test_suggestion_cache_refusal.py
git commit -m "fix(chat): carry the cart in, the suggestion out, and never cache it"
```

---

## Task 8: Client types, copy, and the cart payload

**Files:**
- Create: `frontend-customer/src/lib/suggestions.ts`, `frontend-customer/src/lib/suggestions.test.ts`
- Modify: `frontend-customer/src/lib/api.ts`

**Interfaces:**
- Consumes: `CartLine` from `bangkok-store.tsx`
- Produces: `SellSuggestion` type, `cartLinesForRequest(cart)`, `suggestionCopy(suggestion, itemName)`, `api.getSuggestion`, `api.declineSuggestion`

**Note:** vitest runs with `environment: "node"` and there is no jsdom, so this
task tests pure functions only. Component rendering is verified manually in
Task 9.

- [ ] **Step 1: Write the failing test**

Create `frontend-customer/src/lib/suggestions.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { cartLinesForRequest, suggestionCopy } from "./suggestions";

describe("cartLinesForRequest", () => {
  it("sends identifiers only, never names or prices", () => {
    const [line] = cartLinesForRequest([
      {
        lineId: "l1",
        itemId: "item-1",
        restaurantId: "r1",
        restaurantName: "Bangkok Bowl",
        restaurantLocationId: "loc-1",
        name: "Green Curry",
        image_url: null,
        quantity: 2,
        unitPrice: 12.5,
        sizeId: "size-1",
        sizeName: "Large",
        optionIds: ["opt-1"],
        addOnNames: ["Extra peanuts"],
      },
    ] as never);

    expect(line).toEqual({
      menu_item_id: "item-1",
      quantity: 2,
      size_id: "size-1",
      customization_option_ids: ["opt-1"],
    });
    expect(JSON.stringify(line)).not.toContain("Green Curry");
    expect(JSON.stringify(line)).not.toContain("12.5");
  });

  it("handles an empty cart", () => {
    expect(cartLinesForRequest([])).toEqual([]);
  });
});

describe("suggestionCopy", () => {
  it("claims evidence only when there is evidence", () => {
    const mined = suggestionCopy(
      { kind: "cross_sell", basis: "co_occurrence", menu_item_id: "i" },
      "Thai Iced Tea",
    );
    const guess = suggestionCopy(
      { kind: "cross_sell", basis: "category_default", menu_item_id: "i" },
      "Thai Iced Tea",
    );

    expect(mined).toContain("Often ordered");
    expect(guess).toContain("Most people");
    // The whole point of `basis`: these must not read alike.
    expect(mined).not.toEqual(guess);
  });

  it("names the saving on a combo upgrade", () => {
    const copy = suggestionCopy(
      { kind: "up_sell", basis: "combo_upgrade", saving: "4.00" },
      "Curry Feast",
    );

    expect(copy).toContain("4.00");
  });

  it("falls back to something neutral for an unknown basis", () => {
    // A new basis added on the backend must not render `undefined` to a customer.
    const copy = suggestionCopy(
      { kind: "cross_sell", basis: "something_new", menu_item_id: "i" },
      "Thai Iced Tea",
    );

    expect(copy).toContain("Thai Iced Tea");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend-customer && npx vitest run src/lib/suggestions.test.ts`
Expected: FAIL — cannot resolve `./suggestions`

- [ ] **Step 3: Write the implementation**

Create `frontend-customer/src/lib/suggestions.ts`:

```ts
import type { CartLine } from "@/lib/bangkok-store";

export type SellSuggestion = {
  kind: string;
  basis: string;
  menu_item_id?: string | null;
  combo_id?: string | null;
  size_id?: string | null;
  customization_option_id?: string | null;
  saving?: string | null;
  extra_cost?: string | null;
};

export type CartLineRequest = {
  menu_item_id: string;
  quantity: number;
  size_id: string | undefined;
  customization_option_ids: string[];
};

/**
 * Identifiers only.
 *
 * Sending names or prices would give the reply a second source of truth for
 * both, and the one that disagrees with the menu page is always the one the
 * customer notices.
 */
export function cartLinesForRequest(cart: CartLine[]): CartLineRequest[] {
  return cart.map((line) => ({
    menu_item_id: line.itemId,
    quantity: line.quantity,
    size_id: line.sizeId,
    customization_option_ids: line.optionIds,
  }));
}

/**
 * What the prompt says, chosen by `basis` and nothing else.
 *
 * The client does not get to invent a reason. A mined pairing has evidence
 * behind it and may say so; a category default is a guess and must read like
 * one. Wording them alike would present a guess as a measurement.
 */
export function suggestionCopy(suggestion: SellSuggestion, itemName: string): string {
  switch (suggestion.basis) {
    case "co_occurrence":
      return `Often ordered with what you've got — ${itemName}?`;
    case "category_default":
      return `Most people add ${itemName}.`;
    case "combo_upgrade":
      return `Make it the ${itemName} and save ${suggestion.saving ?? ""}.`;
    case "size_upgrade":
      return `Go large on the ${itemName}? ${suggestion.extra_cost ?? ""} more.`;
    case "add_on":
      return `Add ${itemName}?`;
    default:
      // A basis this build does not know about still has to render something
      // a person can read, rather than "undefined".
      return `${itemName}?`;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend-customer && npx vitest run src/lib/suggestions.test.ts`
Expected: PASS, 6 tests

- [ ] **Step 5: Add the API calls**

In `frontend-customer/src/lib/api.ts`, following the existing `request` helper
pattern:

```ts
export async function getSuggestion(params: {
  restaurantLocationId: string;
  sessionId: string;
  cart: CartLineRequest[];
}): Promise<SellSuggestion | null> {
  const query = new URLSearchParams({
    restaurant_location_id: params.restaurantLocationId,
    session_id: params.sessionId,
    cart: JSON.stringify(params.cart),
  });
  const envelope = await request<{ suggestion: SellSuggestion | null }>(
    `/suggestions?${query.toString()}`,
  );
  return envelope.suggestion;
}

export async function declineSuggestion(sessionId: string, menuItemId: string): Promise<void> {
  await request("/suggestions/decline", {
    method: "POST",
    body: { session_id: sessionId, menu_item_id: menuItemId },
  });
}
```

- [ ] **Step 6: Typecheck and commit**

Run: `cd frontend-customer && ./node_modules/.bin/tsc --noEmit && npx vitest run`
Expected: clean, all tests pass

```bash
git add frontend-customer/src/lib/suggestions.ts frontend-customer/src/lib/suggestions.test.ts frontend-customer/src/lib/api.ts
git commit -m "feat(customer): suggestion types, copy chosen by basis, cart payload"
```

---

## Task 9: The one renderer, mounted in three places

**Files:**
- Create: `frontend-customer/src/lib/chat-session.ts`, `frontend-customer/src/components/bangkok/waiter-prompt.tsx`
- Modify: `frontend-customer/src/routes/concierge.tsx`, `frontend-customer/src/routes/index.tsx`, `frontend-customer/src/routes/cart.tsx`

**Interfaces:**
- Consumes: `SellSuggestion`, `suggestionCopy`, `cartLinesForRequest`, `api.getSuggestion`, `api.declineSuggestion`, `useMenuItem` from `@/lib/queries`, `useBangkokStore`
- Produces: `readChatSession()`, `storeChatSession(id)`, `clearChatSession()`, `<WaiterPrompt placement="home" | "cart" />`

**Verified names — the earlier draft of this plan had all three wrong:**

| Needed | Actual |
|---|---|
| the selected branch | `useBangkokStore().orderLocation?.id` — there is no `selectedLocationId` |
| the suggested item's name | `useMenuItem(id)` from `@/lib/queries` — the store holds no menu items |
| the chat session id | module-level `SESSION_KEY` helpers **inside** `concierge.tsx` — not on the store |

- [ ] **Step 1: Extract the chat session id so both transports share it**

The session id currently lives in `concierge.tsx` as a module-level
`SESSION_KEY = "bangkok-bowl-chat-session"` with local `readSession` /
`storeSession` / `clearSession` helpers. `WaiterPrompt` needs the same id —
suppression is keyed by it, and a prompt dismissed on the home page must not
reappear in the chat.

Move those three helpers verbatim into a new
`frontend-customer/src/lib/chat-session.ts`, exporting them as
`readChatSession`, `storeChatSession` and `clearChatSession`, keeping the same
`SESSION_KEY` string so existing browsers keep their session. Update
`concierge.tsx` to import them instead of declaring them.

If `readChatSession()` returns null — a customer who has never chatted — the
component mints one with `crypto.randomUUID()` and stores it, so guidance works
before any conversation exists.

- [ ] **Step 2: Write the component**

Create `frontend-customer/src/components/bangkok/waiter-prompt.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useBangkokStore } from "@/lib/bangkok-store";
import { readChatSession, storeChatSession } from "@/lib/chat-session";
import { useMenuItem } from "@/lib/queries";
import { cartLinesForRequest, suggestionCopy, type SellSuggestion } from "@/lib/suggestions";

/**
 * One suggestion, rendered where the customer already is.
 *
 * Deliberately NOT a chat. There is no transcript, no input and no history:
 * a single line with one action and a dismiss. A customer who ignores it sees
 * the site exactly as it was, because guidance here is additive and never
 * gates a path.
 *
 * Dismissing counts as a decline, and two declines silence suggestions for the
 * session — which is why the dismiss button posts rather than only hiding.
 */
export function WaiterPrompt({ placement }: { placement: "home" | "cart" }) {
  const store = useBangkokStore();
  const [suggestion, setSuggestion] = useState<SellSuggestion | null>(null);

  const locationId = store.orderLocation?.id;

  // Minted here when the customer has never chatted, because guidance must not
  // require a conversation to have happened first.
  const sessionId = useMemo(() => {
    if (typeof window === "undefined") return null;
    const existing = readChatSession();
    if (existing) return existing;
    const minted = crypto.randomUUID();
    storeChatSession(minted);
    return minted;
  }, []);

  useEffect(() => {
    if (!locationId || !sessionId) return;
    let cancelled = false;
    void (async () => {
      try {
        const next = await api.getSuggestion({
          restaurantLocationId: locationId,
          sessionId,
          cart: cartLinesForRequest(store.cart),
        });
        if (!cancelled) setSuggestion(next);
      } catch {
        // Guidance must never break a page. Silence is the correct failure.
        if (!cancelled) setSuggestion(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [locationId, sessionId, store.cart]);

  // The name and price come from the client's OWN menu data, never from the
  // suggestion — one price path, so this can never contradict the menu page.
  const { data: item } = useMenuItem(suggestion?.menu_item_id ?? undefined);

  if (!suggestion || !item) return null;

  async function dismiss() {
    setSuggestion(null);
    if (sessionId && suggestion?.menu_item_id) {
      try {
        await api.declineSuggestion(sessionId, suggestion.menu_item_id);
      } catch {
        // A decline that fails to record is not worth telling the customer about.
      }
    }
  }

  return (
    <aside className={`waiter-prompt waiter-prompt--${placement}`} role="note">
      <p className="waiter-prompt__text">{suggestionCopy(suggestion, item.name)}</p>
      <Button size="sm" onClick={() => store.addItem(item)}>
        Add
      </Button>
      <Button size="sm" variant="ghost" onClick={dismiss} aria-label="No thanks">
        <X />
      </Button>
    </aside>
  );
}
```

- [ ] **Step 3: Add the styles**

In `frontend-customer/src/styles.css`, beside the existing `.category-pill`
block, add a rule that keeps the prompt to one line with its actions on the
right, and make `--home` sit under the hero and `--cart` sit above the totals.
Follow the file's existing conventions; do not introduce a new styling system.

- [ ] **Step 4: Mount it**

In `src/routes/index.tsx`, render `<WaiterPrompt placement="home" />`
immediately below the hero and above "Your personalised picks". In
`src/routes/cart.tsx`, render `<WaiterPrompt placement="cart" />` above the
order summary.

Do **not** mount it on `menu.index.tsx` in this task — the menu heading variant
is a different treatment (a heading, not a card) and is left to Phase 3 rather
than approximated here.

- [ ] **Step 5: Typecheck and verify by hand**

Run: `cd frontend-customer && ./node_modules/.bin/tsc --noEmit && npx vitest run`

Then, with all three services running:
1. Open the home page signed in as `customer1@example.com` / `password123`.
2. Add a Green Curry to the cart, return home — a prompt should appear.
3. Dismiss it; reload — the same item must not come back.
4. Dismiss a second suggestion; reload — no prompt at all for the session.
5. Confirm the home page still shows hero, picks and categories, and that
   nothing resembling a chat transcript appears anywhere outside `/concierge`.

- [ ] **Step 6: Commit**

```bash
git add frontend-customer/src/lib/chat-session.ts frontend-customer/src/components/bangkok/waiter-prompt.tsx frontend-customer/src/routes/concierge.tsx frontend-customer/src/routes/index.tsx frontend-customer/src/routes/cart.tsx frontend-customer/src/styles.css
git commit -m "feat(customer): the waiter speaks through the page, one line at a time"
```

---

## Task 10: The chat renders the same suggestion

**Files:**
- Modify: `frontend-customer/src/routes/concierge.tsx`, `frontend-customer/src/lib/api.ts`

**Interfaces:**
- Consumes: everything from Tasks 8 and 9
- Produces: nothing new

- [ ] **Step 1: Send the cart with each message**

In `api.ts`, add `cart: cartLinesForRequest(cart)` to the `/chat/message` body,
threading the cart in from the caller rather than reading a store inside the
API layer.

- [ ] **Step 2: Render the suggestion in the thread**

In `concierge.tsx`, when a turn's response carries `suggestion`, render the
same `suggestionCopy` text with an Add action beneath that turn's reply. Reuse
the copy function — the chat must not word the same `basis` differently from
the home strip, which is the drift this whole design exists to prevent.

- [ ] **Step 3: Verify the shared session**

Run the app and confirm the shared-memory behaviour end to end:
1. On the home page, dismiss a suggestion for a specific dish.
2. Open `/concierge` and ask something that would surface the same dish.
3. That dish must **not** be suggested — same session, same memory.

- [ ] **Step 4: Typecheck, test, commit**

Run: `cd frontend-customer && ./node_modules/.bin/tsc --noEmit && npx vitest run`

```bash
git add frontend-customer/src/routes/concierge.tsx frontend-customer/src/lib/api.ts
git commit -m "feat(customer): one suggestion contract, chat and page worded alike"
```

---

## Self-Review

**Spec coverage for Phase 1:**

| Spec requirement | Task |
|---|---|
| Cross-sell from mined patterns, overlap-by-exactly-one | 1 |
| Diet and availability filter before ranking | 1, 2 |
| Category fallback with honest `basis` labelling | 2, 8 |
| Up-sell ladder: combo → size → add-on | 3 |
| Suppression: one per reply, no repeats, stop after two declines | 4 |
| Shared suppression across both transports, same `session_id` | 4, 6, 10 |
| `GET /api/suggestions` for pages with no message | 6 |
| Request carries the cart, treated as untrusted | 5, 6, 7, 8 |
| Identifiers only across the wire | 6, 8 |
| Reply carrying a suggestion is never globally cached | 7 |
| Guidance renders in-page, never as a transcript outside `/concierge` | 9 |
| Suggestion failure never breaks a page | 6, 9 |

**Deferred to Phase 3, deliberately:** the menu-heading variant ("Because you
like it spicy") and the docked bar. Both are presentation-only and neither
changes the contract; Task 9 notes the omission rather than approximating it.

**Not in this plan, by constraint:** `cart_actions`, `turn_id`,
`applyCartActions`, and anything that mutates a cart from a chat turn. Those
are Phase 2.

**Type consistency:** `SellSuggestion` carries the same field names in the
service dataclass (Task 1), the Pydantic response (Task 6) and the TypeScript
type (Task 8). `CartLineFacts` is the internal shape; `CartLinePayload` is the
wire shape; `CartLineRequest` is its TypeScript mirror. `basis` values are
fixed in Task 1–3 and consumed by name in Task 8.

**All call sites verified against the source.** An earlier draft guessed three
of them and got two wrong, which is recorded here because the corrections
changed the shape of Task 9:

| Guessed | Actual | Effect |
|---|---|---|
| `MenuItemCustomizationGroup.menu_item_id` | correct | none |
| `get_user_preferences(db, user_id)` | `get_user_preferences_response(db, user)` in `recommendations.py:1636` | takes the `User`, not an id |
| `store.selectedLocationId` | `store.orderLocation?.id` | — |
| `store.menuItems` | `useMenuItem(id)` from `@/lib/queries` | the store holds no menu items |
| `store.chatSessionId` | module-level helpers inside `concierge.tsx` | **added Task 9 Step 1** to extract them to `chat-session.ts`, since both transports must share one id |

The session-id extraction is the one structural change the verification forced,
and it is load-bearing: without it, suppression state cannot be shared and a
prompt dismissed on the home page would reappear in the chat.
