# CLAUDE.md

Persistent context for this repo. Read this first; it exists so no session has to
re-derive the map from scratch.

Companion file: `.claude/worklog.md` — dated log of what each session actually
did. Read the last 2-3 entries before starting work, append an entry when done.

---

## What this is

A monorepo for a multi-restaurant ordering platform with two AI surfaces —
customer-facing RAG food chat, and an AI Restaurant Manager for owners — plus a
Marketing Hub for owner-run campaigns and a kitchen order board.

| Path | What it is | Stack |
|---|---|---|
| `backend/` | source of truth for every business rule | FastAPI 0.115, SQLAlchemy 2.0, Postgres + pgvector, Celery + Redis, Ollama (qwen3:8b, nomic-embed-text), Stripe, Firebase Admin |
| `frontend-customer/` | customer web app | TanStack Start + React 19, Tailwind, shadcn/Radix, TanStack Query (SSR) |
| `frontend-admin/` | shared ADMIN + OWNER dashboard | React 19 + Vite, only `lucide-react` + fontsource |
| `frontend-kitchen/` | the kitchen order board (KDS) | React 19 + Vite, TanStack Query, hand-written CSS, `lucide-react` + fontsource |
| `mobile/` | customer app | React Native 0.85 CLI, React Navigation, Firebase phone auth, Stripe RN, Notifee |

---

## Conventions that are easy to violate by accident

**No new dependencies in `frontend-admin`.** It is deliberately
dependency-free at runtime: routing hand-rolled over the History API in
`src/App.tsx` (regex-matched pathnames, a `usePathname` hook), state in React
Context (`src/store/AdminStore.tsx`), styling hand-written CSS in
`src/index.css` (9.5k lines) — no Tailwind, no CSS-in-JS, no component
library. Reaching for react-router, redux or a UI kit breaks the house style
there. **One documented exception: `socket.io-client`** (2026-09-24), because
the kitchen board, customer web and mobile all speak Socket.IO to the same
server and a hand-written Engine.IO client would be a fourth implementation of
a protocol with heartbeats and reconnection to get wrong. It is the only one;
it does not reopen the rule.

**`frontend-customer` no longer follows that rule.** It was replaced wholesale
on 2026-09-13 with a generated TanStack Start app: file-based routing,
Tailwind, shadcn/Radix, TanStack Query, ~60 runtime deps, and SSR via nitro.
The generator's own wrapper around the plugin set was removed on 2026-09-20 —
`vite.config.ts` now composes the plugins itself and explains each one. Read it
before changing it: the order matters, and its `importProtection` override is
what allows `lib/storefront.server.ts` to be imported from a route.
Everything below about hand-written CSS, `AppStore.tsx` and the token files
describes the app that was REPLACED; treat it as history when working in
`frontend-customer`, and as current when working in `frontend-admin`.

**Comments explain *why*, not what.** See `backend/app/config/settings.py` — it
reads like a lab notebook: measured timings, why `ollama_think_mode` is
per-deployment, why revenue diagnostics exclude `CANCELLED`. Match that density
when touching backend code. Terse "what" comments read as foreign here.

**The LLM never invents data.** Every AI path retrieves rows from Postgres
first, filters them by business rules, and only then lets the model phrase an
answer over that fixed set. The narrator's numbers are verified back against the
fact pack (`ai_manager_number_tolerance`). Every LLM path has a deterministic
template fallback, and every AI feature flag defaults **off**.

**Backend enforces, UI only hides.** Role filtering, branch scoping, payment
method availability, slot validity and report scope are all re-validated
server-side. Never treat a UI guard as the rule.

**An ADMIN has no implicit restaurant; an OWNER may not name one.**
`resolve_insights_scope` requires `restaurant_id` from an ADMIN and refuses it
from an OWNER, and every insights and marketing route takes it as an optional
query parameter for exactly that reason. `frontend-admin` is one dashboard for
both roles, so any screen reading tenant-scoped data needs an admin restaurant
picker — `AIManagerPage` and `MarketingPage` both have one, persisted in
localStorage. Omitting it is not a subtle failure: every call comes back
`400 restaurant_id is required for admin insights requests`, and the screen
renders it as "this feature is broken".

**A disabled button says why, in the button or beside it.** The cart screen
has always done this — "Closed right now", "Minimum ₹150 to order" — and the
checkout did not, which produced a complete-looking page with two dead Pay
buttons for any restaurant settling through Razorpay alone. The rule lives in
`frontend-customer/src/lib/pay-gate.ts` and returns a REASON rather than a
boolean, ordered by what the customer should do next; `canSubmit` is derived
from it. There are two Pay buttons — the sticky summary and the phone bar — so
a gate written inside a component is one the other copy cannot read. On a phone
the reason goes ABOVE the row, never inside the button: it is `flex-1` at
393px, so a sentence there breaks the 44px touch floor `e2e/mobile-layout.
spec.ts` enforces.

**A payment under way is persisted, and resumed only after asking the server.**
`src/lib/pending-payment.ts`. Stripe is handed a `returnUrl` and redirects the
browser itself; Razorpay is a modal with no redirect, so its `onPaid` must
navigate — `leaveForOrder` — or a successful payment leaves the customer on a
checkout whose cart is now empty, which renders as the address step. The stored
value is never trusted: `canResumePayment` is deliberately STRICTER than the
order page's "confirming payment" test, because `PAYMENT_PENDING` with
`payment_status: PAID` is the gap between a settled payment and the status
advancing, and reopening a gateway there would charge somebody twice. The
persist effect must not clear on null — `pending` starts null on the very load
that is about to restore it, which is the same race `bangkok-store.tsx` guards
with `hydrated`.

**A delivery order needs a POINT, and a saved address is one.** The backend
refuses a delivery order from a checkout that carries no coordinates
(`orders.py`, `if known_drop is None and require_payment_validation`) — a typed
line geocodes to a neighbourhood, which prices the wrong trip and sends a rider
to the wrong place. There are two ways to satisfy it, and both must work:
`latitude`/`longitude` from the autocomplete, or `saved_address_id`, whose row
carries the rooftop it was geocoded to when it was saved. The quote endpoint
read the second from the start and the order path did not, so the two
disagreed about the same address — priced, then refused. If you add a third
client, send one of the two or it cannot place a delivery order. On the
storefront side `pointFromSaved` is the only way the point gets set, from both
the prefill effect and the picker, so they cannot drift.

