# Narrowing a Vague Menu Request — Offer Categories, Don't Ask

**Status:** approved in conversation, 2026-09-14
**Surfaces:** `backend/app/services/rag.py`, `backend/app/schemas/chat.py`, `frontend-customer`
**Related:** the branch scoping in `ee2534a`, which is what makes a category list meaningful

---

## Why

"Show me the menu" is answered with six dishes. The branch has **117 items across
11 categories** — Beverages, Curry, Dessert, Main Course, Noodles, Pizza, Rice,
Appetizer, Combo, Salads, Soup, roughly ten each. Six arbitrary dishes is not a
menu; it is a sample nobody asked for, and the customer cannot tell what was left
out.

The request genuinely needs narrowing. The question is how.

## What this is not

**Not a question that blocks.** The proposal this replaces was to ask "what do
you want to order?" and wait. That costs a turn for everyone, including the
customer who already said "I want pad thai" and should never be interrupted —
and the concierge's whole value is skipping navigation. A chat that walks you
down a category tree is a worse menu page: linear, invisible, and you cannot see
where you are.

**Not a replacement for the menu page.** For someone who wants to browse, the
honest answer is the menu page, and the reply should link to it.

**Not another embedding threshold.** Vagueness is decided from fields the intent
already carries, not by similarity. See below.

---

## The rule

**Offer, don't ask.** A vague request gets an answer AND a row of category chips:

> We've got 117 dishes at Bodakdev — what are you after?
> `[Curry] [Noodles] [Pizza] [Dessert] [Soup] …`
> …plus a few crowd favourites underneath.

- Someone browsing taps once, which is faster than typing a reply to a question
- Someone specific is never interrupted
- There is always an answer on screen, never only a question

A chip sends its category as the next message, so it re-enters the ordinary
retrieval path rather than needing a mode.

---

## Deciding "vague"

Deterministic, from `ExtractedIntent`, which already carries every field needed:

```
vague  ==  intent is a general recommendation
       and dish is None and items is empty
       and cuisine is None and category is None
       and budget is None and diet is None
       and spicy is None and mood is None
       and not show_more and not new_only
```

If the customer named anything at all — a dish, a cuisine, a budget, a diet, a
flavour — the request is not vague and no chips appear.

Deliberately NOT an embedding comparison. The information is already extracted
and exact; a similarity threshold here would be slower, need re-measuring per
embedding model, and could be wrong about a question the parser already answered
precisely. The dish-name guardrail uses distance because the menu is the only
authority on what a dish is; vagueness is a property of the parse.

`show_more` matters: "show me more" is a follow-up with no fields set, and would
look vague by the field test alone. It is excluded explicitly.

---

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `is_vague_menu_request(intent)` | the rule above, pure | `ExtractedIntent` |
| `category_chips(db, location_id)` | that branch's categories, ordered | `menu_items.category` |
| `ChatMessageResponse.category_suggestions` | transport | — |
| chip row in `concierge.tsx` | render, send on tap | existing `STARTERS` pattern |

`is_vague_menu_request` is pure so the rule is testable without a database, a
model or a request — the same reason `durable_traits_from_intent` is.

### Ordering and size

Categories come from the **selected branch**, not the restaurant: branches carry
different menus, and offering a category this kitchen cannot serve is the bug
`ee2534a` fixed one level up.

Ordered by item count descending, capped at 8. Eleven chips wrap to three lines
on a phone and stop reading as a choice. The cap must be **logged when it
truncates** — a silently dropped category reads as "we do not sell desserts".

---

## Data flow

1. Customer sends a vague request
2. Backend resolves intent as today, retrieval runs as today
3. `is_vague_menu_request` is true → `category_suggestions` is populated
4. Client renders chips beside the usual dish cards
5. Tapping a chip sends that category as an ordinary message

Nothing about retrieval changes. The dishes returned for a vague request are the
same ones returned today; the chips are additive.

---

## Error handling

| Failure | Behaviour |
|---|---|
| No branch selected | no chips — the categories would belong to no kitchen |
| Category lookup fails | log, return no chips, answer normally |
| Branch has one category | no chips; a single choice is not a choice |

Chips are an enhancement. Every failure returns the reply exactly as it is
today.

---

## Testing

`unittest` for the backend, `vitest` for the client.

- `is_vague_menu_request` is true for a bare "show me the menu"
- false when ANY field is set — one subtest per field, since the whole rule is
  that naming anything disqualifies
- false for `show_more`, which has no fields set and is not vague
- categories come from the selected branch, and a category another branch has is
  not offered
- truncation logs what it dropped
- a failing lookup leaves the reply unchanged

---

## Known gaps

**The seeded distribution is unnaturally even** — 11 categories at ~10–11 items
each. A real menu is lopsided, with 40 mains and 2 salads, and chips are worth
*more* there. But it means the local data cannot show whether the ordering rule
is right. Worth checking against a real menu before tuning the cap.

**Categories are free text.** `menu_items.category` has no constraint, so two
branches can spell the same idea differently ("Dessert" / "Desserts") and both
would appear as separate chips. Out of scope, but it will look like a bug the
first time it happens.

**A chip is a new message, so it costs a turn anyway** — for the customer who
taps. The saving is that they type nothing and were never blocked. If the tap
rate turns out low, the honest conclusion is that vague askers want the menu
page, and the link matters more than the chips.
