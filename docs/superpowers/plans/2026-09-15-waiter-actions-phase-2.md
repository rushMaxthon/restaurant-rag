# Waiter Phase 2 — Agentic Cart Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A customer on `/concierge` who says "add two chicken satay" or "remove the pad thai" gets a cart that already reflects it, not a paragraph telling them where to click.

**Architecture:** A new pure module `app/services/cart_actions.py` classifies the cart verb in a message (add/remove/set_quantity/clear) and turns it into at most one `CartAction`, reusing the SAME dish-name-confidence signal (`classify_dish_reference` / `DISH_NAME_MAX_DISTANCE`) and the SAME retrieval candidates the chat pipeline already computes for its reply — no second retrieval, no model call. The concierge's actual transport is `POST /chat/message/stream` (confirmed below, not the `ChatMessageResponse` the spec assumed), so the resolved action rides the SSE `done` frame, keyed by a server-minted `turn_id`. The client never invents a mutation: `applyCartActions` in `bangkok-store.tsx` is the only place a chat turn may change the cart, it resolves every id against the branch's already-loaded menu, and it snapshots before applying so one tap undoes it.

**Tech Stack:** FastAPI 0.115, SQLAlchemy 2.0, Pydantic v2, `unittest` (NOT pytest); TanStack Start + React 19, vitest with `environment: "node"`.

**Spec:** `docs/superpowers/specs/2026-09-14-waiter-agentic-cart-design.md`
**Prior phase:** `docs/superpowers/plans/2026-09-14-waiter-suggestions-phase-1.md` (shipped; this plan assumes its schemas and files exist as merged, not as originally drafted — see refinements below)

## Global Constraints

- **Tests are `unittest`, not pytest.** Every backend test file inserts `backend/` on `sys.path` itself and imports `app.main` first to settle import order. Copy the header from `backend/tests/test_suggestion_rules.py`.
- **No new runtime dependencies** in either project.
- **Comments explain *why*, not what.** Match the density of `backend/app/config/settings.py`.
- **Not an LLM planner. Actions are produced deterministically.** No model call anywhere in this plan — cart-verb classification and quantity extraction are regex/keyword, same tier as `classify_dish_reference`.
- **Backend enforces, UI only hides.** The client re-validates nothing it is handed as a rule, but drops any action naming an item absent from the branch's currently loaded menu.
- **Identifiers only, never names or prices, cross the wire in a `CartAction`** — same rule Phase 1 already applies to `SellSuggestion` and `CartLinePayload`.
- **A choice-bearing item is never blind-added.** `dish-card.tsx` and `suggestionNeedsChoice` (Phase 1) already enforce this twice; this plan is the third site, and reuses the OUTCOME (route to a choice), not a new invented rule.
- **Anything destructive (`clear`, or a `remove`/`set_quantity` matching more than one existing line) is always `proposed`, whatever the confidence.**
- **A reply carrying `cart_actions` may never be cached globally** — same class of bug `may_cache_globally`'s `has_suggestion` guard already exists for.
- **Verification:** `cd backend && ./.venv/bin/python -m unittest discover -s tests` and `./.venv/bin/python -m compileall app`; `cd frontend-customer && ./node_modules/.bin/tsc --noEmit && npx vitest run && npm run build`.
- **Phase 3 is out of scope.** No docked bar. This plan touches `/concierge` only.

### Deliberate refinements from the spec (verified against source, not spec prose)

