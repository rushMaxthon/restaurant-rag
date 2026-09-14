# The Site as a Waiter — Agentic Cart Actions and Evidence-Backed Selling

**Status:** approved in conversation, 2026-09-14
**Surfaces:** `backend/app/services/` (new `suggestions.py`, changes to `rag.py`),
`backend/app/schemas/chat.py`, `frontend-customer/src/lib/bangkok-store.tsx`,
`frontend-customer/src/routes/concierge.tsx`, a new docked component
**Related:** `2026-09-14-category-chips-design.md` (the other answer to a vague
request), `2026-09-14-dish-name-guardrail-design.md` (the confidence signal this
reuses), `ee2534a` (branch scoping, without which none of this is safe)

---

## Why

The concierge advises; it cannot act. A customer who says "two veg pad thai,
medium spicy, and something sweet" gets a paragraph and then has to go find
three things by hand. A waiter writes it down.

Two capabilities, one spec because they share a response contract:

1. **Agentic cart actions** — understood requests change the cart.
2. **Cross-sell and up-sell** — offered by the same backend service to both the
   new waiter and the chat that already exists.

The second point is the load-bearing one. Selling logic placed inside the waiter
component would drift from the chat within a month, and the house rule already
settles it: scoring is backend-driven, labels come from scoring, never
handcrafted in a client.

## What this is not

**Not a server-side cart.** The cart is `localStorage` via `bangkok-store.tsx`
and there is no cart API. Building one drags in guest carts, merge-on-login and
conflict resolution — a larger project than the waiter. The backend resolves and
validates; the client applies.

**Not a checkout agent.** The waiter stops at a filled cart. It cannot choose
delivery or pickup, pick a slot, or touch payment. A resolution mistake must
stay a visible wrong cart, never a charge.

**Not an LLM planner.** Actions are produced deterministically. See "The tier-2
seam".

---

## Scope: three shippable phases

| Phase | Ships | Depends on |
|---|---|---|
| 1 | `suggestions.py`, wired into the existing `/concierge` chat | — |
| 2 | Resolver, action contract, client applier — `/concierge` only | — |
| 3 | The docked waiter bar on every page | 1, 2 |

Phase 1 first: smallest, improves the chat that already exists, and carries no
risk of putting a wrong item in a cart. Phase 2 is the risky one and lands on
one screen before it lands on fourteen.

---

## Architecture: backend resolves, client applies

### The request must carry the cart

Both selling rules are functions of what is in the cart, and the cart lives in
the browser. The backend cannot see it. So `ChatMessageRequest` gains:

```python
cart: list[CartLine] = Field(default_factory=list)
```

where a `CartLine` is `menu_item_id`, `quantity`, optional `size_id`, and
`customization_selection_ids` — identifiers only, matching the response
direction.

The backend treats this as **untrusted input**, because it is: it re-loads every
item from the database scoped to the selected branch and ignores any ID that
does not resolve there. Prices and names are never taken from the request. An
empty or absent `cart` is normal — it simply means no cross-sell and no up-sell
can be computed this turn, and both rules return nothing rather than guessing.

This is the one place the design adds a client→server payload, and it is what
makes Phase 1 shippable on its own: the existing chat starts sending its cart
and starts receiving a suggestion, with no agentic behaviour involved.

### The response

`ChatMessageResponse` gains two fields:

```python
turn_id: uuid.UUID                      # idempotency key for this reply
cart_actions: list[CartAction]          # ordered, may be empty
```

and `suggestion: SellSuggestion | None` — at most one, ever.

A `CartAction` carries **identifiers only**:

| Field | Meaning |
|---|---|
| `kind` | `add` / `remove` / `set_quantity` / `clear` |
| `menu_item_id` | resolved against this branch's menu |
| `quantity` | integer |
| `customization_selection_ids` | reuse the existing customization schema |
| `size_id` | when the item has sizes |
| `status` | `applied` / `proposed` |
| `reason` | `named` / `ambiguous` / `destructive` |

No names and no prices cross the wire. The client renders every action from the
menu data it already loaded, so there is exactly one price path and the waiter
cannot display a price the menu page disagrees with.

### Client side

One function — `applyCartActions(turnId, actions)` in `bangkok-store.tsx` — is
the only place chat-driven mutation may happen, with an undo stack beside it.
It:

