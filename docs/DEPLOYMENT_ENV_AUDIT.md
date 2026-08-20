# Deployment Environment Variable Audit

**Date:** 19 August 2026 · **Revision 2** — refreshed after the G1–G11 configuration fixes
**Subject:** the Docker deployment: `docker-compose.yml`, `docker-compose.override.yml`, `docker-compose.prod.yml`, `backend/Dockerfile`, the two frontend Dockerfiles, and `nginx/`
**Status:** audit only. Nothing was modified to produce this revision.

Companion documents: [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) (how to run it) and
[AI_MANAGER_PRODUCTION_AUDIT.md](AI_MANAGER_PRODUCTION_AUDIT.md) (why it is shaped this way).

> **What changed in revision 1 → 2.** Every gap this document previously listed under §11 has been
> closed. The configurable surface grew from 38 to 48 application settings; the four variables that
> used to start a misconfigured stack silently now refuse to boot; the Celery broker moved off the
> cache database; connection pooling, Celery time limits, Ollama tuning, proxy-header trust,
> container timezone and immutable image tags are all now configured. The counts, tables and
> checklists below are re-derived from the current files, not carried over.

---

## 0. How configuration actually flows

This matters more than any individual variable.

```
  .env  (repository root, gitignored, NEVER committed)
    │
    │  read by `docker compose` for ${VAR} substitution ONLY
    ▼
  docker-compose*.yml
    │
    ├─ x-backend-env anchor ──▶ container environment ──▶ pydantic Settings ──▶ the app
    │                                                     (48 settings + TZ)
    ├─ api service env ──────▶ gunicorn / proxy trust (5 vars, never seen by Settings)
    ├─ service config ───────▶ ports, memory, image tags, Postgres and Redis server flags
    ├─ build args ───────────▶ baked into the JS bundle at BUILD time (frontends)
    └─ secrets ──────────────▶ file mounted at /run/secrets/… (Firebase key)
```

Four consequences to hold on to:

1. **`backend/.env` is not used in production.** It is excluded by `backend/.dockerignore` and verified absent from the image. Only the **root `.env`** matters, and only as a source for `${VAR}` substitution.
2. **A variable reaches the app only if `docker-compose.yml` explicitly forwards it.** `Settings` is configured `extra="ignore"` (`backend/app/config/settings.py:17`), so anything else is silently dropped. 48 of 182 settings are forwarded — see §11.1.
3. **Frontend variables are build-time.** Vite inlines `import.meta.env.*`. Changing one requires a rebuild, never a restart.
4. **In development only**, the bind mount `./backend:/srv/backend` exposes `backend/.env` inside the container as a dotenv file. Environment variables outrank dotenv in pydantic-settings, so compose still wins.

### Legend

| Mark | Meaning |
|---|---|
| 🔴 | **Secret.** Never commit, never log, never put in a client bundle. |
| ✋ | **You must provide this manually.** No safe default exists. |
| ⚙️ | Has a working default; change only if you have a reason. |
| 🏗️ | Already configured by the Docker implementation; nothing to do. |
| 🖥️ | Production server only. |

---

## 1. The four classifications

### 1.1 ✅ Already configured by the Docker implementation — do nothing

Set by compose from service topology, not by you. Listed so you do **not** put them in `.env` and break the wiring.

| Variable | Value set by compose | Why it is fixed |
|---|---|---|
| `POSTGRES_SERVER` | `postgres` | Docker service name |
| `POSTGRES_PORT` | `5432` | in-network port |
| `REDIS_URL` | `redis://redis:6379/0` | cache database |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` | task results |
| `CELERY_BROKER_URL` | `redis://redis:6379/2` | **queued work, deliberately off the cache database** |
| `FCM_CREDENTIALS_PATH` | `/run/secrets/firebase-service-account.json` | Docker secret mount point |
| `OLLAMA_BASE_URL` | `http://ollama:11434` (default) | override only for a dedicated AI host — §7.3 |
| `ENVIRONMENT` / `DEBUG` | `production` / `false` | forced by `docker-compose.prod.yml` |

Also fully handled by the implementation, with no variable to set: startup ordering, health checks
(per service, not inherited from the image), network isolation and egress, the non-root runtime user,
gunicorn's worker class and proxy-header trust, Celery task time limits, log rotation, and the
Postgres `max_connections` / Redis `maxmemory-policy` server flags.

### 1.2 ✋ Must be configured before deployment

**Production requires 14 variables.** Every one of them now **refuses to start** rather than falling
back to a default — there is no longer a category of variable that boots a quietly-wrong stack.

