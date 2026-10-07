"""Ola Maps - address suggestions, place details and geocoding for India.

Chosen 2026-10-07, after Google refused the platform's key because billing
was switched off on its Cloud project and checkout lost its address
dropdown. Ola's free tier is 100,000 requests a month per API (autocomplete,
geocoding, place details) with no card or prepaid credit needed inside it,
and its data is built for Indian addresses - where OpenStreetMap, the other
fallback, could not find "Rander Road, Surat" at all.

Its responses use Google's OLDER JSON shape: `formatted_address`,
`geometry.location`, `geometry.location_type`, and `address_components` with
`long_name` and `types`. So the precision grading (`google.confidence_for`)
and the address-box flattening (`google.address_parts`) are reused rather
than written twice - they are the parts with history, and the history is
the same.

The key goes in the query string (`api_key=`), which is how Ola takes it.
Request URLs are logged by the HTTP client, so `log_privacy.RedactSecrets`
blanks it before any log line is written.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from app.services.geocoding.base import AddressQuery, GeocodeConfidence, GeocodedPoint, GeocodingError
from app.services.geocoding.google import address_parts, confidence_for

logger = logging.getLogger(__name__)

PROVIDER_NAME = "ola"

#: 30 km: a city and its suburbs, without excluding the customer one town over.
_BIAS_RADIUS_METRES = 30000


class OlaMapsGeocoder:
    """Ola Maps' Places APIs, in the shape `GoogleGeocoder` offers."""

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.olamaps.io",
        timeout_seconds: float = 5.0,
        country_codes: str = "",
        language: str = "en",
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._countries = [c.strip().lower() for c in country_codes.split(",") if c.strip()]
        self._language = language

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get(self, path: str, params: dict[str, Any], timeout: float | None) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self._base_url}{path}",
                params={**params, "api_key": self._api_key},
                # Ola asks for a request id on every call, for their tracing.
                headers={"X-Request-Id": str(uuid.uuid4())},
                timeout=timeout or self._timeout,
            )
        except httpx.HTTPError as error:
            raise GeocodingError(f"Could not reach Ola Maps: {error}") from error
        if response.status_code >= 400:
            try:
                body = response.json() or {}
                detail = str(body.get("message") or body.get("error_message") or body.get("error") or "")[:200]
            except ValueError:
                detail = response.text[:200]
            # 401/403 is the key, its restrictions or the account, and fails
            # identically forever; 429 and 5xx are worth trying again later.
            raise GeocodingError(
                f"Ola Maps refused {path}: {response.status_code} {detail}".strip(),
                retryable=response.status_code >= 500 or response.status_code == 429,
            )
        try:
            return response.json() or {}
        except ValueError as error:
            raise GeocodingError(f"Ola Maps sent a non-JSON reply: {error}") from error

    # --- typed addresses ---------------------------------------------------

    def geocode(self, query: AddressQuery, *, timeout: float | None = None) -> GeocodedPoint | None:
        if query.is_empty:
            return None
        body = self._get(
            "/places/v1/geocode",
            {"address": query.as_text(), "language": self._language},
            timeout,
        )
        results = body.get("geocodingResults") or []
        if not results or not isinstance(results[0], dict):
            return None
        result = results[0]
        location = ((result.get("geometry") or {}).get("location")) or {}
        try:
            latitude, longitude = float(location["lat"]), float(location["lng"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Ola Maps returned a result with no coordinates")
            return None
        return GeocodedPoint(
            latitude=latitude,
            longitude=longitude,
            confidence=confidence_for(result),
            matched=str(result.get("formatted_address") or ""),
            provider=self.name,
            raw=result,
        )

    # --- suggestions ---------------------------------------------------------

    def suggest(
        self,
        text: str,
        *,
        session_token: str,
        latitude: float | None = None,
        longitude: float | None = None,
        timeout: float | None = None,
    ) -> list[dict[str, str]]:
        """Suggestions for what somebody has typed so far.

        Biased toward the restaurant's own city when its location is known;
        no type filter, because many Indian addresses are a society or a
        complex rather than a street address (the same reasoning as Google's).
        `session_token` is accepted for the shared interface; Ola does not
        bill by session.
        """

        if not text.strip():
            return []
        params: dict[str, Any] = {"input": text.strip(), "language": self._language}
        if latitude is not None and longitude is not None:
            params["location"] = f"{latitude},{longitude}"
            params["radius"] = _BIAS_RADIUS_METRES
        body = self._get("/places/v1/autocomplete", params, timeout)

        out: list[dict[str, str]] = []
        for prediction in body.get("predictions") or []:
            if not isinstance(prediction, dict):
                continue
            place_id = str(prediction.get("place_id") or "")
            if not place_id:
                continue
            structured = prediction.get("structured_formatting") or {}
            description = str(prediction.get("description") or "")
            out.append(
                {
                    "place_id": place_id,
                    "primary": str(structured.get("main_text") or "") or description,
                    "secondary": str(structured.get("secondary_text") or ""),
                    "description": description,
                }
            )
        return out

    def resolve(
        self, place_id: str, *, session_token: str, timeout: float | None = None
    ) -> tuple[GeocodedPoint, dict[str, str]] | None:
        """Coordinates and address parts of the place the customer picked.

        ROOFTOP because the customer chose this place from a list: there is no
        more precise statement available.
        """

        place_id = place_id.strip()
        if not place_id:
            return None
        body = self._get("/places/v1/details", {"place_id": place_id, "language": self._language}, timeout)
        result = body.get("result")
        if not isinstance(result, dict):
            return None
        location = ((result.get("geometry") or {}).get("location")) or {}
        try:
            latitude, longitude = float(location["lat"]), float(location["lng"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Ola Maps returned a place with no coordinates")
            return None
        point = GeocodedPoint(
            latitude=latitude,
            longitude=longitude,
            confidence=GeocodeConfidence.ROOFTOP,
            matched=str(result.get("formatted_address") or ""),
            provider=self.name,
            raw=result,
        )
        return point, address_parts(result)


__all__ = ["PROVIDER_NAME", "OlaMapsGeocoder"]
