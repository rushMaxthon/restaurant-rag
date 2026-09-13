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
