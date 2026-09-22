# Restaurant Marketing Hub — Codebase Audit & Implementation Plan

Living document. Updated at each P1 milestone.

**Last updated:** 2026-09-21 — P1 complete, one real push verified. Dispatch is behind
`enable_marketing_dispatch`, which defaults **off**.

> The originating documents live as Claude Docs, not in this repo:
>
> - Codebase Audit & Implementation Plan — `https://claude.ai/code/artifact/ad7bdd21-8b0b-417a-86d4-9b8538e416de`
> - Functional Specification — `https://claude.ai/code/artifact/a8c635ff-ba55-419c-8445-6baf01135575`
> - Scope Summary — `https://claude.ai/code/artifact/fccf6698-2d94-49e4-b803-d6aacc15bcc2`
>
> This file and `MARKETING_HUB_SCOPE.md` were originally rebuilt from the P1
> frontend contract (`frontend-admin/src/services/marketing/types.ts`), the mock
> rules in `marketingApi.ts`, the worklog and a fresh read of the backend,
> because the Claude Docs connector was unavailable to that session.
>
> **Reconciled 2026-09-19.** The audit and the scope summary now each carry a
> dated status section covering slices 1–3 and the frontend, so the four
> documents agree. One real divergence was found and is recorded in all of
> them: consent shipped as opt-**out** (default true, existing customers
> grandfathered), where the specification called for per-channel opt-**in**.
> Defensible for push; it does not carry to Phase 2.

---

## 1. The contract

`frontend-admin/src/services/marketing/types.ts` is the specification. The
whole P1 UI was built against it while the backend was a mock, so every
component already speaks it and the backend's job is to satisfy it rather than
renegotiate it. `marketingApi.ts` is the only module any screen talks to —
replacing its function bodies is the entire frontend migration.

---

## 2. Audit findings

### Already existed and is reused

| Asset | Used for |
|---|---|
| `push_notification_campaigns` | The campaign table itself. Already had the exact six status values, `scheduled_for`, `timezone`, `deep_link`, `restaurant_id`, `data_payload` and four delivery counters. |
| `push_notification_events` | Per-user delivery trail; the frequency cap is derived from it. |
| `notifications.py::_dispatch_push_campaign` | Token chunking, FCM bootstrap, dead-token deactivation, counter updates. |
| `UserDeviceToken` | Two of the three push reach blockers. |
| `insights/scope.py::resolve_insights_scope` | Owner/branch tenancy. Reused verbatim — one answer to "which restaurant may this request touch". |
| `insights/metrics.py::counted_order_statuses` | Cancelled orders never make someone a regular; segments and revenue reports cannot disagree. |
| `GeneratedOffer` | The attachable-offer catalogue. Maps to `MarketingOffer` nearly field-for-field. |
| `insights/offer_performance.py` | Revenue-minus-discount maths for attribution (pending). |
| `location_fulfillment_slot` | Branch opening hours, projected to flat `opens_at`/`closes_at`. |

### Gaps found, and how each was closed (or is still open)

| Gap | Status |
|---|---|
| No consent model of any kind | **Closed** — `users.marketing_opt_in` + `marketing_opt_in_changed_at` (migration `0063`) |
| Audience was role-based only (no segments, no branch scoping) | **Closed** — `services/marketing/segments.py`, 8 segments |
| No frequency-cap data | **Closed** — derived from `push_notification_events`, MARKETING campaigns only |
| Campaign columns missing vs `types.ts` | **Closed** — 11 additive columns (migration `0064`) |
| Sending is synchronous, in-request, 404s on empty audience | **Closed** — `services/marketing/dispatch.py` on the notifications queue; an empty audience is SENT with a reason, not a 404 |
| Nothing executes scheduled campaigns | **Closed** — `run_due_marketing_campaigns` on beat, every `marketing_scheduler_interval_minutes` |
| No campaign→order attribution | **Closed** — `push_notification_campaign_recipients` (migration `0068`) + `services/marketing/attribution.py` |
| No `CLICKED`/`UNSUBSCRIBED` event types | **Partly closed** — enum values added; nothing writes them yet |

---

## 3. Decisions taken (confirmed 2026-09-19)

1. **Consent is opt-out**, defaulting true, existing customers grandfathered.
   `marketing_opt_in_changed_at` stays null on backfill so "never asked" stays
   distinguishable from "agreed".
