from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api import api_router
from app.config import safety
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.config import get_settings
from app.services.model_warmup import start_model_warm_up
from app.services.realtime.server import (
    asgi_app as realtime_asgi_app,
    start_background_tasks as start_realtime,
    stop_background_tasks as stop_realtime,
)

settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Pull the models into memory before the first customer arrives.

    This used to warm the embedding model alone, once. It now warms the
    generation model too — the expensive one, 5.6GB against 274MB — and keeps
    warming both, because `keep_alive` is a window that a quiet hour closes just
    as surely as a restart does. See `services/model_warmup` for the 54-second
    turn that made the difference measurable.

    Off the event loop and daemonised, both for the same reasons as before: a
    cold load takes tens of seconds, every non-chat route works without the
    models, and a slow Ollama must not hold up shutdown.
    """

    start_model_warm_up(name="model-warmup-api")
    # The realtime revocation listener and session sweep, one pair per worker
    # process because each worker holds its own sockets. No-ops while
    # `enable_realtime` is off.
    await start_realtime()
    try:
        yield
    finally:
        await stop_realtime()


# Before anything is served: a real deployment configured unsafely stops here
# with a sentence naming the setting, rather than running open.
safety.check(settings)
_docs_url, _redoc_url, _openapi_url = safety.docs_urls(settings)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    # Never on outside local development, whatever DEBUG says (`safety`).
    debug=safety.effective_debug(settings),
    lifespan=lifespan,
    # The API map is served locally only (`config/safety.py`).
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# Every API response left this server uncompressed. One branch's menu is
# 164 KB of JSON for 136 dishes, fetched by the home page and the menu page,
# and a storefront customer is on a phone on mobile data — so this is the
# cheapest performance change available to this codebase.
#
# `minimum_size` is above the size of the small JSON this API mostly returns:
# compressing a 300-byte response costs CPU on both ends and saves nothing.
#
# The two `text/event-stream` endpoints are NOT compressed, and they opt out
# themselves by declaring `Content-Encoding: identity` — Starlette skips any
# response that already names an encoding. Compressing a stream would buffer
# the tokens it exists to deliver one at a time.
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Every response tells the browser how to treat it: no framing, no sniffing,
# no referrer, https only, and nothing signed-in cached (2026-10-07 review).
app.add_middleware(SecurityHeadersMiddleware, local=safety.is_local(settings))

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins_list,
    # Includes every tenant subdomain of `platform_domain`, so onboarding a
    # restaurant does not need a redeploy to let its storefront call the API.
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)

# Socket.IO, mounted rather than wrapped around the app, so `app.main:app`
# stays the FastAPI object gunicorn runs and the test suites import. Under the
# API prefix so every proxy that already routes `/api` routes this too; nginx
# still needs the Upgrade headers on it (`nginx/snippets/api-proxy.conf`).
# Always mounted: with `enable_realtime` off it refuses each handshake with a
# reason the clients understand, rather than a 404 they would retry forever.
app.mount(f"{settings.api_v1_prefix}/socket.io", realtime_asgi_app)


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}
