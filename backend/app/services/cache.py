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
    return Redis.from_url(settings.redis_url, decode_responses=True)


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
        deleted = int(get_redis_client().delete(*keys))
    except RedisError:
        logger.exception("Redis connection failure during DELETE keys=%s", keys)
        return 0

    logger.info("Redis cache delete keys=%s deleted=%s", keys, deleted)
    return deleted


def cache_delete_pattern(pattern: str) -> int:
    try:
        client = get_redis_client()
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
