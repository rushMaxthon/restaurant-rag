"""Looking up an address once, and never again.

A geocode result does not change. The coordinates of a building are the same
tomorrow, so every repeat lookup is a wasted call — and with Google that is a
wasted payment, while with Nominatim it is a step toward a block. Caching is
therefore not an optimisation here, it is part of using either provider
correctly.

Three layers, cheapest first:

1. **The row itself.** A branch has `latitude`/`longitude` columns and a saved
   address now does too. A coordinate stored on the record it belongs to costs
   nothing to read and survives every cache flush. This is the layer that
   matters: a returning customer ordering to a saved address is priced with
   ZERO geocoder calls.
2. **`geocode_cache`**, a table keyed by the normalised address text, for
   addresses typed fresh that we do not own a row for.
3. **Redis**, in front of the table, because the checkout asks on a keystroke
   boundary and a Postgres round trip per address is avoidable.

A failed lookup is cached too, and deliberately: an address that does not
resolve will not resolve on the next attempt either, and re-asking on every
page load is how a quota disappears. But only when the geocoder ANSWERED "no
match" — a timeout or a refused key is not a fact about the address, and
caching it would pin a good address to "unknown" until the entry expired.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.geocode_cache import GeocodeCache
from app.services.cache import cache_get_json, cache_set_json
from app.services.geocoding.base import (
    AddressQuery,
    GeocodeConfidence,
    GeocodedPoint,
    GeocodingError,
)
from app.services.geocoding.registry import geocoder

logger = logging.getLogger(__name__)

#: Bumped when the stored shape changes, so old entries are ignored rather
#: than mis-read. Cheaper than a migration for cache data.
_CACHE_VERSION = 1


def _fingerprint(query: AddressQuery) -> str:
    """A short stable id for an address, for both cache layers.

    A hash rather than the text itself because the text can be 300 characters
    and is the key of an indexed column. SHA-256 truncated to 32 hex
    characters: a collision needs roughly 2^64 distinct addresses, and the
    consequence of one would be a wrong delivery quote for a single address,
    not a security failure.
    """

    return hashlib.sha256(query.cache_key().encode("utf-8")).hexdigest()[:32]


def _redis_key(fingerprint: str) -> str:
    return f"geocode:v{_CACHE_VERSION}:{fingerprint}"


def _from_stored(
    latitude: float | None, longitude: float | None, confidence: str, provider: str, matched: str
) -> GeocodedPoint | None:
    if latitude is None or longitude is None:
        return None
    try:
        level = GeocodeConfidence(confidence)
    except ValueError:
        # A confidence we no longer recognise. Treated as imprecise rather
        # than discarded: the coordinate is still real, it just cannot be
        # trusted to price a delivery on its own.
        level = GeocodeConfidence.LOCALITY
    return GeocodedPoint(
        latitude=float(latitude),
        longitude=float(longitude),
        confidence=level,
        matched=matched,
        provider=provider,
    )


def locate(db: Session, query: AddressQuery) -> GeocodedPoint | None:
    """Where this address is. Cached at both layers, and never asked twice.

    Returns None for "nobody could place it", which callers must handle — it is
    the normal outcome for a half-typed address and for the free-text blocks
    stored before any of this existed.
    """

    if query.is_empty:
        return None
    fingerprint = _fingerprint(query)

    cached = cache_get_json(_redis_key(fingerprint))
    if isinstance(cached, dict):
        if cached.get("miss"):
            return None
        point = _from_stored(
            cached.get("lat"),
            cached.get("lng"),
            str(cached.get("confidence") or ""),
            str(cached.get("provider") or ""),
            str(cached.get("matched") or ""),
        )
        if point is not None:
            return point

    row = db.scalar(select(GeocodeCache).where(GeocodeCache.fingerprint == fingerprint))
    if row is not None and not _is_stale(row):
        _remember_in_redis(fingerprint, row)
        if row.latitude is None:
            return None
        return _from_stored(
            row.latitude, row.longitude, row.confidence, row.provider, row.matched
        )

    provider = geocoder()
    settings = get_settings()
    try:
        point = provider.geocode(query, timeout=settings.geocoding_timeout_seconds)
    except GeocodingError as error:
        # Not written to either cache. A transport failure or a bad key says
        # nothing about the address, and recording it as "not found" would
        # blind us to a perfectly good address for as long as the entry lived.
        logger.warning("Could not geocode %r: %s", query.cache_key()[:80], error)
        return None
    except Exception:  # noqa: BLE001 - a checkout must survive a geocoder bug
        logger.exception("Geocoding raised; treating the address as unlocatable")
        return None

    _store(db, fingerprint, query, point, provider_name=getattr(provider, "name", ""))
    return point


def _is_stale(row: GeocodeCache) -> bool:
    """Whether a stored lookup is old enough to be worth asking again.

    Addresses are not immutable forever — new buildings appear, and a provider
    that knew nothing last month may know the street now. A long expiry rather
    than none, so a "not found" from a thin OSM month does not become
    permanent, and long enough that the cache still does its job.
    """

    days = get_settings().geocoding_cache_days
    if days <= 0:
        return False
    fetched = row.updated_at or row.created_at
    if fetched is None:
        return True
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - fetched > timedelta(days=days)


def _remember_in_redis(fingerprint: str, row: GeocodeCache) -> None:
    payload = (
        {"miss": True}
        if row.latitude is None
        else {
            "lat": float(row.latitude),
            "lng": float(row.longitude or 0.0),
            "confidence": row.confidence,
            "provider": row.provider,
            "matched": row.matched,
        }
    )
    cache_set_json(_redis_key(fingerprint), payload, ttl_seconds=60 * 60 * 24)


def _store(
    db: Session,
    fingerprint: str,
    query: AddressQuery,
    point: GeocodedPoint | None,
    *,
    provider_name: str,
) -> None:
    """Write the answer to both layers, including a miss.

    Uses its own nested transaction so a cache write can never take down the
    request that produced it: this runs inside a checkout, and an address
    somebody else geocoded a millisecond earlier must not turn a delivery
    quote into a 500.
    """

    row = db.scalar(select(GeocodeCache).where(GeocodeCache.fingerprint == fingerprint))
    try:
        with db.begin_nested():
            if row is None:
                row = GeocodeCache(fingerprint=fingerprint, query_text=query.cache_key()[:500])
                db.add(row)
            row.latitude = point.latitude if point else None
            row.longitude = point.longitude if point else None
            row.confidence = point.confidence.value if point else ""
            row.provider = (point.provider if point else provider_name) or provider_name
            row.matched = (point.matched if point else "")[:500]
    except IntegrityError:
        # Another request stored the same address first. Its answer is as good
        # as ours; nothing to do.
        logger.info("Geocode for %s was already cached by another request", fingerprint)
        return

    stored = GeocodeCache(
        fingerprint=fingerprint,
        latitude=row.latitude,
        longitude=row.longitude,
        confidence=row.confidence,
        provider=row.provider,
        matched=row.matched,
    )
    _remember_in_redis(fingerprint, stored)


__all__ = ["locate"]
