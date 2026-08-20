# Docker deployment

Operational guide for the containerised stack. The reasoning behind the
architecture is in [AI_MANAGER_PRODUCTION_AUDIT.md](AI_MANAGER_PRODUCTION_AUDIT.md)
§4–§5; this document is how to run it.

## Files

| Path | Purpose |
|---|---|
| `backend/Dockerfile` | one image, six roles (api, 4 workers, beat, migrate) |
| `backend/.dockerignore` | keeps `.env`, the Firebase key and `.venv` out of the build context |
| `frontend-admin/Dockerfile`, `nginx.conf` | Vite build → static nginx, SPA fallback |
| `frontend-customer/Dockerfile`, `nginx.conf` | same |
| `docker-compose.yml` | base topology: 11 services, 4 volumes, 4 networks |
| `docker-compose.override.yml` | dev: `--reload`, bind mounts, loopback ports |
| `docker-compose.prod.yml` | prod: gunicorn, no mounts, TLS, log rotation, mem limits |
| `nginx/nginx.conf` | edge proxy base config |
| `nginx/snippets/api-proxy.conf` | shared API + **SSE** rules |
| `nginx/snippets/tls.conf` | TLS ciphers + security headers |
| `nginx/conf.d/dev/default.conf` | port-routed local access |
| `nginx/conf.d/prod/default.conf.template` | domain-routed, TLS, envsubst-rendered |
| `.env.docker.example` | configuration template — copy to `.env` |

## Quick start (development)

```bash
cp .env.docker.example .env
# fill in the two required values:
#   JWT_SECRET_KEY   → openssl rand -hex 32
#   POSTGRES_PASSWORD → openssl rand -base64 24

docker compose build
docker compose up -d postgres redis
docker compose run --rm migrate           # alembic upgrade head
docker compose up -d                      # everything else

# models (once — downloads ~5GB)
docker compose --profile setup run --rm ollama-pull
```

Then:

| URL | What |
|---|---|
| `http://localhost` | customer web app |
| `http://localhost:8081` | admin panel |
| `http://localhost/api/...` | API, same-origin from both apps |
| `http://localhost:8000` | API directly (dev only) |

## Running the tests

The suite lives in the image and is `unittest`, not pytest:

```bash
docker compose run --rm --no-deps api python -m unittest discover -s tests
```

Database-backed tests create and drop a throwaway `restaurant_rag_insights_test`
database and **skip themselves automatically** when Postgres is unreachable, so
`--no-deps` still runs the ~800 that need no database. To include them, drop
`--no-deps` and leave `postgres` up.

> The container path is `/srv/backend`, not `/app`, and that is deliberate: the
> tests resolve their import root as `Path(__file__).parents[2] / "backend"`, so
> the parent directory must literally be named `backend` or every test fails to
> import `app`.

## Production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Requires in `.env`: `API_DOMAIN`, `ADMIN_DOMAIN`, `APP_DOMAIN`,
`ADMIN_API_BASE_URL`, `CUSTOMER_API_BASE_URL`, plus the two secrets. Compose
refuses to start without them rather than falling back to a default — that is
what the `${VAR:?...}` syntax is for, and it is the reason a deployment cannot
silently come up with a publicly-known JWT signing key.

Certificates must exist before nginx starts; see the ACME bootstrap note at the
bottom of `nginx/conf.d/prod/default.conf.template`.

## Things that will bite you

**Frontend API URL is baked in at build time.** Vite substitutes
`import.meta.env.VITE_API_BASE_URL` into the bundle. Changing it needs
`docker compose build frontend-admin`, not a restart. There is no runtime
override.

**Ollama is never published.** It has no authentication, so an exposed `:11434`
is a free inference endpoint and an exfiltration path. It sits on the internal
`ai` network plus `egress` (needed to pull models). In dev only, it is bound to
`127.0.0.1` for convenience.

**`internal: true` blocks outbound, not just inbound.** `postgres` and `redis`
are on the internal `backend` network and cannot reach the internet — correct,
neither should. But `worker-notifications` calls FCM and `worker-default` calls
Stripe's `cancel_intent`, so both carry the separate `egress` network. Removing
it would break push notifications and unpaid-order cleanup with a DNS error.

**Exactly one `beat`.** `--scale beat=2` runs every nightly briefing twice.
Nothing in the schedule prevents it.

**`pgvector/pgvector:pg16`, not `postgres:16`.** The first migration runs
`CREATE EXTENSION vector` and fails on the stock image.

**Gunicorn's `--timeout` must exceed the AI answer timeout.** It defaults to 180s
here against a 110s `AI_MANAGER_CHAT_ANSWER_TIMEOUT_SECONDS`. Lower it below that
and gunicorn kills the worker mid-answer, so the owner sees a dropped connection
instead of the deterministic fallback the app was about to send. The same applies
to nginx's `proxy_read_timeout`.

**SSE needs `proxy_buffering off`.** Already set in
`nginx/snippets/api-proxy.conf` for both stream endpoints. Without it the answer
arrives in one lump at the end — the stream still "works", which is why this is
usually noticed late.

**GPU on macOS.** Docker cannot pass a GPU into a container on macOS, so the
`ollama` container is CPU-only there. To use the host's native Ollama instead,
set `OLLAMA_BASE_URL=http://host.docker.internal:11434` and stop the service.
On Linux with NVIDIA, uncomment the `deploy.resources.devices` block in
`docker-compose.override.yml`.

## Common commands

```bash
docker compose ps                                  # states + health
docker compose logs -f api
docker compose run --rm migrate                    # apply new migrations
docker compose exec postgres psql -U postgres -d restaurant_rag
docker compose exec worker-default celery -A app.config.celery:celery_app inspect active_queues
docker compose exec nginx nginx -t && docker compose exec nginx nginx -s reload
docker compose down                                # stop, keep volumes
docker compose down -v                             # stop and DELETE the database
```
