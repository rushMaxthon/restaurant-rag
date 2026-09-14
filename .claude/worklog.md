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
## YYYY-MM-DD — short title

**Goal:** what was asked.
**Changed:** files/areas touched, one line each.
**Verified:** exact commands run and their result. "Not verified" if not run.
**Open:** anything unfinished, deferred, or uncertain.
**Learned:** non-obvious things worth keeping (promote permanent ones to CLAUDE.md).
```

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
- **Under Pixel 5 emulation, checkout reports `innerWidth` 551 against
  `documentElement.clientWidth` 393.** This predates all of this work and is
  NOT caused by the app: removing Stripe's injected
  `__privateStripeMetricsController` iframe changes nothing, and the gap is
  identical with `src/` stashed. Stripe does set `min-width: 100% !important`
  INLINE on that iframe (so no stylesheet rule can override it), but it is a
  symptom, not the cause. `overflow-x: clip` on `html` does not help either —
  a `position: fixed` element is not clipped by an ancestor's overflow. Left
  unfixed and unexplained rather than papered over; the mobile-layout suite
  measures app elements against `innerWidth` so it still catches real overflow.
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
