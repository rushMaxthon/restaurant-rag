"""The customer menu, from Redis until it actually changes.

Found 2026-10-07: Supabase's free plan includes 5 GB of egress a month and the
project had used 5.35 GB while the whole database is 48 MB. The egress was
the same menus read over and over: `GET /menu-items` had no cache, so every
storefront page view pulled a whole branch - for Bhagwati 187 dishes and 298
sizes, about 90 KB of rows - from Supabase. The heaviest query alone had run
7,564 times.

A cached answer is keyed by a FINGERPRINT of the branch's menu: one small
query returning, for dishes, sizes, groups and options, the row count, the
latest edit time, and sums of prices and stock. Any change a customer could
see moves it, including stock written by a bulk UPDATE that does not touch
`updated_at` - so there is no window in which the cache shows a stale menu,
and nothing has to remember to invalidate it. An unchanged menu then costs
one row from Supabase instead of hundreds.

What the fingerprint does not cover is the order-count badges inside the
answer (bestseller, "ordered N times"), which move with orders rather than
the menu: entries expire after `MENU_CACHE_TTL_SECONDS` so those are never
older than that.

If Redis is unreachable the menu is built from the database, as before.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.cache import get_redis_client

logger = logging.getLogger(__name__)

#: How old the order-count badges in a cached menu may be.
MENU_CACHE_TTL_SECONDS = 120

_FINGERPRINT_SQL = text(
    """
    WITH items AS (
        SELECT id, updated_at, price, stock_quantity, stock_daily_quantity, out_of_stock, is_available
        FROM menu_items WHERE restaurant_location_id = :location_id
    ),
    sizes AS (
        SELECT s.id, s.updated_at, s.price, s.stock_quantity, s.stock_daily_quantity, s.is_active
        FROM menu_item_sizes s JOIN items ON items.id = s.menu_item_id
    ),
    groups AS (
        SELECT g.id, g.updated_at, g.is_active
        FROM menu_item_customization_groups g
        WHERE g.menu_item_id IN (SELECT id FROM items) OR g.menu_item_size_id IN (SELECT id FROM sizes)
    ),
    options AS (
        SELECT o.updated_at, o.extra_price, o.is_active
        FROM menu_item_customization_options o JOIN groups ON groups.id = o.group_id
    )
    SELECT
        (SELECT json_build_array(
            count(*), max(updated_at), sum(price), sum(coalesce(stock_quantity, -1)),
            sum(coalesce(stock_daily_quantity, -1)), count(*) FILTER (WHERE out_of_stock),
            count(*) FILTER (WHERE is_available)) FROM items),
        (SELECT json_build_array(
            count(*), max(updated_at), sum(price), sum(coalesce(stock_quantity, -1)),
            sum(coalesce(stock_daily_quantity, -1)), count(*) FILTER (WHERE is_active)) FROM sizes),
        (SELECT json_build_array(count(*), max(updated_at), count(*) FILTER (WHERE is_active)) FROM groups),
        (SELECT json_build_array(
            count(*), max(updated_at), sum(extra_price), count(*) FILTER (WHERE is_active)) FROM options)
    """
)


def fingerprint(db: Session, location_id: uuid.UUID) -> str:
    """A short digest that changes whenever this branch's menu does."""

    row = db.execute(_FINGERPRINT_SQL, {"location_id": location_id}).one()
    raw = json.dumps([list(part) if part is not None else None for part in row], default=str, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def cached_menu(
    db: Session,
    location_id: uuid.UUID,
    *,
    variant: str,
    build: Callable[[], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """The branch's menu as JSON-ready dicts: from Redis, or `build()` and stored.

    `variant` separates answers that differ for the same branch, such as
    available-only against everything.
    """

    key = f"menu:v1:{location_id}:{variant}:{fingerprint(db, location_id)}"
    try:
        stored = get_redis_client().get(key)
        if stored:
            return json.loads(stored)
    except (RedisError, ValueError):
        logger.warning("Menu cache unreadable; building the menu from the database")
    built = build()
    try:
        get_redis_client().set(key, json.dumps(built, default=str), ex=MENU_CACHE_TTL_SECONDS)
    except RedisError:
        pass
    return built


__all__ = ["MENU_CACHE_TTL_SECONDS", "cached_menu", "fingerprint"]
