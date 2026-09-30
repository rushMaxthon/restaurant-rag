"""OpenStreetMap's Nominatim — the geocoder that needs no account.

Chosen as the default because it is the only one of the three that works the
moment this code ships: no key, no billing profile, no card. That makes the
delivery quote real for every deployment rather than for the ones that have
been through a Google Cloud console.

It is also the one with rules, and they are not optional. The OSM foundation
runs this on donated hardware and blocks abusers by User-Agent and IP:

* **At most one request per second.** Enforced here in `_throttle`, process
  wide, rather than trusted to callers.
* **A genuine identifying User-Agent.** A default library agent is grounds for
  a block, so `geocoding_user_agent` is a setting and the header is never
  omitted.
* **Cache aggressively.** Handled a layer up in `service.py`, which is why
  this module does no caching of its own.

Accuracy is the trade. In Indian cities OSM's building-level coverage is
patchy and `_CONFIDENCE` will honestly return `POSTCODE` or `LOCALITY` for
addresses Google resolves to a rooftop — which is exactly why confidence
travels with the point instead of being assumed. For production accuracy,
configure Google or Mapbox; the registry will prefer them.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from app.services.geocoding.base import (
    AddressQuery,
    GeocodeConfidence,
    GeocodedPoint,
    GeocodingError,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "nominatim"

#: Their `addresstype`/`type` vocabulary, mapped onto ours. Only the entries
#: that mean something for pricing a delivery are listed; everything else
#: falls through to LOCALITY, which is the safe direction — an unrecognised
#: type must not be mistaken for a rooftop.
_CONFIDENCE = {
    "building": GeocodeConfidence.ROOFTOP,
    "house": GeocodeConfidence.ROOFTOP,
    "residential": GeocodeConfidence.ROOFTOP,
    "apartments": GeocodeConfidence.ROOFTOP,
    "commercial": GeocodeConfidence.ROOFTOP,
    "retail": GeocodeConfidence.ROOFTOP,
    "industrial": GeocodeConfidence.ROOFTOP,
    "amenity": GeocodeConfidence.ROOFTOP,
    "shop": GeocodeConfidence.ROOFTOP,
    "office": GeocodeConfidence.ROOFTOP,
    # Named residential complexes, which is how a great many Indian addresses
    # identify themselves. OSM tags these inconsistently, so several spellings
    # of the same idea are listed rather than one canonical tag.
    "hamlet": GeocodeConfidence.LOCALITY,
    "isolated_dwelling": GeocodeConfidence.ROOFTOP,
    "terrace": GeocodeConfidence.ROOFTOP,
    "detached": GeocodeConfidence.ROOFTOP,
    "semidetached_house": GeocodeConfidence.ROOFTOP,
    "bungalow": GeocodeConfidence.ROOFTOP,
    "dormitory": GeocodeConfidence.ROOFTOP,
    "hotel": GeocodeConfidence.ROOFTOP,
    "school": GeocodeConfidence.ROOFTOP,
    "hospital": GeocodeConfidence.ROOFTOP,
    "place_of_worship": GeocodeConfidence.ROOFTOP,
    "mall": GeocodeConfidence.ROOFTOP,
    "supermarket": GeocodeConfidence.ROOFTOP,
    "restaurant": GeocodeConfidence.ROOFTOP,
    # Deliberately NOT precise: a lake, a park or a river is a landmark people
    # navigate by, not a door a rider can hand food to.
    "lake": GeocodeConfidence.LOCALITY,
    "park": GeocodeConfidence.LOCALITY,
    "garden": GeocodeConfidence.LOCALITY,
    "water": GeocodeConfidence.LOCALITY,
    "road": GeocodeConfidence.STREET,
    "street": GeocodeConfidence.STREET,
    "highway": GeocodeConfidence.STREET,
    "postcode": GeocodeConfidence.POSTCODE,
    "postal_code": GeocodeConfidence.POSTCODE,
    "suburb": GeocodeConfidence.LOCALITY,
    "neighbourhood": GeocodeConfidence.LOCALITY,
    "quarter": GeocodeConfidence.LOCALITY,
    "village": GeocodeConfidence.LOCALITY,
    "town": GeocodeConfidence.LOCALITY,
    "city": GeocodeConfidence.LOCALITY,
    "municipality": GeocodeConfidence.LOCALITY,
    "county": GeocodeConfidence.REGION,
    "state": GeocodeConfidence.REGION,
    "state_district": GeocodeConfidence.REGION,
    "country": GeocodeConfidence.REGION,
}

#: One second between calls, which is their published limit. A module-level
#: lock rather than a per-instance one: the limit is per CLIENT, and two
#: provider instances in one process would otherwise each keep to it and
#: together break it.
_throttle_lock = threading.Lock()
_last_call = 0.0


def _throttle(min_interval: float) -> None:
    """Hold the caller until a request is allowed.

    Deliberately blocking, and deliberately here rather than at the call site.
    A checkout that waits 900ms is slower; an IP banned by OSM is a feature
    that stops working for everybody, and no caller can be relied on to
    remember the rule.
    """

    global _last_call
    with _throttle_lock:
        waited = time.monotonic() - _last_call
        if waited < min_interval:
            time.sleep(min_interval - waited)
        _last_call = time.monotonic()


def confidence_for(payload: dict[str, Any]) -> GeocodeConfidence:
    """What a Nominatim result is precise enough to be used for.

    Reads `addresstype` first, then `type`, then `class`, because which of the
    three carries the useful value depends on what matched — a house comes back
    as `addresstype: building`, a road as `type: residential` under
    `class: highway`, and trusting only one of them silently downgrades half
    the results to LOCALITY.
    """

    for key in ("addresstype", "type", "class"):
        value = str(payload.get(key) or "").strip().lower()
        if value in _CONFIDENCE:
            return _CONFIDENCE[value]
    return GeocodeConfidence.LOCALITY


class NominatimGeocoder:
    """OpenStreetMap's geocoder, within its usage policy."""

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        base_url: str = "https://nominatim.openstreetmap.org",
        user_agent: str,
        min_interval_seconds: float = 1.0,
        timeout_seconds: float = 5.0,
        country_codes: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._min_interval = min_interval_seconds
        self._timeout = timeout_seconds
        # Restricting the search to the countries a deployment actually serves
        # is the cheapest accuracy win available: without it, an Indian street
        # name matches a same-named street in another country and the answer
        # looks perfectly reasonable.
        self._country_codes = country_codes.strip().lower()

    def is_configured(self) -> bool:
        # No key to check. A missing User-Agent is the one thing that makes
        # this unusable, because their policy treats it as abuse.
        return bool(self._base_url and self._user_agent)

    def geocode(self, query: AddressQuery, *, timeout: float | None = None) -> GeocodedPoint | None:
        if query.is_empty:
            return None

        # Freeform, NOT structured, and this was measured rather than assumed.
        #
        # Nominatim's structured search treats `street` as a field that must
        # match an OSM street, and it will not fall back. "Kankaria Lake,
        # Ahmedabad, Gujarat, India" returns the lake as freeform and returns
        # NOTHING at all as structured. Indian addresses are written from
        # landmarks and society names far more often than from numbered
        # streets, so structured search fails on the majority of real input
        # here — silently, with a 200 and an empty list, which reads exactly
        # like "that address does not exist".
        #
        # Google is the opposite way round and handles structured input well;
        # see `google.py`. This is a per-provider fact, which is the reason
        # each provider builds its own request from `AddressQuery` instead of
        # a shared request builder deciding for both.
        params: dict[str, Any] = {
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
            "q": query.as_text(),
        }
        if self._country_codes:
            params["countrycodes"] = self._country_codes

        _throttle(self._min_interval)
        try:
            response = httpx.get(
                f"{self._base_url}/search",
                params=params,
                headers={"User-Agent": self._user_agent, "Accept": "application/json"},
                timeout=timeout or self._timeout,
            )
        except httpx.HTTPError as error:
            raise GeocodingError(f"Could not reach Nominatim: {error}") from error

        if response.status_code == 429:
            # Their rate limiter, which means the throttle above was not
            # enough — another process sharing this IP, most likely.
            raise GeocodingError("Nominatim is rate-limiting us", retryable=True)
        if response.status_code >= 400:
            raise GeocodingError(
                f"Nominatim refused the lookup: {response.status_code}",
                retryable=response.status_code >= 500,
            )
        try:
            results = response.json()
        except ValueError as error:
            raise GeocodingError(f"Nominatim sent a non-JSON reply: {error}") from error
        if not isinstance(results, list) or not results:
            return None

        top = results[0]
        try:
            latitude = float(top["lat"])
            longitude = float(top["lon"])
        except (KeyError, TypeError, ValueError):
            # A result with no usable coordinate is a no-match, not an error.
            logger.warning("Nominatim returned a result with no coordinates: %r", top)
            return None

        return GeocodedPoint(
            latitude=latitude,
            longitude=longitude,
            confidence=confidence_for(top),
            matched=str(top.get("display_name") or ""),
            provider=self.name,
            raw=top,
        )


__all__ = ["PROVIDER_NAME", "NominatimGeocoder", "confidence_for"]
