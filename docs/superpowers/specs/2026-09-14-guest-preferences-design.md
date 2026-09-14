# Guest Preferences — Remembered Locally, Promoted on Login

**Status:** approved in conversation, 2026-09-14
**Surfaces:** `backend` (chat + preferences), `frontend-customer`
**Related:** `docs/per-app-identity.md` for the identity model this must not violate

---

## Why

The concierge is usable before login by design — the sign-in wall sits at
checkout, not in front of browsing (`services/chat_principal.py`). A visitor can
have a five-turn conversation, say "I'm vegetarian" twice, and get meat
recommended on turn six of their next visit, because nothing about them survives
the session.

Meanwhile the preference machinery already exists and is well built.
`user_preferences` holds diet, spice level, cuisines and budget; the chat reads
them; `upsert_user_preferences` invalidates the chat cache and refreshes AI
recommendations when they change. Two things are missing, and only two:

1. A guest has no row in `users`, so there is nowhere to put what they said.
2. Nothing ever writes preferences from the conversation. `rag.py` touches
   `UserPreferences` in exactly one place, a `select`. The only writer in the
   whole backend is `PUT /api/preferences`, reached from a form that
   **`frontend-customer` does not have** — the eight existing rows came from
   seeding or mobile.

So the conversation is the richest signal this product has about a customer, and
it is discarded.

## What this is not

- **Not a preferences UI.** No settings screen, no onboarding wizard. Capture is
  inference only. A visible, editable record of what has been remembered is the
  obvious follow-up and is deliberately out of scope; see "Known gaps".
- **Not a new extractor.** The backend already computes `diet`, `spicy`,
  `budget` and `cuisine` per turn in `ExtractedIntent`. This persists a signal
  that already exists.
- **Not a confirmation flow.** The customer is never asked "shall I remember
  that?". Recorded as a known gap, not solved here.

---

## Constraints

These bind every decision below.

**Backend enforces, UI only hides** (CLAUDE.md). Preferences for an
authenticated user come from the database and nowhere else. This is the
constraint the whole design bends around, because accepting preferences from a
client is exactly the sort of thing it forbids.

**A guest is a browser, not a person.** `GuestPrincipal.id` is
`uuid5(namespace, session_id)` — stable for a session, meaningless across
devices, and shared by everyone using that machine.

**Guests get no `chat_history` rows.** That table's `user_id` is NOT NULL with
an FK to `users`. Guest state lives in Redis and localStorage or not at all.

**Every AI path degrades to a deterministic fallback.** Nothing here may turn a
missing preference into an error.

---

## The three decisions

Settled in conversation before this document existed. They are the design.

### 1. Inference, not a form

Capture comes from the chat. The alternative — build a preferences screen — was
rejected because guests skip onboarding before they have seen any value, and
because the signal is already being computed and thrown away every turn.

### 2. Account wins on login

| Situation | Outcome |
|---|---|
| Account has **no** preferences | guest preferences are promoted, local copy cleared |
| Account **has** preferences | guest preferences are discarded, silently |

A browser's inferences must never overwrite something a person deliberately set
on a real account. The rejected alternatives: "guest wins" lets one session on a
borrowed laptop rewrite a long-standing profile invisibly; "field-by-field
merge" produces a profile belonging to neither source, which nobody can explain
when it is wrong; "ask on login" puts a modal in front of someone who wanted to
log in.

Promotion therefore only ever happens once per account, on the visit where it
first has none — the new-signup case, which is the common one anyway.

### 3. Durable traits only — `diet` and `spice_level`

These describe the person. `cuisine` and `budget` describe the meal: "something
cheap tonight" is not a claim about how this customer always eats, and storing
it would make one cheap lunch into a permanent budget tier.

Nothing else in `UserPreferencesPayload` is written by this feature.
`cuisines`, `favorite_items` and `budget` remain settable only through the
existing endpoint.

---

## Architecture

**The server infers; the client only stores.**

Re-implementing intent parsing in TypeScript would duplicate a parser that took
real work to get right, and would drift from it. Instead the backend derives
durable traits from the `ExtractedIntent` it already has, returns them, and the
browser is a dumb bucket that hands them back next time.

### Data flow — guest

1. Guest sends a message. Backend resolves `GuestPrincipal` as today.
2. Backend extracts intent (existing), derives durable traits from it.
3. Backend returns `inferred_preferences` on the `meta` and `done` stream
   events, and on the non-streaming response.
4. Client merges into `localStorage["bangkok-bowl-guest-prefs"]`.
5. Next request carries them back as `guest_preferences` on
   `ChatMessageRequest`.
6. Backend applies them — see "Where preferences are applied".

### Data flow — login

7. On successful login, client calls `GET /api/preferences`.
8. If the account has preferences → clear local storage, do nothing else.
9. If it has none and a local copy exists → `PUT /api/preferences` with the
   guest traits, then clear local storage.

Step 9 goes through `upsert_user_preferences`, so the existing chat-cache
invalidation and AI-recommendation refresh come along unchanged. Writing to
`user_preferences` directly from here would silently skip both.

### The trust boundary

