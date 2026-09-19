# CLAUDE.md

Persistent context for this repo. Read this first; it exists so no session has to
re-derive the map from scratch.

Companion file: `.claude/worklog.md` — dated log of what each session actually
did. Read the last 2-3 entries before starting work, append an entry when done.

---

## What this is

A monorepo for a multi-restaurant ordering platform with two AI surfaces:
customer-facing RAG food chat, and an AI Restaurant Manager for owners.

| Path | What it is | Stack |
|---|---|---|
| `backend/` | source of truth for every business rule | FastAPI 0.115, SQLAlchemy 2.0, Postgres + pgvector, Celery + Redis, Ollama (qwen3:8b, nomic-embed-text), Stripe, Firebase Admin |
| `frontend-customer/` | customer web app | TanStack Start + React 19, Tailwind, shadcn/Radix, TanStack Query (SSR) |
| `frontend-admin/` | shared ADMIN + OWNER dashboard | React 19 + Vite, only `lucide-react` + fontsource |
| `mobile/` | customer app | React Native 0.85 CLI, React Navigation, Firebase phone auth, Stripe RN, Notifee |

---

## Conventions that are easy to violate by accident

**No new dependencies in `frontend-admin`.** It is deliberately
dependency-free at runtime: routing hand-rolled over the History API in
`src/App.tsx` (regex-matched pathnames, a `usePathname` hook), state in React
Context (`src/store/AdminStore.tsx`), styling hand-written CSS in
`src/index.css` (9.5k lines) — no Tailwind, no CSS-in-JS, no component
library. Reaching for react-router, redux or a UI kit breaks the house style
there.

**`frontend-customer` no longer follows that rule.** It was replaced wholesale
on 2026-09-13 with a Lovable-generated TanStack Start app: file-based routing,
Tailwind, shadcn/Radix, TanStack Query, ~60 runtime deps, and SSR via nitro
(`vite.config.ts` wraps `@lovable.dev/vite-tanstack-config`, which already
supplies the plugin set — adding those plugins by hand breaks the build).
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

**Tests are `unittest`, not pytest.** 42 files in `backend/tests/`, each
inserting `backend/` on `sys.path` itself. Many encode a question that was once
answered *wrong* — read the module docstring before changing an assertion.

**Typography is owned, and self-hosted.** `frontend-customer` ships Inter
Variable (48KB, latin-only) from `public/fonts/` via `src/styles/fonts.css`,
imported before `index.css` in `main.tsx` and preloaded from `index.html`. This
reverses an earlier documented decision to ship no webfont; that decision
avoided render-blocking but meant nobody chose the result — the UI stack fell
through to Segoe UI/Avenir Next and the display stack to Palatino Linotype on
Windows / Iowan Old Style on macOS, differing by platform. `font-display: swap`
answers the original concern directly. `--font-display` still exists as a
token rather than being deleted — it now resolves to `--font-ui` — because it
is still named at 12 sites across `home.css` and `screens.css`.
`src/styles/fonts.test.ts` guards the chain end to end: every `@font-face`
file exists in `public/`, `font-display: swap` is present, and `main.tsx`
actually imports `fonts.css` (a missing import fails silently — the page just
renders in the fallback stack).

**Know which file owns which token.** `src/index.css` `:root` owns fonts,
radii, spacing, and the type scale (`--text-xs` 11px through `--text-3xl`
31px on a 1.2 ratio, plus `--leading-tight`/`--leading-normal`) — added so
headings sit on an explicit scale instead of ad hoc sizes.
`src/theme/applyTheme.ts` owns colours AND shadows, writing them onto the root
element at runtime — so it OVERRIDES the `--shadow-*` values declared in
`index.css`.
Editing shadow values in CSS appears to do nothing. `themeBase.ts` also
exports `radius` and `spacing` objects; these currently have zero consumers in
components and are not published to CSS. `src/styles/tokens.test.ts` guards
this map by asserting every `var(--token)` referenced in the stylesheets
resolves to a definition from one of these two sources.

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
- Roles: `ADMIN`, `OWNER` (platform staff, `app_client_id` NULL), `CUSTOMER`.
  One owner to exactly one restaurant. The role/app-client split is a DB CHECK
  (`ck_users_app_client_scope_matches_role`), and customer uniqueness lives in
  partial indexes defined in migration `0036`, not in the SQLAlchemy model.

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

## Where to make changes

- business rules -> `backend/app/services/`
- routes and contracts -> `backend/app/api/` + `backend/app/schemas/`
- schema -> `backend/app/models/` + `backend/alembic/versions/`
- admin UI -> `frontend-admin/src/pages/`, `frontend-admin/src/components/`
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
python -m unittest discover -s tests      # tests are unittest-based, not pytest
python -m compileall app alembic          # the repo's usual syntax check

# web (from frontend-admin/ or frontend-customer/)
npm run dev | npm run build | npm run lint

