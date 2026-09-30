"""Google — geocoding and Places, the accurate option.

Worth the account. In Indian cities Google resolves society names, apartment
blocks and landmark-relative addresses that OSM has never heard of, and those
are exactly how people here write where they live. "Radhe Shyam Society,
Singanpor" is a real address that Nominatim shrugs at.

Two surfaces, and they answer different questions:

* **Geocoding** (`geocode`) takes an address we already hold and returns a
  point. This is the WhatsApp and saved-address path, where nobody is sitting
  in front of a dropdown.
* **Places** (`suggest` / `resolve`) powers an autocomplete box. The customer
  picks a real place and its coordinates come back from Google's own record,
  so nothing is parsed, guessed or interpolated. This is the accurate path and
  the one a checkout should use.

The key lives **server side**. Every call here is ours, and the browser never
sees the credential — which is the reason the autocomplete talks to our own
endpoint rather than loading Google's JavaScript with a key in the bundle. A
referrer-restricted browser key is the usual practice and it is not wrong, but
it is a key in public with a quota attached, and the same feature works without
that exposure.

`session_token` on the Places calls is not decoration. Google bills
autocomplete per SESSION when the keystrokes and the final details lookup share
a token, and PER REQUEST when they do not. Dropping it turns one billable
session into one charge per character typed.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.geocoding.base import (
    AddressQuery,
    GeocodeConfidence,
    GeocodedPoint,
    GeocodingError,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "google"

#: Their `location_type`, which is the field that actually says how the point
#: was arrived at. ROOFTOP is a real building; RANGE_INTERPOLATED is a guess
#: along a street and good enough to price; the other two are centroids.
_LOCATION_TYPES = {
    "ROOFTOP": GeocodeConfidence.ROOFTOP,
    "RANGE_INTERPOLATED": GeocodeConfidence.STREET,
    "GEOMETRIC_CENTER": GeocodeConfidence.LOCALITY,
    "APPROXIMATE": GeocodeConfidence.LOCALITY,
}

#: Their `types` array, read when `location_type` is absent or approximate. A
#: result typed `premise` or `street_address` is precise regardless of what
#: `location_type` says, and a `postal_code` result is not — reading only
#: `location_type` marks a perfectly good street address APPROXIMATE and
#: throws the quote away.
_RESULT_TYPES = {
    "premise": GeocodeConfidence.ROOFTOP,
    "subpremise": GeocodeConfidence.ROOFTOP,
    "street_address": GeocodeConfidence.ROOFTOP,
    "establishment": GeocodeConfidence.ROOFTOP,
    "point_of_interest": GeocodeConfidence.ROOFTOP,
    "route": GeocodeConfidence.STREET,
    "intersection": GeocodeConfidence.STREET,
    "postal_code": GeocodeConfidence.POSTCODE,
    "neighborhood": GeocodeConfidence.LOCALITY,
    "sublocality": GeocodeConfidence.LOCALITY,
    "locality": GeocodeConfidence.LOCALITY,
    "administrative_area_level_2": GeocodeConfidence.REGION,
    "administrative_area_level_1": GeocodeConfidence.REGION,
    "country": GeocodeConfidence.REGION,
}

#: Statuses that mean "asked correctly, found nothing" — an answer, not a
#: failure, and the difference decides whether the result is worth caching.
_EMPTY_STATUSES = {"ZERO_RESULTS", "NOT_FOUND"}


def confidence_for(result: dict[str, Any]) -> GeocodeConfidence:
    """How precise a Google result is.

    Takes the BEST of what `location_type` and `types` claim, because they
    disagree in both directions: a society entrance comes back
    `establishment` with `location_type: APPROXIMATE`, and reading only the
    latter would refuse to price a perfectly deliverable address.
    """

    best: GeocodeConfidence | None = None
    geometry = result.get("geometry")
    geometry = geometry if isinstance(geometry, dict) else {}
    mapped = _LOCATION_TYPES.get(str(geometry.get("location_type") or "").strip().upper())
    if mapped is not None:
        best = mapped
    for entry in result.get("types") or []:
        candidate = _RESULT_TYPES.get(str(entry).strip().lower())
        if candidate is None:
            continue
        # Enum members are not ordered, so "better" is spelled out: precise
        # beats imprecise, and among the rest the first reading stands.
        if best is None or (candidate.is_precise and not best.is_precise):
            best = candidate
    return best or GeocodeConfidence.LOCALITY


class GoogleGeocoder:
    """Google's Geocoding and Places APIs."""

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://maps.googleapis.com/maps/api",
        timeout_seconds: float = 5.0,
        country_codes: str = "",
        language: str = "en",
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        # `components=country:in|ca` on geocoding, `components=country:in` on
        # autocomplete. Both narrow the search to where a deployment actually
        # delivers, which is the cheapest accuracy win there is.
        self._countries = [c.strip().lower() for c in country_codes.split(",") if c.strip()]
        self._language = language

    def is_configured(self) -> bool:
        return bool(self._api_key and self._base_url)

    def _get(self, path: str, params: dict[str, Any], timeout: float | None) -> dict[str, Any]:
        params = {**params, "key": self._api_key}
        try:
            response = httpx.get(
                f"{self._base_url}{path}", params=params, timeout=timeout or self._timeout
            )
        except httpx.HTTPError as error:
            raise GeocodingError(f"Could not reach Google: {error}") from error
        if response.status_code >= 400:
            raise GeocodingError(
                f"Google refused {path}: {response.status_code}",
                retryable=response.status_code >= 500,
            )
        try:
            body = response.json() or {}
        except ValueError as error:
            raise GeocodingError(f"Google sent a non-JSON reply: {error}") from error

        status = str(body.get("status") or "")
        if status in {"OK", *_EMPTY_STATUSES}:
            return body
        # REQUEST_DENIED is a key or billing problem and will fail identically
        # forever; OVER_QUERY_LIMIT is worth trying again later. Never retried
        # in a loop from here either way — the caller is a checkout.
        raise GeocodingError(
            f"Google answered {status}: {body.get('error_message') or 'no detail'}",
            retryable=status != "REQUEST_DENIED",
        )

    # --- geocoding --------------------------------------------------------

    def geocode(self, query: AddressQuery, *, timeout: float | None = None) -> GeocodedPoint | None:
        if query.is_empty:
            return None
        params: dict[str, Any] = {"address": query.as_text(), "language": self._language}
        if self._countries:
            params["components"] = "|".join(f"country:{c}" for c in self._countries)

        body = self._get("/geocode/json", params, timeout)
        results = body.get("results") or []
        if not results:
            return None
        return self._point(results[0])

    def _point(self, result: dict[str, Any]) -> GeocodedPoint | None:
        geometry = result.get("geometry")
        geometry = geometry if isinstance(geometry, dict) else {}
        location = geometry.get("location")
        location = location if isinstance(location, dict) else {}
        try:
            latitude = float(location["lat"])
            longitude = float(location["lng"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Google returned a result with no coordinates: %r", result)
            return None
        return GeocodedPoint(
            latitude=latitude,
            longitude=longitude,
            confidence=confidence_for(result),
            matched=str(result.get("formatted_address") or ""),
            provider=self.name,
            raw=result,
        )

    # --- places -----------------------------------------------------------

    def suggest(
        self,
        text: str,
        *,
        session_token: str,
        latitude: float | None = None,
        longitude: float | None = None,
        timeout: float | None = None,
    ) -> list[dict[str, str]]:
        """Address suggestions for what somebody has typed so far.

        Returns `place_id` plus the two-part label Google formats for a list —
        "12, MG Road" and "Navrangpura, Ahmedabad" — because a single joined
        string reads badly in a dropdown and every client would split it again.

        `latitude`/`longitude` bias results toward the restaurant's own city.
        Without a bias, three characters of an Indian street name return
        matches from four states, and the customer scrolls past their own
        neighbourhood.
        """

        if not text.strip():
            return []
        params: dict[str, Any] = {
            "input": text.strip(),
            "sessiontoken": session_token,
            "language": self._language,
            # Addresses, not petrol stations. `geocode` would also return
            # cities, which are not somewhere a rider can deliver to.
            "types": "address",
        }
        if self._countries:
            params["components"] = "|".join(f"country:{c}" for c in self._countries)
        if latitude is not None and longitude is not None:
            # 30 km, which covers a city and its suburbs without excluding the
            # customer who lives one town over.
            params["location"] = f"{latitude},{longitude}"
            params["radius"] = 30000

        body = self._get("/place/autocomplete/json", params, timeout)
        out: list[dict[str, str]] = []
        for entry in body.get("predictions") or []:
            place_id = str(entry.get("place_id") or "")
            if not place_id:
                continue
            formatting = entry.get("structured_formatting")
            formatting = formatting if isinstance(formatting, dict) else {}
            out.append(
                {
                    "place_id": place_id,
                    "primary": str(formatting.get("main_text") or entry.get("description") or ""),
                    "secondary": str(formatting.get("secondary_text") or ""),
                    "description": str(entry.get("description") or ""),
                }
            )
        return out

    def resolve(
        self, place_id: str, *, session_token: str, timeout: float | None = None
    ) -> tuple[GeocodedPoint, dict[str, str]] | None:
        """The coordinates and address parts of a place the customer picked.

        This is the accurate path and the reason Places is worth having. The
        point is Google's own record of that address, not an interpretation of
        a string somebody typed — so `confidence` is ROOFTOP because the
        customer chose a building, and the structured parts come back filled
        in rather than parsed out of a blob.
        """

        if not place_id.strip():
            return None
        body = self._get(
            "/place/details/json",
            {
                "place_id": place_id.strip(),
                "sessiontoken": session_token,
                "language": self._language,
                # Asked for explicitly: Places bills by the fields requested,
                # and the default set is the expensive one.
                "fields": "formatted_address,geometry/location,address_component,name",
            },
            timeout,
        )
        result = body.get("result")
        if not isinstance(result, dict):
            return None
        point = self._point({**result, "types": ["premise"]})
        if point is None:
            return None
        return point, address_parts(result)


#: Which Google component type fills which of our address boxes. Longest-lived
#: part of this module: their component tree is stable and our form is not.
_COMPONENTS = {
    "street_number": "street_number",
    "route": "route",
    "sublocality_level_1": "sublocality",
    "sublocality": "sublocality",
    "locality": "city",
    "administrative_area_level_2": "district",
    "administrative_area_level_1": "state",
    "postal_code": "postal_code",
    "country": "country",
}


def address_parts(result: dict[str, Any]) -> dict[str, str]:
    """Google's component tree, flattened into our form's boxes.

    The house number and street arrive as separate components and belong in one
    box, which is the only assembly done here. Everything else is a direct
    mapping, because inventing a city from a postcode is the kind of help that
    sends food to the wrong place.
    """

    found: dict[str, str] = {}
    for component in result.get("address_components") or []:
        if not isinstance(component, dict):
            continue
        long_name = str(component.get("long_name") or "")
        for entry in component.get("types") or []:
            key = _COMPONENTS.get(str(entry).strip().lower())
            if key and key not in found:
                found[key] = long_name

    line1 = " ".join(p for p in (found.get("street_number"), found.get("route")) if p).strip()
    if not line1:
        # A named building with no street number — common for societies and
        # apartment complexes here, and the name is the address.
        line1 = str(result.get("name") or "").strip()
    return {
        "line1": line1,
        "line2": found.get("sublocality", ""),
        # Some Indian addresses carry the district rather than a locality.
        "city": found.get("city") or found.get("district", ""),
        "state": found.get("state", ""),
        "postal_code": found.get("postal_code", ""),
        "country": found.get("country", ""),
        "formatted": str(result.get("formatted_address") or ""),
    }


__all__ = ["PROVIDER_NAME", "GoogleGeocoder", "address_parts", "confidence_for"]