`guest_preferences` is honoured **only when `is_guest(principal)` is true.**

For an authenticated user the field is ignored outright — not merged, not used
as a fallback, not logged as a conflict. The database is the only source. This
is what keeps "backend enforces" true while still letting a client carry state
for someone who has no server-side identity.

Blast radius if the field is forged: a guest steers their own ranking toward veg
food. No scope widening, no cross-tenant read, no effect on any account. Both
values pass through the existing `_normalize_diet_value` and
`_normalize_spice_level`, so anything unrecognised becomes `None` rather than
reaching a query.

---

## Where preferences are applied

This section changes existing behaviour for signed-in customers and is the part
most likely to surprise a reviewer.

Today, preferences are loaded only when the message looks personal
(`rag.py:5249`):

```python
uses_personal_context = _message_requests_personal_context(message) or is_follow_up
if uses_personal_context:
    preferences = _fetch_user_preferences(db, user.id)
```

The markers are `"my "`, `"me "`, `"for me"`, `"my usual"`, `"again"`,
`"based on my"`. So a signed-in vegetarian asking **"show me momos"** gets meat
momos: that phrasing does not trip the gate, and their stored diet is never
read.

**`diet` and `spice_level` are promoted to always-applied, independent of the
gate.** They are hard constraints, not personalization flourishes. Serving meat
to a vegetarian is not a missed nicety, it is wrong — and a feature that only
works when the customer happens to phrase a request personally would look broken
in exactly the case it was built for.

Everything else — `favorite_cuisines`, `favorite_items`, `average_budget`,
new-item ranking — stays behind the gate exactly as today.

Cost: one indexed lookup by `user_id` per turn for signed-in customers, where
today it is skipped on impersonal questions. Zero additional cost for guests,
whose preferences arrive in the request body. This is accepted deliberately; the
gate was a cost optimisation and correctness outranks it for these two fields.

---

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `durable_traits_from_intent(intent)` | `ExtractedIntent` → `{diet, spice_level}` or empty. Pure, no I/O. | existing normalizers |
| `guest_preference_profile(payload)` | validated `guest_preferences` → the shape retrieval already consumes | normalizers |
| `ChatMessageRequest.guest_preferences` | transport in | — |
| `inferred_preferences` on chat responses | transport out | — |
| `promoteGuestPreferences()` (client) | the step 7–9 decision on login | `getChatHistory`-style API client |
| `guest-prefs` localStorage module | read / merge / clear, never throws | — |

`durable_traits_from_intent` is pure so the "cuisine and budget are not stored"
rule is testable without a database, a model, or a request.

---

## Error handling

Every failure degrades to "no memory", never to a broken chat or a blocked
login.

| Failure | Behaviour |
|---|---|
| `localStorage` unavailable (private mode) | skip silently; chat works, nothing remembered |
| Stored JSON malformed | discard and clear the key |
| `guest_preferences` fails validation | treat as absent; never 422 the chat |
| `GET /api/preferences` fails on login | keep the local copy, retry next login |
| `PUT /api/preferences` fails on login | keep the local copy, retry next login |

Login never blocks on any of this. A customer who cannot sign in because a
preference promotion failed is a far worse outcome than a customer whose
inferred diet took one more visit to stick.

---

## Testing

`unittest`, matching the house style in `backend/tests/`.

**Backend**

- `durable_traits_from_intent` returns diet and spice from an intent that has
  them; returns empty for an intent that has only cuisine and budget — the rule
  from decision 3, pinned.
- Guest preferences are applied for a `GuestPrincipal`.
- **Guest preferences are ignored for an authenticated `User`,** even when they
  contradict the database row. This is the trust-boundary test and the most
  important one in the set.
- Malformed `guest_preferences` produce a normal reply, not an error.
- `diet` is applied to a signed-in customer's impersonal question ("show me
  momos") — the gate change above.
- Promotion writes only when the account has no preferences; an existing row is
  left untouched.

**Frontend**

- `tsc --noEmit`
- storage module: merge, malformed-value recovery, and clear-on-promotion

---

## Known gaps

Recorded deliberately, not oversights.

**A guest is a browser.** On a shared laptop, one visitor's inferred diet
greets the next. It can never reach a real account — decision 2 prevents that —
but results may lean vegetarian because someone else used the machine. The fix
is a visible, clearable record of what has been remembered, which is a UI
feature and a larger build.

**Nothing is confirmed.** The customer is never told "I've remembered you're
vegetarian" and cannot correct it. Inference from a single sentence can be
wrong — ordering for a friend reads identically to a dietary requirement. The
honest shape is confirm-before-persist; it needs a UI mechanic this spec does
not include.

**Inference quality is unmeasured.** `ExtractedIntent` was built to steer one
retrieval, where a wrong `diet` costs one mediocre answer. Promoting it to a
stored trait raises the cost of the same error. A measurement pass over real
`chat_history` should precede turning promotion on.

---

## Out of scope

- A preferences screen on `frontend-customer`
- Storing `cuisines`, `favorite_items` or `budget` from conversation
- Any change to mobile
- Migrating the eight existing `user_preferences` rows
