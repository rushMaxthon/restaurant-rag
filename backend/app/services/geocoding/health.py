"""Whether Google has been refusing us, for Platform watch.

Found 2026-10-07: Google answered every call REQUEST_DENIED ("enable Billing on
the Google Cloud Project") and Places 403, and the only sign was a customer
being told their address was not on the map. A refusal that retrying will not
fix (a key or billing problem) is recorded here; any successful answer clears
it. Platform watch reads it (`platform_watch._check_maps`).

Kept in Redis for a day, so every API worker sees the same answer.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError

from app.services.cache import get_redis_client

logger = logging.getLogger(__name__)

REFUSAL_KEY = "geocoding:google-refused"
_KEEP_SECONDS = 24 * 3600


def record_refusal(service: str, message: str) -> None:
    """`service` is "geocode" or "places"."""

    try:
        get_redis_client().set(
            REFUSAL_KEY,
            json.dumps({"at": datetime.now(UTC).isoformat(), "service": service, "message": str(message)[:300]}),
            ex=_KEEP_SECONDS,
        )
    except RedisError:
        logger.warning("Could not record a Google refusal")


def record_success() -> None:
    try:
        get_redis_client().delete(REFUSAL_KEY)
    except RedisError:
        pass


def last_refusal() -> dict[str, Any] | None:
    try:
        raw = get_redis_client().get(REFUSAL_KEY)
    except RedisError:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        data["at"] = datetime.fromisoformat(data["at"])
        return data
    except (ValueError, KeyError, TypeError):
        return None


__all__ = ["REFUSAL_KEY", "last_refusal", "record_refusal", "record_success"]
