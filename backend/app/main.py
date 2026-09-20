from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api import api_router
from app.config import get_settings
from app.services.embeddings import warm_embedding_provider

settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Pull the embedding model into memory before the first customer arrives.

    On a thread, not inline: a cold load measured 23s here, and blocking the
    event loop for that long would leave the API refusing connections while it
    looked like a hang. Health checks and every non-chat route work fine without
    the model, so there is no reason to make them wait for it.

    Daemon, so a slow or unreachable Ollama cannot hold up shutdown.
    """

    threading.Thread(
        target=warm_embedding_provider,
        name="embedding-warmup",
        daemon=True,
    ).start()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
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


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}
