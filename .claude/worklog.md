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