| Variable | Enforced in | Note |
|---|---|---|
| 🔴 `JWT_SECRET_KEY` | base | `openssl rand -hex 32`, unique per environment |
| 🔴 `POSTGRES_PASSWORD` | base + prod | `openssl rand -base64 24` |
| `POSTGRES_USER` | prod | |
| `POSTGRES_DB` | prod | |
| `API_DOMAIN` | prod | DNS must resolve first |
| `ADMIN_DOMAIN` | prod | |
| `APP_DOMAIN` | prod | |
| `ADMIN_API_BASE_URL` | prod | build arg; a rebuild is needed to change it |
| `CUSTOMER_API_BASE_URL` | prod | build arg |
| `BACKEND_CORS_ORIGINS` | prod | was a silent failure in revision 1 |
| 🔴 `STRIPE_SECRET_KEY` | prod | was a silent failure |
| `STRIPE_PUBLISHABLE_KEY` | prod | was a silent failure; not itself a secret |
| 🔴 `STRIPE_WEBHOOK_SECRET` | prod | was a silent failure |
| `IMAGE_TAG` | prod | must be immutable — a git SHA or release version |

Enforcement mechanism: `${VAR:?message}`. For the five added in this round it is applied through
top-level `x-require-*` keys in `docker-compose.prod.yml` — compose substitutes across the whole
document, so one reference makes a variable mandatory without colliding with any service's own
`environment:` mapping.

One item is required but is **not** a variable:

* `FIREBASE_CREDENTIALS_FILE` must point at a real file, or compose fails to start the secret mount.

### 1.3 🖥️ Must be configured only on the production server

`API_DOMAIN`, `ADMIN_DOMAIN`, `APP_DOMAIN`, `ACME_EMAIL`, `IMAGE_TAG`, `API_MEM_LIMIT`,
`OLLAMA_MEM_LIMIT`, `OLLAMA_MEM_RESERVATION`, `GUNICORN_WORKERS`, `GUNICORN_TIMEOUT`,
`POSTGRES_MAX_CONNECTIONS`, `FORWARDED_ALLOW_IPS`, and the production values of
`BACKEND_CORS_ORIGINS`, `ADMIN_API_BASE_URL`, `CUSTOMER_API_BASE_URL`.

Server-side artefacts that are not variables:

* `firebase-service-account.json` — copied to the server out of band
* TLS certificates — in the `letsencrypt` volume, issued on the server
* the `postgres_data` volume — the production database

### 1.4 🚫 Must NOT be committed to Git

| Item | Protection | Verified |
|---|---|---|
| `.env` (root) | `.gitignore:6` | ✅ |
| `backend/.env` | `.gitignore:7` | ✅ only `.env.example` is tracked |
| `firebase-service-account.json` | `.gitignore:1-2` + `backend/.dockerignore` | ✅ not tracked; absent from the built image |
| Real secrets of any kind | only `${VAR}` references exist in compose | ✅ |
| TLS private keys | Docker volume, never a repo bind mount | ✅ |

**Safe to commit and intended to be:** `.env.docker.example`, `backend/.env.example`,
`mobile/.env.example`, every compose file, every Dockerfile, everything under `nginx/`.

> `backend/alembic.ini` previously carried a hardcoded `postgresql+psycopg://postgres:<password>@…` URL in
> version control. It is now blank, with a comment pointing at `alembic/env.py`, which sets the real
> URL from settings before any migration runs.

---

## 2. Master table — which file each variable belongs to

| File | Committed? | Contains | Consumed by |
|---|---|---|---|
| **`.env`** (root) | 🚫 **no** | every `${VAR}` below | `docker compose` substitution |
| `.env.docker.example` | ✅ yes | the same names with placeholder values | humans; copy to `.env` |
| `docker-compose.yml` | ✅ yes | env anchor, build args, secrets, server flags | Docker |
| `docker-compose.override.yml` | ✅ yes | dev-only ports and mounts | Docker (auto) |
| `docker-compose.prod.yml` | ✅ yes | prod overrides, required-var enforcement | Docker (explicit `-f`) |
| `backend/Dockerfile` | ✅ yes | `GUNICORN_*` and `FORWARDED_ALLOW_IPS` defaults in `CMD` | the container at start |
| `frontend-*/Dockerfile` | ✅ yes | `VITE_API_BASE_URL` build arg | the Vite build |
| `nginx/conf.d/prod/default.conf.template` | ✅ yes | `${API_DOMAIN}` etc. | nginx envsubst entrypoint |
| `backend/alembic.ini` | ✅ yes | **no URL** — set by `env.py` from settings | Alembic |
| `backend/.env` | 🚫 no | legacy local dev config | **not used by Docker at all** |
| `backend/firebase-service-account.json` | 🚫 no | service-account private key | mounted as a Docker secret |

