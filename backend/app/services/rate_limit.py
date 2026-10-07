"""How many times anyone may try something, counted where they cannot reset it.

Found in the 2026-10-07 security review: nothing limited how often anything
could be called. Passwords could be guessed without end; the six-digit print
pairing code could be swept in minutes, and a hit streams every kitchen
ticket (customer phone and address) to the attacker; anonymous chat could
burn the LLM quota; address and delivery lookups ran up paid Google and
Pidge calls.

A limit is a fixed window - at most `limit` attempts per `window_seconds` -
counted in Redis so every API worker shares one count. `hit` raises 429 with
Retry-After past it. Callers count per IP and, where there is one, per
account or identifier, so neither many accounts from one machine nor one
account from many machines gets around it.

The IP is Cloudflare's `CF-Connecting-IP` (every Render web service sits
behind Cloudflare, which overwrites it), else the LAST X-Forwarded-For entry.
Never the first entry: that is whatever the caller sent, which is exactly
what someone dodging a limit would rotate. If Redis is unreachable the request is allowed:
a cache outage must not take the login page down with it.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable

from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError

from app.services.cache import get_redis_client

logger = logging.getLogger(__name__)


def client_ip(request) -> str:
    # Render puts Cloudflare in front of every web service, and Cloudflare
    # overwrites CF-Connecting-IP with the real visitor - a caller cannot set
    # it. X-Forwarded-For is only appended to, so behind Cloudflare its last
    # entry can be a proxy shared by many customers, who would then share one
    # login limit. Locally there is no Cloudflare and the fallbacks apply.
    cloudflare = (request.headers.get("cf-connecting-ip") or "").strip()
    if cloudflare:
        return cloudflare
    forwarded = [part.strip() for part in (request.headers.get("x-forwarded-for") or "").split(",") if part.strip()]
    if forwarded:
        return forwarded[-1]
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


def _key(name: str, identity: str) -> str:
    # Hashed: emails, phone numbers and addresses do not belong in key names.
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return f"ratelimit:{name}:{digest}"


def hit(name: str, identity: str, *, limit: int, window_seconds: int) -> None:
    """Count one attempt; 429 when this identity is past `limit` in the window."""

    key = _key(name, identity)
    try:
        client = get_redis_client()
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, window_seconds)
        if count <= limit:
            return
        retry_after = int(client.ttl(key) or window_seconds)
    except RedisError:
        logger.warning("Rate limit %s not enforced: Redis unavailable", name)
        return
    retry_after = max(retry_after, 1)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many attempts. Please wait {retry_after} seconds and try again.",
        headers={"Retry-After": str(retry_after)},
    )


def per_ip(name: str, *, limit: int, window_seconds: int) -> Callable[[Request], None]:
    """A FastAPI dependency: `Depends(per_ip("chat", limit=20, window_seconds=60))`.

    Declared first in a route's signature, so a caller past the limit is
    refused before the route touches the database or a paid service.
    """

    def dependency(request: Request) -> None:
        hit(name, f"ip:{client_ip(request)}", limit=limit, window_seconds=window_seconds)

    return dependency


__all__ = ["client_ip", "hit", "per_ip"]
