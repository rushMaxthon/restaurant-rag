# Ordering Windows in the Chat — Tell, Don't Block

**Status:** approved in conversation, 2026-09-14
**Surface:** `backend/app/services/rag.py` — the service-info tier
**Related:** `071d57a`, `6141109` (service questions), `b2edad6` (prep time vs window end)

---

## Why

A customer can hold an entire conversation with the concierge, be recommended
three dishes, add them to a cart, and only discover at checkout that the kitchen
is shut. Nothing in the chat knows the branch has hours.

The enforcement is not missing — `_load_location_for_order` refuses an
out-of-window order before anything is created, with distinct messages for a
closed restaurant, an inactive branch, a closed branch (carrying the owner's own
reason), disabled delivery or pickup, and a kitchen that cannot finish in time.
All of it from the database, in `Asia/Kolkata`.

It is just the last thing the customer meets instead of the first.

## What this is not

- **Not new enforcement.** Checkout already refuses. Duplicating that in the
  chat would mean two places to keep correct, and the chat would be the weaker
  one — it does not create orders, so it cannot be the gate.
- **Not a booking flow.** The chat will not offer or take a time slot. That is a
  second ordering surface to keep in sync with checkout, and the schedule
  picker already does it properly.
- **Not a blocker.** A closed branch still gets recommendations. Someone
  browsing at midnight for tomorrow's lunch is a customer, not an error.

---

## The one rule that matters

**The chat must read openness from the same function ordering does.**

There are two sources of hours in this schema and they disagree:

- `RestaurantLocation.opening_time` / `closing_time` — the simple pair
- `LocationFulfillmentSlot` — per day-of-week, per delivery/pickup

`_get_current_window_end_for_fulfillment` resolves this: **the slot schedule
wins when a branch has slots, and the simple pair is the fallback.** Your data
has 252 slot rows across 18 branches, so for most branches the simple pair is
not the answer.

A chat that read `opening_time` directly would tell a customer the branch is
open while checkout refused the order — which is worse than today's silence,
because it is confidently wrong rather than merely quiet.

So the chat calls `get_location_fulfillment_status(location, fulfillment_type)`
and reports what it returns. That function already accounts for prep time
against the window end (`b2edad6`), so "closing soon" comes out correctly
without this spec restating the rule.

---

## Two behaviours

### 1. Answer an hours question

New patterns in the service-info tier, beside the existing fee and minimum ones:
"what time do you open", "are you open", "opening hours", "how late", "till when",
"are you open now", "when do you close".

The reply names the branch and its real times. Where a branch runs slots, the
times come from today's slots rather than the simple pair, because that is what
ordering will honour.

**No branch chosen** follows the precedent set in `6141109`: hours are per
branch, so the honest answer says that and asks which branch, rather than
inventing one or falling through to the model — which is how "we don't offer
delivery through our app" happened.

### 2. Volunteer the state when it matters

When the branch is closed or closing within the prep window, the reply leads
with it — once, briefly — then answers the question as normal.

> "We're closed right now — Bodakdev opens at 10:00. In the meantime, the Pad
> Thai Veg is worth a look…"

Only on turns where it is material: a dish search, a recommendation, a request
to order. Not on a greeting, not on small talk, and never twice in a session —
a warning repeated every turn reads as nagging and stops being read.

---

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `_is_hours_query(message)` | recognise an hours question | patterns |
| `branch_availability(db, location_id, fulfillment)` | `(is_open, reason, opens_at, closes_at)` for one branch | `get_location_fulfillment_status` |
| `_hours_reply(...)` | the sentence for an hours question | the above |
| `_closed_notice(...)` | the one-line prefix, or None | the above |

`branch_availability` is the only new thing that reads the schema, and it reads
it through the ordering path rather than beside it. The two reply builders are
formatting.

---

## Where it sits

Beside `_service_info_reply`, in the deterministic tier that runs **before** the
model. Nothing generated states an hour: the branch's times are facts, and the
codebase's own rule is that the model phrases answers over retrieved rows and
never produces a figure — the same reason `_service_info_reply` exists rather
than letting the model answer "how much is delivery".

The closed notice is prepended to the final reply after generation, so it
survives whichever path produced the reply — cached, templated or generated.

---

## Error handling

| Failure | Behaviour |
|---|---|
| No branch resolvable | say hours are per branch, ask which — never guess |
| `get_location_fulfillment_status` raises | log, omit the notice, answer normally |
| Branch has neither slots nor opening times | omit the notice; absent data is not "closed" |

A missing notice costs a customer a warning. A wrong one contradicts checkout.
Where they conflict, stay quiet.

---

## Testing

`unittest`, matching the house style.

- an hours question is recognised and answered from the branch's real times
- **a branch with slots is reported from its SLOTS, not from
  `opening_time`** — the regression that would make the chat contradict checkout
- closed branches lead with the notice; open ones do not
- the notice appears on a dish search and not on a greeting
- no branch chosen asks which branch rather than naming one
- a raising availability lookup leaves the reply intact

---

## Known gaps

**Overnight windows are still broken, and this surfaces it.** `_time_in_slot` is
`start <= t <= end`, so a branch open 18:00–02:00 reads as closed at every hour,
and `validate_slot_window` refuses to save such a window at all. Today that is
latent — none of the 252 slots cross midnight. Once the chat starts *announcing*
openness, a wrong answer becomes visible to every customer rather than only to
someone attempting an order. **Fixing it is out of scope here and should be its
own change, but it should land before a late-night branch is onboarded.**

**One fulfillment type at a time.** A branch can be open for pickup and closed
for delivery. The notice will speak about one — delivery, as the default the
cart uses. A customer who intended pickup could read it as more restrictive than
it is. Naming both doubles the sentence for a case that is currently rare; worth
revisiting if branches start diverging.

**The notice is time-sensitive and the reply may be cached.** Response caching
already refuses anything shaped by session context, and the notice is prepended
after generation rather than baked into the cached body, so a stale "we're
closed" cannot be served — but this is the constraint that makes the
prepend-after-generation placement mandatory rather than stylistic.