**79 distinct variables** are referenced across the three compose files.

---

## 3. Backend production environment

The 48 settings the application receives, plus `TZ`. Set them in the **root `.env`**.

### 3.1 Core application

| Variable | Class | Prod value | Notes |
|---|---|---|---|
| `ENVIRONMENT` | 🏗️ | `production` | forced by prod override |
| `DEBUG` | 🏗️ | `false` | forced by prod override |
| `TZ` | ⚙️ | `Asia/Kolkata` | log timestamps; keep aligned with `BUSINESS_TIMEZONE` (compose cannot nest defaults) |
| `APP_NAME` | ⚙️ | `Restaurant RAG API` | cosmetic |
| `APP_VERSION` | ⚙️ | `1.0.0` | shown by `/health` |
| `API_V1_PREFIX` | ⚙️ | `/api` | changing it breaks the nginx `location /api/` blocks |
| `BUSINESS_TIMEZONE` | ⚙️ | `Asia/Kolkata` | every metric bucket is computed in this zone |
| `BACKEND_CORS_ORIGINS` | ✋ | exact origins | required in prod — §9 |

### 3.2 Database and connection pool

| Variable | Class | Prod value | Notes |
|---|---|---|---|
| `POSTGRES_SERVER` / `POSTGRES_PORT` | 🏗️ | `postgres` / `5432` | |
| `POSTGRES_USER` | ✋ | your role | required in prod |
| `POSTGRES_PASSWORD` | 🔴 ✋ | generated | required everywhere |
| `POSTGRES_DB` | ✋ | `restaurant_rag` | required in prod |
| `DATABASE_ECHO` | ⚙️ | `false` | `true` logs every SQL statement |
| `DB_POOL_SIZE` | ⚙️ | `5` | **per process** |
| `DB_MAX_OVERFLOW` | ⚙️ | `5` | |
| `DB_POOL_RECYCLE` | ⚙️ | `1800` | below any proxy idle timeout |
| `DB_POOL_TIMEOUT` | ⚙️ | `30` | wait for a free connection before failing |
| `POSTGRES_MAX_CONNECTIONS` | ⚙️ 🖥️ | `200` | server flag, not an app setting |

**The arithmetic that ties these together.** The pool is per process, so:

```
(GUNICORN_WORKERS + sum of CELERY_*_CONCURRENCY) × (DB_POOL_SIZE + DB_MAX_OVERFLOW)
        (4        +            9              ) × (     5        +       5        ) = 130
```

plus beat and the transient migrate job, against `POSTGRES_MAX_CONNECTIONS=200`. **Raise any worker
count and this sum must be redone**, or Postgres begins refusing connections under load — which
surfaces as intermittent 500s, not a clean failure.

### 3.3 Authentication

| Variable | Class | Prod value | Notes |
|---|---|---|---|
| `JWT_SECRET_KEY` | 🔴 ✋ | generated | `openssl rand -hex 32`. **Different value per environment** — a shared secret makes a staging token valid in production. |
| `JWT_ALGORITHM` | ⚙️ | `HS256` | |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | ⚙️ | `1440` | 24h; no refresh token exists |

### 3.4 Redis / Celery

| Variable | Class | Prod value | Notes |
|---|---|---|---|
| `REDIS_URL` | 🏗️ | `redis://redis:6379/0` | cache |
| `CELERY_RESULT_BACKEND` | 🏗️ | `redis://redis:6379/1` | results |
| `CELERY_BROKER_URL` | 🏗️ | `redis://redis:6379/2` | **queued work** |
| `REDIS_CACHE_TTL_SECONDS` | ⚙️ | `259200` | |
| `REDIS_MAXMEMORY_POLICY` | ⚙️ | `noeviction` | server flag — §7.2 |
| `CELERY_LOG_LEVEL` | ⚙️ | `info` | |
| `CELERY_DEFAULT_CONCURRENCY` | ⚙️ | `2` | |
| `CELERY_ANALYTICS_CONCURRENCY` | ⚙️ | `1` | **keep at 1** — Ollama serves one generation at a time |
| `CELERY_EMBEDDINGS_CONCURRENCY` | ⚙️ | `2` | |
| `CELERY_NOTIFICATIONS_CONCURRENCY` | ⚙️ | `4` | |
| `CELERY_TASK_SOFT_TIME_LIMIT` / `_TIME_LIMIT` | ⚙️ | `300` / `360` | default, embeddings, notifications |
| `CELERY_ANALYTICS_SOFT_TIME_LIMIT` / `_TIME_LIMIT` | ⚙️ | `3600` / `3900` | far longer on purpose — §7.4 |