**Saved addresses are de-duplicated on the SERVER.**
`_matching_saved_address` in `services/profile.py` fingerprints the six
address parts, case-folded and whitespace-collapsed, and `create_user_saved_
address` returns the row you already have rather than inserting a second. The
label and the phone number are not part of the fingerprint: one doorstep saved
as HOME and as WORK is one doorstep. `isSameAddress` in
`frontend-customer/src/lib/delivery-address.ts` looks like the guard and is
not — it compares against a cached query, so the first order writes the row
and the second order the same evening still sees no match. That is how a
duplicate got written. Client-side checks there only save a request.

**Half-and-half is a group flag, not an item flag.** Only a customization group
the owner marked `supports_halves` may be split, a half costs half the listed
extra, a group is split OR the same all over (never both), and a lone half is
refused — both sides must be described. The owner's maximum counts on EACH half,
not across the pair. The rules live in three places that must agree, because a
disagreement means the customer sees one price and is charged another:
`backend/app/services/menu_item_customizations.py`,
`frontend-customer/src/lib/customization.ts` and
`mobile/src/utils/menuItemCustomization.ts`.

**Tests are `unittest`, not pytest.** 42 files in `backend/tests/`, each
inserting `backend/` on `sys.path` itself. Many encode a question that was once
answered *wrong* — read the module docstring before changing an assertion.

**Typography is per tenant, and resolved on the server.** The backend offers
five faces (`app/services/app_branding.py`); the storefront serves whichever
one the restaurant picked. `src/lib/fonts.ts` maps `branding.font_family` to a
family and a `@fontsource` import, and `routes/__root.tsx` writes the tokens
into the document head during SSR — so the first byte already carries the
tenant's face rather than swapping to it after hydration. `src/lib/fonts.test.ts`
guards the two rules that fail silently: a display serif must never become the
body face (DM Serif Display at 13px in a form label), and the default here must
match `DEFAULT_FONT_ID` in the backend allowlist, or a restaurant that changed
nothing sees its storefront change.

This section used to describe `src/styles/fonts.css`, `public/fonts/` and a
self-hosted Inter. None of those exist; neither does `src/styles/`,
`src/index.css`, `src/theme/applyTheme.ts`, `themeBase.ts`, `home.css`,
`screens.css` or `tokens.test.ts`. They were the app that was REPLACED on
2026-09-13 and the description outlived it by three weeks.

**Know which file owns which token.** `frontend-shared/tokens.css` is the
source for both web apps: colour, the type scale (`--fs-micro` through
`--fs-display-xl`), radii, shadows, spacing (`--space-1`..`--space-20`),
motion and control heights. `frontend-customer/src/styles.css` holds the
Tailwind v4 `@theme inline` bridge plus the storefront's own component
classes; `src/polish.css` is the later layer on top of it. There is no
PostCSS step and no `tailwind.config` — all configuration is inside
`styles.css`.

**The admin panel has three more scales, and a ratchet.** Weight (`--fw-regular`
500, `--fw-medium` 600, `--fw-strong` 700, `--fw-heavy` 800 — the last for a
page title and a stat figure only), role spacing (`--pad-*`, `--gap-*`) and
role radius (`--radius-control`, `--radius-card`, `--radius-modal`) live in
`frontend-admin/src/index.css`, written to be promoted into the shared file.
`src/styleBudget.test.ts` counts off-token padding, gap, weight and colour in
`legacy.css` per class family; a number there may be lowered and never raised.
Four families are deliberately not zero, each with its reason beside its
number: marketing (`mkt`, `hub`) for its scoped token definitions and the
phone and message mock-ups, the branding phone preview (`ph`), which draws
another app, and one white tick on a brand swatch (`bp`).

**`--on-primary` is the ink for a BRAND fill and nothing else.** It inverts in
dark mode, so it is wrong on any ground that does not flip with the theme: a
mock-up screen, a preset swatch, a dark-mode hairline. Replacing a literal
white with it broke all three at once; `styleBudget.test.ts` now names them.

**Colour is written at runtime and beats the stylesheet.** `src/lib/theme.ts`
(`applyBrandColor`) sets `--primary`, `--primary-soft`, `--on-primary` and the
`--placeholder-*` tiles on the root element from `/app-config`, so a tenant's
accent overrides whatever the CSS declares. Editing those values in CSS appears
to do nothing. Anything built around a warm accent breaks for the Teal, Indigo,
Forest and Slate presets — warmth has to come from the neutrals, the
photography and the spacing.

**The type scale tops out low.** `--fs-display-lg` is 36px and `--fs-display`
is 28px, because the scale was built for the operator panel where that is a
page title. A storefront section heading set at `--fs-display-sm` reads small;
the brand page's lead uses a `clamp()` past the top of the scale deliberately.

---

## Domain model

Two-level restaurants:

- `Restaurant` — brand identity: discovery, ownership, branding.
- `RestaurantLocation` — the orderable branch. Menu items, orders, generated
  combos, payment methods, fulfillment toggles and weekly slots all hang off the
  **location**, not the brand.
- Cart scope is `restaurant + location`, so two branches cannot mix in one cart.

Identity:

- `AppClient` scopes customers. The same phone in the Marketplace app and in a
  single-restaurant app are **two separate accounts**; JWTs are bound to their
  app. See `docs/per-app-identity.md`.
- Roles: `ADMIN`, `OWNER`, `KITCHEN` (all platform staff, `app_client_id`
  NULL), `CUSTOMER`. One owner to exactly one restaurant. The role/app-client
  split is a DB CHECK (`ck_users_app_client_scope_matches_role`), and customer
  uniqueness lives in partial indexes defined in migration `0036`, not in the
  SQLAlchemy model. Those platform-uniqueness indexes name the staff roles
  explicitly — `0071` had to widen them, or a KITCHEN account would have had
  no uniqueness on its email at all.