- ignores the call entirely if `turnId` matches the last applied turn
  (idempotency; see "Failure modes")
- drops any action whose `menu_item_id` is absent from the current branch's
  loaded menu, and says so rather than applying it
- pushes a snapshot before applying, so undo restores the exact prior cart

### `status` is decided by confidence, not by the model

`classify_dish_reference` already returns `named` / `absent` / `unknown` against
`DISH_NAME_MAX_DISTANCE`. That signal decides:

- `named` → `applied`, with undo
- `unknown` or more than one candidate → `proposed`, rendered as a choice
- **anything destructive** (`clear`, or a `remove` matching several lines) →
  `proposed` always, whatever the confidence

Reusing the guardrail's signal matters: it is measured and tested. A second
threshold invented here would need its own calibration and would drift from the
first one.

---

## Cross-sell: patterns already mined from real orders

`generated_combos.py` enumerates `itertools.combinations(distinct_item_ids, n)`
for every counted order, keyed by `(restaurant, location, sorted item ids)`,
accumulating `order_count` and `unique_user_ids`. Pairwise co-occurrence is
therefore already computed and stored for every pattern that clears the bar.

Given the cart's item IDs and the branch:

1. Load active, customer-visible `GeneratedCombo` rows for that location.
2. Keep patterns overlapping the cart by **≥1 item and missing exactly one**.
   That missing item is the candidate.
3. Filter by business rules before ranking: available at this branch, in stock,
   and not excluded by the customer's diet. A VEG customer is never offered a
   non-veg pairing.
4. Rank by the stored `confidence_score`. Take one.

No new mining, no new table, no invented threshold. The evidence bar is the
combo pipeline's own: `generated_combo_min_order_count` (3),
`generated_combo_min_visible_unique_users` (3), `DELIVERED` and `PAID`/`COD`,
inside `generated_combo_lookback_days` (90).

### The category fallback

Measured on 2026-09-14: **7 customer-visible combos, 6 of them pairs, mined
from 17 multi-item DELIVERED orders.** Six pairs cannot cover a 117-item menu,
so evidence-backed cross-sell will be silent most of the time until order volume
grows.

When no mined pair qualifies, fall back to the location's dynamic bestseller
(`bestsellers.py`) from a category the cart lacks — drink, dessert.

