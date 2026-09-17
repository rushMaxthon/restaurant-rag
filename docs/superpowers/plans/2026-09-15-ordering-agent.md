# The Ordering Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** A customer-facing agent that understands anything a person says, plans which tools to call, and orders food — retrieval, pricing, hours and cart mutation all done by validated tools rather than by the model's imagination.

**Supersedes:** `2026-09-15-waiter-actions-phase-2.md`, which produced classification with extra steps. Tasks 1–4 of that plan are merged and their code survives as **tool implementations and a fallback tier**, not as the primary path.

**Spec:** `docs/superpowers/specs/2026-09-14-waiter-agentic-cart-design.md`, especially **"Understanding is the model's job; validating is not"**.

---

## Why this architecture, and why it is not new

This repo already runs a tool-calling planner in production for the owner-facing AI: `backend/app/services/insights/tool_chat.py`. It has a `TOOLS` registry of Pydantic argument models, a `CHAT_TOOLS` whitelist, `build_planner_prompt` generated from the tools' **real** signatures, `clean_arguments` validation, and one rule that matters more than the rest:

> never include a restaurant, branch, customer or user id: you do not choose whose data is read, and a call containing one is discarded

The customer-side agent mirrors that. Nothing here is a novel pattern for this codebase; it is the owner-side agent pointed at ordering.

## Global Constraints

- **No word lists decide meaning.** Binding, per the spec section named above. The model reads the sentence; tools do the work; the deterministic layer validates. The regex tier in `cart_actions.py` survives **only** as the fallback when the model is unreachable.
- **The model never supplies an id.** Not a restaurant id, branch id, customer id, cart line id, or menu item id it invented. Ids come from tool *results*, which come from the database, scoped server-side. A planned call containing a caller-supplied scope id is discarded.
- **The model never invents data.** Every dish, price, time and total in a reply traces to a row a tool returned.
- **Destructive tools never execute.** `clear_cart`, and any `remove` matching more than one line, return a *proposal* the customer confirms. No model output can override this.
- **Additive, never substitutive.** The agent may attach actions and enrich a reply. It may never take over a turn that the existing pipeline would have answered — menu questions, opening hours, delivery and pickup windows, last-order cutoffs all keep working exactly as they do today.
- **These 146 tests are untouchable** and must pass unchanged: `test_chat_question_routing` (25), `test_chat_intent` (23), `test_chat_ordering_windows` (11), `test_schedule_prep_cutoff` (10), `test_time_word_topics` (7), `test_requested_time_validation` (6), `test_rag_chat_fallback` (3), `test_chat_tools` (61). Several exist because this exact class of change broke the chat before — read `test_time_word_topics.py`'s docstring.
- **Flag-gated, defaults off**, with a deterministic fallback — house rule. When the flag is off, the model is unreachable, or the loop exceeds its budget, the customer gets today's reply.
- Tests are `unittest`, not pytest. venv python is `backend/.venv/bin/python`.
- Comments explain WHY. No new dependencies.
- **Verification gate:** zero `FAIL:` lines, and every error matching one of two known signatures — pgvector `could not open extension control file`, or `EMAXCONNSESSION` from the remote Supabase pooler. Counts are load-dependent; prove no-regression by stash-and-compare, never by an absolute number.
- **Hard limits on every dispatch:** never push, never create a branch or worktree, never spawn a subagent, never work outside the named task.

## Environment facts (verified 2026-09-15, older notes are stale)