Orders: `PAYMENT_PENDING -> PLACED -> ACCEPTED -> PREPARING -> OUT_FOR_DELIVERY
-> DELIVERED`, strictly linear, plus `CANCELLED`. There is no human cancellation
path — every cancellation is system-derived (`OrderCancellationReason`).

All enums live in one place: `backend/app/models/enums.py`. Read it early; it is
the fastest way to understand the domain.

---

## The AI layers

**1. Customer RAG chat** — `backend/app/services/rag.py` (~5.5k lines, the
single biggest file). Order of operations: lightweight deterministic intent
parsing, then Qwen intent extraction only when that is unreliable, then keyword
and/or pgvector retrieval, then business-rule filtering, then Qwen phrases the
answer — or is skipped entirely when grounded keyword matches already suffice —
with a DB-backed fallback if the model is slow. Session memory and response
cache in Redis. Combo-aware and new-item-aware. Deep dive:
`backend/docs/chat-rag-workflow.md`.

**2. AI Restaurant Manager** — `backend/app/services/insights/`. Three tiers:
deterministic rules, then an LLM tool planner over 28 read-only tools, then
honest refusal. `analyst/` is a separate LLM loop behind **three** flags on
purpose (`enable_ai_manager_analyst`, `ai_manager_analyst_shadow_mode`,
`enable_ai_manager_ai_findings`) — running it, storing its output and showing it
to an owner are different decisions. Action proposals never spend money without
an explicit approval call. Full walkthrough: `AI_RESTAURANT_MANAGER_WORKFLOW.md`.

**3. Personalization** — `personalized_offers.py`, `recommendations.py`,
`ai_recommendations.py`, `generated_combos.py`. Scoring is backend-driven;
labels come from scoring, never handcrafted in a client.

---

## The Marketing Hub

Owner-facing campaign tooling in `backend/app/services/marketing/` and
`frontend-admin` (`MarketingPage`, `CampaignEditorPage`, `CampaignDetailPage`,
`components/marketing/`, `services/marketing/`). P1 is complete; see
`docs/MARKETING_HUB_AUDIT_AND_PLAN.md` for the slice-by-slice record.

**The Create Campaign flow is channel-first, one channel per campaign.** Six
questions — **Where → Why → Who → Words → When → Ready** — and the answer to
"where" changes the *shape* of the rest, not just its labels. Everything that
differs per channel is declared in
`frontend-admin/src/components/marketing/channels.ts`: field limits, whether
there is a headline at all, whether merge fields mean anything, whether a
photo is required, SMS segment length and per-message cost, which goals the
channel can honestly deliver, the button verb, and `availability` — the one
place that says push is still the only channel with a dispatcher. Reach for a
`channel === 'PUSH' ?` branch in a component and you have put a rule somewhere
nothing else can read it.

The split that everything turns on is **DIRECT vs SOCIAL**:

- **DIRECT** (push, WhatsApp, SMS, email) — the owner picks *people*. Consent
  applies, reach is countable, recipient rows are written, attribution is
  per recipient. Everything below describes this case.
- **SOCIAL** (Instagram, Facebook) — the owner picks *nobody*. There is no
  consent to check and no recipient row to write, so the attribution rule
  below **does not apply at all**; a public post is attributed by a promo
  code. Do not add a segment picker, a minimum-audience block or a reach
  count to a social campaign — each one would be a number with nothing
  behind it.

A channel that cannot send yet is never a dead end: the whole campaign can be
built and saved, and the refusal happens at the send button. The draft holds
`channel`; the wire still carries `channels: [channel]`, the existing column
untouched, and reads go through `primaryChannel()`. Channel-specific content
(photo, hashtags, promo code, boost budget) rides in `content.extra`, a
size-capped passthrough stored **namespaced** under `content_extra` in
`data_payload` — a column shared with the transactional push path, so it is
merged into, never assigned over.

**Whether a channel can send is a fact about the restaurant, never a
constant.** `restaurant_channel_connections` holds it, `services/marketing/
connections.py` answers it, and both the picker and the dispatcher ask the
same function so they cannot disagree. Absence of a row *is* the
not-connected state, so there is no NOT_CONNECTED status to fall out of step
with it. Push is the one channel with no row at all — its credentials are the
platform's shared Firebase account, and giving it a connection would let an
owner disconnect the channel their order notifications ride on. `config` is
returned to the owner; `credentials` is returned to nobody, and a re-save
merges so a form that cannot display a token does not blank it.

**`dispatch.py` knows nothing about how any channel delivers.** It owns what
every send shares — recompute the audience, write a row per customer, group
by rendered copy, commit progress per batch, decide the terminal status — and
asks `providers.provider_for` for something that can deliver. Adding a channel
is a provider plus one row in that factory. Every provider raises
`ProviderError` with a sentence written for the owner, because that string
lands in `campaign.last_error` and then on their screen.

**A social campaign takes a different function, not a different branch.**
`publish_campaign` has no audience, no consent check, no recipient rows and no
frequency cap. Running a post through the direct path with the people-shaped
parts skipped would report it as a send with an audience of zero.

**The frequency cap counts recipient rows, and STOP is honoured.** Both were
promises the product made and did not keep until 2026-09-21. The cap read
`push_notification_events` of type SENT/DELIVERED, which nothing writes — only
`engagement.py` writes that table, and only OPENED/CLICKED/UNSUBSCRIBED — so
it suppressed nobody while the UI said otherwise. It now reads
`push_notification_campaign_recipients`, counts only rows that actually
reached someone, and is counted across channels rather than per channel. STOP
and START arrive on the WhatsApp webhook (checked **before** the allowlist,
the our-number test and the assistant) and on `POST /marketing/sms/inbound`
(shared secret, unset means refuse everything). A phone number identifies a
person, so every `AppClient`-scoped account on it is opted out.