### 3.5 Ollama and models

| Variable | Class | Prod value | Notes |
|---|---|---|---|
| `OLLAMA_BASE_URL` | 🏗️/🖥️ | `http://ollama:11434` | change to a private address when Ollama moves to its own host |
| `OLLAMA_CHAT_MODEL` | ⚙️ | `qwen3:8b` | customer RAG |
| `OLLAMA_EMBEDDING_MODEL` | ⚙️ | `nomic-embed-text` | must be pulled before the first embed task |
| `AI_MANAGER_CHAT_ANSWER_MODEL` | ⚙️ | `qwen3:8b` | |
| `CHAT_TOOL_PLANNER_MODEL` | ⚙️ | `qwen3:8b` | |
| `AI_MANAGER_NARRATION_MODEL` | ⚙️ | `qwen3:8b` | |
| `ANALYST_MODEL` | ⚙️ | `qwen3:8b` | |

All five deliberately name the same model: two different ones evict each other and cost a reload per
turn. This is also why `OLLAMA_MAX_LOADED_MODELS` can safely stay at 1.

### 3.6 AI Manager flags and budgets

| Variable | Class | Default | Effect |
|---|---|---|---|
| `ENABLE_AI_MANAGER_CHAT_TOOLS` | ⚙️ | `true` | Tier-2 planner + 28 read-only data tools |
| `ENABLE_AI_MANAGER_CHAT_ANSWERS` | ⚙️ | `true` | Qwen writes the owner-facing reply |
| `ENABLE_AI_MANAGER_CHAT_LLM_ROUTER` | ⚙️ | `true` | costs a model call when the rules miss |
| `ENABLE_AI_MANAGER_NARRATION` | ⚙️ | `false` | owner-facing briefing narration |
| `ENABLE_AI_MANAGER_INSIGHTS` | ⚙️ | `false` | nightly briefing generation |
| `ENABLE_AI_MANAGER_ACTIONS` | ⚙️ | `false` | proposals; nothing executes without explicit approval |
| `AI_MANAGER_CRON_ENABLED` | ⚙️ | `false` | the beat entries for nightly analysis |
| `AI_MANAGER_CHAT_ANSWER_TIMEOUT_SECONDS` | ⚙️ | `110` | **the anchor of the timeout chain** — §10 |
| `AI_MANAGER_CHAT_ANSWER_MAX_TOKENS` | ⚙️ | `120` | the single biggest latency lever |

### 3.7 Gunicorn and proxy trust (api service only — never seen by `Settings`)

| Variable | Class | Default | Notes |
|---|---|---|---|
| `GUNICORN_WORKERS` | ⚙️ 🖥️ | `4` | counts toward the pool arithmetic in §3.2 |
| `GUNICORN_TIMEOUT` | ⚙️ 🖥️ | `180` | must exceed the answer timeout |
| `GUNICORN_GRACEFUL_TIMEOUT` | ⚙️ | `30` | |
| `GUNICORN_KEEPALIVE` | ⚙️ | `5` | |
| `FORWARDED_ALLOW_IPS` | ⚙️ 🖥️ | `*` | gunicorn's default of `127.0.0.1` makes it ignore nginx, which connects from a bridge address; safe as `*` because the API publishes no port in production |

---

## 4. frontend-admin production environment

**One variable. Build-time only.**

| Variable | Class | Where | Prod value |
|---|---|---|---|
| `ADMIN_API_BASE_URL` → build arg `VITE_API_BASE_URL` | ✋ | root `.env` → `docker-compose.yml` build arg | `https://api.example.com/api` |

* Read at `frontend-admin/src/services/api.ts:42`, fallback `http://localhost:8000/api`.
* Required by `docker-compose.prod.yml` — the production build fails rather than shipping a localhost bundle.
* **A rebuild is required to change it.** There is no runtime override.
* Not a secret: it ships to every browser by definition.
* Pointing it at the API domain makes the panel **cross-origin**, so `BACKEND_CORS_ORIGINS` must list `https://admin.example.com`. See §9 for the same-origin alternative.

## 5. frontend-customer production environment

Identical, via `CUSTOMER_API_BASE_URL`. Read at `frontend-customer/src/services/api.ts:27`.
The only other `import.meta.env` reference in either app is `import.meta.env.DEV`, set by Vite.

## 6. Mobile app — no environment configuration exists

* `mobile/src/services/api.ts:46` hardcodes `http://192.168.29.236:8000/api` — a LAN address over plain HTTP.
* `mobile/.env.example` documents that the app deliberately has no env loader (to keep Stripe keys off the client) and notes the base URL as a known gap.
* iOS `Info.plist` sets `NSAllowsArbitraryLoads: false` with `NSAllowsLocalNetworking: true`, so the current URL works only on the LAN.
* **A production blocker for the mobile app, unchanged and not addressed by the Docker work.**