# mobile (from mobile/)
npm run start | npm run android | npm run ios
./node_modules/.bin/tsc --noEmit
npm run lint | npm run test
```

Verification this repo actually uses: `compileall` for backend, `npm run build`
for both webs, `tsc --noEmit` for mobile.

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

Working as of 2026-09-13. No Docker here, and Ollama is not installed; Redis IS
now installed and running as a service (see below).

- **Python**: the default `python` is 3.10.11 and **cannot** run this backend
  (`StrEnum` needs 3.11+). A 3.11.9 venv lives at `backend/.venv`, built with
  `py -3.11 -m venv .venv`. Always invoke `backend/.venv/Scripts/python.exe`,
  never bare `python`.
- **Database**: the app points at **Supabase** (project `restaurant-rag`, ref
  `eeorvcsfpndaovhvgyom`, org Foodie, ap-south-1), via `DATABASE_URL` in
  `backend/.env`. Migrated to `0049` and seeded. Measured from here: restaurants
  ~0.09s, login ~0.35s.
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
  - **RLS is ON for all 40 public tables, with no policies.** Supabase grants
    `anon` and `authenticated` full DML including TRUNCATE on everything in
    `public`, and the anon key is published inside client apps — so RLS off
    meant anyone with that key could read every user and order and empty the
    tables. This app never uses PostgREST: the FastAPI backend owns auth and
    every business rule, and connects as `postgres`, which owns the tables and
    therefore bypasses RLS. Deny-by-default is correct here; do not disable it.
    If one table ever needs direct client access, add a policy for that table.
    NOT yet reproducible — applied to this project only, with no Alembic
    migration, so a fresh environment starts open. See the worklog follow-up.
  - The Supabase MCP role is **not** superuser: `ALTER USER postgres WITH
    PASSWORD` fails with "permission denied to alter role". Password changes
    must go through the dashboard.
- **Local Postgres (fallback)**: PostgreSQL 15 runs as service `postgresql-x64-15` from
  `C:\Program Files\PostgreSQL\15`, on 127.0.0.1:5432 as `postgres/postgres`.
  Its `bin/` is NOT on PATH, so call `psql.exe` by full path. Database
  `restaurant_rag` exists, migrated to `0049` and seeded.
- **pgvector**: 0.8.0, built from source with MSVC 14.50 against PG15. To
  rebuild: clone `pgvector v0.8.0`, run `vcvars64.bat`, set `PGROOT` to the PG15
  directory, `nmake /F Makefile.win`, then copy `vector.dll`, `vector.control`
  and `sql/vector--*.sql` into `lib/` and `share/extension/` **elevated** — the
  install step needs admin rights and otherwise fails with "Access is denied".
- **Redis**: installed and running as the Windows service `Redis`, from a
  portable build at `C:
edis-portable` (Redis 5.0.14.1, the tporadowski
  Windows port — open source and free, unlike Memurai whose free tier is
  development-only). AUTO_START, so it survives a reboot; `redis-cli.exe ping`
  in that folder is the quickest check. `redis_url` already defaulted to
  `redis://localhost:6379/0`, so nothing needed configuring.
  - Memurai was tried first and its MSI fails with 1603: the custom action
    `ca_SilentCheckIfPortIsAvailable` errors even though 6379 is free. Do not
    spend time on it; the portable build works.
  - Every op in `services/cache.py` still catches `RedisError` and degrades to
    a miss, so the API survives Redis going away — but with it running, chat
    session memory, the response cache and Celery all work.
- **Ollama**: INSTALLED and serving on `http://localhost:11434`, with `qwen3:8b`
  (generation) and `nomic-embed-text` (embeddings) pulled. This line used to say
  it was not, which is why several sessions tested the AI paths by scripting the
  model seam instead of running it. `enable_ordering_agent` is on, so the
  customer chat and the WhatsApp agent answer for real here — a turn takes
  roughly 3-8 seconds. `backend/scripts/dryrun_whatsapp.py` replays scripted
  conversations through the whole live path with only Meta's send stubbed, and
  is the fastest way to see what a customer actually gets.

Start the three services, each in its own shell:

```bash
cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd frontend-customer && npm run dev -- --port 5173 --strictPort
cd frontend-admin && npm run dev -- --port 5174 --strictPort
```

The ports are not arbitrary: both web apps hardcode `http://localhost:8000/api`
for dev, and 5173/5174 are both in the backend's default CORS list. Seeded
logins are `admin@example.com` and `customer1@example.com`, password
`password123`.

## Known rough edges in this checkout
- `readme.md` and several docs cross-link with absolute macOS paths
  (`/Users/imac/Desktop/restaurant-rag/...`), broken on this Windows checkout.
- Migration numbering skips `0033`-`0035` (jumps `0032` to `0036`). Intentional
  or not, do not "fix" it; the chain is defined by `down_revision`.
- Windows + Git Bash: use forward slashes; working directory is `F:\restaurant-rag`.

---

## Docs worth reading before big changes

| File | Covers |
|---|---|
| `AI_RESTAURANT_MANAGER_WORKFLOW.md` | the owner-facing AI, tier by tier, all 28 tools |
| `LLM_ARCHITECTURE.md` | which model, why, backend vs LLM responsibilities |
| `PROJECT_UNDERSTANDING.md` | broad product overview |
| `backend/docs/chat-rag-workflow.md` | customer chat internals |
| `docs/per-app-identity.md` | the AppClient identity split |
| `docs/recommendation-flow.md`, `docs/personalized-offers.md` | scoring rules |
| `MENU_ITEM_CUSTOMIZATION_FLOW.md`, `STRIPE_PAYMENT_INTEGRATION_PLAN.md` | those flows |