**Spend caps are enforced through the reach estimate, not the UI.** Per
campaign and per calendar month, raised as BLOCK notices by `estimate_reach`
— so the builder and the dispatcher get the same answer from one rule, and
dispatch re-runs it at send time. Spend is derived from channel plus
`sent_count` plus message parts, never stored, so it cannot drift from what
went out.

**Social attribution is a promo code, and it is a weaker claim.** A post is
seen by people this platform has no identity for, so `orders.
marketing_promo_code` — typed at checkout in both customer apps, priced on by
nothing — is the only join available. It misses everyone who saw the post and
ordered without the code, and it has no honest baseline, so the report carries
`baseline_orders: 0` and the UI says what the number measures rather than
placing it beside a push campaign's as if they were comparable.

Five rules it is built around, each of which was a bug first:

- **Sending is behind `enable_marketing_dispatch`, which defaults off.** With it
  off the whole path runs against the real audience and writes real recipient
  rows — a dry run an owner can inspect — and Firebase is never called.
  Test-send honours the same flag, so no path escapes it. This is the same
  posture as the AI flags, for the same reason: a campaign reaches a lock screen
  unprompted and cannot be recalled.
- **The audience is recomputed at send, never trusted from the draft.** A
  campaign scheduled Tuesday for Friday goes to Friday's segment; people opt out
  and uninstall in between.
- **Attribution reads recipient rows, never the segment.** Segment membership is
  recomputed continuously — by report time, "lapsed regulars" no longer contains
  the people the campaign won back. The window is measured per recipient from
  *their own* send instant, because a large send spans minutes.
- **The claim is the concurrency control.** `claim_for_sending` moves the row to
  SENDING and commits immediately; the second caller is refused. SENDING leads
  only to SENT or FAILED, both written by the dispatcher — which is why
  `mark_send_failed` must survive a session dirtied by the error it is handling,
  or the campaign is stranded there forever.
- **Marketing never touches the transactional order push.** It shares
  `_get_firebase_app` and `_should_deactivate_token` from
  `services/notifications.py` and nothing else. That module 404s an empty
  audience and raises `HTTPException` mid-dispatch — both wrong for a background
  send, and bending it to serve both would risk order notifications.

Consent is **opt-out**: `users.marketing_opt_in` defaults true and existing
customers were backfilled true. `marketing_opt_in_changed_at` stays null on that
backfill on purpose — null means "never expressed a preference", which is a
different fact from an explicit opt-in and the first thing a consent audit asks
for.

---

## The kitchen board

`frontend-kitchen/` is the screen a kitchen works from, and `UserRole.KITCHEN`
(migration `0071_kitchen_staff`) is the login it runs on. Both exist because
advancing an order was `require_owner`, so the only way to put a board in a
kitchen was to leave the owner signed in on it — one token that also edits the
menu, spends marketing budget and reads revenue, on a tablet on a wall.

**`resolve_order_board_scope` is the rule, and it is the only rule.** One
function in `services/auth.py` answers "which restaurant, which branch" for all
three board roles, and `GET /orders`, `GET /orders/{id}` and `PATCH
/orders/{id}/status` all go through it — so a cook can never be shown an order
they may not advance, or advance one they were never shown. An ADMIN names a
restaurant or gets all of them, an OWNER gets their own, a KITCHEN account gets
what is stored on its row. A requested value may only ever NARROW a scope;
asking outside it is 403, never silently ignored.

**The assignment is two columns on `users`, and the database enforces the
pairing.** `staff_restaurant_id` and `staff_restaurant_location_id`, with
`ck_users_kitchen_assignment` making it exhaustive — a KITCHEN row without a
restaurant is rejected, and any other role carrying either column is too. The
branch is tied to the restaurant by a COMPOSITE foreign key onto
`(id, restaurant_id)`, not a plain one onto `id`, so a cook pinned to somebody
else's branch is unrepresentable rather than merely unlikely. A NULL location
means every branch of that restaurant and is a real answer, not a missing one.
All of it is mirrored in `__table_args__` as well as in the migration, because
the test suites build from `create_all` and never run a migration.

**Out-of-scope orders are 404, not 403.** The scope narrows the query rather
than being checked after it, so a cook learns nothing about an order that is
not theirs — including whether it exists.

**Nothing else creates a kitchen account.** `POST /kitchen-staff` is the only
route that does; the platform's one other staff-creating path is
`POST /restaurants`, which makes a single OWNER beside a new restaurant. A
KITCHEN account cannot create another, and deactivating or re-branching one
bumps `token_version`, or the tablet keeps working until its token expires.
`PATCH /admin/users/{id}` — the Users page's own deactivate — now bumps it
too, for any role: it reaches the same row by another door, and only the
kitchen route was ending sessions.

**The owner-facing screen is `KitchenStaffPage`** (`/kitchen-staff`, both
staff roles). Add, rename, reassign a branch, activate/deactivate — and no
delete, because `order_status_events.actor_user_id` points at these rows and
removing one would take its audit trail with it. The email and password are
not editable after creation, because the backend refuses both: re-pointing a
live login at a different person is how a revoked account quietly comes back.
It reuses `useMarketingScope` for the admin restaurant picker rather than
growing a fourth copy of that logic, and the form rules live in
`services/kitchenStaff.ts` so they can be tested without rendering a form.

**A KITCHEN account shows up in the Users list.** `/admin/users` returns every
account to an ADMIN, so `ROLE_META` in `AdminUsersPage` has to be exhaustive —
a missing role is not a cosmetic gap, it is `meta.icon` on `undefined` and the
whole page goes down. That is why `UserRole` in `frontend-admin/src/types` now
includes `KITCHEN` even though no route in the panel admits that role.

**`OrderEventActor.KITCHEN` exists so the audit log stays honest.** Without it
`actor_for_user` falls through to SYSTEM and every advance a cook makes reads
as something the platform did by itself.

**Order history is by DELIVERED time, from the event log.** The board's
"Completed" overlay reads `GET /orders?order_status=DELIVERED&completed_from=`
sorted `completed_at:desc`; both come from `order_status_events`, because
`orders` has no completion column and `updated_at` moves on a later refund.
Today by default, search spans all dates. It is an overlay on purpose — the
board stays mounted so a cook looking something up still hears the next
ticket.