---

## 7. PostgreSQL / Redis / Ollama service configuration

### 7.1 PostgreSQL

| Setting | Where | Value |
|---|---|---|
| image | `docker-compose.yml` | `pgvector/pgvector:pg16` — **not** `postgres:16`; the first migration runs `CREATE EXTENSION vector` |
| `command` | `docker-compose.yml` | `postgres -c max_connections=${POSTGRES_MAX_CONNECTIONS:-200}` — stock is 100, below the pool demand in §3.2 |
| credentials | root `.env` | consumed by both the server container and the app |
| volume | `postgres_data` | **the only volume whose loss is unrecoverable** |
| health check | `pg_isready -U … -d …` | gates the migrate job |
| published port | none in production | `docker compose exec`, or an SSH tunnel |
| egress | **none** (internal network) | verified: cannot resolve external hosts |

### 7.2 Redis

| Setting | Where | Value |
|---|---|---|
| image | `docker-compose.yml` | `redis:7-alpine` |
| persistence | command | `--appendonly yes` |
| eviction | command | `--maxmemory-policy ${REDIS_MAXMEMORY_POLICY:-noeviction}` |
| databases | env anchor | `/0` cache · `/1` results · `/2` broker |
| volume | `redis_data` | |
| password | **none** | acceptable only because Redis is on an internal network with no published port. A managed Redis would need credentials in `REDIS_URL`. |
| egress | **none** | verified |

Two decisions worth understanding together. The broker sits on **DB 2**, away from the cache, so no
cache operation can touch queued work. And the policy is **`noeviction`**, because under an LRU
policy Redis would silently drop pending tasks to make room for cache entries — a lost push
notification with no error anywhere. With `noeviction` a full Redis fails writes instead, and
`cache_set_json` already catches `RedisError` and degrades to a cache miss: the cache absorbs the
pressure while queued work survives.

### 7.3 Ollama

| Setting | Where | Value |
|---|---|---|
| image | `docker-compose.yml` | `ollama/ollama:latest` |
| volume | `ollama_models` | ~6 GB; without it every restart re-downloads |
| networks | `ai` + `egress` | `ai` is internal; `egress` is required for `ollama pull` |
| published port | **none, in any environment** | Ollama has **no authentication** |
| dev convenience | `docker-compose.override.yml` | bound to `127.0.0.1` only |
| memory | `docker-compose.prod.yml` | `OLLAMA_MEM_LIMIT` / `OLLAMA_MEM_RESERVATION` |
| model pull | `--profile setup` one-shot | `docker compose --profile setup run --rm ollama-pull` |

Server tuning, now explicit rather than left to image defaults:

| Variable | Default | Why this value |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `1` | matches the measured `-np 1`; each parallel slot costs KV-cache memory. Raise only after the model host has real headroom (production audit §3, A1/A3). |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | two resident models were 8.1 GB on a 16 GB machine and a direct cause of the measured swap thrash |
| `OLLAMA_KEEP_ALIVE` | `60m` | matches the `keep_alive` the app sends per request |
| `OLLAMA_CONTEXT_LENGTH` | `4096` | matches the `num_ctx` the chat answer call pins |

**To move Ollama to a dedicated GPU host:** set `OLLAMA_BASE_URL` and stop the container. No code
change, no rebuild. On macOS the GPU cannot be passed into a container, so use the host's native
Ollama at `http://host.docker.internal:11434`.

### 7.4 Celery task time limits

Set on each worker's command line, not in application code.

| Queue | Soft | Hard | Reasoning |
|---|---|---|---|
| `default`, `embeddings`, `notifications` | 300s | 360s | short tasks; a hung one should not hold a slot |
| `analytics` | 3600s | 3900s | `generate_owner_briefings_task` iterates up to 100 restaurants in **one** task, each of which may call the model. A short limit here would kill legitimate nightly runs. |

Without limits, a hung job holds its slot forever — and with analytics at concurrency 1 that stops
the nightly analysis entirely.

---

## 8. Stripe and Firebase

### 8.1 Stripe