2. **Audience is scoped to the restaurant's own `app_client_id`** — its
   SINGLE_RESTAURANT app, never the marketplace client. A restaurant without
   its own app raises `SegmentUnavailable` rather than returning an empty
   audience.
3. **Attribution is recipient-window**; offer redemption additionally supplies
   `discount_given`.
4. **Extend `push_notification_campaigns`** rather than add a table. `kind`
   separates MARKETING from TRANSACTIONAL.

Deferred, no rework risk: branch hours (read-path projection, done), test-send
recipient, currency.

---

## 4. Status

### Completed

**Slice 1 — Consent**
- Migration `0063`: `users.marketing_opt_in` (default true), `marketing_opt_in_changed_at`, partial reach index.
- `services/marketing/consent.py` — audience base vs consent predicates kept separate so opting out removes someone from *reach*, not from their segment.
- `GET`/`PUT /api/profile/marketing-preferences`. Customer-only; there is deliberately no owner or admin route that writes this column.

**Slice 2 — Segments & reach**
- `services/marketing/segments.py` — all 8 segment keys as real SQL, app-client scoped, counted-orders only.
- `services/marketing/catalog.py` — 8 goals, 7 templates, branch hours projected from fulfillment slots, attachable offers.
- `services/marketing/reach.py` — per-channel reachability with itemised blockers, frequency cap, quiet hours, minimum audience, branch-closed/inactive warnings.
- `GET /api/marketing/reference`, `POST /api/marketing/reach-estimate`.

**Slice 3 — Campaign CRUD**
- Migration `0064`: 11 additive columns, `notification_campaign_kind` enum, `SEGMENT` audience, `CLICKED`/`UNSUBSCRIBED` events.
- `services/marketing/campaigns.py` — save/list/get/duplicate/delete/cancel/schedule with an explicit transition table.
- `GET/POST /api/marketing/campaigns`, `GET/DELETE /campaigns/{id}`, `POST /campaigns/{id}/{duplicate,cancel,schedule}`.

**Tests:** 41 new across `test_marketing_segments.py` (13), `test_marketing_campaigns.py` (16), `test_marketing_consent.py` (12).

### In progress

Nothing. Slice 3 is the last completed unit; slice 4 has not started.

### Completed 2026-09-19 (slices 4–6)

**Slice 4 — Dispatch.** `services/marketing/dispatch.py`, `tasks/marketing.py`,
`POST /campaigns/{id}/send`. The route claims the campaign (DRAFT/SCHEDULED →
SENDING, committed immediately) and queues the work; the worker owns everything
after the claim. The claim is the concurrency control — a second caller finds
SENDING and is refused. Merge fields render per recipient with the same
fallbacks `frontend-admin/src/components/marketing/mergeFields.ts` uses, so the
preview the owner approved is the message that goes out.

Deliberately **not** wrapping `_dispatch_push_campaign`, as the old plan said:
that function raises `HTTPException` from inside a dispatch and 404s an empty
audience, both wrong for a background send, and bending it to serve both would
have put the transactional order push at risk. It shares `_get_firebase_app`
and `_should_deactivate_token` and nothing else.

**Slice 5 — Scheduled execution.** `run_due_marketing_campaigns` on beat every
`marketing_scheduler_interval_minutes` (default 5). Reach and quiet hours are
recomputed at fire time; a campaign scheduled Tuesday for Friday goes to
Friday's segment.

**Slice 6 — Attribution & dashboard.** Migration **`0068`**, not `0065` — the
shared database already carries 0065–0067 from the unknown lineage below, so
our chain runs `0064 → 0068`. `services/marketing/attribution.py` credits an
order when a customer who *received* the campaign ordered within the window
**after their own send instant**, which is why the recipients table exists: a
send spanning minutes must not have the last customer's window cut short by the
first customer's clock. `GET /marketing/dashboard` totals it;
`campaign_view(campaign, db=...)` populates the report, and is passed a session
only by the detail route because attribution is two queries a list must not pay
per row.

**Dispatch is behind `enable_marketing_dispatch`, default off.** With it off the
whole path runs against the real audience and writes real recipient rows — the
owner can see exactly who a send would have reached — and Firebase is never
called. Test-send honours the same flag, so there is no path that escapes it.

### Completed 2026-09-19 (consent UI)

The P1 item with legal weight, and the last one that did not need an external
account. `GET/PUT /api/profile/marketing-preferences` had existed since slice 1
with **no caller in either customer app** — nobody could opt out.