Client side: four queries, one per column, `refetchIntervalInBackground` on
because a wall-mounted board is never focused. A Socket.IO push (see "Realtime"
below) invalidates them the moment an order moves; the poll is the safety net —
30s while the socket is live, 6s the moment it is not. The header says Live /
Polling / Not updating accordingly. The rules worth testing are pure and live
in `src/lib/board.ts` and `src/lib/realtime.ts`.

---

## Realtime (Socket.IO)

`backend/app/services/realtime/` + one `realtime.ts` client per app (kitchen
`src/lib`, admin `src/services`, customer `src/lib`, mobile `src/services`,
kept identical in behaviour). Behind **`enable_realtime`, default off** — with
it off every handshake is refused with `realtime_disabled`, the clients stop
retrying and poll exactly as before.

**A push is a hint, never data.** `order:updated` carries an order id and its
new status, nothing else; every client reacts by refetching over REST. So the
socket cannot show anybody a row the REST scope would not, and REST stays the
only source of truth.

**Rooms ARE the scope, chosen by `resolve_order_board_scope`.** A staff socket
joins exactly one room — `location:{id}` (pinned cook), `restaurant:{id}`
(owner, unpinned cook), `admin:all` (admin with no restaurant). A customer
joins `user:{id}` only. An order event goes to its branch, restaurant,
`admin:all` and customer rooms. A pinned cook must never sit in the restaurant
room, or they hear every branch.

**Every transition is emitted from one line**, in `record_order_status_event`,
and only **after commit** (`realtime/outbox.py`: queued on `session.info`,
flushed by a class-level `after_commit` listener, dropped on
`after_soft_rollback` — `after_rollback` was tried and leaked a queue into the
next commit, see `test_realtime`). A Celery worker emits through a write-only
`RedisManager`; the API processes fan out through `AsyncRedisManager`. An emit
failure is logged and swallowed — a push must never cost an order.

**WebSocket transport only, on both ends.** Long-polling needs sticky sessions
and gunicorn has none between workers. Mounted INSIDE FastAPI at
`/api/socket.io` so `app.main:app` and every `TestClient(app)` test are
unchanged. The Origin check is engine.io's, fed this backend's own CORS rule.

**The handshake is `get_current_user`** (`_get_user_from_token` itself), with
the app identity in the `auth` payload — `app_host` from a storefront,
`bundle_id`/`platform` from mobile — because a browser cannot set
`X-Forwarded-Host` on a WebSocket. Refusal reasons are a contract the clients
branch on: `auth` signs out, `realtime_disabled`/`forbidden` stop retrying,
anything else retries.

**Revocation is immediate and has a backstop.** The four places that bump
`token_version` also queue `session:revoked`; after commit it is emitted AND
published on `{realtime_redis_channel}:control`, which every API process
listens to and disconnects its own sockets for that account — a write-only
manager cannot disconnect anything (verified). A per-process sweep
(`realtime_session_sweep_seconds`) catches expired tokens and lost messages.

**A reconnect always refetches.** Redis pub/sub keeps nothing for a
disconnected client, so the client reports a (re)connect as "anything may have
changed" (`onChange(null)`).

---

## Where to make changes

- business rules -> `backend/app/services/`
- marketing campaigns -> `backend/app/services/marketing/` +
  `frontend-admin/src/services/marketing/`
- routes and contracts -> `backend/app/api/` + `backend/app/schemas/`
- schema -> `backend/app/models/` + `backend/alembic/versions/`
- admin UI -> `frontend-admin/src/pages/`, `frontend-admin/src/components/`
- kitchen board -> `frontend-kitchen/src/` (rules in `src/lib/board.ts`)
- customer web UI -> `frontend-customer/src/pages/`, `.../components/`
- mobile UI -> `mobile/src/screens/`, `.../components/`, `.../navigation/`

---

## Commands

```bash
# backend (from backend/)
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
alembic upgrade head
python seed.py
celery -A app.config.celery:celery_app worker --loglevel=info -Q embeddings,notifications,default,analytics
# On Windows add: --pool=solo --logfile logs/celery.log   (see the note below)
python -m unittest discover -s tests      # tests are unittest-based, not pytest
python -m compileall app alembic          # the repo's usual syntax check

# web (from frontend-admin/, frontend-customer/ or frontend-kitchen/)
npm run dev | npm run build | npm run lint

# mobile (from mobile/)
npm run start | npm run android | npm run ios
./node_modules/.bin/tsc --noEmit
npm run lint | npm run test
```

Verification this repo actually uses: `compileall` for backend, `npm run build`
for both webs, `tsc --noEmit` for mobile.

`frontend-admin`, `frontend-customer` and `frontend-kitchen` all have vitest
suites (`npm run test`), and `mobile` has jest (`npm run test`) — worth running
when touching their logic, since none of them is covered by a build alone. The
backend suites need the local Postgres up: each creates and drops its own
throwaway database and skips itself entirely if it cannot connect, so a green
run with Postgres down means nothing ran.

---

## Deployment

- `docker-compose.yml` — postgres, redis, ollama (+ model pull), migrate, api,
  four queue-specific Celery workers (default / analytics / embeddings /
  notifications), beat, both frontends, nginx.
- `render.yaml` — managed Postgres + keyvalue + api / worker / beat.
  `DATABASE_URL` is injected by Render and **overrides** the discrete
  `POSTGRES_*` settings, so one image runs unchanged on Render and under compose.
- Generation and embeddings are configured separately on purpose: Ollama Cloud
  serves no embedding route, so embeddings can stay local while generation is
  remote (`ollama_embedding_base_url`).

---

## Running it locally on this machine