- Ollama **is** reachable at `http://localhost:11434`; `OLLAMA_CHAT_MODEL=qwen3:8b`.
- The database is the **remote Supabase pooler**, not a local Postgres.
- The customer web app calls `POST /chat/message/stream` (SSE), **not** the non-streaming route.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/ordering_agent/__init__.py` (create) | package marker |
| `.../tools.py` (create) | the tool registry: Pydantic arg models, descriptions, handlers |
| `.../planner.py` (create) | prompt building, model call, plan parsing, argument validation |
| `.../loop.py` (create) | the bounded call loop, budget, fallback |
| `.../guards.py` (create) | id-stripping, scope injection, destructive-action policy |
| `backend/app/services/cart_actions.py` (modify) | demoted to fallback + reused as mutation-tool internals |
| `backend/app/services/rag.py` (modify) | invoke the agent additively on a chat turn |
| `backend/tests/test_ordering_agent_*.py` (create) | one file per task |

---

## Task 1: The tool registry

**Files:** create `ordering_agent/tools.py`, `tests/test_ordering_agent_tools.py`

Define the tool contract before any tool exists: a name, a Pydantic argument model with `extra="forbid"`, a one-line description, and a handler signature. Mirror `insights/tool_chat.py`'s `TOOLS` shape so the two agents read alike.

**Read-only tools** (this task defines the registry and these seven):
`search_menu`, `get_dish`, `view_cart`, `check_hours`, `price_quote`,
`restaurant_info`, `payment_options`.

The customer's requirement is that the agent answers **anything** about the
restaurant, the menu, the cart or payment — so the read-only surface has to
cover all four, not just the menu. `restaurant_info` reads real
`RestaurantLocation` columns (address, phone, delivery/pickup availability,
ETA, minimum order, delivery fee, prep time). `payment_options` reads
`get_enabled_payment_methods` (`restaurant_locations.py:227`).

**`payment_options` is strictly read-only.** It answers "do you take card?".
Its argument model must make initiating a payment structurally impossible — no
amount, no method to charge, no order id. The spec stops the agent at a filled
cart; answering a question about payment is inside that boundary, performing
one is not.

**No handler may accept a restaurant, branch, customer or user id as an argument.** Scope is injected by the caller from the authenticated session. A tool whose arg model exposes a scope id is a defect.

- [ ] Write failing tests: registry lookup, `extra="forbid"` rejects an unknown argument, every tool's arg model is free of scope ids, descriptions are non-empty.
- [ ] Run, observe RED.
- [ ] Implement the registry and the five arg models. Handlers may raise `NotImplementedError`; Task 2 fills them.
- [ ] Run, observe GREEN. Full suite, stash-and-compare.
- [ ] Commit.

## Task 2: Read-only tool handlers

**Files:** modify `ordering_agent/tools.py`, create `tests/test_ordering_agent_readonly.py`

Implement the five read-only handlers over existing services — **no new business logic**:
- `search_menu` → the retrieval `rag.py` already performs (branch-scoped, diet-filtered)
- `get_dish` → dish resolution using the existing dish-name confidence signal
- `view_cart` → the cart the request carried, re-resolved against the branch
- `check_hours` → existing `restaurant_locations` window/cutoff logic
- `price_quote` → **delegates to `validate_order_draft`** (`orders.py`, exposed
  as `POST /api/orders/validate`), the client's own pricing source for subtotal,
  delivery fee, tax and total. Never arithmetic invented here — two pricing
  paths that disagree is the bug this codebase already guards against by
  keeping exactly one.
- `restaurant_info` → `RestaurantLocation` columns, branch-scoped
- `payment_options` → `get_enabled_payment_methods`, read-only

Every handler returns plain data with ids that came from the database.

- [ ] Tests first: each handler returns rows scoped to the branch; an id from another branch is ignored; `price_quote` totals match the existing pricing service for the same input.
- [ ] RED, implement, GREEN, full suite, commit.


## Task 2b: Suggestions become a tool — and learn the customer

> **DEFERRED — 2026-09-15, customer's instruction: "let's do one by one, all
> can't be implemented now. First complete the agentic that we have
> discussed."** Nothing here is cancelled and nothing in Phase 1 is removed —
> `suggestions.py` keeps serving the home and cart prompts throughout. This task
> runs only after the agent works end to end (Task 8 green). It is written down
> now so the design is not re-derived later.

**Files:** modify `ordering_agent/tools.py`, `backend/app/services/suggestions.py`,
create `tests/test_ordering_agent_suggestions.py`

**Phase 1 is not replaced. It is promoted.** `suggestions.py` — cross-sell from
mined order patterns, the labelled category fallback, the up-sell ladder, the
suppression memory — stays exactly as it is and keeps serving the home and cart
prompts. This task gives the agent a tool over the same service, so a
conversation and a page cannot drift apart. One suggestion contract, one more
renderer.

Register `suggest_addition` — read-only, returns at most one suggestion for the
current cart, honouring the existing suppression rules (never twice, never after
two declines, never something already in the cart).

### Personal history, which the customer asked for

Today cross-sell is **branch-wide**: what everyone ordered together. The
customer wants it to also reflect *their own* past orders.

`recommendations.py` already computes exactly this signal —
`_load_order_history(db, user_id)` returns an `OrderHistoryProfile` with per-item,
per-category and per-cuisine counts drawn from that customer's PAID, eligible
orders. Reuse it; do not write a second history query.

**Ranking, strongest evidence first:**

| Basis | Means | Wording it licenses |
|---|---|---|
| `personal_history` | *this* customer ordered these together before | "you usually add…" |
| `co_occurrence` | other customers ordered them together | "often ordered with…" |
| `category_default` | nobody did; cheapest in a missing category | "most people add a drink" |

This is the honesty rule extended, not bent: a stronger claim requires stronger
evidence, and `basis` still decides the wording. A personal claim is the
strongest of the three and needs the narrowest evidence — **this customer's own
orders**, not a demographic guess.

**Guards:**
- A signed-out guest has no history; the rule must degrade to `co_occurrence`
  silently, never invent a personal claim for someone it cannot identify.
- One order is not a habit. Require enough repetition to justify the word
  "usually" — pick a floor, state it in a comment, and test the boundary.
- Diet, branch scope, availability and suppression all still apply first.

- [ ] Tests: a customer with a repeated pairing gets `personal_history`; one with
      a single order does not; a guest never does; a personal suggestion still
      obeys diet and suppression; the three bases produce three distinguishable
      wordings.
- [ ] RED, implement, GREEN, full suite, commit.


## Three outcomes, never two — customer's ruling, 2026-09-15

A cart line can end up in one of three states, and conflating any two of them
tells the customer something false.

| State | What it means | What the agent does |
|---|---|---|
| **Not at this branch** | the id resolves to nothing here | **never mention it** — it is not on this menu, so it does not exist in the conversation |
| **Needs a choice** | the dish is real and available, but has sizes, or has toppings the customer has not chosen | **ask** — "which size?"; for toppings, offer the defaults and ask whether to keep or change them |
| **Complete** | fully specified | price it, add it, act |

The customer's words:

> "If item is not available at branch then do not show on their menu. We can ask
> user about size and we can select topping as per their choice and we can ask
> them to do you want to change or go with default toppings"

**Why this matters more than a wording nit.** `price_quote` currently answers
*"None of these items are on this branch's menu"* for a pizza that is very much
on the menu and merely lacks a size. That is the same class of mistake the
Add-vs-Choose bug was in Phase 1: a dish needing a choice is not a missing dish,
and the two demand different answers — "we don't have that" versus "which one?".

**So every tool that resolves cart lines must return these three outcomes
distinctly**, and a "needs a choice" result must carry *what* the choices are —
the available sizes, the customization groups and their defaults — so the agent
can ask a real question rather than a vague one. A tool that only answers
"couldn't price it" forces the agent to guess, which is what this whole
architecture exists to avoid.

Toppings specifically: defaults are pre-selected and the customer is asked
whether to keep or change them. Never silently applied, never demanded before a
price can be given.

---


### The selection flow, in order — customer's ruling, 2026-09-15

> "For the size we will ask when we select the item from the menu. After user
> select the size we will show default topping and it's price then we will ask
> them to customised"

Three steps, in this order, and the price appears at step 2 — not withheld until
the customer has finished customising.

| Step | Agent says | Needs from tools |
|---|---|---|
| 1. Dish chosen | "Which size?" — the sizes with their prices | the dish's active sizes, each with its own price |
| 2. Size chosen | "That comes with X, Y — that's $N" | the default toppings for **that size**, and the price of size + defaults |
| 3. Price shown | "Want to change anything?" | the customization groups the customer may alter |

**Why the price lands at step 2.** A customer deciding whether to order needs the
number before being asked to fiddle with toppings, not after. Withholding it
until customisation is complete makes the cost feel like something being
revealed rather than offered.

**Size is asked at selection, not at pricing.** By the time `price_quote` sees a
line it should already carry a size. A line reaching pricing without one means
the flow was skipped — that is still "needs a choice", not "not on the menu",
but it is a fallback, not the normal path.

**Toppings are pre-selected, never silently applied.** Step 2 *states* the
defaults. The customer is told what they are getting before being asked whether
to change it. Silence is consent only because the defaults were said out loud.

Note that a size carries its own price (`MenuItemSize.price` is absolute, not a
delta) and each chosen option adds `extra_price`. Step 2's figure is the size
price plus the defaults' extras — computed by the pricing path, never by the
model.


---

## Task 3: Cart-mutating tools

**Files:** modify `ordering_agent/tools.py`, create `tests/test_ordering_agent_mutations.py`

`add_to_cart`, `remove_from_cart`, `set_quantity`, `clear_cart`.

These return **actions**, they do not mutate anything server-side — the cart lives in the browser. Reuse `cart_actions.py`'s safety rules as the internals: destructive always `proposed`, choice-bearing dishes never silently applied, identifiers only.

- [ ] Tests: `clear_cart` is always `proposed`; a remove matching two lines is `proposed`; a dish with sizes is never `applied`; no action carries a name or price.
- [ ] RED, implement, GREEN, full suite, commit.

## Task 4: The planner

**Files:** create `ordering_agent/planner.py`, `tests/test_ordering_agent_planner.py`

Build the prompt from the tools' real signatures (as `_describe_chat_tools` does), call the model, parse the plan, validate arguments through each tool's arg model.

- [ ] Tests, with **hand-written model responses** — no live model in the suite: a valid plan parses; an unknown tool name is discarded; a call carrying a scope id is discarded; malformed JSON degrades to no plan; a plan with extra arguments is rejected by `extra="forbid"`.
- [ ] RED, implement, GREEN, full suite, commit.

## Task 5: The loop and its budget

**Files:** create `ordering_agent/loop.py`, `ordering_agent/guards.py`, `tests/test_ordering_agent_loop.py`

Bounded: a maximum number of tool rounds, a wall-clock budget, and a fallback when either is exceeded. Feed tool results back to the model; stop when it answers or the budget ends.

- [ ] Tests: the loop stops at the cap; exceeding the budget yields the fallback, not a partial answer; a failing tool does not abort the turn; results are fed back in order.
- [ ] RED, implement, GREEN, full suite, commit.

## Task 6: Wire into the chat turn — additively

**Files:** modify `rag.py`, create `tests/test_ordering_agent_turn.py`

Behind a flag defaulting **off**. The agent runs alongside the existing pipeline and attaches actions; it never replaces the reply path.

- [ ] **Run the eight protected test files explicitly and quote the result**, separately from the full suite.
- [ ] Tests: with the flag off, a turn is byte-identical to today; a menu question still answers with the menu; an hours question still answers with hours; a model failure leaves the reply intact.
- [ ] RED, implement, GREEN, full suite, commit.

## Task 7: Client — apply actions

**Files:** `bangkok-store.tsx`, `concierge.tsx`, `lib/api.ts`

`applyCartActions(turnId, actions)` is the only chat-driven mutation path: idempotent per turn, drops ids absent from the loaded branch menu, snapshots before applying so one tap undoes it. Proposals render as confirmations.

- [ ] `tsc --noEmit` silent, vitest green, `npm run build` succeeds.
- [ ] Commit.

## Task 8: End-to-end verification

Drive real sentences with Ollama running and the flag on, covering all four
subjects the customer named. **Phrase every one so it shares no keyword with any
tool name or the old regex tier** — that is the point of the architecture.

| Subject | Sentences to drive |
|---|---|
| Restaurant | "what time do you shut?", "whereabouts are you?", "is there a minimum spend?", "how long does delivery usually take?" |
| Menu | "something spicy but not too heavy", "what's good here?", "anything without dairy?", "tell me about the pork belly" |
| Cart | "go on then", "nah I'm good", "scrap that", "make it two instead", "what have I got so far?" |
| Payment | "can I pay by card?", "do you take cash on the door?" |
| Suggestions | "what goes with this?", "surprise me", "the usual?" — and confirm a returning customer's own history outranks the branch-wide default |
| Totals | "how much is that altogether?", "what's the damage?" |

- [ ] Confirm every answer traces to a tool result — no invented dish, price or time.
- [ ] Confirm hours and menu questions are unchanged with the flag both on AND off.
- [ ] Confirm no payment is ever initiated, only described.
- [ ] Quote every result.

---

## Known risks

**Latency.** A tool loop on qwen3:8b will be slower than today's single call. The budget and fallback exist for this; measure before defending the default.

**The model will try to pass ids.** `insights/tool_chat.py` hit this and discards such calls. Expect the same and test it.

**Flag-off must be provably identical**, or the feature cannot ship dark. Task 6's first test is that equivalence, not the agent working.
