from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def normalize_cache_query(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    normalized = re.sub(r"\s+([?!.,])", r"\1", normalized)
    return normalized


@lru_cache(maxsize=1)
def get_redis_client() -> Redis:
    """The shared client, with a deadline on reaching the server.

    Every cache operation below already catches `RedisError` and degrades to a
    miss, so an absent Redis is a supported state rather than an outage. What
    was missing was a bound on how LONG that degradation takes: with no connect
    timeout the client falls back to the OS default and retries, and a single
    menu request that touches the cache eight times spent 8.15 seconds failing
    to reach a server that was not running — long enough that the clients gave
    up and rendered empty screens.

    A short deadline makes the miss immediate, which is what "degrades
    gracefully" was always meant to mean. It is deliberately small: Redis is
    either alongside the app or a few milliseconds away, so anything slower than
    this is already a failure, and waiting longer only makes a request slower
    before returning the same miss.
    """

    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_redis_delete_client() -> Redis:
    """A second connection, used only by the delete/scan path, on a longer leash.

    `redis_socket_timeout_seconds` is right for a GET: a read that times out is
    a cache miss, and the caller falls through to the database for one slower
    but correct answer. `cache_delete_pattern` walks `scan_iter`, which can take
    several round trips against a large keyspace — one slow round trip under
    the read deadline used to raise `RedisError` mid-scan and abandon the
    delete, leaving the already-matched keys undeleted. Those keys then serve a
    stale menu or offer for the full `redis_cache_ttl_seconds` (three days),
    which is a far worse outcome than one invalidation call taking longer. A
    separate client, rather than passing a timeout per call, because
    redis-py pins `socket_timeout` to the connection at construction time.
    """

    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
        socket_timeout=settings.redis_delete_socket_timeout_seconds,
    )


def cache_get_json(key: str) -> Any | None:
    try:
        raw_value = get_redis_client().get(key)
    except RedisError:
        logger.exception("Redis connection failure during GET key=%s", key)
        return None

    if raw_value is None:
        logger.info("Redis cache miss key=%s", key)
        return None

    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        logger.warning("Redis cache payload decode failed key=%s", key)
        cache_delete(key)
        return None

    logger.info("Redis cache hit key=%s", key)
    return payload


def cache_set_json(key: str, value: Any, ttl_seconds: int | None = None) -> bool:
    ttl = ttl_seconds or settings.redis_cache_ttl_seconds
    try:
        get_redis_client().set(key, json.dumps(value, default=str), ex=ttl)
    except RedisError:
        logger.exception("Redis connection failure during SET key=%s", key)
        return False

    logger.info("Redis cache save key=%s ttl=%ss", key, ttl)
    return True


def cache_delete(*keys: str) -> int:
    if not keys:
        return 0

    try:
        deleted = int(get_redis_delete_client().delete(*keys))
    except RedisError:
        logger.exception("Redis connection failure during DELETE keys=%s", keys)
        return 0

    logger.info("Redis cache delete keys=%s deleted=%s", keys, deleted)
    return deleted


def cache_delete_pattern(pattern: str) -> int:
    try:
        client = get_redis_delete_client()
        keys = list(client.scan_iter(match=pattern, count=200))
        if not keys:
            logger.info("Redis cache delete pattern=%s deleted=0", pattern)
            return 0
        deleted = int(client.delete(*keys))
    except RedisError:
        logger.exception("Redis connection failure during DELETE pattern=%s", pattern)
        return 0

    logger.info("Redis cache delete pattern=%s deleted=%s", pattern, deleted)
    return deleted
