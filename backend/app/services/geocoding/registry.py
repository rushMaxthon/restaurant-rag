"""Which geocoder answers.

Platform-level, like the courier and unlike payments: a coordinate is not
anybody's money, and every tenant wants the same accuracy.

**Ola Maps, then Google, when their keys exist; Nominatim otherwise.** Not a preference dial, an
ordering by accuracy — and the fallback is what makes this feature real in a
deployment that has never opened a Google Cloud console. Nothing to configure
for it to work, and one environment variable to make it good.

`None` is impossible here, which is the point: a geocoder is always available,
so callers never have to handle "there is no way to locate an address". What
they DO have to handle is a geocoder answering imprecisely, which is a
different problem and is what `GeocodedPoint.confidence` is for.
"""

from __future__ import annotations

import logging
import threading

from app.config import get_settings
from app.services.geocoding.base import Geocoder
from app.services.geocoding.google import GoogleGeocoder
from app.services.geocoding.nominatim import NominatimGeocoder
from app.services.geocoding.ola import OlaMapsGeocoder

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_geocoder: Geocoder | None = None


def geocoder() -> Geocoder:
    """The configured geocoder. Built once and held.

    Held because Nominatim's rate limit is enforced per process and a fresh
    instance per call would still share the module-level throttle, but Google's
    client would rebuild its connection pool on every keystroke of an
    autocomplete.
    """

    global _geocoder
    with _lock:
        if _geocoder is not None:
            return _geocoder
        settings = get_settings()
        if settings.ola_maps_api_key:
            _geocoder = OlaMapsGeocoder(
                api_key=settings.ola_maps_api_key,
                timeout_seconds=settings.geocoding_timeout_seconds,
                country_codes=settings.geocoding_country_codes,
            )
            logger.info("Geocoding through Ola Maps")
        elif settings.google_maps_api_key:
            _geocoder = GoogleGeocoder(
                api_key=settings.google_maps_api_key,
                timeout_seconds=settings.geocoding_timeout_seconds,
                country_codes=settings.geocoding_country_codes,
            )
            logger.info("Geocoding through Google")
        else:
            _geocoder = NominatimGeocoder(
                user_agent=settings.geocoding_user_agent,
                timeout_seconds=settings.geocoding_timeout_seconds,
                country_codes=settings.geocoding_country_codes,
            )
            logger.info(
                "Geocoding through OpenStreetMap; set GOOGLE_MAPS_API_KEY for "
                "building-level accuracy"
            )
        return _geocoder


def places_geocoder() -> GoogleGeocoder | OlaMapsGeocoder | None:
    """The geocoder that can power an autocomplete, if there is one.

    Separate from `geocoder()` because address SUGGESTIONS are not something
    every provider offers. Nominatim has no autocomplete worth putting in front
    of a customer — no session billing, no relevance ranking, and a rate limit
    of one request per second, which is slower than somebody types. So the
    checkout gets a dropdown when Google is configured and falls back to plain
    text boxes when it is not, rather than getting a dropdown that feels
    broken.
    """

    found = geocoder()
    return found if isinstance(found, (GoogleGeocoder, OlaMapsGeocoder)) else None


def reset_geocoder() -> None:
    """Forget the cached geocoder. For tests, and for a settings reload."""

    global _geocoder
    with _lock:
        _geocoder = None


__all__ = ["geocoder", "places_geocoder", "reset_geocoder"]


_fallback: NominatimGeocoder | None = None


def fallback_geocoder() -> NominatimGeocoder:
    """OpenStreetMap, for when Google refuses the key.

    Used only after a refusal that retrying will not fix - a key or billing
    problem (2026-10-07: Google answered REQUEST_DENIED for every address and
    nothing could be located). Less precise than Google, but an address that is
    located by it is priced and accepted; one that is not located at all is
    neither. Never for suggestions: Nominatim's terms forbid autocomplete.
    """

    global _fallback
    with _lock:
        if _fallback is None:
            settings = get_settings()
            _fallback = NominatimGeocoder(
                user_agent=settings.geocoding_user_agent,
                timeout_seconds=settings.geocoding_timeout_seconds,
                country_codes=settings.geocoding_country_codes,
            )
        return _fallback

