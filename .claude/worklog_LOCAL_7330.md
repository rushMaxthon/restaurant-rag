# Worklog

Running log of what each session did. Newest entry at the top.

**How to use this file**

- At the **start** of a session: read the top 2-3 entries. That plus `CLAUDE.md`
  should be enough to resume without re-exploring the repo.
- At the **end** of a session: add one entry using the template below. Keep it
  short — what changed, what was verified, what is still open. Do not restate
  what `git log` already says; record the reasoning and the loose ends, which git
  does not capture.
- If something learned is a permanent fact about the repo (a convention, a
  gotcha, an architectural rule), put it in `CLAUDE.md` instead — this file is
  for history, `CLAUDE.md` is for standing truth.

**Template**

```
## 2026-09-21 (5) — The reconciled chain deployed, and a badge that lied

**The migration is applied to Supabase.** `alembic upgrade head` ran against
the shared database and completed: `0068b` and `0069` no-opped past objects
that were already there, `0070` created
`restaurant_channel_connections` and `orders.marketing_promo_code`. Stamp
moved `0068_payment_transaction_payment_id` -> `0070_channel_connections`.

Verified against a snapshot taken immediately before: 48 tables -> 49, one
new table and **none lost**; `orders` 33 -> 34 columns with all **416 rows
intact**; RLS confirmed on for the new table — the first table in this
database where that is reproducible from a migration rather than applied by
hand. Then the real thing: `connections.all_views()` run against Supabase
returns PUSH connected and the other five not, which is exactly what the
channel picker asks for.

**The bug the screenshot caught.** Every channel card read "NEEDS SETUP",
including push. Two pieces of logic read the same registry and only one
honoured `ALWAYS_ON`:

- the **send gate** used `availability !== 'ALWAYS_ON' && !connected`, which
  is right — push was never actually blocked, and campaigns on it worked
  throughout;
- the **badge** used `connected` alone, so a `/marketing/channels` call that
  had not answered — or had failed — rendered all six as needing setup.

So the product worked and the screen said it did not. The cause of the failed
call was the migration above: the route queried a table that did not exist
yet. Fixed three ways — push now reads Ready from the registry in every
state, the others show "Checking…" rather than asserting "Needs setup" before
we have asked, and the fetch failure is surfaced as a notice instead of being
swallowed into an empty map. 12 new tests pin the badge rule and the send
rule **together**, since the defect was precisely the gap between them.

**Verified:** `frontend-admin` build clean, **176** tests (16 files), lint 55
errors — baseline, unchanged.

**Worth knowing next session:** the five reconstructed revisions are now
stamped into the shared database. If the real 0065-0068 ever land, the
duplicate-id collision will surface at import rather than at deploy, and the
resolution is still to delete ours — but the database will already be past
them, so that reconciliation is now a stamp question, not a schema one.


## 2026-09-21 (4) — Deployment unblocked, and four promises made true

Six things, in the order they were asked for. The first one turned out to be
different from what this file and CLAUDE.md both said it was.

**The migration chain is reconciled, and alembic works against Supabase.**
CLAUDE.md recorded the shared database as stamped
`0067_restaurant_payment_accounts`. It is stamped
`0068_payment_transaction_payment_id` — the divergence had grown since anyone
last looked. Rather than guess again, the live schema was introspected
read-only (one connection, no retry: the IP ban warning in CLAUDE.md is
real), and the unpushed lineage turned out to be three tables
(`app_client_push_credentials`, `restaurant_capabilities`,
`restaurant_payment_accounts`), one column on `payment_transactions`, and —
found only by diffing columns rather than tables — five more on `app_clients`
and `restaurants`. **None of the eight appears in any model here**, so nothing
in this codebase reads them.

All of it was rebuilt as `0065`, `0066`, `0067`,
`0068_payment_transaction_payment_id` and `0068b_orphan_columns`, each guarded
on "does this already exist", so they are no-ops against Supabase and a
catch-up on a fresh database. Our two marketing migrations were renumbered to
`0069`/`0070`; safe because nothing was ever stamped with the old ids — they
reached Supabase by having `upgrade()` run by hand.

Verified properly rather than by reading: a database built from base and
diffed against Supabase is **identical apart from what 0070 adds**, and
`alembic current` + `upgrade head` against a database stamped exactly as
Supabase is now resolves and applies cleanly. That is the production
operation, rehearsed.

The reconstructions cannot recover intent, and if the real 0065-0068 are ever
pushed alembic refuses to start on the duplicate ids — loudly, which is the
right failure. Delete ours at that point.

**The ADMIN channels bug.** `ChannelsPage` shipped without a restaurant
picker, so an admin arriving by deep link or refresh got
`400 restaurant_id is required` — the exact failure CLAUDE.md names. Rather
than paste MarketingPage's picker into a third place, the logic came out into
`useMarketingScope` + `RestaurantScopePicker`, and **MarketingPage was moved
onto it too** so the two cannot drift. The next page that needs it now cannot
forget.

**The weekly frequency cap counted nothing.** It read
`push_notification_events` of type SENT or DELIVERED; the only writer of that
table is `engagement.py`, whose schema restricts the event to OPENED, CLICKED
and UNSUBSCRIBED. Zero rows matched, so the cap suppressed nobody — while the
schedule screen told owners "anyone who already heard from you this week is
left out automatically". It now reads recipient rows, which is what migration
0069's own docstring said they were for. A FAILED or SKIPPED row does not use
up the allowance: holding a message back over a delivery we never made is
backwards. Counted across channels, not per channel — six messages from one
restaurant is six.

**STOP is honoured.** Both inbound paths now reach `optout.py`. The WhatsApp
webhook already existed for the ordering concierge and already received these
replies and dropped them; STOP is now checked **before** the allowlist, the
our-number check and the assistant, because all three are our configuration
problems and none is a reason to keep messaging someone who said no — and
because answering an opt-out with "would you like to see the menu?" is the
worst possible reply. SMS needed a new endpoint: no signature standard exists
across Indian aggregators, so it takes a shared secret and reads whichever of
`from`/`sender`/`msisdn` and `text`/`body`/`message` arrived, JSON or form.
An unset secret refuses everything — an open endpoint here would let anyone
opt any customer out by guessing a phone number.

Two decisions worth remembering: a phone number identifies a **person**, so
every `AppClient`-scoped account on that number is opted out (telling someone
who texted STOP that they are still subscribed on their other account is a
technicality used against them); and the opt-out is credited to the last
campaign that reached them, because an opt-out rate per campaign is how an
owner learns a piece of copy cost them their list.

**Spend caps are enforced, not displayed.** Per campaign and per calendar
month, as BLOCK notices from `estimate_reach` — which means one rule decides
both what the builder shows and what the dispatcher allows, since dispatch
re-runs the estimate and refuses on any blocking notice. A draft that was
under the cap on Tuesday and over it by Friday is refused on Friday. Spend is
derived from channel + `sent_count` + parts rather than stored, so it cannot
drift from what actually went out, and a half-failed send is charged for
half. Zero disables a cap; the defaults are non-zero because a deployment
that has not thought about this should be protected.

**A failed campaign can be retried.** The backend always allowed
FAILED -> SENDING and recipient rows always made it safe — dispatch skips
anyone already reached — but `canEdit` excluded FAILED, so the UI offered
neither an edit nor a retry and the only route was to duplicate and lose the
report. Now a "Try again" button, with a confirm that says nobody gets it
twice.

**Verified:** backend `compileall` clean; marketing suites **120 → 151**
passed (31 new guardrail tests); `test_whatsapp_webhook` 44 passed (13 new,
covering the STOP interception and the SMS endpoint's auth); full backend
suite unchanged from the documented baseline. `frontend-admin` build clean,
164 tests, lint **55 errors — baseline, unchanged**. The migration chain was
verified by two real runs against throwaway databases, not by inspection.

**Two of the new tests failed first and were wrong, not the product:** a tone
compared against `"BLOCK"` when the enum's value is lowercase `"block"`, and
a timestamp compared with `.replace(tzinfo=UTC)` where Postgres returns the
value in the server's zone — which shifts the wall clock instead of
converting it.

**Still open**, unchanged from the previous entry except where noted: no
integration has touched a real provider; connecting is a form rather than
OAuth; boost budgets are stored and never spent; `credentials` is plain
JSONB. Newly relevant:
- **Delivery receipts are still not read.** Meta posts them to the same
  WhatsApp webhook that now handles STOP, so the seam exists — `sent` still
  means "the gateway accepted it", not "it arrived".
- **Consent is still one flag for every channel.** Someone who wants push but
  not SMS cannot say so, and opt-out defaults that are defensible for push
  are not for SMS in most jurisdictions.
- **India DLT registration** is still a precondition for real SMS.
- Throughput is unchanged: WhatsApp and SMS are one sequential request per
  recipient in a single Celery task, with no 429 handling.


## 2026-09-21 (3) — The other five channels actually send

**Why.** The channel-first flow shipped earlier today could plan, write and
save a WhatsApp or Instagram campaign and then refused at the send button,
because nothing behind it existed. This is what was behind it.

**Connections.** `restaurant_channel_connections` (migration `0069`) +
`services/marketing/connections.py`. Per restaurant, because it *is* per
restaurant — two brands here send from two different WhatsApp numbers and a
settings value cannot hold both. **Absence of a row is the not-connected
state**, so there is no NOT_CONNECTED status able to disagree with the row's
existence. `config` is returned to the owner, `credentials` to nobody, and a
re-save **merges** — a connect form cannot display a stored token, so an owner
correcting their sender name leaves that box empty, and treating empty as
"clear it" would break the channel with nothing reporting it until the next
send. Push deliberately has no row: its credentials are the platform's shared
Firebase account, and a connection for it would let an owner disconnect the
channel their order notifications ride on.

Availability now comes from here for both the picker and the dispatcher, which
is the point — the old `PHASE_TWO_CHANNELS` map in `catalog.py` could only
ever say "no", so a channel that HAD been connected still rendered unavailable
and still refused to send.

**Providers.** `services/marketing/providers/`, two protocols in `base.py`.
`DirectProvider` takes people and a rendered message and reports per person;
`SocialProvider` publishes one thing and returns an id and a permalink. A
social provider has no `send` and a direct one has no `publish`, because a
post has no recipients and a message has no permalink — one interface would
mean every implementation carrying a method that raises.

- **WhatsApp** — Meta Cloud API, `type: template`. Free text is not an option
  the API has; sending it would build a feature WhatsApp refuses at the far
  end. Meta's error codes are mapped to sentences an owner can act on, and
  only the codes that mean "this number will never work" retire an address.
- **SMS** — provider-agnostic JSON POST to a URL the owner supplies. Weaker
  than a first-party SDK and the honest choice: hardcoding Twilio excludes
  every restaurant not on Twilio. The STOP footer is appended *here*, not by
  the editor, so the message sent matches the one costed.
- **Email** — stdlib `smtplib`, so every mail service works and the deployment
  gains no dependency. Every message carries the per-recipient unsubscribe
  link built from the HMAC token P1 minted for exactly this, plus
  `List-Unsubscribe-Post: One-Click` — safe because the hosted page only
  mutates on POST.
- **Instagram / Facebook** — Graph API. IG is two calls (container, then
  publish) and refuses a post with no photo; FB is one. The hashtag comment
  is best-effort and never fails the publish: the post is already live, and
  reporting the campaign failed over a comment would be false.

**`dispatch.py` no longer knows how anything delivers.** It kept what every
send shares and asks the factory for a sender. A `ProviderError` inside a
batch fails that batch's recipients and lets the rest through — the campaign
is already SENDING and the other nine hundred people are still owed their
message. Dead-address retirement stays push-only on purpose: blanking a
customer's phone number because one gateway refused it once would cost the
restaurant a delivery address.

**Social is a separate function, not a branch.** `publish_campaign` has no
audience, no consent, no recipient rows, no cap. Routing a post through the
direct path with the people-shaped parts skipped would have reported it as a
send with an audience of zero. Its record is the post id and permalink in
`data_payload["social_post"]`; the delivery counters stay at zero because they
count *people*, and `sent: 1` for a post would put a post and a person in one
column.

**Reach, per channel.** `_push_reach` generalised to `_direct_reach`: consent,
then an address for *this* channel, then the weekly cap, in that order and
never double-counted. SMS and WhatsApp need a phone, email needs an address.
Cost is parts × people × rate — parts, because a long text is billed as two
and quoting the one-part price halves the number the owner was shown.

**Attribution for a post, and how weak it is.** `orders.marketing_promo_code`
(same migration), typed at checkout in both customer apps, priced on by
nothing. It is the only join available: a post reaches people this platform
has no identity for. Two honesty decisions are in the code and in the UI —
`baseline_orders` is **0** rather than fabricated, because "these same
customers before the send" names a set that does not exist for a post; and the
report says out loud that everyone who saw the post and ordered without the
code is missing. A push campaign's 41 and a post's 6 are not comparable, and
presenting them as if they were would be the most expensive lie in the
product.

**Insights are polled, not pushed.** `refresh_social_insights_task`, hourly,
bounded to `marketing_social_insight_days`. A post has no delivery callback —
it just accumulates impressions nothing tells us about — and Meta's webhook
for it needs an app review this product has not had. Metrics are stored as
whatever the platform returned: one it stops serving disappears rather than
reading as zero, because an owner seeing "0 impressions" on a post that
clearly got seen would conclude the product is broken.

**UI.** New `ChannelsPage` at `/marketing/channels` (connect, pause, edit,
disconnect — pause and disconnect are different buttons because re-authorising
Meta after a month off is not something to do by accident). The picker and the
editor read connection state from the server. `SocialReport` replaces the
sent-to-ordered funnel on a post. The campaign builder's own flow is unchanged,
as asked.

**Checkout.** A promo code field on `frontend-customer`'s checkout and
`mobile`'s cart, both optional and neither validated — an unrecognised code
buys nothing, so a typo costs the customer nothing and only means one post
goes uncredited.

**Verified:** backend `compileall` clean; marketing suites **82 → 120**
passed (38 new in `test_marketing_channels.py`); full backend suite 1774
tests, failures **unchanged from the documented baseline** — the 24
`test_ordering_agent_*` and the two errors that were already there.
`frontend-admin` build clean, 164 tests pass, lint **55 errors — baseline,
unchanged**. `frontend-customer` build clean, `tsc --noEmit` clean. `mobile`
`tsc --noEmit` clean, jest 133 passed with the one pre-existing
`App.test.tsx` gesture-handler failure (128 passed on a stashed tree, so the
same one).

**Two tests changed, both because the thing moved rather than broke:**
`test_marketing_dispatch` patched `dispatch._get_firebase_app`, which now
lives in the push provider; `test_dependency_imports` lists every Celery task
by name and correctly demanded the new one be added, exactly as its comment
says it should.

**Still open.**
- **Nothing here has been run against a real provider.** Every integration is
  written against the documented API and covered by tests with the HTTP
  mocked. The first real WhatsApp send will find something — most likely in
  template parameter shapes, which vary by how the owner registered them.
- WhatsApp templates are named by the campaign's `template_id`; there is no
  UI to *list* an owner's approved layouts from Meta, so they type the name
  the editor's template picker supplies. Fetching the real list is the next
  obvious slice.
- Connecting is a form, not OAuth. An owner pastes ids and tokens from Meta's
  dashboard. A Meta connector is available in this environment and would turn
  three of these forms into a sign-in.
- `credentials` is plain JSONB. Excluded from every response, behind RLS and
  a backend-only database — but not encrypted at rest. One place to change if
  a deployment needs it.
- Boost budgets are collected and stored and **nothing spends them**: the
  post publishes organically. Paid promotion is a separate Marketing API
  integration.
- `0069` enables RLS in the migration, unlike every table before it. The three
  tables listed in CLAUDE.md are still open.


## 2026-09-21 (2) — Create Campaign, rebuilt channel-first

**Why.** The wizard asked *Goal → Audience → Content → Channels → Schedule*.
Channel was the fourth question and it decided the other four, so by the time
an owner reached it they had written a 65-character push title against a
lock-screen preview. Step 4 was then six checkboxes with five of them
`disabled` and the words "arrives in Phase 2" — an owner cannot act on that;
it reads as a broken screen, not a roadmap.

**The flow now.** Six questions: **Where → Why → Who → Words → When → Ready.**
Where is first, one channel per campaign, and it changes the *shape* of what
follows rather than re-skinning it.

**The distinction the whole thing turns on** is DIRECT vs SOCIAL, declared in
`components/marketing/channels.ts`:

- **DIRECT** (push, WhatsApp, SMS, email) — the owner picks *people*. Consent,
  countable reach, recipient rows, per-recipient attribution. This is what the
  Hub backend already does.
- **SOCIAL** (Instagram, Facebook) — the owner picks *nobody*. No consent, no
  recipient rows, and therefore the Hub's central attribution rule ("read
  recipient rows, never the segment") **has no meaning at all**. A public post
  is attributed by a promo code, which is why the offer picker is replaced by
  a code field on those two channels and the reach rail by a spend card.

Collapsing those two into one audience step is precisely why the old step 4
could offer nothing but disabled boxes.

**Nothing is a dead end any more.** A channel that cannot send says so, says
what switching it on involves, and still lets the owner build and save the
whole campaign. The refusal moved from the door to the send button. Push is
still the only channel with a dispatcher; `availability: 'LIVE'` in the
registry is the single place that says so.

**Registry-driven, not `channel === 'PUSH' ?`-driven.** Field limits, whether
there is a headline at all, whether merge fields make sense, whether a photo
is required, the SMS segment length and per-message cost, the goals a channel
can honestly deliver, the button verb — all rows in `channels.ts`. Adding a
channel is a row plus a preview plus a dispatcher.

**Per-channel previews** (`ChannelPreview.tsx`): lock screen, SMS thread with
the billed opt-out footer shown greyed, WhatsApp bubble, email card, and an
Instagram/Facebook feed card at the real 4:5 and 1.91:1 crops. Social previews
have no recipient switcher on purpose — a "sample recipient" would teach
something false about how a post works.

**Two bugs found on the way:**

1. **A new draft could not be saved at all.** `emptyDraft()` left title and
   body empty, the backend requires `min_length=1` on both, and `persist` runs
   on the first Continue — so accepting the default goal and clicking Continue
   answered "Draft not saved". `forSaving` now fills name, title and body from
   the goal's own template.
2. The test-send endpoint sends a **push** whatever the draft names, so the
   button is now gated on `availability === 'LIVE'`. Offering it on WhatsApp
   would have put a push on the owner's phone and let them conclude WhatsApp
   worked.

**Backend: one additive change, no migration.** `CampaignContentSchema.extra`
— a size-capped passthrough dict for what belongs to one or two channels only
(photo, hashtags, promo code, boost budget). Stored under `content_extra` in
`data_payload`, which is **namespaced rather than assigned over** because that
column is shared with the transactional push path. `last_step` ceiling 5 → 6.
`duplicate_campaign` copies it, or an Instagram duplicate would be a caption
with no image. Four tests cover the round trip, the namespacing, the empty
case and the duplicate.

**One channel per campaign.** The draft holds `channel`; the wire still sends
`channels: [channel]`, which is the existing column and schema untouched.
Reads go through `primaryChannel()`, which defaults to push — so every
campaign written before today opens correctly. `withExtra()` in
`marketingClient.ts` guarantees `content.extra` exists on anything from the
wire, since an older row comes back without the key and every editor reads it
directly.

**Verified:** `npm run build` clean; `npm run test` 164 passed (15 files,
including 11 new registry tests); `npm run lint` **55 errors — the documented
pre-existing baseline, unchanged** (the two fast-refresh errors this work
introduced were fixed by extracting `contentRules.ts`, the same move
`noticeUtils.ts` already documents); `compileall` clean; backend marketing
suites 78 → 82 passed.

**One test changed, deliberately:** `scope.test.ts` stubbed every response as
`{}`, and the campaign-list normaliser maps over what it is given. The stub is
now `[]`. Those tests assert paths, not shapes.

**Still open.** No dispatcher exists for WhatsApp, SMS, email, Instagram or
Facebook, and no channel-connection storage — the Connect panel explains what
each would need and nothing performs it. Social attribution is a promo code an
owner types into the caption; nothing reads it back yet, so a social campaign
has no report. Goals are filtered per channel client-side, in the registry,
rather than by `/reference` — fine while the taxonomy is presentation, worth
moving if a goal ever gains a rule. A Meta Ads connector is available in this
environment and is the shortest route to making Instagram/Facebook real.



## 2026-09-21 — P1 closed: engagement, unsubscribe, FCM fixed, one real push

**Done:** the last two P1 items, the FCM misconfiguration, and the first
marketing push this product has actually delivered.

**Open/click reporting.** `services/marketing/engagement.py` +
`POST /marketing/engagement`. `opened_count`/`clicked_count` were read by the
campaign report and written by nothing, so every campaign looked like it lost
its whole audience between "delivered" and "opened". Two rules decide the
shape: counted **once per person per kind** (phones re-report opens; the
counters summarise distinct people), and **only a real recipient may report**
(the body carries a campaign id, so without a recipient check any signed-in
customer could move any restaurant's numbers). Mobile reports OPENED on a tap
and CLICKED when the payload carries a destination — fire-and-forget, because
a statistic must never delay the screen someone just tapped through to.

**Unsubscribe.** Two routes for two situations. In-app the customer is already
authenticated, so `POST /marketing/engagement` with `UNSUBSCRIBED` opts them
out *and* attributes it to the campaign — an opt-out rate per campaign is how
an owner learns a piece of copy cost them their list. Outside the app,
`GET/POST /marketing/unsubscribe/{token}` with an HMAC-signed token: no table,
no expiry (someone acting on a six-week-old message is exactly who it is for),
and the capability is one-directional. **GET renders a confirmation and only
POST mutates** — mail clients and link scanners fetch URLs with no human
involved, and a GET that unsubscribed would silently opt people out of messages
they never opened. That is also what makes it safe to reuse for email in P2.

**Deliberately not done:** a per-recipient unsubscribe URL in the push payload.
The dispatcher multicasts one message to many tokens grouped by rendered copy,
so per-user data would mean one Firebase call per customer. The app needs no
token; the hosted link covers the rest.

**The FCM mismatch.** `FCM_PROJECT_ID=restaurant-rag` was overriding a correct
committed default. The service account *and* `mobile/android/app/google-
services.json` are both `quickbite-7833a`; the override pointed the SDK at a
project the credentials cannot touch, and Firebase answered "FCM API has not
been used in project restaurant-rag". Removing the line beats setting it —
the right value then lives in one place. Also set `PUBLIC_BASE_URL` (the
unsubscribe link needs it) and `ENABLE_MARKETING_DISPATCH=true`.

**Verified: a real push.**
`Marketing campaign dispatched id=708f84c2 audience=1 sent=1 failed=0
skipped=0 dry_run=False` → campaign SENT, `delivered=1`, one recipient row for
`hiteshk086@gmail.com` — the only registered device in the database. Also
checked: the unsubscribe page renders and offers a button rather than acting,
a rubbish token says so, and `/marketing/engagement` 401s unauthenticated.

**The trap on the way there, now in CLAUDE.md:** the default Celery **prefork**
pool **segfaults** on macOS the instant a task touches Firebase —
`WorkerLostError: signal 11 (SIGSEGV)`. Firebase Admin pulls in gRPC and macOS
cannot safely `fork()` after it initialises. Three campaigns were left in
SENDING with no recipient rows, which looks identical to a hung send.
`--pool=solo` works. Linux is unaffected, so compose and Render are fine.

**Also corrected:** my earlier warning that draining the `notifications`
backlog would blast stale order pushes was **wrong**.
`tasks/notifications.py::send_order_status_notification` only *logs* a payload
— it never calls Firebase. All 570 drained harmlessly.

**Verified:** 78 marketing tests (10 new), `compileall` clean, mobile
`tsc --noEmit` clean, 133 mobile tests pass. `App.test.tsx` fails to load on a
missing `RNGestureHandlerModule` mock — pre-existing, unrelated to these files.

**Open:**
- **`ENABLE_MARKETING_DISPATCH=true` is now live in `backend/.env`.** Any send
  from this machine reaches real devices. Set it back to false when done
  testing.
- Two campaigns (`448238dc`, `c48dde8a`) are still SENDING — their tasks died
  in the segfault. Re-enqueue with a solo worker or resolve manually.
- Opens and clicks only ever arrive from the mobile app; the web customer app
  has no push channel.
- Migration divergence with Supabase is unchanged and still the biggest hazard.


## 2026-09-19 (4) — Consent: the P1 item nobody could act on

**Goal:** give customers a way to opt out. `GET/PUT
/api/profile/marketing-preferences` had existed since slice 1 with **no caller
in either customer app**, so the Marketing Hub could send to 36 people none of
whom had been asked or could refuse.

**Done:**
- `frontend-customer/src/routes/preferences.tsx` — a Marketing messages section,
  plus `getMarketingConsent`/`putMarketingConsent` in `lib/api.ts`.
- `mobile` — the Promotions switch on the notification settings screen, plus the
  two client methods and a `MarketingConsent` type.

**What the mobile screen actually was.** All three switches on
`NotificationSettingsScreen` were local `useState` with nothing behind them.
"Promotions" looked exactly like a marketing opt-out and did nothing: switch it
off, believe you have opted out, keep receiving campaigns. That is worse than no
control at all. Promotions is now real. **Order alerts and AI suggestions are
still fake** — no endpoint backs them, and deleting someone's settings UI is a
product decision, not mine. Flagged, not touched.

**Three rules, both clients:**
- Saved on the toggle, never behind a Save button — withdrawal has to be at
  least as easy as giving consent.
- Kept out of `PUT /preferences/me`, which replaces every column it is given;
  folding consent in would let a screen that never showed the toggle rewrite a
  legal record. A test in each app pins this.
- A null `marketing_opt_in_changed_at` is rendered as "You haven't changed this
  yet", not as a date. Every existing customer is in that state.

The switch moves optimistically and rolls back on refusal; a read failure
disables it rather than rendering "off", which would claim an opt-out the server
does not hold.

**Verified:** live round trip against Supabase — `(true, null)` → opt out →
`(false, <timestamp>)` → reachable audience **36 → 35**, proving consent feeds
`marketing_reachable_conditions` and not just a column. Restored the customer's
exact prior state `(true, null)` by SQL rather than through the API, because
opting them back in would have stamped a timestamp they never chose. 11 new
tests (6 web, 5 mobile); mobile 133 pass, web 236 pass, both build, both lint at
baseline — web lint actually fell 411 → 407, since prettier fixed two
pre-existing errors in a file I was already editing.

**Also:** corrected two things in the claude.ai plan doc that had gone wrong —
the "confirm the migration head is 0061" prerequisite (it is 0068 now, and
0065–0067 belong to the unknown lineage), and the Celery queue line. On that
second one the doc was **right and I was not**: it specifies a dedicated
`marketing` queue "isolated so a ten-thousand-recipient blast cannot starve
order notifications", and I put dispatch on the shared `notifications` queue.
At one campaign to tens of recipients it has not bitten, but the doc's reasoning
is the stronger one at volume. Recorded in the doc as something to move before
any real send rather than quietly left.

**Open:**
- Order alerts and AI suggestions switches on mobile are still decorative.
- Unsubscribe deep link still needs `public_base_url`, declared but unset.
- Dispatch still runs on the `notifications` queue; should get its own before
  volume.
- Everything previously open: multi-channel gated on the business/accounts/legal
  checklist, migration lineage, three tables without RLS.

**Learned:**
- Jest refuses out-of-scope variables in a `jest.mock` factory unless they are
  `mock`-prefixed.
- A `Response` object can only be read once, so a fetch mock must mint a fresh
  one per call or the second request in a test fails with "Body is unusable"
  rather than with whatever it was checking.

## 2026-09-19 (3) — Marketing Hub: the admin could not open it, and slices 4–6

**The reported bug.** "The Marketing Hub didn't load —
`restaurant_id is required for admin insights requests`". Not an insights bug:
`resolve_insights_scope` requires an ADMIN to name a restaurant and refuses one
from an OWNER, every `/marketing/*` route already accepted `restaurant_id`, and
the frontend never sent it. An owner never saw this; an admin never saw
anything else.

Fixed with a module-level scope in `marketingApi` (`setRestaurantScope`),
appended by `marketingClient.scoped()` to all nine calls, driven by a restaurant
picker on the Hub modelled on `AIManagerPage`'s. Seeded from localStorage so a
deep link to a campaign editor — which has no picker of its own — is scoped
before its first fetch. An unscoped admin now gets "Whose marketing?" instead of
a failure screen. Six tests in `services/marketing/scope.test.ts` pin the query
parameter onto the request, not just onto the setter: a scope that is stored and
never sent looks identical from the UI and fails exactly the same way.

**Then slices 4–6**, per `docs/MARKETING_HUB_AUDIT_AND_PLAN.md`. Two decisions
were the user's and are recorded there: dispatch sits behind
`enable_marketing_dispatch` (**default off**, dry run writes real recipient rows
and calls nothing), and the recipients table took migration **0068** rather than
the planned 0065, because the shared database already carries 0065–0067 from a
lineage that is in no branch here.

**Two bugs the live run found, both invisible without a real database:**

1. `_upsert_recipient` looked its row up with a query each time. A row added to
   the session but not yet flushed is invisible to that query, so the same
   customer got a second INSERT and the unique constraint failed the **entire
   send at commit — after Firebase had been called**. Now one preloaded map
   (also one query instead of N for a large audience).
2. The handler that puts a failed campaign down ran on a session left dirty by
   the very exception it was handling, and raised `PendingRollbackError`. The
   campaign was then stranded in SENDING, which only leads to SENT or FAILED —
   unretryable and uncancellable. `mark_send_failed` now rolls back first.

Both are pinned by tests that say why they exist.

**Verified**, against Supabase and a throwaway local database:

- Full lifecycle live: create → send → claimed SENDING (audience 19) → dispatch
  → SENT, 1 recipient row, counters and progress correct, dry run, no FCM call.
- Scheduler live: not due → time passes → due → claimed → dispatched → SENT.
- Pre-send checks refuse correctly ("Pick at least one branch").
- Detail route returns a real attribution report; the list route returns
  `attribution: null` for every row, so it stays cheap.
- 68 marketing tests pass (32 new: 16 attribution, 11 dispatch, and the
  existing suites). Admin: `tsc -b` clean, 144 tests, build clean, lint
  unchanged from baseline.
- Test campaigns removed from Supabase afterwards; 0 marketing campaigns and 0
  recipient rows left behind.

**Earlier the same day:** admin login was 500ing —
`column users.marketing_opt_in does not exist`. Migrations 0063/0064 had never
been applied to Supabase and `alembic upgrade` cannot run there (stamped
`0067_restaurant_payment_accounts`, unknown to this repo). Applied all three
(0063, 0064, 0068) out of band by running their guarded `upgrade()` directly.
**`alembic_version` is still 0067 and no longer describes the schema.**

**Also done: `CLAUDE.md` brought back in line with reality.** It described a
Windows machine — `.venv/Scripts/python.exe`, `C:\Program Files\PostgreSQL\15`,
`F:\restaurant-rag`, "Ollama: not installed" — while this checkout is macOS at
`/Users/imac/data/restaurant-rag` with Python 3.13, Homebrew PG16, and Ollama
running and serving embeddings. Following it here wastes a session. The Windows
notes are kept under "The Windows checkout" rather than deleted (the pgvector
build and the Memurai dead end are hard-won), and one corrupted path in them was
repaired: a stray CR had turned `C:\redis-portable` into `C:` + newline +
`edis-portable`. Added: the Marketing Hub section, the ADMIN-needs-a-restaurant
convention, the half-and-half rule and where its three implementations live, the
migration-divergence warning, and the pre-existing lint/test baselines so the
next session does not read them as a regression.

**Found while updating it:** RLS was off for four public tables, one of them
`push_notification_campaign_recipients` — the table created earlier today, which
names customers. Enabled it there, matching the documented deny-by-default
posture. `app_client_domains`, `restaurant_capabilities` and
`restaurant_payment_accounts` are still open; they belong to the other lineage,
so they were left alone and are now named in `CLAUDE.md`. The root cause is that
RLS is applied by hand rather than by migration, so **every new table starts
open** — now written down.

**Open:**
- Reconciling the migration lineages still needs whoever owns 0065–0067.
- Three tables from the other lineage have no RLS on Supabase.
- No customer-facing consent UI in `frontend-customer` or `mobile` against the
  existing `GET/PUT /api/profile/marketing-preferences`. Nothing lets a customer
  opt out today, and that is the P1 item with legal weight.
- Open/click reporting and the unsubscribe deep link are unbuilt; the columns
  and event types exist but nothing writes them.
- `enable_marketing_dispatch` is off, so no campaign can actually reach a phone
  until it is turned on.

**Learned:**
- `PushNotificationDeliveryType` has `INSTANT`, not `IMMEDIATE`; `Order`'s
  customer column is `customer_id`, not `user_id`. Both cost a round trip.
- `test_dependency_imports` asserts the worker's task list **by name** — adding
  a task fails it until the expectation is updated, which is the point.

## 2026-09-19 (2) — Migration divergence: diagnosed, rehearsed, blocked on three files

**Asked to fix the 0065–0067 conflict.** It is diagnosed and the resolution is
proven on a replica, but it **cannot be completed here**: the three migration
scripts the shared database was built with do not exist on this machine or in
this GitHub repo. No stamping was used and the repo's migrations are unchanged.

**Where things actually stand (evidenced, not inferred):**
- The shared Supabase DB is at a **single head**, `0067_restaurant_payment_accounts`
  — not a fork in the database itself.
- It **has** `0062_app_client_domains` applied, so the fork is at 0062, not 0061
  as first suspected.
- It **lacks** every column from our `0063`/`0064`.
- Tables it has that this branch does not create: `restaurant_capabilities` and
  `restaurant_payment_accounts`. (`app_client_push_credentials` looked like a
  third but comes from our own `0032` — corrected mid-investigation.)

So the history genuinely forks at `0062`: ours goes `0063 → 0064`, theirs goes
`0065 → 0066 → 0067`, and only theirs was ever applied.

**Searched exhaustively for 0065–0067:** every local and remote branch
(`main`, `V2`, `ordering-agent`, after `git fetch --all`), all four stashes,
`git log --all -S`, the second checkout at `~/Desktop/restaurant-rag`, and a
disk-wide find. They are in none of them. They were applied to a shared
database from a checkout that never pushed them.

**The fix, rehearsed end to end on a replica and verified:**

One line — re-parent our chain onto theirs:
`0063_marketing_consent.down_revision`: `"0062_app_client_domains"` →
`"0067_restaurant_payment_accounts"`. That linearises history to
`0062 → 0065 → 0066 → 0067 → 0063 → 0064`; `upgrade head` then applies exactly
our two additive migrations.

Rehearsal method: a scratch database migrated through our real migrations to
0062, then through throwaway stand-ins for 0065/0066/0067 (written in the
scratchpad from the live schema's shape, **never committed**) to reach exactly
the production revision and shape. Then representative pre-existing rows, then
the re-parent, then `upgrade head`. Results:
- Data intact — 3 users, 1 campaign, identical `md5` fingerprint before and
  after; campaign title and body preserved verbatim.
- Backfill correct — `marketing_opt_in=true` with `marketing_opt_in_changed_at`
  NULL, so "never asked" stays distinguishable from "agreed".
- The pre-existing push campaign was classified `kind=TRANSACTIONAL`, so an old
  operational push is **not** swept into the Marketing Hub. Worth knowing that
  this is now proven rather than assumed.
- Single head throughout; final revision `0064_marketing_campaign_fields`.
- **Reversible**: `downgrade 0067` removes the columns cleanly and leaves the
  same data fingerprint.

**Deliberately NOT done:**
- No `alembic stamp`, as instructed, and it would have been wrong anyway — the
  schema differences are real, not bookkeeping.
- **The re-parent was not applied to the repo.** Pointing `down_revision` at a
  revision that does not exist here would break every fresh database and CI
  run until the real files land. It is a one-line change to make the moment
  they do.
- The three stand-ins are rehearsal doubles. Committing them would forge
  history and collide with the real revision ids when they surface.

**The one input needed:** whoever owns `0065`–`0067` pushes them (or says what
`0065.down_revision` is). If their chain also branches from `0062`, the
re-parent above is the whole fix. If they numbered anything `0063`/`0064`
themselves, there is a filename collision to settle too — revision *ids* would
still differ, so alembic would cope, but the numbering would be misleading.

**Open, unchanged:** slices 4–6; no customer consent UI; 283 `.pyc` files still
tracked — running the backend during this work dirtied 44 of them, restored by
hand afterwards.


## 2026-09-19 — Marketing Hub: frontend wired to the real backend (slices 1–3)

**Done:** `marketingApi.ts` is no longer a pure mock. It is now a façade that
routes to `/api/marketing/*` or to the in-memory dataset, chosen at runtime.

- New `services/marketing/marketingClient.ts` — the live half. Reuses the
  exported `request()` from `services/api.ts` rather than its own fetch, so an
  expired session fires the same sign-out event on this screen as on every
  other one. Reads the token from `storage.readAuth()`, which keeps the live
  and mock signatures identical — that is what lets the façade swap without
  touching a call site.
- **Reference data is fetched once and read synchronously.** Goals, segments,
  branches, offers and templates are looked up *during render* all over the Hub
  (`getSegment(campaign.segment_key).name` inside a table cell). Making those
  async would mean rewriting every call site and threading loading state
  through components that should not know about it. Instead every async call
  awaits `ensureReference()` first, and the sync readers fail soft — a render
  before the cache fills shows a placeholder, never a crash. `marketingReference`
  is mutated in place rather than replaced, because screens read its properties
  during render.
- `getDashboard`, `sendNow` and `sendTest` have no route behind them (slices 6,
  4, 4). Dashboard silently keeps the mock's figures; **send and test-send throw
  in live mode** rather than returning a fake success. A campaign that did
  nothing while the UI said "Sent" is the worst failure this screen has.
- `DemoStateSelect` gained a Live/Mock switch, so the UI is still reviewable
  with no API running.

**The contract divergence this found.** The wizard mints `cmp-<random>` for a
draft that exists only in the browser; `save_draft` types that field as
`uuid | null` and treats null as "create". Sending the local id verbatim is a
**422 on the first keystroke of every new campaign** — confirmed live. Fixed by
sending null when the id is not a UUID and adopting the id that comes back;
`CampaignEditorPage` now does that in `persist()` and before send/schedule, or
every save would have created another campaign.

**Verified against a real backend**, not by reading schemas. A scratch database
(`mkt_check`, local Postgres) migrated to `0064` and seeded, backend on :8099,
authenticated as a seeded owner:

- `/reference` top-level keys exactly match `types.ts`; all 8 segment keys match
  `SegmentKey`; segment, branch, channel and campaign field names all match.
- `/reach-estimate` returns `ReachEstimate` field for field.
- Create with `id: null` → 200; same id again → **updated, one row not two**;
  `id: "cmp-abc1234"` → 422 as predicted; duplicate → DRAFT; delete → 204.
- Frontend: `tsc -b`, `npm run build`, 138 tests pass, lint unchanged at 4 over
  baseline.

**BLOCKER — the shared Supabase database has diverged from this repo.**
`alembic current` against it fails: *"Can't locate revision
'0067_restaurant_payment_accounts'"*. That revision, and 0065/0066, exist
**nowhere in this repository's history** — not on `main`, not on `V2`, not in
any commit. Someone has migrated the shared database from work that is not
pushed here. Consequences:

- `0063`/`0064` **cannot** be applied as things stand; alembic cannot resolve
  the database's current revision against our chain.
- Our chain is `0061 → 0062 → 0063 → 0064`. Whether that merges cleanly depends
  on what `0065`'s `down_revision` is, which nobody here can see. If the two
  lines forked, a merge migration is needed and the numbering may already
  collide.
- Do **not** `alembic stamp` your way out of this on a shared database.

Needs whoever owns 0065–0067 to push them, or to say what they branch from.

**Open:**
- Scratch DB `mkt_check` left in place on local Postgres — useful for the next
  integration pass; `dropdb mkt_check` to remove.
- Slices 4–6 unchanged. The Hub can build and schedule against real data but
  cannot send.
- Still no customer-facing consent UI in `frontend-customer` or `mobile`,
  against the existing `GET/PUT /api/profile/marketing-preferences`. It is the
  P1 requirement with legal weight and nothing lets a customer opt out today.
- 283 `.pyc` files still tracked in git.


## 2026-09-18 (2) — Marketing Hub visual redesign

**Done:** rebuilt the Hub's look so it reads as a campaign-creation product
rather than another admin console. No data-layer or route changes — the mock
services, types and API seam are untouched.

- **It no longer borrows the admin's page furniture.** `PageIntro`, `StatTiles`,
  `DataToolbar` and `ResponsiveTable` are gone from these three screens, because
  every one of them made the Hub look like the Orders page. The shared things
  that are *behaviour* rather than chrome — `ConfirmDialog`, `AnimatedCharts` —
  stayed. That is a deliberate reversal of the previous entry's "reuse
  everything" stance, and only for the Hub.
- **One local token block** on `.mkt` drives spacing, radii, shadow and accent,
  so the whole Hub re-skins from ~20 lines. Every rule is namespaced `mkt-` and
  nothing selects outside it; the CSS diff starts at line 10036 and is confined
  to the block added last session.
- **One selectable-card recipe** (`.mkt-pick`) now serves goals, segments,
  offers, branches, channels and schedule. Five near-identical components was
  how the first pass ended up with five slightly different paddings — which is
  most of what read as "cramped".
- **The stepper is one connected path**, not five chips: the reassurance a
  multi-step form has to give is "you are 3 of 5 through a thing that ends".
- **The builder rail is sticky** so the phone preview and the message being
  typed are on screen together, and the action bar is sticky so Continue is
  always reachable.
- Campaign list moved from a table to cards — a campaign has a status, an
  audience and an amount of money, which is more than a table row carries well.
- `hasBlockingNotice` split into `noticeUtils.ts`, following the precedent
  `components/statusPillUtils.ts` set for Fast Refresh.
- `[data-density='compact']` now reaches the Hub. The app-wide compact rules
  target `.admin-surface`, which the Hub no longer uses, so the workspace
  setting would have silently done nothing here.

**Verified:** `tsc -b` clean, `npm run build` clean, `npm run test` 118 passed,
dev server serves all three routes 200 and every module transforms. Lint on the
Hub's files is down from 6 errors to 4, all the fetch-on-mount pattern the other
20 data pages already trip.

**Open:**
- **Not visually verified.** There is no browser tool in this session, so the
  layout is reasoned about and compiled, not looked at. Worth a real pass at
  1280px and on a phone before sign-off; the sticky rail and the stepper
  connector are the two things most likely to need a nudge.
- The user referred to a reference image that did not arrive in the message.
  The direction came from their written brief instead, on the existing brand
  orange. A re-attach would likely move the palette and shape language.
- Segment cards show selection through the count badge rather than a tick,
  unlike the other card types. Defensible, slightly inconsistent.

## 2026-09-18 (2) — Marketing Hub home rebuilt to a supplied reference

**Done:** the home screen only (`MarketingPage.tsx` + an appended CSS block).
The builder and the report were not touched.

**Note on state:** the working tree had rolled back to the end of the previous
entry — two intermediate redesigns were not on disk. Built on what was actually
there rather than trying to reconstruct them.

- Laid out to a screenshot the user supplied: gradient banner with a two-line
  headline, primary CTA + "Quick start" card beside it, four stat cards with
  pastel icon chips and a delta pill, a full-width attention bar with a pager,
  one chart panel, then a campaigns **table** beside a quick-actions rail and a
  promo card.
- **The illustration is drawn, not shipped.** A soft disc, a megaphone and
  three orbiting channel badges, all CSS + lucide. The admin has no image
  pipeline and an asset would be one more file to keep in sync.
- **The chart's window selector is real** — 7/14/30 slices the 30-day mock
  rather than relabelling one line.
- Quick actions point at routes that exist (`/offers`, `/reports`, the
  builder); "View Campaign History" expands the table in place.
- Namespaced `hub-` under `.mkt-hub`, so none of it can reach the builder or
  report, which keep the `mkt-` system.

**Palette, second pass:** the reference was blue and the first build copied it
literally. On request it was swapped to the app's brand. Because the colours
were already local tokens it was one block — and the tokens now resolve to
`var(--primary)`, `var(--accent)`, `var(--success-soft)` and so on rather than
to hexes, so the Hub follows a theme change instead of needing to be re-edited
beside one. The slots were renamed `--hub-blue*` -> `--hub-brand*`; leaving
orange in a variable called "blue" would have been worse than the wrong colour.
Two literals kept deliberately: WhatsApp's `#25d366` on its badge, because it
is that product's brand and not ours to restyle, and a darker `#b57a00` for
amber text, because `--warning` is tuned for fills and fails on a pale wash.

**Verified:** `tsc -b`, `npm run build`, `npm run test` 118 passed, three routes
200. Lint unchanged at 4 over baseline, all fetch-on-mount. CSS diff is purely
appended from line 12018.

**Open:**
- **Not visually verified** — no browser tool in this session. The banner
  illustration and the table at narrow widths are the two things most worth a
  real look.
- Currency stays CAD via the app's `formatCurrency`; the reference showed
  rupees. Changing it would misstate the data, so it was left alone.
- The demo-state selector sits at the foot of the rail so the loading, empty
  and error screens stay reviewable. It leaves with the mock layer.

## 2026-09-18 — Marketing Hub, Phase 1 frontend on mock data

**Done:** the whole P1 Marketing Hub UI in `frontend-admin`, end to end and
clickable, with no backend. Three new routes: `/marketing`, the five-step
builder at `/marketing/campaigns/new` and `/marketing/campaigns/<id>/edit`, and
the report at `/marketing/campaigns/<id>`.

- **The seam is `src/services/marketing/`.** `types.ts` is shaped like the JSON
  a `/api/marketing/*` route would return (snake_case, ids not references), and
  `marketingApi.ts` is the only module any screen talks to. It is promise-based
  with simulated latency and can reject — a component written against a
  synchronous mock has to be rebuilt when the network arrives, one written
  against this does not. Replacing the function bodies is the whole migration.
- **`DemoStateSelect`** forces normal / slow / empty / failing. Loading, empty
  and error screens are the hardest thing to sign off because reaching them
  needs a broken server; this makes each one a click. It leaves with the mocks.
- **Reused, not re-invented:** `PageIntro`, `StatTiles`, `ResponsiveTable`,
  `DataToolbar`, `ConfirmDialog`, `StatusPill`, `EmptyPanel`/`ErrorPanel`,
  `TableActions`, `Breadcrumbs`, `AnimatedCharts` (with the existing
  `dashboard-admin-*` chart classNames), and `MenuItemEditorPage`'s
  `.branch-picker`/`.branch-card` markup verbatim for branch targeting. No new
  dependencies. The only genuinely new shape is the phone preview, which has no
  precedent in the admin to borrow.
- **Merge fields are the one piece with tests** (`mergeFields.test.ts`, 9 cases)
  because the failure is invisible in the happy path: a customer with no name
  must never receive "Hi {first_name}" or "Hi null". The preview's recipient
  switcher always ends on that recipient for the same reason.

**Verified:** `tsc -b` clean, `npm run build` clean, `npm run test` 118 passed
(109 pre-existing + 9 new). Dev server serves `/marketing` 200 and every new
module transforms. `git status` shows only `App.tsx`, `Sidebar.tsx` and
`index.css` modified — no unrelated admin behaviour touched.

**Open:**
- Backend, real sending, consent enforcement and every non-push channel are
  explicitly out of scope and not started. Channels other than PUSH render as
  disabled "Phase 2" rows.
- Adds 6 `react-hooks/set-state-in-effect` lint errors, all the fetch-on-mount
  pattern. That rule already fires 39 times across 20 existing files including
  `NotificationsPage` and `OrdersPage`; diverging would have meant inventing a
  data-loading pattern this app does not use. Left consistent, flagged here.
- The mock store is module-scope, so a browser reload resets scheduled/sent
  campaigns to seed. Honest for mock data, worth knowing when demoing.
- Currency renders through the app's existing `formatCurrency`, which is CAD.
  The spec's worked example was in rupees; mock figures are dollar-scale.

**Learned:**
- `push_notification_campaigns` really is a campaign table wearing a
  notification's name — the P1 UI needs almost no columns it does not already
  have. Recorded in the audit doc rather than here.
- The admin's chart components take a `className` that must match existing CSS
  (`dashboard-admin-area-chart`, `dashboard-admin-bars`); they are reusable
  across pages only because of that, which is easy to miss and worth copying.

## 2026-09-18 (2) — One design layer for both apps (4a53cd5, b71fb43)

User: "we have frontend-customer folder where i like that UI so i preffer to
use that type of UI and common component to the frontend-admin". Plan updated
(§5A in `~/.claude/plans/vivid-tumbling-whistle.md`). Decisions: Tailwind v4
only (not shadcn/Radix), one shared stylesheet, first pass = shell + the 9
shared components + form vocabulary + new SaaS screens, Plus Jakarta Sans.

**The finding that made this cheap:** the customer app's look is NOT its 50
shadcn primitives (`<Card>` is imported in 2 files). It is `styles.css` (1,417
lines) + `polish.css` (1,781) — `.elevated-panel`, `.empty-state`, `.skeleton`,
`.status-chip`, the focus halo. That ports as CSS with zero dependencies.
`--primary: #ff5200` was already identical in both apps.

**Done — `frontend-shared/tokens.css`.** Imported FIRST by both apps, so an app
redeclaring a name keeps its own value. Adoption is per token, by deleting a
line. Verified in the built CSS: shared tokens present, admin's values still
winning. Customer dropped its duplicated `:root`/`.dark`, kept its extras.

**Done — the font, which was a real bug.** `--font-sans` named Manrope since
the storefront was written, with no font file, package or stylesheet link ever
shipped. Every visitor had been reading the system fallback — including in the
screenshots that made us like the design. Both apps now self-host Plus Jakarta
Sans. It carries weights 200-800 and 63 places asked for 900 (12 CSS rules +
51 `font-black` utilities), which browsers fake by smearing outlines; all now
800. Page reports zero elements at 900.

**Done — Tailwind v4 in admin, no preflight.** `theme.css` + `utilities.css`
imported separately; the build is grepped for preflight fingerprints. Old CSS
moved to `legacy.css` in `@layer legacy` declared before utilities, so
utilities can override it. **Gotcha:** the admin's `:root` had to be moved back
OUT of that layer — layered loses to unlayered, so the shared tokens would have
silently won and turned a no-op into a visual change.

**Verified empirically, not from the spec:** a throwaway `outline-2
outline-red-500` on `.page-intro` (which a legacy rule already styles) won —
computed `oklch(0.637 0.237 25.331)`, Tailwind's red-500 — then removed. Pages
unchanged, 129 admin tests, typecheck clean, CSS +3.7 KB.

**Next:** `frontend-shared/polish.css` (the signature classes), then the shell
and the 9 shared components, then the SaaS screens.

## 2026-09-18 — SaaS conversion, steps 1-3 backend (a0d1dc6, aacab0a)

Plan approved: multi-tenant SaaS. Subdomain per tenant, each restaurant brings
its own WhatsApp number, Stripe Connect, admin shell before page migration.
Plan file: `~/.claude/plans/vivid-tumbling-whistle.md`.

**Done — tenant resolution by host.** New `app_client_domains` (host globally
unique) + `AppClientDomainKind`. Deliberately NOT a `WEB` row in
`app_client_identifiers`: that table is keyed `(platform, identifier,
environment)` so STAGING and PROD could both claim one host, and its platform
enum is load-bearing in ~6 places that assume iOS/Android only.
`app_clients.normalize_host` / `find_app_client_by_host` /
`resolve_app_client_by_host` / `platform_host_for`, and the status checks both
lookups share moved into `_assert_client_usable` so a SUSPENDED tenant cannot
still serve through whichever path was used. `/app-config` resolves bundle id
first (mobile untouched), then **`X-Forwarded-Host`** — never raw `Host`, which
the client controls. Unknown host is 404, not a silent marketplace fallback.

**Done — credentials at rest.** `services/secrets.py`, Fernet, keyed by
`SECRETS_ENCRYPTION_KEY`. Refuses rather than storing plaintext when unset;
a value that will not authenticate raises rather than being returned as-is.
`cryptography` named directly in requirements (was transitive via python-jose).

**Done — branding per tenant.** `services/app_branding.py`: logo, dark logo,
favicon, cover, accent, font (allowlist + resolved CSS stack), app name,
tagline. Validated on the way in (`javascript:`/`data:` URLs refused, control
characters stripped, length caps); every key always present on read so a
half-onboarded tenant still renders. Wired into `build_app_config_response`,
which keeps its existing precedence — `Restaurant.theme` wins on
`primary_color` because that is what the owner controls.

**Gotcha:** the migration backfilled hosts from `lower(app_key)`, which keeps
underscores — invalid in DNS and not what `platform_host_for` generates. Fixed
in the migration and repaired in place. `_to_host_label` hyphenates.

**Verified:** suite 1688 OK (was 1655). Migration 0062 applied to Supabase; all
six seeded restaurants now resolve by host. Live: `bangkok-bowl.localhost` and
`dragon-wok.localhost` return different restaurants from `/app-config`,
`nobody.localhost` 404s, bundle id still works, neither gives a 400.

**Scope note (user, same day):** hosting is out for now — development and
management only. No DNS, certificates or deploy work. Subdomains already work
in development because browsers resolve `*.localhost` to 127.0.0.1 unaided.

**Done — admin route table (step 4, commit f4f0dae).** The same decision was
being made in four places: a 150-line nested ternary in `App.tsx`, a
`staticAllowed` map, and two `Set`s in `Sidebar.tsx`. They had drifted —
ADMIN could open `/menu-items` and `/generated-combos` (both pages have
deliberate admin-wide branches) and the sidebar offered neither. New
`src/routes.tsx`: one `RouteDef` per address carrying pattern, roles,
`restaurantOf`, nav entry and render. `navFor(role)` builds the sidebar from
the routes themselves. Owner scoping was five near-identical id checks, now
one rule. `App.tsx` 534 -> 144 lines. No new dependencies.

**Verified:** `tsc --noEmit` clean, `npm run build` clean, 129 vitest tests
(20 new). In the browser as an owner: navigation, the bounce from Dragon
Wok's URL back to their own restaurant, the sidebar highlight holding on an
order detail, no console errors.

**Next:** admin shell + tenant switcher + tenants list (step 5), then the
onboarding wizard. Customer app SSR + de-Bangkok rename (step 3 frontend) is
lower priority while hosting is out of scope.

## 2026-09-17 (7) — The order waiting to be paid (commit 580eb17)

**Done:** new `app/services/ordering_agent/open_orders.py` — `waiting_order`,
`lines_of`, `can_move`, `move_to`, `abandon`, `payment_link_for`. Placing a
card order empties the cart and clears the draft, so between the link and the
payment the order was the only record of what somebody wanted and nothing in
the conversation could reach it.

- **Move:** an unpaid order can be rescheduled; `schedule_slot_is_available`
  decides, and `can_move` refuses once anything is charged.
- **Pay:** `pay_now` in the reading resends the same Checkout session.
- **Drop:** `PAYMENT_ABANDONED` (the reason the enum already has), actor
  CUSTOMER, reconciled with the provider first exactly as the reaper does —
  `abandon` returns False if the money actually landed, and the turn says so.
- **Never on a guess:** cancelling is always a question, a message naming a
  dish never reaches it ("remove the corn fritters" read as a cancellation),
  and the question is asked the way round they raised it (`drop_order` vs
  `keep_order`) so the natural yes does not do the opposite.
- **Nothing lost:** a cancelled order's dishes are offered back and re-added
  through `_run_add`, re-resolved against the live menu.
- A dismissed Stripe payment offers the same instead of ending the thread;
  `_offer_the_dishes_back` holds the standing question on the chat draft.
- A turn with nothing else to do mentions an unpaid order, twice at most
  (`OrderDraft.waiting_asks`).

**Two real bugs found while testing:** `loop.py` never imported `uuid` (with
`from __future__ import annotations` every `uuid.UUID` in a signature is a
string, so nothing had needed it at runtime) — the NameError was swallowed by
the rag fail-open seam and showed up as reply-pipeline prose. And `_run_add`
was refusing the restored lines because the add guard only accepts ids this
turn has seen; `guards.grow_seen_ids(seen, args)` first.

**Verified:** suite 1655 OK. Live end to end: place -> "Sorry! I need this
order tomorrow at 7 pm" -> moved, link reissued; "send me the payment link
again"; "cancel that order" -> "Shall I cancel it?" -> yes -> cancelled ->
"Shall I put those dishes back?" -> yes -> basket restored and readable.

## 2026-09-17 (6) — Ordering for a day that is not today (commit cc2fe86)

**Done:** four faults in one screenshot.
- "I need this order tomorrow" had nowhere to go: the reading had no shape
  for a day without a clock time, so it returned `when=None` plus
  `asks_hours=True` and was answered with TODAY's hours. `when` now accepts
  a bare `"YYYY-MM-DD"`, and `asks_hours` is false whenever `when` is filled.
- `loop._take_time` treats a 10-character `when` as a day that still needs a
  time: it records `needs_a_time` with that day's own hours and holds the day
  on the standing question (`yes="time_on_day"`, subject=the ISO date). The
  loop passes it to `read_order_intent(for_day=...)`, so the "3 PM" that
  comes back lands on Friday rather than on nothing.
- `describe_time_settled` (new, in both answer chains) says a time that was
  kept and asks about a day that still needs one. Previously a kept time was
  answered with silence, and the reply pipeline filled it with two answers
  that contradicted each other ("yes at 3 pm" then "not at 3 pm").
- A refused time offers `next_available_slot_start(reference_dt=max(chosen,
  now))` — the refusal for the 18th had offered Thu 15:00, the day before.
- `restaurant_locations.describe_hours` names a future day ("Delivery on
  Friday") instead of "today", and omits "we are open now" for another day.
- `_take_time` defaults to DELIVERY when nobody has said, like everywhere
  else that guesses; it had said "Pickup" to a customer who wanted delivery.

**Verified:** suite 1642 OK. Live: "18th Sep" -> asks the time with Friday's
hours -> "3 PM" -> "Right, I have that down for Fri 15:00" -> details ->
read-back showing "For Fri 15:00" -> placed for Fri 15:00 with the link.
Also "tomorrow at 7 pm" in one sentence, a closed future time (offers Sat
10:30, never earlier), and a real hours question still answered as one.

**Not done:** changing the time of an order ALREADY placed. The screenshot
began with that ("Sorry! I need thos order tomorrow" after the payment link),
and there is no path for it — the cart is emptied at placement. Worth adding.

## 2026-09-17 (5) — Suggesting when they want more (commit fcc09ca)

**Done:** "I want to add more item in my cart" was answered with the cart
they had just been shown. The reading matched nothing in that sentence — no
dish, no section — so the turn had nothing to do and fell back to
`cart_readback`, the last resort in `_settled`.

`read_order_intent` now reports `wants_to_add` (wanting more without saying
what), and `tools.dishes_to_suggest` answers it from rows: bestsellers then
popularity, excluding what is already in the cart and the sections it
covers, **at most one item per section** — ordered by popularity alone the
three suggestions came back as three main courses to a customer already
holding a pizza. `loop._suggest_more` says them and holds an answerable
question ("Tell me the name and I will add it"), so the next message lands
on the add path.

**Verified:** suite 1634 OK. Live: pizza list -> "I love Green Curry Pizza"
-> yes -> cart -> "I want to add more item in my cart" -> three suggestions
from three different sections -> "thai iced tea" -> offered -> yes -> added.
Backend + worker restarted on fcc09ca; sessions cleared.

## 2026-09-17 (4) — Calling a customer by their name (commit 6bcb94b)

**Done:** the name is said at three moments, not on every line: the
greeting, the order read back before money is spent, and the payment
landing or failing. `order_draft.first_name` decides what is worth saying —
first word, capitalised only if typed all lower case, so "McDonald" and
"d'Souza" survive; an email in the name box, a single initial or something
absurdly long returns None and the sentence reads correctly without a name.
`payments.service._called` does the same for an order row.

**The trap:** the greeting response cache is keyed on the greeting ALONE
(`_greeting_response_cache_key`) and shared by every customer who sends one.
A name written into that text would be said to the next person who said
hello. So `rag._greeting_with_name` is applied after the cache is read and
written, and the stored copy stays impersonal. `_customer_first_name` reads
the signed-in account or, for a guest, the account behind the verified
phone.

**Verified:** suite 1629 OK. Live: "hi" -> "Good afternoon, Vishal 👋 ...",
then add / deliver / confirm details / read-back ("Here is your order,
Vishal:") / placed with the link, total matching. Payment messages checked
directly, with and without a name. Backend + worker restarted; sessions
cleared.

## 2026-09-17 (3) — The order is read back before it goes (commit 87d21ca)

**Done:** a real restaurant repeats the order before charging for it. The
last thing before an order exists is now the order itself — every line, the
total, where it is going and when, and one question ("Shall I place it?").
`loop.describe_order_to_confirm` builds it; the total comes from
`price_quote` -> `validate_order_draft`, the same arithmetic checkout runs,
with the fee and the tax on their own lines. The first cut read back $16.98
over an order placed for $20.62.

Every path that can place is gated on `_order_stood_behind()`: the
`if records:` path, the top-of-round place, the answer path and the round
cap. `OrderDraft` carries `order_confirmed` and `place_asks` (asked at most
twice — the order is created unpaid and the link is what spends money).
A cart that changes after they agreed clears the flag and is read back again.

Also: `read_order_intent` returns `add` as a LIST, so one English sentence
can order several dishes; pausing ("no wait", "hold on", "one sec") is a
decline rather than silence; `_hold(..., asks=...)` gives the model a short
question instead of the read-back, which it was mining for the customer's
own address (a "yes" came back carrying a delivery address, was read as a
new instruction, and the order was read back a second time); agreeing to
details now gets on with the order instead of falling to the reply pipeline;
and details typed for a pickup are not read back again.

**Verified:** suite 1620 OK. Live on the test number: delivery, pickup,
returning customer, pausing and resuming, Hinglish agreement, declining then
adding more — every one ending in a placed order whose total matches the one
read back. Backend + worker restarted on 87d21ca; sessions cleared.

**Open:** ngrok webhook still in place for Mr Tailor; qwen3 turn times 3-8s.

## 2026-09-17 (2) — "Yes" means the question we just asked (commit e54972d)

**Done:** the agent ended every turn with a question and remembered none
of them, so a bare "Yes" fell through to the reply pipeline. `OrderDraft`
now carries `awaiting` (JSON: the question in our own words, what agreeing
does, and the dish in question). `loop._hold` writes it as each read-back
asks; `_answer_standing` acts on the reply. `read_order_intent` gained an
`asked` slot that states the question verbatim, so "haan bhai kar do",
"nothing else" and "yes and add a thai iced tea too" are all read correctly
— no word list in code.

Also: `read_order_intent` gets the branch's real menu sections
(`tools.menu_categories`) and returns `category`, so "some drink" finds
Beverages; a named dish beats a guessed section; `dishes_to_show` stems
plurals and matches a named section exactly; one matching dish is offered
("Thai Iced Tea is $4.14. Shall I add one?") instead of listed; `describe_applied`
asks one question ("Anything else?") not two; checking out an empty cart
says so. The plain-sentence fast path yields to an open question for
"checkout" only — "go ahead"/"kar do" are how people agree — while plain
cart and menu reads keep it.

**Verified:** suite 1610 OK. The screenshot conversation replayed live end
to end: drinks, naming a dish, "Yes", cart, "haan bhai order kar do",
details, minimum-order guidance. Backend + worker restarted; test sessions
cleared.

**Open:** no explicit read-back of items and total before placing (the user
has asked about adding one); ngrok webhook still in place for Mr Tailor.

## 2026-09-17 — WhatsApp messages dressed for the phone (commit ec9a472)

**Done:** `format_for_whatsapp` in `backend/app/services/whatsapp.py`, applied
inside `send_text` so every outgoing message (agent, payments notifications,
reply pipeline prose) gets it. Bold on amounts, the dish just added, the time a
scheduled order is for, and receipt labels; `- ` lists become `• `; ✅ / ❌ on a
payment that landed / failed; 🛒 on the cart. The pipeline's `**markdown**`
had been reaching phones as literal asterisks — it now becomes WhatsApp bold.
`describe_cart` (loop.py) reads one dish per line on every channel with
"Subtotal: $x" (was one run-on sentence). Idempotent; links untouched.

**Verified:** suite 1597 OK; three real turns sent to the test number and the
exact delivered bodies printed (menu list, add, cart) — all formatted.
Backend + worker restarted on ec9a472; test sessions cleared.

**Open:** qwen3 speed (menu ~11s, add ~8s, cart 1.7s); seed prices odd; Meta
webhook still points at the ngrok tunnel — restore
`https://mrtailor-api-prod.onrender.com/api/v1/whatsapp/webhook` when done.

## YYYY-MM-DD — short title

**Goal:** what was asked.
**Changed:** files/areas touched, one line each.
**Verified:** exact commands run and their result. "Not verified" if not run.
**Open:** anything unfinished, deferred, or uncertain.
**Learned:** non-obvious things worth keeping (promote permanent ones to CLAUDE.md).
```

---

## 2026-09-16 — Every admin save was breaking every cart holding that dish

**Goal:** `half-pizza-end-to-end.spec.ts` passed in the morning and failed in
the afternoon with "The selected size is unavailable for Build Your Own Pizza"
on the checkout screen. Find out why, fix it, push.

**Found:** `_sync_menu_item_customizations` cleared `menu_item.sizes` and
`menu_item.customization_groups` on every save and rebuilt them from the
payload. Same names, same prices, all-new UUIDs. A cart lives in the browser
holding `menu_item_size_id` and `option_id`, and `resolve_menu_item_selection`
refuses ids it cannot find — so an owner correcting a price broke every cart
already holding that dish, and the customer had no way out but deleting the
line. The test failed in the afternoon because dishes were being saved in the
admin panel then (the size rows for a dozen dishes were recreated at a human
pace over two hours, none of it in the local backend log — a deployed API on
the same Supabase database, most likely), and not in the morning because
nobody was.

**Changed:**
- `backend/app/api/menu_items.py` — sizes, groups and options are now
  reconciled in place: matched by id when the client sends one, then by name,
  per scope (item-level vs each size, so two "Toppings" groups cannot swap).
  Unclaimed rows are deleted. Docstring carries the incident.
- `backend/app/schemas/menu_item.py` — optional `id` on size, group and
  option payloads.
- `frontend-admin` — the editor sends the size id it is editing (only real
  UUIDs; its own `size-xxxx` draft ids stay client-side). Groups/options are
  merged across sizes in the form and have no single server id, so they rely
  on the name match.
- `frontend-customer/src/routes/checkout.tsx` — a 400 from the order endpoint
  now links back to the cart instead of being a dead end.
- `backend/tests/test_menu_item_save_identity.py` (8) and
  `frontend-customer/e2e/menu-save-identity.spec.ts` (2) pin it.

**Verified:** backend `unittest discover` 1199 OK; the six admin-save and
split-pizza specs pass on desktop; DB rows for the pizza keep yesterday's
`created_at` across six saves; admin `npm run build` OK. Full E2E and customer
build were running at the time of writing — see the commit for the outcome.

**Open:**
- The fix only protects carts once it is deployed wherever else the admin panel
  saves to (`restaurant-rag-api-xjfx.onrender.com`); until then a save from
  there still rotates ids.
- A rename from a client that sends no ids (mobile, seed) still replaces the
  row. Deliberate: there is nothing to match on.
- From 2026-09-15, not yet in this log: the WhatsApp channel
  (`backend/app/api/whatsapp.py`, worker task, 33 tests) is built and was
  answering; the Meta webhook still points at the ngrok tunnel and must go back
  to `https://mrtailor-api-prod.onrender.com/api/v1/whatsapp/webhook`; the
  Celery worker is down, so WhatsApp does not answer right now.
- Suggestions offered and not acted on: reorder, 71/117 dishes without photos,
  streaming the concierge reply, unpaid-order reaping, three dishes over $100.

**Learned:**
- On Windows the venv `python.exe` is a launcher; `uvicorn` shows as two
  processes (launcher + `Python.3.11_...`). Kill both or the port stays held.
- The backend runs without `--reload` here. A code change is not live until
  it is restarted; a green run against the old process proves nothing.
- Supabase's 15-connection cap: backend + full unit suite + E2E together can
  starve an ad-hoc DB query with `EMAXCONNSESSION`; it is not a code failure.

---

## 2026-09-14 (10) — The halves were being dropped at checkout

**Goal:** follow one half-and-half pizza from the dish page to what the server
stores, because every piece had been tested and the joins between them had not.

**Found, and it was the expensive kind.** `checkout.tsx` built its order
payload as `{option_id, quantity}` and never sent `portion`. So every split
pizza reached the server as a WHOLE one: the kitchen would have put both
toppings over the whole pizza, and the server priced two whole toppings against
a screen that had charged for two halves. The API type had carried `portion`
since the feature landed; the one caller did not fill it in.

**Two display holes beside it.** The cart listed toppings by name alone, so
"half pepperoni, half mushroom" and "both all over" were the same text at
different prices. The checkout summary showed the dish name and price and
nothing else — not even the size, so a Large half-and-half and a Small plain
pizza were two identical lines. Both now carry the size and each topping's
half (`chosenLabels`).

**Also fixed this session:** switching a group between "same all over" and
"half & half" carried the choices across unchanged, so one topping chosen whole
plus one chosen per half came back as TWO toppings on the whole pizza — over a
cap of one. `regroupForMode` re-rations the choices for the mode being entered
and visibly unticks what no longer fits.

**Learned — do not re-derive:**
- **Test the joins, not just the pieces.** Six half-and-half specs passed while
  the feature was being discarded one screen later. The end-to-end spec
  (`half-pizza-end-to-end.spec.ts`) follows one order through the dish page,
  the cart, the checkout summary and back out of `/orders`.
- **`uvicorn --reload` in this app is not reliable.** A reload takes long enough
  (embedding warm-up, Supabase connect) that the old worker keeps serving, and
  a reload that does not finish leaves the old code answering while the log says
  "Reloading...". Restart it properly and wait for "Application startup
  complete".
- **A backend started outside this session cannot be restarted from it.** Port
  8000 was held by PIDs invisible to the agent's session — `taskkill` reported
  "not found" while they answered requests, and a new uvicorn failed with
  `[Errno 10048]` bind-in-use, silently, so the stale server kept serving.
  Check the bind actually succeeded before trusting a "restart".
- The giveaway that a server is stale: an error message the current source
  cannot produce. "Toppings allows at most 1 selections" against a payload
  carrying LEFT and RIGHT could only come from code predating the per-half cap.

**Open:** `half-pizza-end-to-end.spec.ts` cannot pass until that backend is
restarted — the code is right and the server is old. Everything else is green.

---

## 2026-09-14 (9) — The topping cap counts on each half

**Goal:** reported from a screenshot — six toppings spread across two halves of
one pizza. "Either left-right, or full; if I select full then don't allow
anything extra; if I select left and right then don't allow any other thing."
Plus: the limits must come from admin and change without a deploy.

**Now:** `max_selection` counts on EACH half once the item is split. Two on the
left and two on the right under a cap of two, rather than two shared between
them — the halves are two orders of the same size sharing a base, and counting
across both sold one topping per side under a cap of two.

That makes the reported shape a data setting rather than a special case: a cap
of **1** is exactly "half this, half that, nothing else", and the owner can
change it in the dashboard at any time. `e2e/admin-menu-sync.spec.ts` proves
the link by setting the cap to 1 through the same endpoint the dashboard uses,
checking the web menu obeys it, and putting back whatever was there.

**Learned — do not re-derive:**
- **The backend was serving code from before the halves rules.** Restarted
  without `--reload` hours earlier, so `/orders/validate` accepted "whole
  beside a half" — 200, while the unit test for the same rule passed. Every
  green E2E result in between only proved the CLIENT was enforcing it. It now
  runs with `--reload`. Checking the rule over HTTP is what caught it; the unit
  tests could not.
- **`minimum_order_amount` is validated before customizations**, so a cheap
  test order is refused for its total and the customization rule under test
  never runs. Order two.
- A test that mutates menu data must restore what it READ, not a hardcoded
  number, or it quietly rewrites the menu for everyone after it.
- Three E2E runs were thrown away this session for being measured against
  changed code or a stale server. A run started before an edit is not evidence
  about the code after it.

**Open:** the owner's cap on the pizza is still 7, so nothing visibly changes
there until someone sets it to 1 — that is the dial, and it is theirs.

---

## 2026-09-14 (8) — Half and half is one question, not many

**Goal:** the owner's two rules for a splittable group — a split item has to
describe BOTH halves, and a group is either the same all over or split, never
a mixture.

**Enforced on the server** in `resolve_menu_item_selection`, per group: a lone
LEFT (or RIGHT) is refused by name, and WHOLE beside a half is refused. Read
from the portions the CUSTOMER chose, before left+right of one option collapses
to WHOLE — after that collapse "pepperoni on both halves" is indistinguishable
from "pepperoni on the whole pizza", and the two mean opposite things to these
rules.

**The client had to stop inferring the mode from the toppings.** First attempt
judged each option against the rest of its group and produced two dead ends:
the first topping lands on the whole item, which switched the halves off before
a split could start; and with two toppings on the whole item neither could move
to a half, because each read the other as whole. The rule is about the GROUP,
so the customer now answers it once — a "Same all over / Half & half" switch at
the top of the group — and the per-topping picker offers Left and Right only.
"Whole" is not a third choice beside the two halves; it is the other answer to
the question above.

**Learned — do not re-derive:**
- **A per-item rule inferred from per-item state locks itself.** Any constraint
  of the form "these things must agree" needs somewhere to hold the agreement.
  Putting it on the group made the dead ends impossible rather than handled.
- **Validate on what was chosen, normalise afterwards.** The LEFT+RIGHT → WHOLE
  collapse is right for pricing and for the kitchen ticket and wrong for the
  rules, so the rules read a snapshot taken before it.
- A topping ticked into a split group lands on whichever half is still bare
  (`defaultPortionFor`). Landing it on "whole" would create the forbidden
  mixture one tap after the rule started applying.
- Three existing tests ordered half a pizza and said nothing about the other
  half — legal before, not now. The rounding one moved its assertion from the
  order total to the olives line, because a legal split order always has a
  second topping in the total and it buried what the test was pinning.

**Open:** the rule forbids "pepperoni on the whole pizza, mushroom on the left
only", which some kitchens do allow. That is the owner's stated rule, not an
oversight — but it is the first thing to revisit if a restaurant asks.

---

## 2026-09-14 (7) — The admin was switching half-and-half off

**Goal:** three reports — does half-and-half respect the per-group selection
rules, show the min/max an owner sets, and "changing a predefined thing in the
menu item editor then saving does not update".

**The save bug, measured rather than guessed.** Driving the real admin UI:
editing a group's min/max and saving sent `min=2 max=4`, answered **200 in
2.8s**, and the value was in the database afterwards. Editing an option's price
did the same. So the general save works — what does not is one field:

**`frontend-admin` never knew `supports_halves` existed.** It was absent from
both the read interface and the payload interface, so the editor could not show
it and did not send it. `_sync_menu_item_customizations` rebuilds every group
from the payload, so the server reset the column to its default on every save:
**editing a description switched half-and-half off.** That is what wiped the
flag set on 2026-09-14 (4), and why all six half-pizza e2e tests quietly
SKIPPED in the run after — the spec discovers its item by the flag, found
none, and skipped rather than failed.

**Fixed:** the flag is carried through the types, the form state, the draft,
the merge signature and the payload, and an owner sets it with a "Half & half"
checkbox in the composer and the group editor. Offered only on MULTI, because
one choice cannot cover two halves. Verified end to end through the browser:
ticked in the UI, sent as `supports_halves=true`, 200, and read back true.

**Also fixed — the group row's first column was 0px wide.** Measured
`grid-template-columns: 0px 180px 100px 90px 100px 110px 234px`: every column
after the title declared a fixed minimum, those plus the six 12px gaps used the
entire 886px row, and the title's `minmax(0, 1.15fr)` got what was left, which
was nothing. The title then overflowed its zero-width cell and drew on top of
the sizes — "Crust" and "Small (8\")" on the same pixels. Titles now declare a
real minimum. The size checkboxes in the composer had the same problem and were
clipped to "S (-"; they get their own full-width line.

**Customer side:** `selectionHint` puts both numbers in one sentence ("Choose 2
to 4", "Choose exactly 3", "Choose up to 7") with a live "· 3 chosen", and
`canPickMore` greys out further options at the ceiling. The cap was checked
only at the Add button before, so a seventh topping went on and the refusal
arrived at the end.

**Learned — do not re-derive:**
- **A rebuild-from-payload endpoint turns every missing client field into a
  silent reset.** `_sync_menu_item_customizations` clears `sizes` and
  `customization_groups` and recreates them, so anything the admin does not
  send is not "left alone", it is erased. Any new column on those tables needs
  the admin updated in the same change.
- **A skipping test is not a passing test.** The half-pizza specs went from 3
  passing to 6 skipped and the suite still reported green. The skip count moved
  from 6 to 12 and that was the only visible sign.
- **Drive the UI before reading it.** Two hours of plausible hypotheses about
  the editor's draft state were wrong; ten minutes of Playwright against the
  real admin found both the working save and the 0px column.
- Restoring data touched while debugging needs the ORIGINAL values written
  down first: this run left `Toppings` at min=2/max=4/required and Mozzarella
  at $9.25 before they were put back to 0/7/optional and $1.75.

**Open:** the menu-item save takes ~2.8s and shows only "Saving…". The admin
lints with 51 pre-existing errors (unchanged by this work).

---

## 2026-09-14 (6) — Checkout already knew who was ordering

**Goal:** reported — a signed-in customer should not be asked for their name,
number and address on every order.

**What was already there:** all of it. `users` carries `full_name`,
`phone_number` and a free-text `default_address`, and the backend has had
`/profile/me` and a full structured **saved addresses** CRUD
(`/profile/addresses`, with HOME/WORK/OTHER labels and an `is_default`) since
before this web app existed — the mobile app writes them. The web app called
none of it. No backend change was needed; this is four client files.

**Now:** checkout fills the name and number from the account, and the address
from the default saved address. Every field stays editable, and the form says
where the answers came from rather than filling itself in silently. More than
one saved address gets tiles to switch between them. A new address offers to
save itself, so the second order is already filled in — without that the
feature is dormant for anyone who has never used the mobile app.

**Learned — do not re-derive:**
- **The saved-address parts map one-for-one onto the checkout form.**
  `address_line_1/2`, `landmark`, `city`, `state`, `postal_code` are exactly
  the fields collected on 2026-09-14 (2). Nothing to translate, so
  `addressFromSaved` is a rename and nothing more.
- **`users.default_address` is ONE free-text column, not an address.** Parsing
  it is a guess by shape: taken apart only when it is comma-separated and ends
  in something postal-code-shaped, and otherwise dropped whole onto line 1.
  Spreading a wrong guess over five fields is worse than filling one — every
  wrong field is one the customer has to find, and a plausible wrong city
  reaches a rider.
- **Save on order creation, and dedupe.** Without the dedupe every e2e run
  added another copy of the same street to the test account; with it the count
  stayed at 1 across two runs (verified). An address typed into an abandoned
  form is not one the customer asked to keep, so nothing is saved until the
  order exists, and the save's failure is swallowed — "we could not save your
  address" is not a thing to interrupt a payment with.
- **A ref cannot be read for rendering.** The "filled in from your account"
  note was first driven by the same `useRef` that guards the one-shot prefill;
  changing a ref causes no render, so the note appeared only because unrelated
  state happened to change in the same pass. It has its own state now.
- Editing a prefilled address clears the "this is the saved one" link, so the
  save box comes back. Otherwise a corrected flat number is typed, sent, and
  forgotten by the next order.

**Open:** the web app still has no screen for MANAGING saved addresses — they
can be created from checkout and read anywhere, but renaming, relabelling and
deleting are mobile-only. `phone_number` is stored formatted here ("(415)
555-0132") and bare on `users`; both read back fine, but nothing normalises
them to one shape.

---

## 2026-09-14 (5) — The dish page's two columns

**Goal:** reported from a screenshot — the dish page looked wrong on a
desktop.

**What was actually wrong:** the columns were split picture / everything-else.
The left column held one 460px image; the right held the name, the description,
the price, every choice, the total and the button, and ran to three screens. So
the first thing anyone saw was a wide black rectangle of nothing, and the
button that ends the task was below all of it — on a 1900x916 display the Add
button was not on screen at any point until you scrolled past the toppings.

**Now:** the picture and what the dish IS travel together on the left and stay
put (`position: sticky`) while the decisions scroll beside them; the rail holds
only decisions. Quantity, total and Add are pinned to the bottom of the rail,
so the price and the button are on screen the whole time, and so is the line
saying which group is still unanswered.

**Learned — do not re-derive:**
- **`bottom: 0` is wrong on a phone.** The pinned block landed behind the
  four-icon tab bar: visible, and untappable. It offsets by `--mobile-nav-h`
  (a new token in `styles.css`, with a matching `min-height` on
  `.mobile-nav-bar` so the number is true rather than guessed) and drops back
  to `0` at `lg`, where there is no tab bar.
- **Sticky only buys what the taller column lends it.** The lede sticks for
  `row height - lede height` and no further, so on a short dish (wings: 672 vs
  993) it barely moves. That is fine — the balance is what fixed the hole, and
  the stickiness pays on a long dish.
- **Screenshotting the app needs `http://localhost:5173`, not
  `127.0.0.1:5173`.** Only `localhost` is in the backend's CORS list, so on the
  IP every fetch fails and the page sits on its skeleton forever — which looks
  exactly like a hung query. Ten minutes went into that.
- `"From $11.99"` now becomes the chosen size's real price once a size is
  picked. Leaving "From" up asks the customer to keep discounting the headline
  against a number they have already chosen.

**Open:** the pinned block takes ~190px of an 851px phone, which is the usual
shape for this pattern but is a lot on a small screen. Not tuned further
without someone actually using it.

---

## 2026-09-14 (4) — Customization correctness, and half-and-half

**Goal:** a long list of reported customization bugs, then a new feature —
half-and-half toppings — plus a checkout address form and assorted UI work.

**The through-line:** the customer app kept its OWN copy of rules the backend
already owned, and the two disagreed. `MENU_ITEM_CUSTOMIZATION_FLOW.md` says a
selected size price REPLACES the base; the app ADDED it, so a $12 bowl with a
$15 Large read $27 through the cart and on the Pay button while Stripe charged
$15. `lib/customization.ts` now holds those rules once, mirroring
`services/menu_item_customizations.py`.

**Fixed:** size pricing (and therefore the checkout-total mismatch — one bug,
not two); inactive sizes and options rendered and selectable (the client types
did not even carry `is_active`); size-scoped groups shown under every size
(`menu_item_size_id` likewise missing); "not required" with `min_selection: 1`
labelled optional; concierge cards hardcoding `has_sizes: false` so a sized dish
was added at base price and refused at checkout; past orders showing no size or
options (the API always sent the snapshot); and three admin-side data states the
schema allowed — `min_selection` above the option count, the required/minimum
contradiction, and MULTI groups defaulting to `max_selection: 1`.

**Half-and-half:** `menu_item_customization_groups.supports_halves` (0060) plus
`portion: WHOLE|LEFT|RIGHT` on each selected option. No new entity and no "half
pizza" product: it is a flag the owner sets in admin, and the customer UI offers
the split only where that flag is on. A half costs HALF the option's extra
price — a product decision, documented; the same option on both halves
normalises to WHOLE so the ticket reads "Pepperoni" once.

**Learned — do not re-derive:**
- **I was wrong that the size bugs were unreachable.** I said "seed.py creates
  no sizes, so this is latent". `seed.py` indeed has none, but the DATABASE has
  **63 items with sizes, 140 with customizations, 261 groups** — the data came
  from somewhere else. The $27-shown / $15-charged bug was live on real data,
  not latent. Survey before concluding something is unreachable.
- **Two columns of options is worse than one.** Tried it to save height: option
  names wrapped to three lines and the PRICE was clipped to "+$1.7". A price
  that lies is not a saving. One column, a tighter row, and a foldable group
  (which returns ~640px) is the answer.
- **Hardcoding anything about the menu in a test is a trap.** The half-and-half
  spec was pinned first to an item id, then to topping names; both broke,
  because which item is splittable is admin data. It now asks the API which
  item carries the flag and drives whatever it finds.
- **The menu-items LIST endpoint is location-filtered.** 516 items exist but
  only ~166 appear across the six restaurants' lists. An item flagged on the
  wrong location is invisible to the customer app — which is exactly what
  happened on the first attempt at test data.
- The list response already carries each item's `customization_groups`, so
  discovery needs one request per restaurant, not one per dish.
- **The picker's lead time drifted away from the server's.** Another session
  changed `_get_prep_buffer_minutes` to SUM preparation time and the ETA
  (commit `384aa7a`) where it had taken the larger; `leadMinutes` in
  `branch-hours.ts` still took the larger. The picker offered a slot 29 minutes
  out on a branch that would not serve it for 49, and the customer learned that
  from a red alert AFTER filling in the whole checkout form. Found by the
  payment E2E, not by reading. Both sides of that rule have to move together
  — the comment in `leadMinutes` now says so. Within the hour the same
  session changed it AGAIN (`dc63f32`, prep only with the ETA as a fallback,
  because the window is when the shop stops taking ORDERS); the picker
  followed that too before pushing. Three different rules in one day is the
  argument for the comment, not against it.

**Open:** three seeded menu items are priced over $100 (a Margherita at $249)
— leftover rupee values never converted, in the same area another session is
actively changing. Not touched. The business timezone is still one global
setting. `frontend-admin` has no UI for `supports_halves` yet: the column and
the API accept it, but an owner cannot tick it from the dashboard.

---

## 2026-09-14 (3) — Prep-time cutoffs, and the restaurant's clock

**Goal:** two asks from the product side. Show the exact arrival time next to
the ETA, and make every time in the app belong to the RESTAURANT's timezone
rather than the device's. Plus: slots must leave the kitchen time to cook, and
must come from the branch the order is actually placed against.

**Fixed:**
- **The picker offered the closing minute.** A branch closing at 11pm with a 15
  minute prep time let someone book 11pm. ASAP ordering already refused this
  (`get_location_fulfillment_status`); SCHEDULED did not — both the generator
  and the validator used `<= slot_end`. The last bookable slot is now the last
  grid point at or before `closing - max(prep, eta)`. Measured on the seed:
  closes 22:00, 24 minute buffer, last slot was 10:00 PM, now 9:30 PM.
  Enforced in `list_available_schedule_options` AND `schedule_slot_is_available`,
  with a distinct message ("the latest time that day is ...") because "too late
  to cook" and "not available" send the customer somewhere different.
- **Checkout priced and scheduled against the wrong branch.** It read
  `currentLocation` (the branch picker's selection) while placing the order
  against `cart[0].restaurantLocationId`. Store now exposes `orderLocation`.
- **Every time in the app was built on the DEVICE clock.** See below.
- **"Schedule for later" with no time picked silently placed an ASAP order.**
  The Pay button was gated on the branch being shut, not on scheduling being
  chosen. They asked for later and would have been charged for now.
- The picker was a timetable: now leads with "Earliest available", shows six
  upcoming times with the rest behind "Show all N", and has a native time field
  (minutes + am/pm from the platform's own wheel) bounded to the day's first and
  last bookable time and snapped onto the branch's interval.
- ETA now reads "Arrives in about 29 min · by 2:57 p.m." on cart, checkout and
  the order summary.

**The timezone work, which is the part worth reading:**
- `business_timezone` ("Asia/Kolkata") already existed on the backend as the one
  clock everything is computed in. It never reached the client. It now rides on
  `/app-config`, so changing that single setting moves the whole app — nothing
  hardcodes a zone or an offset.
- `frontend-customer/src/lib/timezone.ts` (new) does the arithmetic with `Intl`.
  No library and no stored offsets: America/Toronto is -04:00 in July and -05:00
  in January, and a table goes stale. `zonedTimeToUtc` runs TWO passes — guess
  the offset from the naive instant, then re-read it at the corrected one —
  which is what makes the hour either side of a DST change come out right.
- Every `branch-hours` helper takes an optional trailing `timeZone` that falls
  back to the device's. The refactor therefore changed no behaviour until the
  routes started passing the branch's, which kept the existing tests meaningful.
- Two things only became visible once the zone was real: the branch's WEEKDAY
  can differ from the device's (20:00 UTC Monday is already Tuesday in Kolkata,
  and the slot table is keyed by weekday), and snapping a custom time to the
  interval must use the BRANCH's minutes, because a half-hour offset means the
  two clocks disagree about minutes past the hour.

**Verified:** 1027 backend tests, 98 frontend unit tests, 35 E2E. The decisive
one is `e2e/timezone.spec.ts`: a Playwright context pinned to America/Toronto
picks a slot and the SERVER accepts it, and the same page in Toronto and in
Kolkata lists identical times.

**Learned — do not re-derive:**
- **This machine is in Asia/Calcutta, the same zone as the seeded business.**
  That is why the timezone bug survived every previous pass: locally the device
  clock and the branch clock are the same moment. Any future time work must be
  checked with `test.use({ timezoneId: ... })`, not by looking at the screen.
- **The `--reload` trap bit again**, and the cross-zone test caught it: the new
  `business_timezone` field was in the code and in the tests but the running
  server predated it, so the client saw `undefined` and silently used the device
  zone. Restart the backend after ANY backend change before believing a
  browser-level result.
- The `\b`-in-a-heredoc trap and shell quoting cost several rounds again.
  Writing the patch as a FILE (Write tool, then run it) avoids both; inside one,
  spell a literal backslash `"\x5c"`.

**Open:** unchanged from the previous entry, minus the items fixed above. The
business timezone is still GLOBAL — one setting for every restaurant and branch.
The moment two branches sit in different zones it needs to move onto
`RestaurantLocation` (a column, a migration and an admin field); everything on
the client already takes the zone as a parameter, so only the source changes.

---

## 2026-09-14 (2) — A dry run as a customer, and what it turned up

**Goal:** walk the whole flow as a real user, on a real phone size, and fix
what is broken on either side. Two Fable subagents reviewed the backend and the
frontend in parallel while I drove the app.

**Fixed, in rough order of how badly it hurt a customer:**
- **Checkout was ZOOMED OUT on a phone.** On a 393px screen it laid out at
  551px and Chromium shrank the page to fit, so everything was ~29% smaller
  than designed and the page panned sideways. Cause: the two-column grid
  declared `lg:grid-cols-[...]` and nothing at the base breakpoint, so the
  mobile column was the implicit `auto` and sized to its widest content — the
  horizontally scrolling `.day-rail`. Nothing OVERFLOWED, so an overflow check
  could never see it; the tell is `window.innerWidth` diverging from
  `documentElement.clientWidth`. Five grids shared the shape.
- **Hydration failed on every route.** AuthProvider and the cart store both
  read localStorage in a `useState` initializer, so the server rendered
  `href="/login"`/"Cart (0)" and the client's first render disagreed. React
  discarded and rebuilt the whole tree on every page. Auth now starts empty and
  restores in a layout effect; the guard waits for a new `ready` flag before
  redirecting, or it would throw a signed-in customer out of checkout.
- **Typing before hydration was silently discarded** — controlled inputs assert
  React's empty state over whatever the server-rendered input already held.
  Lost the whole email on one login run in four. `ui/input.tsx` now replays the
  DOM value through `onChange`. This also fixes password-manager autofill.
- **The sticky header ate taps.** 65px at z-50 with no `scroll-padding-top`, so
  anything scrolled to the top landed under it — measured on a phone, a
  quantity stepper was covered by the header's own cart button.
- **The basket survived its own payment.** `clearCart` had NO call site
  anywhere. The clear must write through to storage itself: the payment flow
  navigates the whole page immediately and beats the passive persist effect.
- **The order page said "Card payment confirming…" forever.** `GET /orders/{id}`
  reports the DB; only `GET /orders/{id}/payment-status` asks Stripe and
  promotes the order, and nothing called it. Now polled while unpaid.
- **A vegetarian asking for vegetarian food was offered chicken.** The
  deterministic extractor never set `diet` and took the dietary word for a dish
  name — "what vegetarian dishes do you have" searched for a dish called
  "vegetarian". The `is_veg` filter downstream was fine; nothing ever handed it
  a diet. Non-veg must be tested BEFORE veg (`veg` matches inside `non veg`).
- **"How much is delivery?" was answered "we don't offer delivery on the
  menu"** while delivery was enabled at CAD 1.99. Same shape: service words
  captured as dish names. Added a stop list plus a deterministic service-info
  tier beside the hours tier.
- **Every owner's email was public.** `GET /restaurants/{id}` served the owner
  block to anonymous callers.
- Unpaid orders counted as "In progress" with a progress bar (40 of them on the
  seeded account); scheduled orders never showed their booked time again after
  checkout; a pickup customer was told "Your rider is moving"; the cart
  announced a **$45.00** delivery fee while the branch loaded (a leftover rupee
  fallback); checkout blamed the restaurant in red while the payment config was
  still in flight.

**Verified:** 1010 backend tests, 61 frontend unit tests, 25 Playwright across
desktop and mobile, typecheck and build clean, zero hydration errors on six
routes. Payment proven end to end: Stripe `succeeded` at 48.91 CAD, a
self-signed webhook accepted, order → PLACED/PAID.

**Learned — do not re-derive:**
- **The ``-in-a-heredoc trap bit twice more.** `bytes([8])` is what lands in
  the file. Even `b"\b"` inside a QUOTED heredoc did not survive. The
  reliable move: write the patch as a FILE, and spell a backslash `"\"`.
- **A dev server started without `--reload` does not pick up backend edits.**
  Two verification rounds were wasted curling a stale process. Verify backend
  changes in-process (`SessionLocal()` + call the function) instead of killing
  the user's server.
- The `V2` branch has other sessions pushing to it. Two merges were needed this
  session, one with a real conflict in `auth.tsx`. Fetch before assuming a push
  will land, and note that `git push ... | tail` hides a failed exit code.

**Open:** the cart and checkout price against `currentLocation`, not the cart's
own branch — harmless single-restaurant, wrong the moment a cart comes from
another brand via the concierge. Menu item SIZE prices are added to the base
price in the UI while the backend treats them as replacing it (latent: no
seeded sizes). No 401 handling, so an expired token leaves someone "signed in"
while everything fails. No resume-payment path for an unpaid order. Previous
entry's items still stand, and the Supabase password and Stripe test keys are
still in transcripts and should be rotated.

---

## 2026-09-14 — Scheduling as the answer to "why can't I order yet?"

**Goal:** cover mobile properly, make it obvious to a customer why they cannot
order yet, and give them the branch's opening times and a custom future
date/time picker.

**Did:**
- `frontend-customer/src/routes/cart.tsx` — a closed branch no longer ends the
  journey. The CTA reads "Schedule for later" and links to checkout whenever
  `bookableDays` is non-empty; only a branch with no windows at all keeps the
  disabled button. Opening hours fold behind a `<details>` disclosure.
- `frontend-customer/src/routes/checkout.tsx` — date field beside the day chips
  (bounded by `max_future_days`), times grouped morning/afternoon/evening, the
  day's real opening window shown beside them, and "Pick a time to continue"
  where the Pay button is disabled for want of a slot.
- `frontend-customer/src/lib/branch-hours.ts` — `dateInputValue`,
  `dayFromInputValue`, `lastBookableDay`, `groupByPartOfDay`, with tests.
- `frontend-customer/e2e/mobile-layout.spec.ts` (new) — measures the phone
  layout: nothing past the viewport, no tap target under 44px.

**Verified:** `tsc --noEmit` clean, `npm run build` clean, 53 vitest, 20
Playwright across desktop and mobile (the 2 skips are the desktop runs of the
mobile-only suite).

**Learned — three things that cost time and are worth not re-deriving:**
- **The mobile Pay button was never covered.** A previous session skipped the
  mobile payment test after probing `elementFromPoint` at the centre of the
  fixed BAR — which lands in the gap between the price block and the button,
  so it never tested the button. Hit-testing the BUTTON's centre shows nothing
  covers it. The real cause is `locator.click()`'s `scrollIntoViewIfNeeded`:
  a fixed element never "arrives", so Chromium scrolls the page and then blames
  whatever slid under the stale hit point. `clickFixed()` in `e2e/helpers.ts`
  clicks real coordinates after asserting the point resolves inside the target.
- **Checkout was ZOOMED OUT on a phone.** (This corrects the first version of
  this entry, which called it an emulation artifact and not the app's doing.
  It was the app's doing.) On a 393px screen checkout laid out at 551px and
  Chromium zoomed the page out to fit, so every element was ~29% smaller than
  designed and the page could be panned sideways. The two-column grid declared
  `lg:grid-cols-[minmax(0,1fr)_420px]` and nothing at the base breakpoint, so
  the mobile column was the implicit `auto`, which sizes to its widest content
  instead of the container — and the widest content was the horizontally
  scrolling `.day-rail`. Nothing OVERFLOWED (the rail scrolls, correctly), so
  an overflow check could never see it; the giveaway is `window.innerWidth`
  (551) diverging from `documentElement.clientWidth` (393). Fixed by adding
  `grid-cols-[minmax(0,1fr)]` at the base on all five grids with that shape.
  Stripe's `__privateStripeMetricsController` iframe (inline
  `min-width: 100% !important`) is the widest node on the page and looks like
  the culprit — it is not. Blocking js.stripe.com entirely leaves 551
  unchanged. Bisect by hiding subtrees and watching `innerWidth`; that found it
  in one pass after two wrong guesses.
- **Payment is verified end to end, including the webhook.** Stripe shows
  `succeeded` PaymentIntents at 48.91 CAD with real charge ids. Orders still
  sit at PAYMENT_PENDING locally because no webhook can reach localhost and
  there is no Stripe CLI here — that is environmental, not a bug. Confirmed by
  building a `payment_intent.succeeded` event from a real PaymentIntent,
  signing it with `STRIPE_WEBHOOK_SECRET` the way Stripe does
  (`t=<ts>,v1=HMAC-SHA256(ts + "." + body)`) and POSTing it: the route returned
  `{"status":"paid"}` and the order moved to PLACED / PAID with its scheduled
  time intact.
- **Inter is shipped here as a latin-only subset**, so geometric glyphs like
  U+25BE (▾) are not in the font and fall back per platform — it rendered as a
  stray dot on Windows. Use a lucide icon, not a character, for UI marks.

**Open:** unchanged from the previous entry (`docker-compose.yml` builds a
deleted Dockerfile; migration `0001` IVFFlat ordering; the SSR hydration warning
that also discards fast typing; no FAQ/policy/promotion content; delivery-radius
data absent). The Supabase password and the Stripe test keys are in transcripts
and should still be rotated.

---

## 2026-09-13 (5) — Guest access, CAD, card-only Stripe, and a long UI pass

**Goal:** everything the user hit while clicking through the app as a customer.

**The bugs worth remembering, because each hid behind something that looked fine:**

- The login redirect loop (`?redirect=%2Flogin%3Fredirect%3D…` to 4,000 chars)
  came from six copies of the same guard listing the current href in their
  effect dependencies. The guard's own navigate() changed the href, re-fired the
  effect, and re-encoded the URL it had just produced. One hook now reads the
  href through a ref at fire time.
- Clicking a concierge suggestion from another restaurant 400'd at checkout
  ("menu items were not found for this restaurant"). Cart scope is restaurant +
  location and that rule is right; nothing carried the line's own restaurant.
- `available_payment_methods()` returned COD unconditionally, so with no Stripe
  keys an order still completed and went straight to PLACED. Nobody was ever
  charged. That is what "place order skips payment" actually was.
- `/payments/config` requires a token; the client called it without one. The 401
  failed the query, checkout concluded card was off, and every order was refused
  while Stripe was configured and working.
- "rice" returned Pad Thai because the keyword SQL ORs name, category AND
  description with equal weight, then ranks by popularity — a dish whose
  description mentions rice outranked a dish that is rice.
- "Do you have any customize item in Menu?" was read as a search for a dish
  named "customize". Capability questions are answered from the schema now.
- Fuzzy search only started working after realising the trigram matches were
  being filtered against the same misspelled name they were correcting.

**Changed:** `rag.py` (relevance, capability tier, fuzzy), payments registry +
settings + orders (card-only), `frontend-customer` cart/checkout/menu/orders/
dish pages, branch picker, scrollbars, currency to CAD everywhere. Migrations
0053-0056.

**Verified:** a real Stripe test card (4242) paid CAD 48.91, Stripe reported
`succeeded`, a forged webhook signature was refused 400, the correctly signed
event moved the order to PLACED/PAID, and a redelivery was ignored as duplicate.
Backend 937/939 throughout.

**Open:**
- Webhooks need `stripe listen` locally; the Stripe CLI is not installed here,
  so the last leg was proven with a self-signed event.
- "do you deliver to X" and "what are your timings" still answer poorly — there
  is no opening-hours or delivery-radius data to answer from.
- Still no frontend tests. `docker-compose.yml` still builds a deleted
  Dockerfile.

**Learned:**
- Measure before changing a heuristic. Both RAG guard rewrites this session were
  justified by counts (42% false refusals; 16/20 typos), and both times the
  count contradicted the intuition.
- Two sources of truth for the same fact will drift: `cash_on_delivery_enabled`
  was true on all 18 locations while the business took no cash, because nothing
  outside the serializer read it.

## 2026-09-13 (4) — Ollama, the Lovable UI, discovery, and locking the concierge down

**Goal:** real LLM answers instead of templates; replace `frontend-customer`
with the Lovable-generated UI and wire it to the real backend; add discovery
(craving chips → streaming concierge → personalised picks); then test the
concierge the way an actual customer types, and fix what that broke.

**Result:** all of it works end to end against Supabase. Ollama is installed
with GPU (`qwen3:8b` generating, `nomic-embed-text` embedding, 189 menu items
embedded, 0 failed). Login, cart, checkout, orders, chat and the three
discovery surfaces all run on live data.

**Changed:**
- `frontend-customer/` — replaced wholesale with the TanStack Start app. This
  reverses the zero-runtime-dependency rule in `CLAUDE.md` for THIS app only;
  `frontend-admin` is untouched and still dependency-free.
- `backend/app/services/rag.py` — role lock + domain gate (see below).
- `backend/app/services/cache.py` — split `get_redis_delete_client()` out,
  because redis-py pins `socket_timeout` at construction and deletes need a
  longer leash than reads.
- `backend/app/config/settings.py` — Redis connect/read timeouts; `:8080` CORS.
- `backend/seed.py` — `ensure_restaurant_app_client()`, dish images,
  `LOCATION_SEED_ONLY_KEYS`.

**Verified:** 45 legitimate phrasings pass both concierge guards, 17 attacks
refused, 0 either way, confirmed against the live API. `compileall` clean.
Frontend: `npm run build`. No frontend tests exist to run.

**What cost the most time, so it is not repeated:**
- I polished components for hours inside a layout that was fundamentally
  broken — a 430px phone canvas centred in a 1200px cap on a 1920px screen.
  The user's "why are you not doing attractive UI things" was correct and I
  was solving the wrong level. Check the layout before the components.
- Tightening the concierge to an allowlist of food words refused 28 of 66
  ordinary customer sentences — 42%. No keyword list enumerates how English
  asks for dinner. Blocklist for topic, deterministic guard for role override.
- `"what do you recommend"` was rejected by the SPAM guard, not the domain
  guard: `_query_tokens` strips every word in it as a stopword. Testing the
  functions individually would never have found it; only the pipeline did.
- `X-App-Bundle-Id` on the login request scoped identity to the Bangkok Bowl
  app client, while seeded customers live in `marketplace` — 401 with correct
  credentials.
- IVFFlat cannot be built on an empty table. Drop → backfill → rebuild with
  `lists ≈ rows/1000` (14 here, not the 100 in migration `0001`).

**Open:**
- `docker-compose.yml` still builds a Dockerfile that no longer exists; the
  customer app is SSR now and needs a Node runtime there.
- Migration `0001` still creates the IVFFlat index before any data exists.
- `/offers/personalized` 500s on a DB enum mismatch. Pre-existing.
- Zero frontend tests.
- Phase 2 UI: header, button system, 9 breakpoints and 7 button classes to
  consolidate, mobile.
- The Supabase DB password is still in transcripts and should be rotated.

**Learned:**
- Guard order matters more than guard content. Every false refusal found this
  session came from an earlier guard firing, not from the guard that owned the
  decision.
- Test the pipeline, not the predicate. Both real bugs passed their unit-level
  checks.

## 2026-09-13 (3) — Moved the database to Supabase

**Goal:** replace local Postgres with Supabase as the app database, via the MCP server.

**Result:** done. Project `restaurant-rag` (`eeorvcsfpndaovhvgyom`, org Foodie,
ap-south-1), pgvector 0.8.2, migrated to `0049`, seeded (15 users, 6 restaurants,
6 app clients, 18 locations, 189 menu items). Backend runs against it; the
customer home page renders real Supabase data. Latency: restaurants ~0.09s,
login ~0.35s, health ~0.06s.

**Changed:** `backend/.env` only (gitignored). No application code needed
changing — `DATABASE_URL` already overrode `POSTGRES_*`, and
`normalize_database_url` already rewrote the scheme for psycopg 3.

**What cost the most time, so it is not repeated:**
- The password was being pasted into `POSTGRES_PASSWORD` (the local fallback
  block) instead of into `DATABASE_URL`. The file saved every time; the edit
  landed on a line nothing reads. Four failed rounds. My `.env` layout invited
  it — the fallback block is now commented to say it is ignored.
- The direct host `db.<ref>.supabase.co` is IPv6-only, and retrying failed auth
  against it got this machine's IPv6 address BANNED by Supabase. Use the session
  pooler (IPv4) and never retry auth in a loop.
- Pooler username must be `postgres.<project-ref>`.
- The Supabase MCP role is not superuser, so `ALTER USER … PASSWORD` is refused.

**Open:** Section 1 of the UI work (webfont + tokens) is still not started — the
same item carried over from the previous entry. Home/Cart still untouched.
The Supabase DB password is in this session's transcript and should be rotated.

## 2026-09-13 (2) — Full local stack running; seed.py bug fixed

**Goal:** run backend + frontend-admin + frontend-customer locally and check them together.

**Branch:** `chore/local-dev-setup-and-seed-fix`, commit `84656ce`.

**Changed:**
- `backend/seed.py` — real bug fix. `LOCATION_SEED_ONLY_KEYS` named once and
  applied at both call sites; `ensure_primary_location` now computes the
  filtered dict once instead of repeating the comprehension four times.
- `.gitignore` — added `.venv/`, `venv/`, `__pycache__/`, `*.pyc`.
- `CLAUDE.md` — replaced the "backend can't run here" note with the real local
  setup, now that it does run.

**Verified:** backend `/health` → 200; `/api/restaurants` → real seeded rows;
admin login → JWT with role ADMIN; browser check of both UIs, and the admin
dashboard rendered real data (6 orders, ₹121.62, Dragon Wok activity) after a
UI login as admin@example.com. All 47 migrations to 0049, seed.py to completion
(18 locations, 189 menu items).

**Environment discovered (the useful part):** no Docker/Redis/Ollama, but
PostgreSQL 15 was ALREADY installed and running on 127.0.0.1:5432 with
postgres/postgres — just absent from PATH, so it first looked missing. Only
pgvector was genuinely absent; built from source with the MSVC 14.50 already on
the box. Details in CLAUDE.md under "Running it locally on this machine".

**Open:**
- Not merged to `main` yet — that was the stated plan.
- ~283 `*.cpython-313.pyc` files are tracked from an earlier commit. The new
  ignore rule stops more being added but does not untrack those; needs a
  `git rm -r --cached` decision.
- `readme.md` still cross-links absolute macOS paths.
- Unrelated, found while checking Supabase: `public.offer_packs` in the DEV-SP
  project has RLS disabled. Reported to the user; not acted on.

**Learned:**
- Seeding is append-style, so a partly-failed run leaves committed rows behind —
  the retry reported "Restaurants created this run: 0" because the failed first
  run had already committed them.
- `passlib` logs `AttributeError: module 'bcrypt' has no attribute '__about__'`
  with bcrypt 4.x. Noisy but harmless; hashing works.

## 2026-09-13 — Repo onboarding, persistent context set up

**Goal:** read the codebase end to end, then create files so future sessions do
not have to repeat that exploration.

**Changed:**
- `CLAUDE.md` (new) — architecture map, conventions, commands, rough edges.
- `.claude/worklog.md` (new) — this file.

**Verified:** nothing to build or test; documentation only. Confirmed by reading:
`readme.md`, `backend/app/main.py`, `backend/app/config/settings.py`,
`backend/app/models/enums.py`, `backend/app/models/user.py`, the API router,
directory listings for all four apps, `docker-compose.yml`, `render.yaml`,
and `git log`.

**Open:** user said they would explain the actual task next — nothing started yet.

**Learned:**
- Local Python is 3.10.11 but the backend requires 3.11+ (`StrEnum`), and there
  is no `backend/.venv`. Backend cannot be run or tested in this checkout as-is.
- Both web apps are intentionally zero-runtime-dependency: hand-rolled History
  API routing, Context store, hand-written CSS. Easy to break by reflex.
- Backend tests are `unittest`, not pytest, and many encode questions that were
  previously answered incorrectly.
- `settings.py` is the single best file for understanding product intent — every
  threshold carries the measurement or the incident that produced it.