| Variable | Class | Base default | Production |
|---|---|---|---|
| `STRIPE_SECRET_KEY` | 🔴 ✋ | `sk_test_mock` | **required in prod.** Server-side only — never in a client bundle. |
| `STRIPE_PUBLISHABLE_KEY` | ✋ (not secret) | `pk_test_mock` | **required in prod.** Served to clients at runtime by `GET /payments/config`, so rotating it needs no app release. |
| `STRIPE_WEBHOOK_SECRET` | 🔴 ✋ | `""` | **required in prod.** Without it no card payment can ever be confirmed. |
| `STRIPE_API_VERSION` | ⚙️ | `2024-11-20.acacia` | now forwarded and pinnable |
| `PAYMENT_INTENT_TTL_MINUTES` | ⚙️ | `30` | now forwarded |
| `PAYMENT_CURRENCY` | ⚙️ | `inr` | |
| `RAZORPAY_KEY_ID` / `_SECRET` | ⚙️ | mock | Razorpay is not implemented; not forwarded, and kept only so old config does not break |

The `_mock` sentinel remains a good safe default for development: `settings.stripe_is_configured`
returns false for any key ending in `_mock`, and the app offers cash-on-delivery. In production the
three required variables mean that state can no longer be reached by omission.

The webhook endpoint is deliberately unauthenticated because the Stripe signature *is* the
authentication, and it reads the raw body so the signature verifies.

### 8.2 Firebase

| Item | Class | Value | Notes |
|---|---|---|---|
| `firebase-service-account.json` | 🔴 ✋ 🖥️ | the file itself | a **service-account private key** |
| `FIREBASE_CREDENTIALS_FILE` | ✋ | host path | compose-level; points the Docker secret at the file |
| `FCM_CREDENTIALS_PATH` | 🏗️ | `/run/secrets/firebase-service-account.json` | in-container mount point |
| `FCM_PROJECT_ID` | ⚙️ | `""` from compose | see below |

Mounted as a Docker **secret**, never copied into an image layer — verified absent from the built
image. Only `api`, the four workers, `beat` and `migrate` receive it.

`settings.py:373` hardcodes a real project id (`quickbite-7833a`) as its default. Compose passes an
empty string, which overrides it. This is benign and arguably better: `notifications.py:121` only
sets `projectId` when the value is truthy, so an empty value lets `firebase_admin` infer the project
from the credentials file — correct by construction.

---

## 9. CORS, API and frontend URLs

| Variable | Where | Production value |
|---|---|---|
| `BACKEND_CORS_ORIGINS` | root `.env` → backend | `https://admin.example.com,https://app.example.com` |
| `ADMIN_API_BASE_URL` | root `.env` → build arg | `https://api.example.com/api` |
| `CUSTOMER_API_BASE_URL` | root `.env` → build arg | `https://api.example.com/api` |
| `API_V1_PREFIX` | root `.env` → backend | `/api` — must match the nginx `location /api/` blocks |

Rules that must hold together:

* Every origin a browser loads a frontend from must appear **exactly** in `BACKEND_CORS_ORIGINS` — scheme, host, port, no trailing slash, no wildcard.
* `*` is not usable: `main.py:24-31` sets `allow_credentials=True`, and browsers reject a wildcard with credentials. A wildcard would break login rather than loosen security.
* All three are now **required in production**, so the localhost default can no longer leak into a deployment.
* Two coherent topologies — pick one, do not mix halves:

  | | Cross-origin | Same-origin |
  |---|---|---|
  | `*_API_BASE_URL` | `https://api.example.com/api` | `/api` |
  | nginx | API only on `API_DOMAIN` | `include api-proxy.conf` in the admin/app server blocks |
  | `BACKEND_CORS_ORIGINS` | must list both frontend origins | not exercised at all |

The development topology uses the same-origin arrangement, which is why CORS is not exercised
locally — worth knowing when a CORS bug first appears in staging.

---

## 10. Nginx, domain and HTTPS configuration

| Variable | Class | Consumed by | Notes |
|---|---|---|---|
| `API_DOMAIN` | ✋ 🖥️ | nginx envsubst | required in prod |
| `ADMIN_DOMAIN` | ✋ 🖥️ | nginx envsubst | required in prod |
| `APP_DOMAIN` | ✋ 🖥️ | nginx envsubst | required in prod |
| `ACME_EMAIL` | ✋ 🖥️ | **nothing in compose** | used only in the hand-run `certbot` command |

Mechanism: `docker-compose.prod.yml` mounts `nginx/conf.d/prod/` at `/etc/nginx/templates`, and the
nginx image's entrypoint runs envsubst over `*.template` into `/etc/nginx/conf.d/` before starting.

Non-variable configuration already in place:

* TLS ciphers, session settings, HSTS and security headers — `nginx/snippets/tls.conf`
* HTTP→HTTPS redirect, with `/.well-known/acme-challenge/` left on plain HTTP for renewal
* **SSE settings** — `nginx/snippets/api-proxy.conf`: `proxy_buffering off`, `proxy_read_timeout 180s`, HTTP/1.1 with an empty `Connection` header, on both stream endpoints
* `text/event-stream` excluded from `gzip_types`

