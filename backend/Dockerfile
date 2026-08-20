# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Backend image: FastAPI + Celery + Alembic.
#
# One image serves five roles (api, four worker queues, beat, and the one-shot
# migrate job). They differ only by command, so building once and overriding
# `command` in compose keeps them provably identical — a worker can never be
# running different code from the API that queued its task.
#
# WORKDIR is /srv/backend, not /app, and that is load-bearing. The test suite
# resolves its import root as `Path(__file__).parents[2] / "backend"`
# (tests/test_*.py), which only points at the real source tree when the parent
# directory is literally named `backend`. Copying to /app would leave every test
# inserting a non-existent path and failing to import `app`.
# ---------------------------------------------------------------------------

# --- build stage: compile any wheel that has no binary distribution ---------
FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# build-essential covers the source builds (bcrypt/psycopg fall back to source
# on platforms without a matching wheel); libpq-dev is needed by psycopg when it
# does. Neither survives into the runtime image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# --- runtime stage ---------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# libpq5 is the runtime half of libpq-dev — psycopg needs it, the compiler does
# not. Everything else from the build stage is left behind.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libpq5 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-index --find-links=/wheels -r /tmp/requirements.txt \
 && rm -rf /wheels /tmp/requirements.txt

# Non-root. Created before the source is copied so ownership is set in one pass.
RUN groupadd --system --gid 1001 app \
 && useradd --system --uid 1001 --gid app --create-home --home-dir /home/app app

# Celery beat's PersistentScheduler writes a shelve file. It lives on a named
# volume so a restart does not re-fire the schedule; creating it here with the
# right ownership means Docker seeds the fresh volume with that ownership, which
# a `chown` in an entrypoint could not do for an already-populated volume.
RUN mkdir -p /var/run/celery && chown app:app /var/run/celery

WORKDIR /srv/backend
COPY --chown=app:app . /srv/backend

USER app

EXPOSE 8000

# Deliberately NO image-level HEALTHCHECK.
#
# This one image runs six different roles (api, four Celery queues, beat, and
# the migrate job) and they have nothing in common to probe: only the API serves
# HTTP. An image-level HTTP check is inherited by every role that does not
# override it, which marked beat permanently `unhealthy` — and an always-red
# health signal is worse than none, because it trains everyone to ignore the
# column. Each service declares its own check in docker-compose.yml instead.

# Production default. Never --reload; the dev override replaces this wholesale.
#
# --worker-tmp-dir /dev/shm: gunicorn heartbeats through a temp file, and on a
#   container filesystem that is slow enough to trip the worker timeout under
#   load. /dev/shm is tmpfs.
# --timeout must exceed AI_MANAGER_CHAT_ANSWER_TIMEOUT_SECONDS (110s default),
#   or gunicorn kills the worker mid-answer and the owner sees a dropped
#   connection instead of the deterministic fallback the app was about to send.
# --forwarded-allow-ips defaults to 127.0.0.1, which is wrong here: nginx runs
#   in its own container and connects from a Docker bridge address, so the
#   X-Forwarded-Proto it sets was being ignored and the app believed every
#   request was plain HTTP. Trusting any peer is safe in this topology because
#   the API publishes no port in production — nginx is the only route to it.
CMD ["sh", "-c", "exec gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers ${GUNICORN_WORKERS:-4} \
    --bind 0.0.0.0:8000 \
    --timeout ${GUNICORN_TIMEOUT:-180} \
    --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-30} \
    --keep-alive ${GUNICORN_KEEPALIVE:-5} \
    --forwarded-allow-ips ${FORWARDED_ALLOW_IPS:-*} \
    --worker-tmp-dir /dev/shm \
    --access-logfile - \
    --error-logfile -"]