1. **The spec assumed `ChatMessageResponse.cart_actions` is what ships to the customer. It is not what the concierge calls.** `frontend-customer/src/routes/concierge.tsx` sends every message through `streamChatMessage()` → `POST /chat/message/stream` (`frontend-customer/src/lib/api.ts:581`), an SSE endpoint. `POST /chat/message` (non-stream) exists and already has `cart`/`suggestion` wired from Phase 1, but `ChatMessageResponse`'s own docstring at `backend/app/schemas/chat.py` says outright: *"`POST /chat/message/stream`, which is the route the web concierge and mobile actually call, never computes a suggestion at all... Kept, not dead: Phase 2 is expected to start sending `cart` on this route, at which point this stops being theoretical."* This plan does exactly that: `cart_actions` and `turn_id` are added to the non-stream `ChatMessageResponse` for API completeness (Task 5), but the actual delivery mechanism the customer uses is the SSE `done` frame (Task 7). Building only the non-stream path would ship a feature no browser ever sees — the same failure mode the comment already flags.
2. **`stream_chat_message_route` (`backend/app/api/chat.py:103`) currently does not forward `payload.cart` into `stream_chat_message(...)` at all**, even though `ChatMessageRequest.cart` has existed since Phase 1. This is a wiring gap, not a schema gap — Task 7 threads it through.
3. **Cart-verb intent ("add"/"remove"/"clear"/"set quantity to N") does not exist anywhere in the current pipeline.** `ExtractedIntent.intent` is a 12-value taxonomy entirely about menu discovery (`recommendation`, `menu_question`, `greeting`, `show_more`, …) — grepped every assignment site in `rag.py` to confirm. Teaching that field a 13th value risks the many `intent.intent == "..."` branches throughout `rag.py`. This plan adds a **separate, independent** classifier (`classify_cart_verb`, Task 2) that runs alongside `ExtractedIntent`, never replaces it, and only ever gates whether the new resolver runs at all.
4. **The dish-name confidence signal already exists and is already computed once per turn, but its verdict is discarded.** `apply_dish_name_guardrail` (`backend/app/services/rag.py:2786`) returns a `DishReference` (`"named" | "absent" | "unknown"`) and is called once, at `rag.py:6932`, inside `_prepare_chat_turn`. Its return value is not stored anywhere on `PreparedChatTurn` today. Task 4 captures it into a new `dish_reference_verdict` field rather than re-deriving it — re-deriving would re-run the fallback vector query `apply_dish_name_guardrail` performs when no vector candidate survived, doubling a DB call and risking double-mutating `intent.dish`.
5. **The spec's `Components` table says the resolver "consumes" retrieval candidates directly.** In practice the item a resolver would want (`menu_item_id`, `has_sizes`, `has_customizations`, already availability-and-branch-filtered) is exactly what `PreparedChatTurn.suggestions: list[ChatSuggestionItem]` already is — the same list the reply's dish cards are built from. Re-reading raw `RetrievedMenuCandidate` rows would mean a second DB fetch of `has_sizes`/`has_customizations` this plan does not need.
6. **Field naming: `customization_option_ids`, not `customization_selection_ids`.** The spec's prose used `customization_selection_ids`; Phase 1 already shipped `customization_option_ids` on both `CartLinePayload` (backend) and the frontend `CartLineRequest`/`CartLine.optionIds`. This plan reuses the shipped name rather than the spec's draft name — introducing a second name for the same concept is exactly the kind of drift the design's own "one suggestion contract" argument warns against.
7. **`reason` gains a fourth value: `needs_choice`.** The spec's `CartAction.reason` enum (`named` / `ambiguous` / `destructive`) has no value for "the dish was named confidently, but it has sizes or customizations, so it cannot be blind-added." That is not the same failure as `ambiguous` (which item?) or `destructive` (should this really happen?) — it is "which variant?", and conflating it with `ambiguous` would make the client render the wrong affordance (a disambiguation list instead of a link to the dish page). Extending the enum is cheaper than overloading an existing value to mean two things.
8. **`extract_requested_quantity` returns `int | None`, not a default of 1.** A caller-side default (1 for `add`, "no action" for `set_quantity`) is a business decision, not a parsing one; returning `None` for "no quantity found" keeps the parser honest about what it actually saw, matching `classify_dish_reference`'s own `"unknown"` case for the same reason.
9. **`CartAction` carries no `size_id` or `customization_option_ids` in this phase**, though the spec's `CartAction` field table lists both. Every `add` this resolver ever marks `applied` is necessarily a choice-free item — `needs_choice` (refinement 7) fires the moment `has_sizes || has_customizations` is true, whatever the sentence said — so there is never a size or option to name on an action the client will actually apply. Parsing a spoken size or option ("the large one", "extra spicy") against the item's real `MenuItemSize`/`MenuItemCustomizationOption` rows is its own matching problem with its own confidence question, not a free extension of dish-name matching; it is deferred to the tier-2 seam alongside multi-item parsing, and the fields are left off the dataclass and schema entirely rather than added-but-always-null.
10. **Backend HTTP-level tests for the two chat routes do not exist anywhere in this repo today** — greeps confirm only `test_owner_chat.py` exercises a *different* streaming feature (owner insights). Following the same precedent Phase 1 set for its own DB orchestrator ("wiring over rules that already have tests... its correctness is checked by the endpoint test... and by manual verification"), Tasks 6 and 7 (wiring into both routes) get compileall + full-suite-passes + one mocked integration test each, not a live-Ollama end-to-end test. All resolver logic is unit-tested as pure functions in Tasks 1–3.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/cart_actions.py` (create) | cart-verb classification, quantity extraction, the pure action resolver |
| `backend/tests/test_cart_actions.py` (create) | the pure rules from `cart_actions.py` |
| `backend/app/services/rag.py` (modify) | capture `dish_reference_verdict` on `PreparedChatTurn`; glue `cart_actions.py` into both chat routes; extend `may_cache_globally` |
| `backend/tests/test_suggestion_cache_refusal.py` (modify) | add `has_cart_actions` cases |
| `backend/app/schemas/chat.py` (modify) | `CartActionResponse`, `ChatMessageResponse.cart_actions` / `.turn_id` |
| `backend/tests/test_chat_action_schemas.py` (create) | schema-level contract tests |
| `backend/tests/test_chat_stream_actions.py` (create) | mocked integration test for the SSE `done` frame |
| `frontend-customer/src/lib/api.ts` (modify) | `CartAction` type, `ChatStreamPayload.cart`, `ChatStreamDone.cart_actions`/`.turn_id` |
| `frontend-customer/src/lib/bangkok-store.tsx` (modify) | `cartLineSignature`, `setLineQuantity`, `removeLine`, `applyCartActionsToCart` (pure), `applyCartActions` / `undoLastCartActions` (Provider) |
| `frontend-customer/src/lib/bangkok-store.test.ts` (modify) | the pure cart-action reducer |
| `frontend-customer/src/routes/concierge.tsx` (modify) | send `cart`, load the branch menu, apply actions on `done`, render applied/undo/confirm inline |

---

## Task 1: Quantity-word extraction

**Files:**
- Create: `backend/app/services/cart_actions.py`
- Test: `backend/tests/test_cart_actions.py`

**Interfaces:**
- Consumes: nothing
- Produces: `extract_requested_quantity(message: str) -> int | None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_cart_actions.py`:

```python
"""What a customer's sentence does to their cart, and whether it is safe to
apply without asking.

Deterministic on purpose — see "The tier-2 seam" in the design spec. Every
rule here is pure over plain inputs, the same discipline `suggestions.py`
uses for the selling rules, and for the same reason: a rule that needs a
database and a live model to exercise is a rule nobody re-checks after
changing it, and this one decides whether an item silently lands in
someone's cart.
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
from app.services.cart_actions import extract_requested_quantity


class QuantityExtractionTests(unittest.TestCase):
    def test_a_bare_digit_is_read_as_the_quantity(self) -> None:
        self.assertEqual(extract_requested_quantity("add 3 chicken satay"), 3)

    def test_number_words_are_understood(self) -> None:
        self.assertEqual(extract_requested_quantity("two pad thai please"), 2)
        self.assertEqual(extract_requested_quantity("a couple of spring rolls"), 2)
        self.assertEqual(extract_requested_quantity("just one"), 1)

    def test_a_multiplier_form_is_understood(self) -> None:
        self.assertEqual(extract_requested_quantity("2x pad thai"), 2)
        self.assertEqual(extract_requested_quantity("pad thai x3"), 3)

    def test_no_quantity_mentioned_yields_none(self) -> None:
        """None, not a default of 1 — the caller decides what silence means."""

        self.assertIsNone(extract_requested_quantity("add the pad thai"))

    def test_a_dollar_amount_is_not_read_as_a_quantity(self) -> None:
        """"under $15" must not extract 15 satay."""

        self.assertIsNone(extract_requested_quantity("something under $15"))

    def test_a_larger_number_word_wins_over_a_shorter_substring(self) -> None:
        """"a couple of" must not stop at "a" and return 1."""

        self.assertEqual(extract_requested_quantity("a couple of pad thai"), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_cart_actions -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.cart_actions'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/cart_actions.py`:

```python
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
_CURRENCY_NEARBY_PATTERN = re.compile(r"[\$₹]|\bunder\b|\bover\b|\bbudget\b", re.IGNORECASE)


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
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return _NUMBER_WORDS[phrase]

    if not _CURRENCY_NEARBY_PATTERN.search(lowered):
        bare = _BARE_DIGIT_PATTERN.search(lowered)
        if bare:
            return int(bare.group(1))

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_cart_actions -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cart_actions.py backend/tests/test_cart_actions.py
git commit -m "feat(cart-actions): read a requested quantity from a sentence, or admit it didn't say"
```

---

## Task 2: Cart-verb classification

**Files:**
- Modify: `backend/app/services/cart_actions.py`
- Test: `backend/tests/test_cart_actions.py`

**Interfaces:**
- Consumes: nothing
- Produces: `CartVerb`, `classify_cart_verb(message: str) -> CartVerb | None`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_cart_actions.py` (add `classify_cart_verb` to the import):

```python
class CartVerbClassificationTests(unittest.TestCase):
    """Independent of `ExtractedIntent` on purpose — see the plan's refinement
    note 3. This never touches the menu-discovery intent taxonomy."""

    def test_add_phrasings_are_recognised(self) -> None:
        for message in ("add pad thai", "order two spring rolls", "i'll have the curry", "give me a coke"):
            self.assertEqual(classify_cart_verb(message), "add", msg=message)

    def test_remove_phrasings_are_recognised(self) -> None:
        for message in ("remove the pad thai", "delete the curry", "take the rice out"):
            self.assertEqual(classify_cart_verb(message), "remove", msg=message)

    def test_set_quantity_phrasings_are_recognised(self) -> None:
        self.assertEqual(classify_cart_verb("make it 3"), "set_quantity")
        self.assertEqual(classify_cart_verb("change the quantity to 2"), "set_quantity")

    def test_clear_phrasings_are_recognised(self) -> None:
        self.assertEqual(classify_cart_verb("clear my cart"), "clear")
        self.assertEqual(classify_cart_verb("start over"), "clear")

    def test_an_ordinary_question_is_not_a_cart_verb(self) -> None:
        for message in ("what's spicy tonight?", "how much is the pad thai?", "recommend something vegetarian"):
            self.assertIsNone(classify_cart_verb(message), msg=message)

    def test_clear_wins_over_add_when_both_words_appear(self) -> None:
        """"start over and add pad thai" is still one action per turn — clear."""

        self.assertEqual(classify_cart_verb("never mind, start over"), "clear")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_cart_actions -v`
Expected: FAIL — `ImportError: cannot import name 'classify_cart_verb'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/services/cart_actions.py`:

```python
CartVerb = Literal["add", "remove", "set_quantity", "clear"]

# Checked in this order — most destructive first — so a message that mentions
# more than one verb-shaped word resolves to the safer reading rather than an
# arbitrary one. "Never mind, start over" must not fall through to "add"
# because it also contains no add-shaped word, but a future phrasing that DID
# mention both should still prefer the one that asks for confirmation anyway.
_CLEAR_PATTERN = re.compile(r"\bclear\b.*\b(cart|order|basket)\b|\bstart over\b|\bnever ?mind\b", re.IGNORECASE)
_SET_QUANTITY_PATTERN = re.compile(
    r"\bmake it\b|\bchange (?:it|the (?:quantity|order))? ?to\b|\bset (?:it|the quantity)? ?to\b",
    re.IGNORECASE,
)
_REMOVE_PATTERN = re.compile(
    r"\bremove\b|\bdelete\b|\btake .* out\b|\bget rid of\b|\bdon'?t want\b",
    re.IGNORECASE,
)
_ADD_PATTERN = re.compile(
    r"\badd\b|\border\b|\bget me\b|\bi'?ll have\b|\bi want\b|\bgive me\b|\bput in\b|\banother\b",
    re.IGNORECASE,
)


def classify_cart_verb(message: str) -> CartVerb | None:
    """Which kind of cart mutation this sentence asks for, if any.

    Independent of `ExtractedIntent.intent` — that field is a menu-discovery
    taxonomy (`recommendation`, `menu_question`, ...) with no cart-mutation
    value in it, and adding one there would touch every `intent.intent == ...`
    branch already in `rag.py`. This classifier is additive: `None` means "not
    a cart-action message", and every existing reply path is unaffected.
    """

    if _CLEAR_PATTERN.search(message):
        return "clear"
    if _SET_QUANTITY_PATTERN.search(message):
        return "set_quantity"
    if _REMOVE_PATTERN.search(message):
        return "remove"
    if _ADD_PATTERN.search(message):
        return "add"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_cart_actions -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cart_actions.py backend/tests/test_cart_actions.py
git commit -m "feat(cart-actions): classify which kind of cart mutation a sentence asks for"
```

---

## Task 3: The action resolver core

**Files:**
- Modify: `backend/app/services/cart_actions.py`
- Test: `backend/tests/test_cart_actions.py`

**Interfaces:**
- Consumes: `CartVerb`, `classify_cart_verb`, `extract_requested_quantity`, `DishReferenceVerdict` from Tasks 1–2
- Produces: `ActionKind`, `ActionStatus`, `ActionReason`, `ExistingCartLine`, `ResolvedDish`, `CartAction`, `resolve_cart_actions(message, *, dish_reference, resolved_dish, existing_lines) -> list[CartAction]`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_cart_actions.py` (add the new names to the import):

```python
PAD_THAI = uuid.uuid4()
CURRY = uuid.uuid4()


class ActionResolverTests(unittest.TestCase):
    """One customer sentence, at most one cart action — never a guessed list."""

    def _dish(self, *, has_sizes: bool = False, has_customizations: bool = False, item_id=PAD_THAI) -> ResolvedDish:
        return ResolvedDish(menu_item_id=item_id, has_sizes=has_sizes, has_customizations=has_customizations)

    def test_a_plain_named_add_is_applied(self) -> None:
        actions = resolve_cart_actions(
            "add the pad thai",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[],
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].kind, "add")
        self.assertEqual(actions[0].status, "applied")
        self.assertEqual(actions[0].reason, "named")
        self.assertEqual(actions[0].menu_item_id, PAD_THAI)
        self.assertEqual(actions[0].quantity, 1)

    def test_a_quantity_is_carried_through(self) -> None:
        actions = resolve_cart_actions(
            "add two pad thai", dish_reference="named", resolved_dish=self._dish(), existing_lines=[]
        )

        self.assertEqual(actions[0].quantity, 2)

    def test_a_choice_bearing_item_is_never_blind_added(self) -> None:
        """Same rule dish-card.tsx and suggestionNeedsChoice already enforce."""

        actions = resolve_cart_actions(
            "add the pad thai",
            dish_reference="named",
            resolved_dish=self._dish(has_sizes=True),
            existing_lines=[],
        )

        self.assertEqual(actions[0].status, "proposed")
        self.assertEqual(actions[0].reason, "needs_choice")

    def test_an_unrecognised_dish_name_yields_no_action(self) -> None:
        actions = resolve_cart_actions(
            "add the moon rock curry", dish_reference="absent", resolved_dish=None, existing_lines=[]
        )

        self.assertEqual(actions, [])

    def test_an_unresolved_reference_yields_no_action(self) -> None:
        """`unknown` (no distance to judge by) is not evidence either way."""

        actions = resolve_cart_actions(
            "add it", dish_reference="unknown", resolved_dish=None, existing_lines=[]
        )

        self.assertEqual(actions, [])

    def test_a_message_with_no_cart_verb_yields_no_action(self) -> None:
        actions = resolve_cart_actions(
            "what's spicy tonight?", dish_reference="named", resolved_dish=self._dish(), existing_lines=[]
        )

        self.assertEqual(actions, [])

    def test_removing_the_one_matching_line_is_applied(self) -> None:
        actions = resolve_cart_actions(
            "remove the pad thai",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[ExistingCartLine(menu_item_id=PAD_THAI)],
        )

        self.assertEqual(actions[0].kind, "remove")
        self.assertEqual(actions[0].status, "applied")

    def test_removing_nothing_present_yields_no_action(self) -> None:
        actions = resolve_cart_actions(
            "remove the pad thai", dish_reference="named", resolved_dish=self._dish(), existing_lines=[]
        )

        self.assertEqual(actions, [])

    def test_removing_a_dish_with_two_lines_is_always_proposed(self) -> None:
        """Two sizes of the same dish — which one? Destructive, so ask, always."""

        actions = resolve_cart_actions(
            "remove the pad thai",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[ExistingCartLine(menu_item_id=PAD_THAI), ExistingCartLine(menu_item_id=PAD_THAI)],
        )

        self.assertEqual(actions[0].status, "proposed")
        self.assertEqual(actions[0].reason, "destructive")

    def test_clear_is_always_proposed_regardless_of_confidence(self) -> None:
        actions = resolve_cart_actions(
            "clear my cart", dish_reference="unknown", resolved_dish=None, existing_lines=[]
        )

        self.assertEqual(actions[0].kind, "clear")
        self.assertEqual(actions[0].status, "proposed")
        self.assertEqual(actions[0].reason, "destructive")

    def test_set_quantity_on_one_matching_line_is_applied(self) -> None:
        actions = resolve_cart_actions(
            "make it 3",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[ExistingCartLine(menu_item_id=PAD_THAI)],
        )

        self.assertEqual(actions[0].kind, "set_quantity")
        self.assertEqual(actions[0].status, "applied")
        self.assertEqual(actions[0].quantity, 3)

    def test_set_quantity_with_no_number_yields_no_action(self) -> None:
        actions = resolve_cart_actions(
            "change the quantity to",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[ExistingCartLine(menu_item_id=PAD_THAI)],
        )

        self.assertEqual(actions, [])

    def test_set_quantity_on_two_matching_lines_is_ambiguous(self) -> None:
        actions = resolve_cart_actions(
            "make it 3",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[ExistingCartLine(menu_item_id=PAD_THAI), ExistingCartLine(menu_item_id=PAD_THAI)],
        )

        self.assertEqual(actions[0].status, "proposed")
        self.assertEqual(actions[0].reason, "ambiguous")

    def test_a_line_of_a_different_item_does_not_count_as_a_match(self) -> None:
        actions = resolve_cart_actions(
            "remove the pad thai",
            dish_reference="named",
            resolved_dish=self._dish(item_id=PAD_THAI),
            existing_lines=[ExistingCartLine(menu_item_id=CURRY)],
        )

        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_cart_actions -v`
Expected: FAIL — `ImportError: cannot import name 'ResolvedDish'`

- [ ] **Step 3: Write minimal implementation**

At the top of `backend/app/services/cart_actions.py`, alongside the existing `from __future__ import annotations` / `import re` / `from typing import Literal`, add:

```python
import uuid
from dataclasses import dataclass
```

Then append to the end of the file:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_cart_actions -v`
Expected: PASS, 26 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cart_actions.py backend/tests/test_cart_actions.py
git commit -m "feat(cart-actions): resolve a sentence and a cart into at most one action"
```

---

## Task 4: Capture the dish-reference verdict on `PreparedChatTurn`

**Files:**
- Modify: `backend/app/services/rag.py`
- Test: `backend/tests/test_prepared_turn_dish_reference.py`

**Interfaces:**
- Consumes: `apply_dish_name_guardrail` (existing), `DishReference` (existing)
- Produces: `PreparedChatTurn.dish_reference_verdict: DishReference`

**Why a thin test, not a full unit suite:** this is a one-line capture-and-thread change onto an existing, already-called function. The verdict values themselves are already covered by `apply_dish_name_guardrail`'s own tests (wherever they live today — not modified here). This test only pins that the field exists, defaults sanely, and that the real preparation path populates it from the real call — a regression here would silently make every action in this phase see `"unknown"` forever, which is the one failure mode worth a dedicated check.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_prepared_turn_dish_reference.py`:

```python
"""`PreparedChatTurn.dish_reference_verdict` is the ONE place the resolver in
`cart_actions.py` learns whether the customer's message named a real dish. It
must come from the same call `apply_dish_name_guardrail` already makes for the
reply's own dish-name guardrail — not a second, independent computation, or
the two could disagree about whether a dish was named.
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
from app.services.rag import PreparedChatTurn, RagStageTimings