**This is a macOS machine** at `/Users/imac/data/restaurant-rag`. Verified
2026-09-19. The Windows notes that used to fill this section are kept at the end
under "The Windows checkout" — they describe a different machine, and following
them here (`.venv/Scripts/`, `psql.exe`, `F:\`) wastes a session.

No Docker. Redis and Ollama both run; Postgres runs but the app does not use it
by default.

- **Python**: a 3.13.3 venv lives at `backend/.venv`. Always invoke
  `backend/.venv/bin/python`, never bare `python`.
- **Ollama**: installed and running on `localhost:11434` with `qwen3:8b`,
  `nomic-embed-text`, `qwen2.5:7b-instruct` and `qwen2.5:3b-instruct`. The
  backend warms the embedding model at startup — "Embedding model warm:
  ollama:nomic-embed-text:768" in the log means it reached it. So generated
  prose and pgvector retrieval both work here, unlike on the Windows box.
  `enable_ordering_agent` is on, so the customer chat and the WhatsApp agent
  answer for real rather than falling through to templates — a turn takes
  roughly 3-8 seconds, which is why several sessions mistook a slow turn for a
  hang. `backend/scripts/dryrun_whatsapp.py` replays scripted conversations
  through the whole live path with only Meta's send stubbed, and is the fastest
  way to see what a customer actually gets;
  `backend/scripts/whatsapp_healthcheck.py` checks the Meta half read-only
  (token, number, quality) without messaging anybody.
- **Redis**: Homebrew service `redis`, `redis-cli ping` → PONG. Chat session
  memory, the response cache and Celery all work.
- **Celery**: no worker or beat runs by default. Tasks enqueue to Redis and sit
  there — a marketing send returns SENDING and never progresses until you start
  a worker on the `notifications` queue.
  - **Use `--pool=solo` (or `--pool=threads`) on this machine.** The default
    prefork pool **segfaults** the moment a task touches Firebase:
    `WorkerLostError: Worker exited prematurely: signal 11 (SIGSEGV)`. Firebase
    Admin pulls in gRPC, and macOS cannot safely `fork()` a process that has
    initialised it. The campaign is left in SENDING with no recipient rows,
    which looks exactly like a hung send rather than a crashed one.
    `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` is the other lever. Linux — and
    so `docker-compose` and Render — is unaffected, which is why the documented
    worker command has no pool flag.
- **Database**: the app points at **Supabase** (project `restaurant-rag`, ref
  `eeorvcsfpndaovhvgyom`, org Foodie, ap-south-1), via `DATABASE_URL` in
  `backend/.env`. 48 public tables. To confirm what a running server is actually
  talking to, look at its established connections rather than the file: an
  ap-south-1 address on 5432 is Supabase.
  - **`alembic` works against it.** It did not before 2026-09-21:
    `alembic current` failed with *"Can't locate revision
    '0067_restaurant_payment_accounts'"*, because someone migrated the shared
    database from work never pushed here. That lineage was rebuilt by
    introspection as a bridge, and then on 2026-09-22 the V2 merge brought the
    real migrations and the bridge was deleted — so the chain here is now the
    original one rather than a reconstruction of it. See "Known rough edges"
    below before touching migrations.
  - Use the **session pooler** host `aws-0-ap-south-1.pooler.supabase.com:5432`,
    not `db.<ref>.supabase.co`. The direct host is IPv6-only, and repeated failed
    auth there got this machine's IPv6 address **banned** by Supabase (dashboard
    → Database → Settings → Network bans → Unban IP). Do not retry auth in a loop.
  - The pooler username is `postgres.<project-ref>`, not `postgres`; the plain
    form answers `ENOTFOUND tenant/user`.
  - Port 5432 (session mode) only. psycopg 3 uses prepared statements, which the
    transaction pooler on 6543 breaks, failing Alembic DDL.
  - `POSTGRES_*` in `.env` are the LOCAL fallback and are ignored entirely while
    `DATABASE_URL` is set. Putting a Supabase password in `POSTGRES_PASSWORD`
    does nothing — that mistake cost four debugging rounds.
  - **RLS is ON for 45 of the 48 public tables, with no policies.** Supabase grants
    `anon` and `authenticated` full DML including TRUNCATE on everything in
    `public`, and the anon key is published inside client apps — so RLS off
    meant anyone with that key could read every user and order and empty the
    tables. This app never uses PostgREST: the FastAPI backend owns auth and
    every business rule, and connects as `postgres`, which owns the tables and
    therefore bypasses RLS. Deny-by-default is correct here; do not disable it.
    If one table ever needs direct client access, add a policy for that table.
    NOT yet reproducible for the tables that predate `0070` — applied to this
    project only, with no Alembic migration, so a fresh environment starts
    open for them. See the worklog follow-up. Because it was applied by hand,
    **every table added before 0070 starts without it**: `app_client_domains`,
    `restaurant_capabilities`, `restaurant_payment_accounts` and
    `app_client_push_credentials` are open right now. `0070` broke that
    pattern and enables RLS on `restaurant_channel_connections` in the
    migration itself — confirmed on for real on Supabase after the deploy,
    and the shape every new table should follow, because it is the only way
    a fresh environment comes up closed. Turn RLS on for any table you add
    (`ALTER TABLE public.<t> ENABLE ROW LEVEL SECURITY`) and check the list
    after a migration.
  - The Supabase MCP role is **not** superuser: `ALTER USER postgres WITH
    PASSWORD` fails with "permission denied to alter role". Password changes
    must go through the dashboard.
- **Local Postgres (fallback, and where the tests run)**: PostgreSQL 16.13 via
  Homebrew service `postgresql@16`, on 127.0.0.1:5432 as `postgres/postgres`,
  `psql` on PATH, pgvector available. Database `restaurant_rag` exists but is
  only at `0049` — fifteen revisions behind — so pointing the app at it needs
  `alembic upgrade head` first. The backend test suites do not use it directly:
  each creates and drops its own throwaway database from
  `Base.metadata.create_all`, which is why they need this server running but
  never touch `restaurant_rag`.
- Every op in `services/cache.py` catches `RedisError` and degrades to a miss,
  so the API survives Redis going away.

Start the three services, each in its own shell:

```bash
cd backend && ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
cd frontend-customer && npm run dev -- --port 5173 --strictPort
cd frontend-admin && npm run dev -- --port 5174 --strictPort
cd frontend-kitchen && npm run dev            # 5175, pinned in vite.config.ts
```

The ports are not arbitrary: all three web apps hardcode
`http://localhost:8000/api` for dev, and 5173/5174/5175 are in the backend's
default CORS list. **`backend/.env` overrides that default**, so a new port has
to be added in both places — which is how 5175 was missed the first time. Seeded
logins are `admin@example.com` and `customer1@example.com`, password
`password123`.

`--host 0.0.0.0`, not `127.0.0.1`, because `mobile/src/config/api.ts` points at
this machine's LAN address. `BACKEND_CORS_ORIGIN_REGEX` in `backend/.env` allows
the private ranges on any port, so a phone or a second laptop is not a CORS
miss — a regex rather than a pinned IP, which would go stale with the DHCP
lease.

**Per-app identity bites here.** Seeded accounts belong to the `marketplace` app
client. The mobile app's bundle is `com.quickbite.bangkokbowl`, a different app
client, so `customer1@example.com` does **not** exist there — and mobile logs in
by phone + password, not email. Register in the app rather than hunting for a
seeded login that cannot work.

### The Windows checkout

Kept because the notes are hard-won, not because they apply here.

- **Python**: default `python` was 3.10.11 and cannot run this backend
  (`StrEnum` needs 3.11+); a 3.11.9 venv at `backend/.venv`, invoked as
  `backend/.venv/Scripts/python.exe`.
- **Postgres**: PostgreSQL 15 as service `postgresql-x64-15` from
  `C:\Program Files\PostgreSQL\15`; `bin/` not on PATH, so call `psql.exe` by
  full path.
- **pgvector**: 0.8.0, built from source with MSVC 14.50 against PG15. To
  rebuild: clone `pgvector v0.8.0`, run `vcvars64.bat`, set `PGROOT` to the PG15
  directory, `nmake /F Makefile.win`, then copy `vector.dll`, `vector.control`
  and `sql/vector--*.sql` into `lib/` and `share/extension/` **elevated** — the
  install step needs admin rights and otherwise fails with "Access is denied".
- **Redis**: the Windows service `Redis` from a portable build at
  `C:\redis-portable` (Redis 5.0.14.1, the tporadowski port — open source,
  unlike Memurai whose free tier is development-only). Memurai was tried first
  and its MSI fails with 1603: the custom action
  `ca_SilentCheckIfPortIsAvailable` errors even though 6379 is free. Do not
  spend time on it.
- **Celery**: `--pool=solo` there too, for a different reason than on macOS —
  the prefork pool's children crash-loop on `PermissionError: [WinError 5]`
  from `billiard/synchronize.py` while the parent keeps acking tasks, so
  nothing runs and nothing is logged. `app/config/celery.py` forces
  `worker_pool="solo"` on win32; Docker and Render are Linux and keep prefork.
  - **Always start the worker with `--logfile`.** This cost an afternoon: a
    WhatsApp message arrived, the webhook returned 200, the task left the
    queue and no reply was sent — and `inspect.ping`, `active_queues` and the
    queue depth all said the worker was healthy and idle. The traceback was
    going to a hidden window's stderr.
- **Ollama**: not installed there at first, so every AI path fell back to
  deterministic templates — the apps worked, generated prose did not. It was
  installed later (`qwen3:8b` + `nomic-embed-text`), which is worth knowing
  because several sessions tested the AI paths by scripting the model seam
  instead of running it.
- Git Bash: use forward slashes; working directory `F:\restaurant-rag`.

## Known rough edges in this checkout

- **The reconstructed 0065-0068 are gone: V2 brought the real ones on
  2026-09-22.** The reconstruction note used to end "if the real 0065-0068
  are ever pushed, delete the reconstructions and keep theirs". That happened,
  and that is what was done.

  The shared Supabase database carried three tables and six columns from a
  lineage that existed in no branch here, and the stamp named a revision no
  file defined, so `alembic current` and `alembic upgrade` both failed
  outright. On 2026-09-21 that lineage was rebuilt by introspection as bridge
  revisions so the chain could at least be walked. On 2026-09-22 the V2 merge
  brought the originals, and the bridges were deleted:

  | deleted (reconstruction) | replaced by (V2, real) |
  |---|---|
  | `0066_restaurant_capabilities` | `0066_restaurant_capabilities` |
  | `0067_restaurant_payment_accounts` | `0067_restaurant_payment_accounts` |
  | `0068_payment_transaction_payment_id` | `0068_payment_transaction_payment_id` |
  | `0068b_orphan_columns` | `0063_app_client_lifecycle_note`, `0064_restaurant_storefront`, `0065_restaurant_currency` |
  | `0065_app_client_push_credentials` | nothing — `0032_app_clients` already created that table |

  That last row is the one worth remembering: the introspection read
  `app_client_push_credentials` as part of the unpushed lineage, but `0032`
  has created it all along. A table being present in the database is not
  evidence that the migration you are looking at is the one that made it.

  V2's `0068` is also strictly better than the bridge it replaced — it adds
  `ix_payment_transactions_provider_payment_id`, which a refund webhook needs
  to match a payment back to an order.

  **The chain is now single-headed and linear**, 70 revisions from
  `0001_initial_schema` to `0069_order_deliveries`, with the two branches
  joined at `0062_app_client_domains`:

  ```
  0062_app_client_domains
    -> 0063_app_client_lifecycle_note -> 0064_restaurant_storefront
    -> 0065_restaurant_currency -> 0066_restaurant_capabilities
    -> 0067_restaurant_payment_accounts -> 0068_payment_transaction_payment_id
    -> 0063_marketing_consent -> 0064_marketing_campaign_fields
    -> 0069_campaign_recipients -> 0070_channel_connections
    -> 0071_kitchen_staff -> 0069_order_deliveries
  ```

  **`0069_order_deliveries` is the head, and it runs after `0071`.** V2 wrote
  it against `0068`, which the marketing chain had already continued from, so
  the 2026-09-30 merge produced two heads. It was re-pointed rather than
  renumbered, for the same reason as 0063/0064 below. Its table was created on
  Supabase by hand before the merge, so there it takes its guarded early return
  and only moves the stamp.

  **`0063_marketing_consent` and `0064_marketing_campaign_fields` run after
  `0068`, despite their numbers.** They were re-pointed off the fork rather
  than renamed, because renaming would rewrite revision ids that
  `0069`/`0070` name — and `0070_channel_connections` is the id Supabase is
  stamped with, so a rename there would reproduce the exact unresolvable-stamp
  failure this whole exercise existed to fix. Read the chain from
  `down_revision`, never from the filename.

  **`0071_kitchen_staff` is the first revision past that stamp**, so unlike
  0063-0068 it is not a no-op on Supabase — it genuinely runs there. It is
  additive (a new enum value on `user_role` and `order_event_actor`, two
  nullable columns, a CHECK, a composite FK, and a rewrite of the two
  platform-uniqueness indexes) and it round-trips: verified upgrade →
  downgrade → upgrade on a throwaway database.

  Two traps it documents, both of which bite anything that adds an enum value
  here. `alembic/env.py` does not set `transaction_per_migration`, so an
  upgrade runs EVERY pending revision in one transaction — and Postgres
  refuses to let a newly added enum value be used until that transaction
  commits, so a later CHECK naming `'KITCHEN'` fails with *unsafe use of new
  value*. Splitting into two revisions does not help; `op.get_context().
  autocommit_block()` is what does. And the metadata naming convention is
  `ck_%(table_name)s_%(constraint_name)s`, which alembic applies to a DROP as
  well as a CREATE — pass the bare name to both, or the downgrade tries to
  drop `ck_users_ck_users_kitchen_assignment`.

  **Supabase is stamped `0071_kitchen_staff`** (checked 2026-09-30), so the
  only pending revision there is `0069_order_deliveries`, a no-op beyond the
  stamp. Everything before it remains a no-op there. Nothing
  re-runs: every object V2's 0063-0068 create already exists, and each of
  those migrations is guarded to return early when it does. New migrations take `0072+`.

- **Supabase's Alembic stamp is behind its schema.** `alembic_version` reads
  `0074_print_agents` (checked 2026-10-05), but `0075`-`0082` were all applied
  there by hand through the Supabase MCP and never stamped. Every one of them
  is guarded to no-op when its objects exist, so `alembic stamp head` (or an
  `upgrade head`, which will no-op through them) is the fix - do it before the
  server deploy runs migrations, and check the stamp after.
- **Six restaurants are demo data** (`restaurants.is_demo`, 2026-10-05): the
  CAD kitchens seeded on 2026-09-13 - Bangkok Bowl, Momo Mountain, Luigi's,
  Dragon Wok, Stacked Grill House, Spice Route. Kept because the Bangkok Bowl
  app client and WhatsApp setup point at one; left out of everything the
  platform admin reads across restaurants (dashboard, `/orders`, live board,
  Platform watch, commission, tenant switcher, Restaurants page unless "Show
  demo" is ticked). Naming one by id still answers. The seven real kitchens
  are all INR, which is also the admin's `DEFAULT_CURRENCY` now.
- Migration numbering also skips `0033`-`0035` (jumps `0032` to `0036`).
  Intentional or not, do not "fix" it; the chain is defined by `down_revision`.
- The whole Marketing Hub, the half-and-half feature and several other surfaces
  are **uncommitted work in progress** — staged or untracked, not committed. A
  `git stash` while measuring a baseline will take the feature with it and make
  an unrelated lint or test count look like a regression.
- `frontend-admin` carries ~55 pre-existing lint errors and
  `test_ordering_agent_*` ~24 pre-existing failures. Measure a delta against the
  working tree, not against zero.
- `readme.md` and several docs cross-link with absolute paths
  (`/Users/imac/Desktop/restaurant-rag/...`) that do not match this checkout's
  location (`/Users/imac/data/restaurant-rag`).
- **nginx drops the shared proxy headers on every `/api` route.** nginx
  inherits `proxy_set_header` from the `http` level ONLY into a location that
  sets none of its own, and both `/api` locations in `snippets/api-proxy.conf`
  set `Connection ""` — so `Host` and `X-Forwarded-*` from `nginx.conf` never
  reach the API there. Found while adding the Socket.IO location (which
  restates them); not fixed, because it changes what the API sees on every
  request. The storefront masks it by sending `X-Forwarded-Host` itself.
  nginx is not installed on this Mac, so none of that config has been run here.
- `backend/celerybeat-schedule.{bak,dat,dir}` are tracked as of the V2 merge.
  They are Celery beat's local shelve of when each periodic task last ran —
  runtime state, regenerated on every beat start, and committed by accident.
  Same class of problem as the tracked `.pyc` files below, and the same fix
  (`git rm --cached` plus a `.gitignore` line); left alone here because
  deleting files V2 committed is not a merge decision.
- ~283 `*.cpython-313.pyc` files are tracked in git and churn on every run.
  `git rm -r --cached` is the fix; nobody has taken the decision.

---

## Docs worth reading before big changes

| File | Covers |
|---|---|
| `AI_RESTAURANT_MANAGER_WORKFLOW.md` | the owner-facing AI, tier by tier, all 28 tools |
| `LLM_ARCHITECTURE.md` | which model, why, backend vs LLM responsibilities |
| `PROJECT_UNDERSTANDING.md` | broad product overview |
| `backend/docs/chat-rag-workflow.md` | customer chat internals |
| `backend/docs/delivery-integration.md` | getting the food to the customer: Pidge, the courier contract, and the webhook that does not trust its payload |
| `docs/per-app-identity.md` | the AppClient identity split |
| `docs/recommendation-flow.md`, `docs/personalized-offers.md` | scoring rules |
| `MENU_ITEM_CUSTOMIZATION_FLOW.md`, `STRIPE_PAYMENT_INTEGRATION_PLAN.md` | those flows |
| `docs/MARKETING_HUB_AUDIT_AND_PLAN.md` | the Marketing Hub slice by slice, what is done and what is not |
| `docs/MARKETING_HUB_SCOPE.md` | what P1 deliberately does and does not cover |
