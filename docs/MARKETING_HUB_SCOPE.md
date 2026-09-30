# Restaurant Marketing Hub — Scope Summary

Living document. Updated at each P1 milestone.

**Last updated:** 2026-09-21 — P1 complete. One real push verified end to end.

The originating Scope Summary lives as a Claude Doc and carries the same status
section: `https://claude.ai/code/artifact/fccf6698-2d94-49e4-b803-d6aacc15bcc2`.
Reconciled against it 2026-09-19.

---

## What the Marketing Hub is

An owner-facing surface in `frontend-admin` for sending campaigns to their own
customers: pick a goal, pick an audience, attach an offer, write the message,
send or schedule it, then read what it earned.

## Phases

| Phase | Scope | State |
|---|---|---|
| **P1** | Push only. Segments, reach, campaign CRUD, send, schedule, attribution. | Frontend done (mock data). Backend 3 of 6 slices done. |
| **P2** | The other channels — email, SMS, WhatsApp, Facebook, Instagram. | Built. Not yet run against a real provider. |
| **P3** | Not yet specified. | Not started. |

As of 2026-09-21 the builder is **channel-first**: it asks where the campaign
runs before anything else, one channel per campaign, and every later screen —
goals offered, audience question, content fields, preview, button verb — is
shaped by that answer. So the P2 channels are no longer disabled rows with a
reason: an owner can plan, write and save a WhatsApp or Instagram campaign in
full, and a channel that has not been connected is refused at the send button
rather than at the door.

Later the same day the plumbing behind those channels landed too.
`restaurant_channel_connections` holds
each restaurant's credentials, `services/marketing/providers/` has a sender
per channel behind two protocols, `dispatch.py` routes to them, reach counts
each channel's own addresses, and a published post is attributed by the promo
code a customer types at checkout. Owners connect channels at
`/marketing/channels`.

What is **not** done, and should not be assumed:

- **No integration has touched a real provider.** Each is written against the
  documented API with its HTTP mocked in tests. Expect the first live
  WhatsApp send to turn something up, most likely in template parameters.
- **Connecting is a form, not OAuth.** The owner pastes ids and tokens from
  Meta's dashboard rather than signing in.
- **Boost budgets are recorded and never spent.** A boosted post publishes
  organically; paid promotion is a separate Marketing API integration.
- **Approved WhatsApp layouts are not listed from Meta**, so the owner picks
  from the Hub's own template list and its name must match theirs.

---

## P1 backend progress

| # | Slice | State |
|---|---|---|
| 1 | Consent | ✅ Complete |
| 2 | Segments & reach | ✅ Complete |
| 3 | Campaign CRUD | ✅ Complete |
| 4 | Dispatch (send now) | ✅ Complete |
| 5 | Scheduled execution | ✅ Complete |
| 6 | Attribution & dashboard | ✅ Complete |
| 7 | Open/click reporting | ✅ Complete |
| 8 | Push unsubscribe | ✅ Complete |

### Done

- **Consent** — opt-out, default true. Customer-owned: no owner or admin route
  writes it. Transactional order notifications ignore it entirely.
- **Segments** — 8 audiences (lapsed regulars, first-time buyers, VIPs, big
  spenders, weekend diners, dish fans, branch customers, never ordered),
  computed from counted orders and scoped to the restaurant's own app.
- **Reach** — per-channel reachability with every excluded person itemised,
  plus quiet hours, minimum audience size, frequency cap and branch warnings.
  Re-decided server-side; the UI only surfaces it.
- **Campaign CRUD** — drafts save from any wizard step; sent campaigns are
  immutable; duplication copies content but never results; another tenant's
  campaign 404s.

### Remaining

Nothing in P1. The last two items — open/click reporting and unsubscribe from a
push — landed 2026-09-21, and a real campaign was delivered to a device with
`dry_run=False`.

Two things are true but are not P1 gaps:

- **Sending is off by default.** `enable_marketing_dispatch` defaults false, and
  a deployment that has not deliberately switched it on runs every send as a
  dry run. That is the design, not an omission.
- **Opens and clicks only arrive from the mobile app.** The web customer app
  has no push channel, so its customers contribute delivery but never
  engagement.

---

## Explicitly out of scope for P1

- Every channel except push.
- Any AI-generated campaign copy. Templates are fixed strings.
- Cross-restaurant or platform-wide campaigns. A campaign belongs to one
  restaurant and reaches only that restaurant's own app's customers.
- Reaching marketplace-app customers from a single-restaurant campaign.

---

## Key constraints

1. **Backend enforces, UI only hides.** Every pre-send check re-runs
   server-side at dispatch, against data that may have moved since the owner
   last saw an estimate.
2. **Per-app identity.** The same person in the marketplace app and in a
   restaurant's own app are two accounts. Campaigns never cross that line.
3. **Counted orders only.** A cancelled order never makes someone a regular.
4. **No new frontend dependencies.** `frontend-admin` stays dependency-free.
5. **Transactional pushes are not marketing.** Order updates ignore consent,
   the frequency cap and quiet hours, and never appear in the Hub.