**Certificates must exist before nginx starts**, or the `ssl_certificate` directives fail and the
container crash-loops. Bootstrap sequence is at the bottom of the template.

**Timeout chain — all three must stay ordered, and all three are now configurable:**

```
AI_MANAGER_CHAT_ANSWER_TIMEOUT_SECONDS  110s   root .env → app
        <  GUNICORN_TIMEOUT             180s   root .env → gunicorn
        ≤  proxy_read_timeout           180s   nginx/snippets/api-proxy.conf
```

If either outer value drops below the app's, the worker is killed or the connection cut mid-answer,
and the owner sees a network error instead of the deterministic fallback the app was about to send.

---

## 11. Remaining configuration observations

Everything §11 previously listed as a gap has been closed. What follows is what is left.

### 11.1 The configurable surface: 48 of 182 settings

`backend/app/config/settings.py` defines **182** fields. `docker-compose.yml` forwards **48** of
them (plus `TZ`, which is not a Settings field). **134 remain at their code defaults**, and because
`Settings` is `extra="ignore"`, adding one to `.env` has no effect and produces no warning.

This is a deliberate curated surface, not a defect — but the failure mode is silent, so it must be
documented. Exposing another one means adding it to the `x-backend-env` anchor.

The operationally-relevant settings that remain unwired:

| Setting | Default | Why it might matter |
|---|---|---|
| `AI_MANAGER_CRON_HOUR` / `_MINUTE` | `4` / `30` | nightly run time; timezone-sensitive |
| `AI_MANAGER_MAX_RESTAURANTS_PER_RUN` | `100` | caps how long a nightly run can take |
| `ENABLE_AI_MANAGER_ANALYST`, `AI_MANAGER_ANALYST_SHADOW_MODE`, `ENABLE_AI_MANAGER_AI_FINDINGS` | `False`/`True`/`False` | analyst rollout switches |
| `ENABLE_AI_OFFER_GENERATION`, `ENABLE_AI_RECOMMENDATION_RERANKING`, `AI_OFFER_CRON_ENABLED` | `False` | spend-adjacent features |
| `OLLAMA_CHAT_TIMEOUT_SECONDS`, `CHAT_TOOL_PLANNER_TIMEOUT_SECONDS`, `AI_MANAGER_ROUTER_TIMEOUT_SECONDS`, `AI_MANAGER_NARRATION_TIMEOUT_SECONDS`, `ANALYST_*_TIMEOUT_SECONDS` | various | sized for a slow CPU host; should come down on faster hardware |
| `INSIGHTS_CACHE_TTL_SECONDS`, `AI_MANAGER_CHAT_ANSWER_CACHE_TTL_SECONDS`, `CHAT_TOOL_PLAN_CACHE_TTL_SECONDS` | `900`/`900`/`86400` | cache freshness |
| `DEFAULT_APP_CLIENT_KEY` | `marketplace` | identity scope for clients arriving without a bundle id |
| `RAZORPAY_KEY_ID` / `_SECRET` | mock | provider not implemented |

### 11.2 `ACME_EMAIL` is in the template but consumed by nothing

It appears in `.env.docker.example` and in the certbot instructions, but no compose service
references it — it is used only when you run `certbot` by hand. Correct as designed; noted so nobody
assumes it is wired up. This is the **only** variable in the template that no compose file reads.

### 11.3 Secrets are environment variables, not Docker secrets

One secret is declared as a file:

```
secrets:
  firebase-service-account.json:
    file: ${FIREBASE_CREDENTIALS_FILE:-./backend/firebase-service-account.json}
```

`JWT_SECRET_KEY`, `POSTGRES_PASSWORD` and the Stripe keys are passed as **environment variables**.
That is the pragmatic choice for single-host compose, with consequences worth stating: environment
variables are visible to `docker inspect`, to anything that can read `/proc/<pid>/environ` in the
container, and are inherited by child processes. Moving them to file-based secrets would require a
`_FILE` convention in the application, which remains out of scope.

### 11.4 Compose-level variables (never reach the application)