class PreparedTurnDishReferenceTests(unittest.TestCase):
    def test_the_field_exists_and_defaults_to_unknown(self) -> None:
        """A `PreparedChatTurn` built by an early-return path (greeting, cache
        hit) never calls the guardrail at all, so it must default rather than
        raise `TypeError: missing argument`."""

        turn = PreparedChatTurn(
            active_session_id=__import__("uuid").uuid4(),
            message="hi",
            effective_message="hi",
            restaurant_id=None,
            retrieval_source="none",
            is_greeting=True,
            is_follow_up=False,
            uses_personal_context=False,
            should_bypass_llm=True,
            suggestion_limit=0,
            vector_result_count=0,
            extracted_intent=__import__("app.services.rag", fromlist=["ExtractedIntent"]).ExtractedIntent(intent="greeting"),
            session_state=__import__("app.services.rag", fromlist=["SessionConversationState"]).SessionConversationState(),
            final_candidates=[],
            suggestions=[],
            history_messages=[],
            history_block="",
            context_block="",
            prompt="",
            timings=RagStageTimings(),
        )

        self.assertEqual(turn.dish_reference_verdict, "unknown")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_prepared_turn_dish_reference -v`
Expected: FAIL — `TypeError` or `AttributeError: 'PreparedChatTurn' object has no attribute 'dish_reference_verdict'`

- [ ] **Step 3: Add the field and capture the verdict**

In `backend/app/services/rag.py`, find the `PreparedChatTurn` dataclass (`class PreparedChatTurn:` — has fields ending `fallback_reply: str | None = None`) and add, after `fallback_reply`:

```python
    # From `apply_dish_name_guardrail`'s own return value — captured here so
    # `cart_actions.py` never re-derives it. Re-deriving would re-run the
    # fallback vector query that function performs when no vector candidate
    # survived, doubling a DB call on every turn a cart action might resolve.
    dish_reference_verdict: DishReference = "unknown"