**The label must tell the truth about which one fired.** An evidence-backed
suggestion says *"often ordered with your Green Curry"*. A fallback says *"most
people add a drink"*. The `SellSuggestion` carries `basis: "co_occurrence" |
"category_default"` and the client renders from that field; wording the two
identically is the failure this distinction exists to prevent.

---

## Up-sell: a ladder ordered by value to the customer

First rung that fires wins:

1. **Combo upgrade** — the cart contains every item of a customer-visible combo
   → offer it at `suggested_combo_price`, showing
   `original_total_price - suggested_combo_price` as the saving. Both columns
   are already stored.
2. **Size upgrade** — a line sits on a size that is not the largest active
   `MenuItemSize` for that item → offer the next size with its price difference.
   63 items currently have sizes.
3. **Paid add-on** — an unfilled customization group with active options where
   `extra_price > 0`, ranked by the owner's `sort_order`. 500 such options
   exist.

The order is deliberate and is the design's opinion: a combo *saves* money, a
size gives *more food*, an add-on only *costs* more. A waiter who opens with the
most profitable add-on is a bad waiter, and customers learn to ignore it.

Rung 3 should eventually rank by how often each option was actually chosen
rather than by `sort_order`. That needs order-item selection data this dataset
does not yet have, and is a later change, not a blocker.

---

## Suppression, shared by both surfaces

- At most **one** suggestion per reply.
- Never the same `menu_item_id` twice in a session.
- Never something already in the cart.
- Never something the diet rules out.
- **Stop suggesting entirely after two declines** in a session.
- Silence when nothing qualifies — after the category fallback has also
  declined to fire.

Decline state lives in the existing Redis `SessionConversationState`, so it
costs no new storage and guests get it too.

---

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `suggestions.py: cross_sell_candidate(db, cart_item_ids, location_id, diet)` | the mined-pattern rule, then the category fallback | `GeneratedCombo`, `bestsellers` |
| `suggestions.py: up_sell_candidate(db, cart_lines, location_id)` | the three-rung ladder | `GeneratedCombo`, `MenuItemSize`, customization options |
| `suggestions.py: choose_suggestion(...)` | suppression, and picking the single winner | `SessionConversationState` |
| `rag.py: resolve_cart_actions(intent, candidates, ...)` | intent → validated action list | `classify_dish_reference` |
| `ChatMessageResponse.cart_actions` / `.suggestion` / `.turn_id` | transport | — |
| `bangkok-store.tsx: applyCartActions` | the only chat-driven mutation path | — |
| the docked bar | render, send, show undo | existing concierge patterns |

`cross_sell_candidate` and `up_sell_candidate` are pure over their inputs so the
rules are testable without a request or a model.

---

## Failure modes

| Failure | Behaviour |
|---|---|
| Reply carries actions or a suggestion | **never globally cached** — see below |
| Request `cart` names an item not at this branch | ignored; not treated as an error |
| Same turn applied twice | `turn_id` matches last applied → ignored |
| Branch switched mid-conversation | action's item absent from loaded menu → dropped, customer told |
| Item went out of stock between resolve and apply | same — dropped, not applied |
| Suggestion service raises | suggestion omitted, reply otherwise unchanged |
| Ollama absent or slow | actions still resolve; only phrasing falls back to templates |
| Wrong item auto-applied | reply names what it did; one-tap undo restores the prior cart |

The cache rule is the one most likely to be got wrong. Replies carrying actions
or a suggestion are cart-shaped and session-shaped — precisely the class
`may_cache_globally` exists to refuse, and which slipped through twice before
because the guard checked only one of its two signals. A cached
"✓ Added Pad Thai ×2" served to a second customer would put an item in their
cart.

---

## The tier-2 seam

An LLM tool-calling planner over cart tools — the `insights/` tier-2 pattern —
would handle phrasings the parser cannot, such as "surprise me with something my
kids would like". It is **designed for and not built**:
`resolve_cart_actions` returning an empty list is the seam a planner would fill,
behind `enable_waiter_llm_planner` defaulting off.

Not built now because it needs Ollama, adds latency to a path that already has
slow-model fallbacks, is unreliable for multi-step plans on `qwen3:8b`, and
would still need the deterministic resolver underneath as its fallback. The
deterministic tier is therefore never wasted work.

---

## Testing

`unittest` for the backend, `vitest` for the client.

- a pattern overlapping the cart by exactly one missing item is chosen; one
  missing two items is not
- a VEG customer is never offered a non-veg pairing, from either basis
- an evidence-backed suggestion and a fallback carry different `basis` values
- the ladder prefers combo over size over add-on when all three could fire
- nothing qualifying, and the fallback also silent, yields no suggestion
- the same item is not offered twice in a session; suggesting stops after two
  declines
- `classify_dish_reference` returning `unknown` yields `proposed`, not `applied`
- `clear` is `proposed` even when confidence is high
- a reply carrying actions is refused by `may_cache_globally`
- a `cart` line naming an item from another branch is ignored, and the turn
  still answers normally
- prices and names in the reply come from the database, never from the
  request's `cart`
- `applyCartActions` called twice with one `turn_id` applies once
- an action naming an item absent from the loaded menu is dropped
- undo restores the exact prior cart, including customizations

---

## Known gaps

**Cross-sell coverage is thin today** — 6 mined pairs. The category fallback
covers the gap, but the feature's evidence-backed half will not look impressive
until order volume grows. Worth re-measuring before tuning any threshold.

**Add-on ranking is owner-ordered, not popularity-ordered.** `sort_order` is a
stand-in for data that does not exist yet.

**The undo stack is per-session and client-side.** A customer who reloads the
page loses the ability to undo the previous turn. Acceptable: the cart itself is
visible and editable by hand.

**Suggestions cost cache hits.** Because a reply carrying a suggestion may not
be cached globally, adding a suggestion to a turn that would otherwise have been
a cache hit makes that turn slower. The suppression rules limit how often this
happens, but it is a real trade and should be watched once measured.

**Quantity parsing is new.** "two", "a couple of", "2x" are not currently
extracted by `_fallback_extract_intent`, and this is the one genuinely new
parsing surface the design adds.