| Variable | Default | Scope |
|---|---|---|
| `IMAGE_TAG` | `local`; **required in prod** | image tag for all nine built images |
| `POSTGRES_MAX_CONNECTIONS` | `200` | Postgres server flag |
| `REDIS_MAXMEMORY_POLICY` | `noeviction` | Redis server flag |
| `OLLAMA_NUM_PARALLEL`, `OLLAMA_MAX_LOADED_MODELS`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_CONTEXT_LENGTH` | see §7.3 | Ollama server tuning |
| `GUNICORN_*` (4), `FORWARDED_ALLOW_IPS` | see §3.7 | api service only |
| `CELERY_*_CONCURRENCY` (4), `CELERY_*_TIME_LIMIT` (4), `CELERY_LOG_LEVEL` | see §3.4, §7.4 | worker command lines |
| `API_MEM_LIMIT`, `OLLAMA_MEM_LIMIT`, `OLLAMA_MEM_RESERVATION` | `2g` / `10g` / `8g` | 🖥️ prod only |
| `FIREBASE_CREDENTIALS_FILE` | `./backend/firebase-service-account.json` | 🖥️ host path for the secret |
| `HTTP_HOST_PORT`, `ADMIN_HOST_PORT`, `API_HOST_PORT`, `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`, `OLLAMA_HOST_PORT` | 80 / 8081 / 8000 / 5432 / 6379 / 11434 | **dev only**, all bound to `127.0.0.1`; ignored in production |

---

## 12. Pre-deployment checklist

Copy `.env.docker.example` to `.env` on the server and work down this list.

**The 14 that refuse to start without a value**
- [ ] 🔴 `JWT_SECRET_KEY` — `openssl rand -hex 32`, unique to production
- [ ] 🔴 `POSTGRES_PASSWORD` — `openssl rand -base64 24`
- [ ] `POSTGRES_USER`, `POSTGRES_DB`
- [ ] `API_DOMAIN`, `ADMIN_DOMAIN`, `APP_DOMAIN` — DNS A records pointing at the server first
- [ ] `ADMIN_API_BASE_URL`, `CUSTOMER_API_BASE_URL`
- [ ] `BACKEND_CORS_ORIGINS` — exact production origins, matching the topology chosen in §9
- [ ] 🔴 `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, 🔴 `STRIPE_WEBHOOK_SECRET`
- [ ] `IMAGE_TAG` — immutable, e.g. `IMAGE_TAG=$(git rev-parse --short HEAD)`

**Required but not a variable**
- [ ] `FIREBASE_CREDENTIALS_FILE` — the file copied to the server out of band

**Sizing — redo the §3.2 arithmetic if you change any of these**
- [ ] `GUNICORN_WORKERS` to CPU cores; confirm `GUNICORN_TIMEOUT` > 110s
- [ ] `POSTGRES_MAX_CONNECTIONS` above (workers + celery children) × (pool + overflow)
- [ ] `OLLAMA_MEM_LIMIT` / `_RESERVATION` above the model's resident size
- [ ] `CELERY_ANALYTICS_CONCURRENCY` left at 1
- [ ] `TZ` aligned with `BUSINESS_TIMEZONE`

**Server-side, not variables**
- [ ] TLS certificates issued (nginx crash-loops without them)
- [ ] `docker compose --profile setup run --rm ollama-pull`
- [ ] Backups for `postgres_data`, and **one restore rehearsed**
- [ ] Confirm `.env` is not tracked: `git check-ignore .env`

**Not solved by the Docker or configuration work**
- [ ] Mobile: hardcoded LAN URL and debug-keystore signing (§6)
- [ ] No rate limiting exists on any endpoint
- [ ] `/docs`, `/redoc`, `/openapi.json` are public unconditionally — needs an app change
- [ ] Postgres tuning beyond `max_connections` (`shared_buffers`, `work_mem`)

---

## Appendix — how this revision was produced

| Check | Method | Result |
|---|---|---|
| Settings surface | parsed field declarations from `settings.py` | 182 |
| Variables reaching the app | parsed the `x-backend-env` anchor | 49 keys = 48 settings + `TZ` |
| Unwired settings | set difference | 134 |
| Every `${VAR}` and its default | regex over all three compose files | 79 distinct |
| Required variables | `${VAR:?}` occurrences per file | 2 base, 13 prod → 14 distinct |
| Template completeness | set difference, template keys vs compose references | complete; `ACME_EMAIL` the only intentional extra |
| Frontend variables | `grep import.meta.env` across both `src/` trees | `VITE_API_BASE_URL`, `DEV` |
| nginx template variables | `grep '${...}'` over the prod template | 3 domains |
| Secret leakage | `git check-ignore`; inspected the built image | `.env` and the Firebase key absent from the image |
| Pool arithmetic | worker counts × (pool + overflow) vs `max_connections` | 130 vs 200 |
| Runtime confirmation | live stack: `show max_connections`, `config get maxmemory-policy`, engine pool introspection, worker cmdlines, `date`, Redis key placement per DB | all as configured |

No file was modified. Every claim above is checkable against the named file and line.