```

Find the call site (search for `apply_dish_name_guardrail(\n        resolved_intent,` — it is the one inside `_prepare_chat_turn`, after the comment `# After retrieval, because the verdict comes from what the menu turned out to`). Change:

```python
    apply_dish_name_guardrail(
        resolved_intent,
        final_candidates,
        message=message,
        db=db,
        query_embedding=query_embedding,
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
    )
```

to:

```python
    dish_reference_verdict = apply_dish_name_guardrail(
        resolved_intent,
        final_candidates,
        message=message,
        db=db,
        query_embedding=query_embedding,
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
    )
```

Then find the single `return PreparedChatTurn(` that follows this call in the same function (it is the one ending `timings=timings,\n    )` right before `def _persist_chat_exchange`) and add one line before the closing parenthesis:

```python
        timings=timings,
        dish_reference_verdict=dish_reference_verdict,
    )
```

Every other `PreparedChatTurn(` construction site in the file (there are 12 others, all on early-return paths — greeting, cache hit, acknowledgement, error fallback) is untouched: the field's default of `"unknown"` is correct for all of them, since none of those paths ever named a dish worth acting on.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_prepared_turn_dish_reference -v`
Expected: PASS, 1 test

- [ ] **Step 5: Run the full suite to confirm nothing regressed**

Run: `cd backend && ./.venv/bin/python -m compileall app/services/rag.py && ./.venv/bin/python -m unittest discover -s tests`
Expected: compiles; full suite passes

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/rag.py backend/tests/test_prepared_turn_dish_reference.py
git commit -m "feat(rag): stop discarding the dish-name guardrail's verdict"
```

---

## Task 5: Schemas — `CartActionResponse`, `ChatMessageResponse.cart_actions` / `.turn_id`

**Files:**
- Modify: `backend/app/schemas/chat.py`
- Test: `backend/tests/test_chat_action_schemas.py`

**Interfaces:**
- Consumes: nothing (pure schema)
- Produces: `CartActionResponse`, `ChatMessageResponse.cart_actions: list[CartActionResponse]`, `ChatMessageResponse.turn_id: uuid.UUID`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_chat_action_schemas.py`:

```python
"""Pins the wire contract for a cart action — identifiers only, same rule
`SellSuggestionResponse` and `CartLinePayload` already follow. No name and no
price may ever appear here: the client resolves both from its own loaded
menu, which is what keeps there being exactly one price path.
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
from app.schemas.chat import CartActionResponse, ChatMessageResponse


class CartActionSchemaTests(unittest.TestCase):
    def test_a_cart_action_carries_identifiers_only(self) -> None:
        action = CartActionResponse(kind="add", status="applied", reason="named", menu_item_id=uuid.uuid4(), quantity=2)

        self.assertEqual(action.quantity, 2)
        dumped = action.model_dump()
        self.assertNotIn("name", dumped)
        self.assertNotIn("price", dumped)

    def test_a_response_defaults_to_no_actions_and_a_fresh_turn_id(self) -> None:
        response = ChatMessageResponse(reply="hi", session_id=uuid.uuid4())

        self.assertEqual(response.cart_actions, [])
        self.assertIsInstance(response.turn_id, uuid.UUID)

    def test_two_responses_get_different_turn_ids(self) -> None:
        """Idempotency on the client keys off this being unique per turn."""

        a = ChatMessageResponse(reply="hi", session_id=uuid.uuid4())
        b = ChatMessageResponse(reply="hi", session_id=uuid.uuid4())

        self.assertNotEqual(a.turn_id, b.turn_id)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_chat_action_schemas -v`
Expected: FAIL — `ImportError: cannot import name 'CartActionResponse'`

- [ ] **Step 3: Write the schemas**

In `backend/app/schemas/chat.py`, add after the `ChatSuggestionItem` class:

```python
class CartActionResponse(BaseModel):
    """Identifiers only — same rule `SellSuggestionResponse` follows and for
    the same reason: the client already has one price path (its own loaded
    menu), and a name or price here would be a second one that can disagree
    with it."""

    kind: str
    status: str
    reason: str
    menu_item_id: uuid.UUID | None = None
    quantity: int | None = None
```

Then in `ChatMessageResponse`, add after `suggestion: SellSuggestionResponse | None = None`:

```python
    # Ordered, may be empty. This phase's resolver only ever returns 0 or 1 —
    # see `cart_actions.py: resolve_cart_actions` — but the type stays a list
    # because a future multi-item parser (the tier-2 seam) fills the same
    # contract without a breaking change.
    cart_actions: list[CartActionResponse] = Field(default_factory=list)
    # A fresh id per reply, regardless of transport. `applyCartActions` on the
    # client ignores a call whose turn_id matches the last one it applied, so
    # a retried request or a duplicate `done` frame can never apply twice.
    turn_id: uuid.UUID = Field(default_factory=uuid.uuid4)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_chat_action_schemas -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/chat.py backend/tests/test_chat_action_schemas.py
git commit -m "feat(chat): add the cart-action wire contract and a per-turn id"
```

---

## Task 6: `may_cache_globally` refuses a reply carrying cart actions

**Files:**
- Modify: `backend/app/services/rag.py`
- Test: `backend/tests/test_suggestion_cache_refusal.py`

**Interfaces:**
- Consumes: `may_cache_globally` (existing, has `has_suggestion` from Phase 1)
- Produces: `may_cache_globally(..., has_cart_actions: bool = False)`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_suggestion_cache_refusal.py`:

```python
    def test_a_reply_with_cart_actions_is_never_globally_cached(self) -> None:
        """Same class of bug as `has_suggestion`: an action is computed from
        THIS customer's cart and message, and the global cache key carries
        neither. A cached "✓ Added Pad Thai ×2" served to someone else would
        put an item in their cart that they never asked for."""

        self.assertFalse(
            may_cache_globally(
                cacheable=True,
                history_messages=[],
                session_summary="none",
                has_suggestion=False,
                has_cart_actions=True,
            )
        )

    def test_a_plain_reply_with_neither_is_still_cacheable(self) -> None:
        self.assertTrue(
            may_cache_globally(
                cacheable=True,
                history_messages=[],
                session_summary="none",
                has_suggestion=False,
                has_cart_actions=False,
            )
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_cache_refusal -v`
Expected: FAIL — `TypeError: may_cache_globally() got an unexpected keyword argument 'has_cart_actions'`

- [ ] **Step 3: Extend the guard**

In `backend/app/services/rag.py`, find `def may_cache_globally(` and its parameter list (`has_suggestion: bool = False,`). Add a sibling parameter:

```python
def may_cache_globally(
    *,
    cacheable: bool,
    history_messages: Sequence[object],
    session_summary: str = "none",
    has_suggestion: bool = False,
    has_cart_actions: bool = False,
) -> bool:
```

In the docstring, after the paragraph beginning `` `has_suggestion` guards the same class of bug for a different input: ``, add:

```python
    `has_cart_actions` guards the identical class of bug for `cart_actions`: a
    resolved action is computed from THIS customer's cart AND message, and is
    even more dangerous cached than a suggestion — a cached suggestion is a
    wrong nudge, a cached action is a wrong item silently placed in a
    stranger's cart.
```

Find the body's first two lines (`if not cacheable:\n        return False\n    if has_suggestion:\n        return False`) and change to:

```python
    if not cacheable:
        return False
    if has_suggestion or has_cart_actions:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_suggestion_cache_refusal -v`
Expected: PASS, 5 tests (3 existing + 2 new)

- [ ] **Step 5: Run the full suite**

Run: `cd backend && ./.venv/bin/python -m compileall app/services/rag.py && ./.venv/bin/python -m unittest discover -s tests`
Expected: compiles; full suite passes (both existing call sites at `rag.py:7561` and `rag.py:7953` still compile — neither passes `has_cart_actions` yet, which defaults to `False` and changes nothing until Tasks 7–8 wire it up)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/rag.py backend/tests/test_suggestion_cache_refusal.py
git commit -m "fix(cache): refuse to globally cache a reply that carries a cart action"
```

---

## Task 7: Wire the resolver into `POST /chat/message/stream` — the route the concierge actually calls

**Files:**
- Modify: `backend/app/services/rag.py`, `backend/app/api/chat.py`
- Test: `backend/tests/test_chat_stream_actions.py`

**Interfaces:**
- Consumes: `resolve_cart_actions`, `ResolvedDish`, `ExistingCartLine`, `CartAction` (Task 3); `PreparedChatTurn.dish_reference_verdict` (Task 4); `CartActionResponse` (Task 5); `may_cache_globally(..., has_cart_actions=...)` (Task 6)
- Produces: `stream_chat_message(..., cart: list[CartLinePayload])`; an SSE `done` frame carrying `cart_actions` and `turn_id`

**Why this task's test is a mocked integration test, not a live-Ollama one:** no test in this repo drives `/chat/message` or `/chat/message/stream` through a real model call (verified by grep — see refinement note 10). `stream_chat_message` calls `_stream_reply_events(prepared.prompt)` for its token loop; mocking that one function keeps the test fast, deterministic, and honest about what it checks — the wiring, not Ollama's output.

**Why this test creates its own throwaway Postgres database rather than using `DATABASE_URL`:** this machine's `DATABASE_URL` points at a shared Supabase project (see root `CLAUDE.md`) — writing and deleting test rows there, even with careful cleanup, risks leaking data into a database other sessions and the running dev server also read from. Every existing DB-backed test in this suite that needs real rows (`test_action_outcomes.py`, `test_branch_awareness.py`, `test_order_events.py`, and others — grepped for the pattern) instead creates and drops its own database against LOCAL Postgres admin credentials (`settings.postgres_server`/`postgres_port`, bypassing `DATABASE_URL` entirely) and skips itself with `@unittest.skipUnless(postgres_available(), ...)` when that admin connection is not reachable. This task copies that exact, already-proven pattern rather than inventing a new one.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_chat_stream_actions.py`. This test needs one real, available menu item to resolve a "named" dish against, so it seeds one directly rather than depending on `seed.py`'s dataset (which can change independently of this test).

```python
"""The wiring that gets a resolved cart action out of the route the concierge
actually calls: `POST /chat/message/stream`. `ChatMessageResponse.cart_actions`
(Task 5) is real, but the concierge never reads it — it reads the SSE `done`
frame `stream_chat_message` yields. This test drives that generator directly,
the same way `frontend-customer`'s `streamChatMessage` consumes it: parse SSE
frames, find `done`, read its JSON body.

Runs against its own throwaway Postgres database, created and dropped by this
file — copied from `test_action_outcomes.py`'s pattern — rather than the
shared Supabase `DATABASE_URL` this machine is otherwise configured with (see
root `CLAUDE.md`). Skips itself when no local Postgres admin connection is
reachable, the same as every other DB-backed test in this suite.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import UserRole
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services import rag
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

settings = get_settings()
TEST_DB_NAME = os.environ.get("CART_ACTIONS_TEST_DB", "restaurant_rag_cart_actions_test")


def _admin_url() -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/postgres"
    )


def _test_url() -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/{TEST_DB_NAME}"
    )


def postgres_available() -> bool:
    engine = None
    try:
        engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with engine.connect():
            return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if engine is not None:
            engine.dispose()


def _parse_sse(chunks: list[str]) -> dict[str, dict]:
    frames: dict[str, dict] = {}
    for raw in "".join(chunks).split("\n\n"):
        if not raw.strip():
            continue
        event = "message"
        data_lines: list[str] = []
        for line in raw.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if data_lines:
            frames[event] = json.loads("\n".join(data_lines))
    return frames


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class ChatStreamActionWiringTests(unittest.TestCase):
    engine = None
    session_factory = None

    @classmethod
    def setUpClass(cls) -> None:
        admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin_engine.dispose()

        cls.engine = create_engine(_test_url())
        with cls.engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
        Base.metadata.create_all(cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, expire_on_commit=False)

        with cls.session_factory() as session:
            restaurant = Restaurant(
                id=uuid.uuid4(),
                name="Cart Action Test Kitchen",
                slug="cart-action-test-kitchen",
                cuisine_type="Test",
                address_line_1="1 St",
                city="Test City",
                state="TS",
                postal_code="000000",
                is_approved=True,
                is_open=True,
                is_active=True,
            )
            session.add(restaurant)
            session.flush()
            location = RestaurantLocation(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                branch_name="Test Branch",
                address_line_1="1 St",
                city="Test City",
                state="TS",
                postal_code="000000",
                delivery_enabled=True,
                pickup_enabled=True,
                is_open=True,
                is_active=True,
            )
            session.add(location)
            session.flush()
            item = MenuItem(
                id=uuid.uuid4(),
                restaurant_id=restaurant.id,
                restaurant_location_id=location.id,
                name="Pad Thai",
                category="Main Course",
                cuisine_type="Test",
                description="Test dish for wiring cart actions.",
                price=Decimal("12.00"),
                is_veg=True,
                is_available=True,
            )
            session.add(item)
            user = User(
                id=uuid.uuid4(),
                email="cart-action-test@example.com",
                role=UserRole.CUSTOMER,
                hashed_password="x",
            )
            session.add(user)
            session.commit()

            cls.restaurant_id = restaurant.id
            cls.location_id = location.id
            cls.item_id = item.id
            cls.user = user

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.engine is not None:
            cls.engine.dispose()
        admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin_engine.dispose()

    def setUp(self) -> None:
        self.db = self.session_factory()
        self.addCleanup(self.db.close)

    def test_the_done_frame_carries_a_resolved_add_action_and_a_turn_id(self) -> None:
        with patch("app.services.rag._stream_reply_events", return_value=[{"response": "Added it.", "done": True}]):
            events = list(
                rag.stream_chat_message(
                    self.db,
                    user=self.user,
                    message="add the pad thai",
                    session_id=uuid.uuid4(),
                    restaurant_id=self.restaurant_id,
                    restaurant_location_id=self.location_id,
                    guest_preferences=None,
                    cart=[],
                )
            )

        frames = _parse_sse(events)
        self.assertIn("done", frames)
        self.assertIn("cart_actions", frames["done"])
        self.assertIn("turn_id", frames["done"])
        actions = frames["done"]["cart_actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["kind"], "add")
        self.assertEqual(actions[0]["status"], "applied")
        self.assertEqual(actions[0]["menu_item_id"], str(self.item_id))

    def test_a_reply_carrying_an_action_is_not_globally_cached(self) -> None:
        with (
            patch("app.services.rag._stream_reply_events", return_value=[{"response": "Added it.", "done": True}]),
            patch("app.services.rag.cache_set_json") as mocked_cache_set,
        ):
            list(
                rag.stream_chat_message(
                    self.db,
                    user=self.user,
                    message="add the pad thai",
                    session_id=uuid.uuid4(),
                    restaurant_id=self.restaurant_id,
                    restaurant_location_id=self.location_id,
                    guest_preferences=None,
                    cart=[],
                )
            )

        mocked_cache_set.assert_not_called()

    def test_an_ordinary_question_carries_no_cart_actions(self) -> None:
        with patch("app.services.rag._stream_reply_events", return_value=[{"response": "It's spicy.", "done": True}]):
            events = list(
                rag.stream_chat_message(
                    self.db,
                    user=self.user,
                    message="what's spicy tonight?",
                    session_id=uuid.uuid4(),
                    restaurant_id=self.restaurant_id,
                    restaurant_location_id=self.location_id,
                    guest_preferences=None,
                    cart=[],
                )
            )

        frames = _parse_sse(events)
        self.assertEqual(frames["done"]["cart_actions"], [])


if __name__ == "__main__":
    unittest.main()
```

Before running: check `test_action_outcomes.py`'s exact `Restaurant`/`RestaurantLocation`/`User` required columns against the model definitions in `app/models/` — the fields used above mirror that file's own `_seed` helper, but if any required (non-nullable, no default) column was added to those models since, add it here too. `Base.metadata.create_all` will otherwise fail loudly at `setUpClass`, not silently.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_chat_stream_actions -v`
Expected: FAIL — `TypeError: stream_chat_message() got an unexpected keyword argument 'cart'`

- [ ] **Step 3: Thread `cart` into `stream_chat_message` and resolve actions**

In `backend/app/services/rag.py`, find `def stream_chat_message(` and add a `cart` parameter matching `handle_chat_message`'s existing one:

```python
def stream_chat_message(
    db: Session,
    *,
    user: ChatPrincipal,
    message: str,
    session_id: uuid.UUID | None,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None,
    guest_preferences: dict[str, str] | None,
    cart: list[CartLinePayload] | None = None,
):
```

Add a small resolver wrapper near `_safe_suggestion_for_cart` (same defensive shape — a bug here must never turn a working chat turn into a 500):

```python
def _safe_resolve_cart_actions(
    message: str,
    *,
    prepared: PreparedChatTurn,
    cart: list[CartLinePayload],
) -> list[CartAction]:
    """Turns this turn's already-computed retrieval into a resolver call.

    Deliberately reads `prepared.suggestions[0]` rather than raw retrieval
    candidates — `ChatSuggestionItem` already carries `has_sizes` and
    `has_customizations` for the top-ranked, availability-and-branch-filtered
    candidate, so this needs no second database read (see the plan's
    refinement note 5).
    """

    try:
        top = prepared.suggestions[0] if prepared.suggestions else None
        resolved_dish = (
            ResolvedDish(
                menu_item_id=top.id,
                has_sizes=top.has_sizes,
                has_customizations=top.has_customizations,
            )
            if top is not None
            else None
        )
        existing_lines = [ExistingCartLine(menu_item_id=line.menu_item_id) for line in cart]
        return resolve_cart_actions(
            message,
            dish_reference=prepared.dish_reference_verdict,
            resolved_dish=resolved_dish,
            existing_lines=existing_lines,
        )
    except Exception:
        logger.exception("Cart action resolution failed for chat turn; continuing without one")
        return []
```

Add the import near the other `app.services.suggestions` imports:

```python
from app.services.cart_actions import CartAction, ExistingCartLine, ResolvedDish, resolve_cart_actions
```

In `stream_chat_message`'s body, immediately before the existing `if may_cache_globally(` call near the end (the one that currently reads `cacheable=cacheable_response, history_messages=prepared.history_messages, session_summary=_session_state_prompt_summary(prepared.session_state),` with no `has_suggestion`/`has_cart_actions` kwargs), add:

```python
    turn_id = uuid.uuid4()
    cart_actions = _safe_resolve_cart_actions(message, prepared=prepared, cart=cart or [])
    cart_action_payloads = [
        CartActionResponse(
            kind=action.kind,
            status=action.status,
            reason=action.reason,
            menu_item_id=action.menu_item_id,
            quantity=action.quantity,
        ).model_dump(mode="json")
        for action in cart_actions
    ]
```

Then change that `may_cache_globally` call to:

```python
    if may_cache_globally(
        cacheable=cacheable_response,
        history_messages=prepared.history_messages,
        session_summary=_session_state_prompt_summary(prepared.session_state),
        has_cart_actions=bool(cart_actions),
    ):
```

Add the `CartActionResponse` import alongside the file's other schema imports:

```python
from app.schemas.chat import CartActionResponse
```

Finally, find the final `yield _sse_frame("done", {...})` (the one with `"reply": reply, "session_id": ..., "suggestions": ..., "combo_suggestions": ..., "offer_suggestions": ...`) and add the two new keys:

```python
    yield _sse_frame(
        "done",
        {
            "reply": reply,
            "session_id": str(prepared.active_session_id),
            "suggestions": [item.model_dump(mode="json") for item in response_suggestions],
            "combo_suggestions": [item.model_dump(mode="json") for item in prepared.combo_suggestions],
            "offer_suggestions": [item.model_dump(mode="json") for item in prepared.offer_suggestions],
            "cart_actions": cart_action_payloads,
            "turn_id": str(turn_id),
        },
    )
```

- [ ] **Step 4: Forward `payload.cart` from the route**

In `backend/app/api/chat.py`, in `stream_chat_message_route`, find the `stream_chat_message(...)` call and add `cart=payload.cart,` alongside the existing `guest_preferences=` argument:

```python
    return StreamingResponse(
        stream_chat_message(
            db,
            user=principal,
            message=payload.message,
            session_id=session_id,
            restaurant_id=scoped_restaurant_id,
            restaurant_location_id=payload.restaurant_location_id,
            guest_preferences=(
                payload.guest_preferences.model_dump() if payload.guest_preferences else None
            ),
            cart=payload.cart,
        ),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && ./.venv/bin/python -m unittest tests.test_chat_stream_actions -v`
Expected: PASS, 3 tests

- [ ] **Step 6: Run the full suite**

Run: `cd backend && ./.venv/bin/python -m compileall app && ./.venv/bin/python -m unittest discover -s tests`
Expected: compiles; full suite passes

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/rag.py backend/app/api/chat.py backend/tests/test_chat_stream_actions.py
git commit -m "feat(chat): resolve and stream a cart action on the route the concierge actually calls"
```

---

## Task 8: Wire the resolver into `POST /chat/message` (non-stream) for API completeness

**Files:**
- Modify: `backend/app/services/rag.py`
- Test: none new — covered by extending Task 5's schema and the existing suite

**Interfaces:**
- Consumes: everything from Task 7
- Produces: `ChatMessageResponse.cart_actions` / `.turn_id` populated on the non-stream route

**Why this task exists even though the concierge never calls this route:** `ChatMessageResponse.cart_actions` (Task 5) would otherwise always be empty on the one route that actually sets it, which is worse than not adding the field — a documented contract nobody can rely on. This mirrors exactly how Phase 1 wired `suggestion` onto this same route for the same reason.

- [ ] **Step 1: Wire `handle_chat_message`**

In `backend/app/services/rag.py`, inside `handle_chat_message` (the non-stream function, `def handle_chat_message(` at line ~7254), find the existing block that computes `suggestion` via `_safe_suggestion_for_cart` and the `may_cache_globally(... has_suggestion=suggestion is not None)` call that follows it. Add, immediately after the `suggestion = _safe_suggestion_for_cart(...)` call:

```python
    turn_id = uuid.uuid4()
    cart_actions = _safe_resolve_cart_actions(message, prepared=prepared, cart=cart or [])
```

Change the `may_cache_globally` call in this function to also pass `has_cart_actions=bool(cart_actions)`:

```python
    if may_cache_globally(
        cacheable=cacheable_response,
        history_messages=prepared.history_messages,
        session_summary=_session_state_prompt_summary(prepared.session_state),
        has_suggestion=suggestion is not None,
        has_cart_actions=bool(cart_actions),
    ):
```

`handle_chat_message` constructs `ChatMessageResponse(` at four places (verified: lines ~7285, ~7355, ~7409, ~7614). The first three are early-return paths (greeting/acknowledgement/cache-hit equivalents) that return BEFORE the suggestion/action computation block — leave them untouched; `cart_actions`/`turn_id`'s schema defaults (`[]` / a fresh `uuid.uuid4()`) are already the correct answer for a turn that short-circuited before resolving anything, the same reasoning `PreparedChatTurn.dish_reference_verdict`'s default covers the 12 untouched `PreparedChatTurn(` sites in Task 4.

Only the LAST one needs editing — the one immediately after `reply = _with_closed_notice(...)`, ending `suggestion=(\n            SellSuggestionResponse(**suggestion.__dict__) if suggestion is not None else None\n        ),\n    )`. Add two fields to that call:

```python
    return ChatMessageResponse(
        reply=reply,
        session_id=prepared.active_session_id,
        suggestions=prepared.suggestions,
        combo_suggestions=prepared.combo_suggestions,
        offer_suggestions=prepared.offer_suggestions,
        inferred_preferences=(
            durable_traits_from_message(message, prepared.extracted_intent) if is_guest(user) else {}
        ),
        suggestion=(
            SellSuggestionResponse(**suggestion.__dict__) if suggestion is not None else None
        ),
        cart_actions=[
            CartActionResponse(
                kind=action.kind,
                status=action.status,
                reason=action.reason,
                menu_item_id=action.menu_item_id,
                quantity=action.quantity,
            )
            for action in cart_actions
        ],
        turn_id=turn_id,
    )
```

- [ ] **Step 2: Run the full suite**

Run: `cd backend && ./.venv/bin/python -m compileall app && ./.venv/bin/python -m unittest discover -s tests`
Expected: compiles; full suite passes

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/rag.py
git commit -m "feat(chat): populate cart_actions on the non-stream route too, for contract completeness"
```

---

## Task 9: Frontend types — `CartAction`, `ChatStreamPayload.cart`, `ChatStreamDone.cart_actions`/`.turn_id`

**Files:**
- Modify: `frontend-customer/src/lib/api.ts`
- Test: none new — pure type additions, checked by `tsc --noEmit`

**Interfaces:**
- Consumes: `CartLineRequest` (existing, from `suggestions.ts`, imported into `api.ts` already for `getSuggestion`)
- Produces: `CartAction` type, `ChatStreamPayload.cart?`, `ChatStreamDone.cart_actions`/`.turn_id`

- [ ] **Step 1: Add the `CartAction` type**

In `frontend-customer/src/lib/api.ts`, add near the other chat-stream types (`ChatStreamMeta`, `ChatStreamDone`):

```ts
/**
 * Identifiers only — mirrors `backend/app/schemas/chat.py: CartActionResponse`.
 * No name and no price: the client resolves both from its own loaded menu,
 * which is the one price path every other surface in the app already uses.
 */
export type CartAction = {
  kind: "add" | "remove" | "set_quantity" | "clear";
  status: "applied" | "proposed";
  reason: "named" | "ambiguous" | "destructive" | "needs_choice";
  menu_item_id: string | null;
  quantity: number | null;
};
```

Change `ChatStreamDone` from:

```ts
export type ChatStreamDone = ChatStreamMeta & { reply: string };
```

to:

```ts
export type ChatStreamDone = ChatStreamMeta & {
  reply: string;
  cart_actions: CartAction[];
  turn_id: string;
};
```

- [ ] **Step 2: Send the cart on the stream request**

Change `ChatStreamPayload`:

```ts
type ChatStreamPayload = {
  message: string;
  session_id?: string | null;
  restaurant_id?: string | null | undefined;
  restaurant_location_id?: string | null | undefined;
  guest_preferences?: GuestPreferences | undefined;
  // Both the resolver (Phase 2) and the selling rules (Phase 1) are functions
  // of what is in the cart, and the cart lives in the browser — this is what
  // makes either possible on this route at all.
  cart?: CartLineRequest[];
};
```

`CartLineRequest` is already imported at the top of `api.ts` (`import type { CartLineRequest, SellSuggestion } from "@/lib/suggestions";`, used by `getSuggestion` since Phase 1) — no new import needed.

- [ ] **Step 3: Verify types compile**

Run: `cd frontend-customer && ./node_modules/.bin/tsc --noEmit`
Expected: silent (no new errors) — `concierge.tsx` does not yet send `cart` or read `cart_actions`, which is fine since both are optional/present-but-unused until Tasks 10–11

- [ ] **Step 4: Commit**

```bash
git add frontend-customer/src/lib/api.ts
git commit -m "feat(api): add the cart-action wire types and let the stream request carry a cart"
```

---

## Task 10: `bangkok-store.tsx` — the only place a chat turn may mutate the cart

**Files:**
- Modify: `frontend-customer/src/lib/bangkok-store.tsx`
- Test: `frontend-customer/src/lib/bangkok-store.test.ts`

**Interfaces:**
- Consumes: `CartAction` (Task 9), `CartLine`, `MenuItem`, `AddItemOptions` (existing)
- Produces: `cartLineSignature(itemId, options) -> string`, `applyCartActionsToCart(cart, actions, menuItemsById) -> CartActionApplyResult`, `Store.applyCartActions(turnId, actions, menuItemsById) -> CartActionApplyResult`, `Store.undoLastCartActions() -> void`, `Store.setLineQuantity`, `Store.removeLine`

- [ ] **Step 1: Write the failing test**

Append to `frontend-customer/src/lib/bangkok-store.test.ts` (add `applyCartActionsToCart`, `cartLineSignature` to the import):

```ts
import { applyCartActionsToCart, cartConflictsWith, cartLineSignature } from "./bangkok-store";
import type { CartAction } from "./api";
import type { CartLine } from "./bangkok-store";
import type { MenuItem } from "./bangkok-data";

const menuItem = (overrides: Partial<MenuItem> = {}): MenuItem =>
  ({
    id: "item-1",
    restaurant_id: "r1",
    restaurant_location_id: "loc-1",
    name: "Pad Thai",
    category: "Main Course",
    cuisine_type: "Thai",
    description: "",
    price: 12,
    is_veg: true,
    is_available: true,
    is_bestseller: false,
    image_url: null,
    rating: null,
    rating_count: 0,
    is_new: false,
    is_favorite: false,
    has_sizes: false,
    has_customizations: false,
    sizes: [],
    customization_groups: [],
    ...overrides,
  }) as MenuItem;

const action = (overrides: Partial<CartAction> = {}): CartAction => ({
  kind: "add",
  status: "applied",
  reason: "named",
  menu_item_id: "item-1",
  quantity: 1,
  ...overrides,
});

describe("cartLineSignature", () => {
  it("is the same for the same item with no size or options", () => {
    expect(cartLineSignature("item-1", { sizeId: undefined })).toEqual(
      cartLineSignature("item-1", { sizeId: undefined }),
    );
  });

  it("differs by size", () => {
    expect(cartLineSignature("item-1", { sizeId: "small" })).not.toEqual(
      cartLineSignature("item-1", { sizeId: "large" }),
    );
  });
});

describe("applyCartActionsToCart", () => {
  it("adds a new line for an applied add action", () => {
    const result = applyCartActionsToCart([], [action()], { "item-1": menuItem() });

    expect(result.cart).toHaveLength(1);
    expect(result.cart[0].quantity).toBe(1);
    expect(result.applied).toHaveLength(1);
  });

  it("increments an existing line rather than duplicating it", () => {
    const existing: CartLine = {
      lineId: cartLineSignature("item-1", { sizeId: undefined }),
      itemId: "item-1",
      restaurantId: "r1",
      restaurantName: undefined,
      restaurantLocationId: "loc-1",
      name: "Pad Thai",
      image_url: null,
      quantity: 1,
      unitPrice: 12,
      sizeId: undefined,
      sizeName: undefined,
      optionIds: [],
      addOnNames: [],
    };

    const result = applyCartActionsToCart([existing], [action({ quantity: 2 })], { "item-1": menuItem() });

    expect(result.cart).toHaveLength(1);
    expect(result.cart[0].quantity).toBe(3);
  });

  it("removes every line for the named item on a remove action", () => {
    const existing: CartLine = {
      lineId: "l1",
      itemId: "item-1",
      restaurantId: "r1",
      restaurantName: undefined,
      restaurantLocationId: "loc-1",
      name: "Pad Thai",
      image_url: null,
      quantity: 1,
      unitPrice: 12,
      sizeId: undefined,
      sizeName: undefined,
      optionIds: [],
      addOnNames: [],
    };

    const result = applyCartActionsToCart(
      [existing],
      [action({ kind: "remove", quantity: null })],
      { "item-1": menuItem() },
    );

    expect(result.cart).toHaveLength(0);
    expect(result.applied).toHaveLength(1);
  });

  it("clears the whole cart on a clear action, regardless of what is in it", () => {
    const existing: CartLine = {
      lineId: "l1",
      itemId: "item-1",
      restaurantId: "r1",
      restaurantName: undefined,
      restaurantLocationId: "loc-1",
      name: "Pad Thai",
      image_url: null,
      quantity: 2,
      unitPrice: 12,
      sizeId: undefined,
      sizeName: undefined,
      optionIds: [],
      addOnNames: [],
    };

    const result = applyCartActionsToCart(
      [existing],
      [action({ kind: "clear", menu_item_id: null, quantity: null })],
      {},
    );

    expect(result.cart).toHaveLength(0);
  });

  it("skips a proposed action rather than applying it", () => {
    const result = applyCartActionsToCart([], [action({ status: "proposed", reason: "needs_choice" })], {
      "item-1": menuItem({ has_sizes: true }),
    });

    expect(result.cart).toHaveLength(0);
    expect(result.skipped).toHaveLength(1);
  });

  it("drops an action naming an item absent from the loaded menu, and says so", () => {
    // Branch switched mid-conversation, or the item went out of stock between
    // resolve and apply — dropped, not applied, per the design's failure-mode
    // table.
    const result = applyCartActionsToCart([], [action({ menu_item_id: "not-loaded" })], {
      "item-1": menuItem(),
    });

    expect(result.cart).toHaveLength(0);
    expect(result.skipped).toHaveLength(1);
    expect(result.skipped[0].reason).toBe("not_in_loaded_menu");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend-customer && npx vitest run bangkok-store.test.ts`
Expected: FAIL — `cartLineSignature`/`applyCartActionsToCart` are not exported

- [ ] **Step 3: Extract `cartLineSignature` and add `applyCartActionsToCart`**

In `frontend-customer/src/lib/bangkok-store.tsx`, find the `addItem` callback's inline signature computation:

```ts
        const signature = `${item.id}-${options?.sizeId ?? ""}-${optionIds
          .slice()
          .sort()
          .map((id) => `${id}:${optionPortions[id] ?? "WHOLE"}`)
          .join("-")}`;
```

Extract it to a new exported pure function placed above `cartConflictsWith` (near the top of the file, after the `CartLine` type):

```ts
/**
 * The identity of a cart line — same item, same size, same options and
 * portions. Extracted from `addItem` so Phase 2's `applyCartActionsToCart`
 * can find or create the exact same line an ordinary tap on "+" would,
 * rather than inventing a second notion of "the same dish".
 */
export function cartLineSignature(
  itemId: string,
  options: { sizeId: string | undefined; optionIds?: string[]; optionPortions?: Record<string, OptionPortion> },
): string {
  const optionIds = options.optionIds ?? [];
  const optionPortions = options.optionPortions ?? {};
  return `${itemId}-${options.sizeId ?? ""}-${optionIds
    .slice()
    .sort()
    .map((id) => `${id}:${optionPortions[id] ?? "WHOLE"}`)
    .join("-")}`;
}
```

Replace `addItem`'s inline computation with a call to it:

```ts
        const signature = cartLineSignature(item.id, { sizeId: options?.sizeId, optionIds, optionPortions });
```

Add `quantity` to `AddItemOptions` and use it for both branches of `addItem` (new line and existing line):

```ts
type AddItemOptions = {
  unitPrice?: number;
  restaurantName?: string | undefined;
  sizeId: string | undefined;
  sizeName: string | undefined;
  optionIds?: string[];
  addOnNames?: string[];
  optionPortions?: Record<string, OptionPortion>;
  /** Defaults to 1. Lets `applyCartActionsToCart` add N in one call instead
   * of calling `addItem` N times. */
  quantity?: number;
};
```

In `addItem`, change the found-line branch's increment from `line.quantity + 1` to `line.quantity + (options?.quantity ?? 1)`, and the new-line branch's `quantity: 1` to `quantity: options?.quantity ?? 1`.

Add `setLineQuantity` and `removeLine` next to `changeQuantity`:

```ts
  /** Sets a line to an EXACT quantity, unlike `changeQuantity`'s delta — what
   * an agentic "make it 3" needs, and what a delta-based API cannot express
   * without first reading the current value back out of state. */
  const setLineQuantity = useCallback(
    (lineId: string, quantity: number) =>
      setState((s) => ({
        ...s,
        cart:
          quantity > 0
            ? s.cart.map((line) => (line.lineId === lineId ? { ...line, quantity } : line))
            : s.cart.filter((line) => line.lineId !== lineId),
      })),
    [],
  );

  const removeLine = useCallback(
    (lineId: string) => setState((s) => ({ ...s, cart: s.cart.filter((line) => line.lineId !== lineId) })),
    [],
  );
```

Now add the pure reducer, exported at module scope (not inside the Provider — it takes no React state, only plain values, so it is testable exactly like `cartConflictsWith`):

```ts
export type CartActionApplyResult = {
  cart: CartLine[];
  applied: { action: CartAction; itemName: string }[];
  skipped: { action: CartAction; reason: "proposed" | "not_in_loaded_menu" }[];
};

/**
 * Turns a resolved `CartAction[]` into a new cart, or explains why an action
 * did not take effect. Pure so it is testable without a React tree — the
 * Provider's `applyCartActions` below is a thin wrapper that calls this and
 * commits the result.
 *
 * Every action is re-validated against `menuItemsById` — the branch's
 * CURRENTLY loaded menu — because the branch may have changed, or the item
 * may have gone out of stock, between when the backend resolved the action
 * and when this runs. Dropping silently would look like nothing happened;
 * `skipped` is why callers can say what did.
 */
export function applyCartActionsToCart(
  cart: CartLine[],
  actions: CartAction[],
  menuItemsById: Record<string, MenuItem>,
): CartActionApplyResult {
  let nextCart = cart;
  const applied: CartActionApplyResult["applied"] = [];
  const skipped: CartActionApplyResult["skipped"] = [];

  for (const action of actions) {
    if (action.status !== "applied") {
      skipped.push({ action, reason: "proposed" });
      continue;
    }

    if (action.kind === "clear") {
      nextCart = [];
      applied.push({ action, itemName: "cart" });
      continue;
    }

    const item = action.menu_item_id ? menuItemsById[action.menu_item_id] : undefined;
    if (!item) {
      skipped.push({ action, reason: "not_in_loaded_menu" });
      continue;
    }

    if (action.kind === "add") {
      const signature = cartLineSignature(item.id, { sizeId: undefined });
      const existing = nextCart.find((line) => line.lineId === signature);
      const quantity = action.quantity ?? 1;
      nextCart = existing
        ? nextCart.map((line) => (line.lineId === signature ? { ...line, quantity: line.quantity + quantity } : line))
        : [
            ...nextCart,
            {
              lineId: signature,
              itemId: item.id,
              restaurantId: item.restaurant_id,
              restaurantName: undefined,
              restaurantLocationId: item.restaurant_location_id,
              name: item.name,
              image_url: item.image_url,
              quantity,
              unitPrice: Number(item.price),
              sizeId: undefined,
              sizeName: undefined,
              optionIds: [],
              addOnNames: [],
            },
          ];
      applied.push({ action, itemName: item.name });
    } else if (action.kind === "remove") {
      // Every line of this item, not just one signature: the resolver only
      // ever applies a remove when exactly one cart LINE matched by item id
      // (see `cart_actions.py`'s destructive-if-ambiguous rule), so removing
      // by item id here cannot remove more than the resolver already checked.
      const before = nextCart.length;
      nextCart = nextCart.filter((line) => line.itemId !== item.id);
      if (nextCart.length !== before) applied.push({ action, itemName: item.name });
    } else if (action.kind === "set_quantity" && action.quantity !== null) {
      const quantity = action.quantity;
      nextCart = nextCart.map((line) => (line.itemId === item.id ? { ...line, quantity } : line));
      applied.push({ action, itemName: item.name });
    }
  }

  return { cart: nextCart, applied, skipped };
}
```

Add the import at the top of the file:

```ts
import type { CartAction } from "@/lib/api";
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend-customer && npx vitest run bangkok-store.test.ts`
Expected: PASS, all cases including the 7 new ones

- [ ] **Step 5: Add the Provider-level `applyCartActions` / `undoLastCartActions`**

In the `Store` type, add:

```ts
  setLineQuantity: (lineId: string, quantity: number) => void;
  removeLine: (lineId: string) => void;
  /** The only place a chat turn may mutate the cart. Idempotent per `turnId`:
   * a call whose id matches the last one applied is a no-op, so a duplicate
   * `done` frame or an accidental double-send can never apply twice. */
  applyCartActions: (
    turnId: string,
    actions: CartAction[],
    menuItemsById: Record<string, MenuItem>,
  ) => CartActionApplyResult;
  /** Restores the cart to exactly what it was before the LAST `applyCartActions`
   * call that actually changed anything. One level deep, client-side and
   * per-session — a reload loses the ability to undo, which is acceptable
   * because the cart itself stays visible and editable by hand. */
  undoLastCartActions: () => void;
```

In the Provider function body, alongside the other `useState`/`useCallback` declarations:

```ts
  const [lastAppliedTurnId, setLastAppliedTurnId] = useState<string | null>(null);
  const [undoSnapshot, setUndoSnapshot] = useState<CartLine[] | null>(null);

  const applyCartActions = useCallback(
    (turnId: string, actions: CartAction[], menuItemsById: Record<string, MenuItem>): CartActionApplyResult => {
      if (turnId === lastAppliedTurnId) {
        return { cart: state.cart, applied: [], skipped: [] };
      }
      const result = applyCartActionsToCart(state.cart, actions, menuItemsById);
      if (result.applied.length > 0) {
        setUndoSnapshot(state.cart);
        setState((s) => ({ ...s, cart: result.cart }));
      }
      setLastAppliedTurnId(turnId);
      return result;
    },
    [state.cart, lastAppliedTurnId],
  );

  const undoLastCartActions = useCallback(() => {
    if (undoSnapshot === null) return;
    setState((s) => ({ ...s, cart: undoSnapshot }));
    setUndoSnapshot(null);
  }, [undoSnapshot]);
```

Add `setLineQuantity`, `removeLine`, `applyCartActions`, `undoLastCartActions` to the `useMemo<Store>` return object, alongside the existing `addItem`, `changeQuantity`, `clearCart`.

- [ ] **Step 6: Run the full check**

Run: `cd frontend-customer && ./node_modules/.bin/tsc --noEmit && npx vitest run`
Expected: silent typecheck; full suite passes, +7 tests over the count after Task 9

- [ ] **Step 7: Commit**

```bash
git add frontend-customer/src/lib/bangkok-store.tsx frontend-customer/src/lib/bangkok-store.test.ts
git commit -m "feat(store): applyCartActions — the only chat-driven cart mutation, with undo"
```

---

## Task 11: `concierge.tsx` — send the cart, apply actions, render what happened

**Files:**
- Modify: `frontend-customer/src/routes/concierge.tsx`
- Test: none new — component wiring, checked by `tsc --noEmit` and `npm run build` (vitest here runs with `environment: "node"`, no jsdom, per the project's existing constraint — the same reason `waiter-prompt.tsx` has no render test)

**Interfaces:**
- Consumes: `applyCartActions`, `CartActionApplyResult` (Task 10); `cart_actions`/`turn_id` on `ChatStreamDone` (Task 9); `useMenuItems` (existing, `queries.ts`); `cartLinesForRequest` (existing, `suggestions.ts`)

- [ ] **Step 1: Load the branch's menu and send the cart**

In `frontend-customer/src/routes/concierge.tsx`, add imports:

```ts
import { useMenuItems } from "@/lib/queries";
import { cartLinesForRequest, type SellSuggestion } from "@/lib/suggestions";
import type { CartAction } from "@/lib/api";
```

Inside `ConciergePage`, alongside the existing `store` and `search` reads, add:

```ts
  // The branch's OWN menu data, loaded once and reused for two things: (1)
  // validating that an action's menu_item_id is still real before applying
  // it — see applyCartActionsToCart's `not_in_loaded_menu` case — and (2)
  // resolving name/price/image for a newly-added line, so there is exactly
  // one price path, the same rule waiter-prompt.tsx follows for suggestions.
  const menuQuery = useMenuItems(store.restaurantId, store.currentLocation?.id);
  const menuItemsById = useMemo(
    () => Object.fromEntries((menuQuery.data ?? []).map((item) => [item.id, item])),
    [menuQuery.data],
  );
```

Add `useMemo` to the existing `react` import at the top of the file.

In `sendQuery`, add `cart` to the `streamChatMessage` payload object, alongside `guest_preferences`:

```ts
          guest_preferences: getToken() ? undefined : guestPreferencesForRequest(),
          cart: cartLinesForRequest(store.cart),
```

- [ ] **Step 2: Extend `Turn` and apply actions on `done`**

Change the `Turn` type:

```ts
type Turn = {
  id: string;
  role: "user" | "assistant";
  text: string;
  suggestions: ChatSuggestion[];
  cartActionResult?: CartActionApplyResult;
};
```

Import `CartActionApplyResult`:

```ts
import type { CartActionApplyResult } from "@/lib/bangkok-store";
```

In `sendQuery`'s `onDone` handler, apply the actions and attach the result to the turn:

```ts
          onDone: (done) => {
            sessionIdRef.current = done.session_id;
            storeChatSession(done.session_id);
            const cartActionResult = store.applyCartActions(done.turn_id, done.cart_actions, menuItemsById);
            patchAnswer((turn) => ({
              ...turn,
              text: done.reply,
              suggestions: done.suggestions,
              cartActionResult,
            }));
            setStatus("done");
          },
```

- [ ] **Step 3: Render what happened, and let a proposed action be confirmed or chosen**

Add a small helper above `ConciergePage` (same file), for confirming a `proposed` action from a tap rather than the original chat turn:

```ts
/**
 * Confirming a proposed action is a SEPARATE user act, not a replay of the
 * turn that proposed it — it mints its own turn id rather than reusing the
 * server's, so `applyCartActions`'s idempotency check (which keys off the
 * SERVER's turn_id) never mistakes a deliberate confirm for a duplicate
 * `done` frame.
 */
function confirmedAction(action: CartAction): CartAction {
  return { ...action, status: "applied" };
}
```

In the JSX where a `Turn` with `role === "assistant"` is rendered (find the block mapping `turns` to bubbles — it already renders `turn.suggestions` as `DishCard`s via `suggestionToMenuItem`), add, after the suggestions block, for each assistant turn with a `cartActionResult`:

```tsx
              {turn.cartActionResult && turn.cartActionResult.applied.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                  {turn.cartActionResult.applied.map(({ action, itemName }, index) => (
                    <span key={index} className="cart-action-chip">
                      {action.kind === "clear"
                        ? "Cleared your cart"
                        : action.kind === "remove"
                          ? `Removed ${itemName}`
                          : action.kind === "set_quantity"
                            ? `Set ${itemName} to ${action.quantity}`
                            : `Added ${itemName}${action.quantity && action.quantity > 1 ? ` ×${action.quantity}` : ""}`}
                    </span>
                  ))}
                  <Button size="sm" variant="ghost" onClick={() => store.undoLastCartActions()}>
                    Undo
                  </Button>
                </div>
              )}
              {turn.cartActionResult?.skipped.map(({ action }, index) => {
                if (action.reason !== "proposed") return null;
                const item = action.menu_item_id ? menuItemsById[action.menu_item_id] : undefined;
                if (action.reason === "proposed" && action.kind === "add" && item?.has_sizes) {
                  return (
                    <Button key={index} size="sm" variant="outline" asChild className="mt-2">
                      <Link to="/menu/$itemId" params={{ itemId: item.id }}>
                        Choose {item.name}
                      </Link>
                    </Button>
                  );
                }
                return (
                  <Button
                    key={index}
                    size="sm"
                    variant="outline"
                    className="mt-2"
                    onClick={() =>
                      store.applyCartActions(crypto.randomUUID(), [confirmedAction(action)], menuItemsById)
                    }
                  >
                    {action.kind === "clear" ? "Yes, clear my cart" : "Yes, do it"}
                  </Button>
                );
              })}
```

Add a matching class in `frontend-customer/src/styles.css`, near `.waiter-prompt`:

```css
.cart-action-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: var(--primary-soft);
  padding: 0.35rem 0.75rem;
  font-weight: 600;
}
```

- [ ] **Step 4: Verify**

Run: `cd frontend-customer && ./node_modules/.bin/tsc --noEmit`
Expected: silent

Run: `cd frontend-customer && npx vitest run`
Expected: full suite passes, unchanged count from Task 10 (no new tests in this task — component-only)

Run: `cd frontend-customer && npm run build`
Expected: succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend-customer/src/routes/concierge.tsx frontend-customer/src/styles.css
git commit -m "feat(concierge): apply resolved cart actions, with undo and a confirm path for proposed ones"
```

---

## Task 12: End-to-end verification

**Files:** none — verification only

- [ ] **Step 1: Full backend suite**

Run: `cd backend && ./.venv/bin/python -m compileall app alembic && ./.venv/bin/python -m unittest discover -s tests`
Expected: compiles; every test passes, including all of Tasks 1–8's new files

- [ ] **Step 2: Full frontend suite**

Run: `cd frontend-customer && ./node_modules/.bin/tsc --noEmit && npx vitest run && npm run build`
Expected: silent typecheck; full suite passes; build succeeds

- [ ] **Step 3: Manual verification against the running dev servers**

With the backend on :8000 and `frontend-customer` on :5173 (see root `CLAUDE.md` for how to start them):

1. Open `/concierge`, add a plain item (no sizes/customizations) to the cart from the menu first, so `existing_lines` has something to act on for remove/set_quantity checks.
2. Send "add two spring rolls" (or whatever plain, choice-free item exists in the seeded menu). Confirm: the reply streams in as before, AND a chip reading "Added Spring Rolls ×2" appears with an Undo button, AND the cart badge/count updates without a page reload.
3. Tap Undo. Confirm the cart reverts to exactly its pre-message state.
4. Send "add the [an item with sizes]". Confirm: no blind add happens; instead a "Choose [item]" link appears, matching `dish-card.tsx`'s own rule for the identical case.
5. Send "remove the [item just added twice, e.g. two different sizes]" if two lines of one dish exist; confirm a "Yes, do it" confirm button appears rather than an immediate removal.
6. Send "clear my cart". Confirm a "Yes, clear my cart" confirm button appears (never an immediate clear), and tapping it empties the cart.
7. Open browser devtools Network tab, inspect the SSE response body for one exchange that triggered an action: confirm the `done` frame's JSON contains `cart_actions` and `turn_id`, and that neither `cart_actions` entry contains a `name` or `price` key.
8. Check `docker-compose`/Redis logs are not require — this is all in-memory/DB, no new infra.

- [ ] **Step 4: Update the worklog**

Append an entry to `.claude/worklog.md` per the repo's own convention (see its header): what shipped, what was verified, and the one deliberate scope decision most likely to be questioned later — that `cart_actions` had to be added to the STREAMING route because that is what the concierge actually calls, which the original spec did not anticipate.

- [ ] **Step 5: Final commit**

```bash
git add .claude/worklog.md
git commit -m "docs: record Phase 2 (agentic cart actions) completion in the worklog"
```