- `frontend-customer/src/routes/preferences.tsx` — a Marketing messages section.
- `mobile` — the Promotions switch on the notification settings screen. It was
  **local `useState` with nothing behind it**: a customer could switch it off,
  believe they had opted out, and keep receiving campaigns. That was worse than
  having no control at all.

Three rules both clients follow:

- **Saved on the toggle, never behind a Save button.** Withdrawing consent has
  to be at least as easy as giving it; a switch needing a second click elsewhere
  is the pattern where someone opts out, walks away satisfied, and keeps
  receiving marketing.
- **Kept out of `PUT /preferences/me`,** which replaces every column it is
  given. Folding consent in would let a screen that never showed the toggle
  rewrite a legal record.
- **A null `marketing_opt_in_changed_at` is not a date.** Existing customers
  were backfilled opted-in with no timestamp, so "You haven't changed this yet"
  is what both clients show — not a decision they never made.

The switch moves optimistically and rolls back if the server refuses, so it
always shows what is actually stored; a read failure disables it rather than
rendering "off", which would claim an opt-out the server does not have.

Verified live: opting out drops the reachable audience 36 → 35, and the state
was restored afterwards. 11 new tests (6 web, 5 mobile).

### Remaining

Nothing. The last two items closed on 2026-09-21:

- **Open/click reporting** — `POST /marketing/engagement`, customer-
  authenticated, counted once per person per kind. The mobile push handler
  reports OPENED on a tap and CLICKED when the payload carries a destination.
  `services/marketing/engagement.py`.
- **Unsubscribe** — two routes, because they answer different situations. In
  the app the customer is already authenticated, so `POST /marketing/engagement`
  with `UNSUBSCRIBED` opts them out and attributes it to the campaign. Outside
  the app, `GET/POST /marketing/unsubscribe/{token}` carries an HMAC-signed
  token. GET renders a confirmation and only POST mutates — mail clients and
  link scanners fetch URLs with no human involved, and a GET that unsubscribed
  would opt people out of messages they never opened. `public_base_url` is now
  set; without it the link is omitted rather than pointing nowhere.

Deliberately **not** in the push payload: a per-recipient unsubscribe URL. The
dispatcher multicasts one message to many tokens, grouped by rendered copy, so
per-user data would mean one Firebase call per customer. The app is
authenticated and needs no token; the hosted link exists for email in Phase 2.

---

## 5. Notes for whoever picks this up

- `campaign_view()` takes an optional `db`. Without it, attribution and
  failure reasons stay empty — which is what the campaign list wants, and the
  reason the detail route is the only caller that passes a session.
- `ReachResult.reachable_user_ids` is computed but deliberately never
  serialised — the owner gets counts, not a list of which customers. The
  dispatcher needs that list; resist widening the response model to carry it.
- Segment thresholds are named constants in `segments.py` and appear twice: in
  the constant and in the owner-facing `definition` string. Change both.
- Migrations `0063`, `0064` and `0068` **have** now been applied to Supabase,
  out of band: `alembic upgrade` cannot run there because the database is
  stamped `0067_restaurant_payment_accounts`, a revision from a lineage that
  exists nowhere in this repository. All three are guarded by existence checks,
  so running their `upgrade()` directly was safe and repeatable. **`alembic_version`
  was left at 0067 and therefore no longer describes the schema** — reconciling
  the chains still needs whoever owns 0065–0067.

## 6. Verification, as of 2026-09-19

- `python -m compileall app alembic` — clean.
- `python -m unittest discover -s tests` — 1733 tests, 23 failures + 2 errors,
  **all pre-existing and none in marketing**:
  - 24 in `test_ordering_agent_order_details` — needs Ollama, which is not
    installed on this machine. Confirmed identical on a tree with the marketing
    work removed.
  - 1 in `test_ai_manager_screen` — `movement_label` returns `₹1,260` where the
    test expects `$1,260`. Currency drift left over from commit `8f4d050`
    ("switch the whole product to USD"); neither `insights/rules.py` nor that
    test is touched by this work. Worth fixing separately.
- The 41 marketing tests pass on their own and inside the full run.

**Unrelated hazard found:** `__pycache__/*.pyc` files are tracked in git in this
repo. A routine `git stash` during verification therefore conflicted on
regenerated bytecode and refused to pop, briefly stranding source edits in the
stash. Worth a `.gitignore` fix before anyone else stashes here.
