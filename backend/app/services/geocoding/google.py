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

    `types` says WHAT was found; `location_type` says how the point was
    derived. They disagree in both directions and neither alone is enough:
    reading only `location_type` marks a society entrance APPROXIMATE and
    throws away a perfectly deliverable address, while reading the more
    optimistic of the two grades a country centroid as good enough to charge
    for. So the type wins, except that an actual address point outranks any
    label.
    """

    geometry = result.get("geometry")
    geometry = geometry if isinstance(geometry, dict) else {}
    located = _LOCATION_TYPES.get(str(geometry.get("location_type") or "").strip().upper())

    # `types` is authoritative about WHAT was found; `location_type` only says
    # how the point was derived. Taking the more optimistic of the two was a
    # bug with a price on it: gibberish geocodes to `types: ["country"]` with
    # `location_type: APPROXIMATE`, and reading APPROXIMATE as a locality
    # graded the centroid of India as precise enough to price a delivery from.
    # The courier honestly quoted 769 km and ₹7,715.85 to deliver a ₹50 loaf.
    typed: GeocodeConfidence | None = None
    for entry in result.get("types") or []:
        candidate = _RESULT_TYPES.get(str(entry).strip().lower())
        if candidate is None:
            continue
        # The most precise recognised type wins, which is what rescues a
        # society entrance typed `establishment` alongside vaguer labels.
        if typed is None or candidate.rank > typed.rank:
            typed = candidate

    # ROOFTOP and RANGE_INTERPOLATED are a stronger claim than any type name:
    # they mean Google has an actual address point rather than a centroid.
    if located is not None and located.is_precise:
        return located
    return typed or located or GeocodeConfidence.LOCALITY


class GoogleGeocoder:
    """Google's Geocoding and Places APIs."""

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://maps.googleapis.com/maps/api",
        #: Places lives on its own host now, and geocoding does not. Kept as a
        #: separate setting rather than derived from the other, because they are
        #: separately versioned services that happen to share a key.
        places_url: str = "https://places.googleapis.com/v1",
        timeout_seconds: float = 5.0,
        country_codes: str = "",
        language: str = "en",
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._places_url = places_url.rstrip("/")
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

    def _places_call(
        self,
        method: str,
        path: str,
        *,
        field_mask: str,
        timeout: float | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """One call to the NEW Places API.

        `places.googleapis.com/v1`, not `maps.googleapis.com/maps/api/place`.

        The legacy Places API went legacy on 1 March 2025 and **cannot be
        enabled on a Cloud project created after that date** — it does not
        appear in the console at all. Code written against it therefore fails
        on every new deployment with a 403, which reads exactly like a bad key
        and sends whoever is debugging it to check the wrong thing. Geocoding
        is unaffected and stays on the old host.

        Two differences shape this:

        * **The field mask is mandatory and IS the billing model.** You are
          charged for the fields you ask for, so the masks below are the
          shortest that answer the question. `*` is both refused on some
          endpoints and an expensive habit.
        * **The key travels in a header**, which is better anyway: query
          strings end up in access logs and proxies.
        """

        try:
            response = httpx.request(
                method,
                f"{self._places_url}{path}",
                headers={
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": field_mask,
                    "Content-Type": "application/json",
                },
                timeout=timeout or self._timeout,
                **kwargs,
            )
        except httpx.HTTPError as error:
            raise GeocodingError(f"Could not reach Google Places: {error}") from error

        if response.status_code >= 400:
            # Their own reason, surfaced. "Places API (New) has not been used in
            # project ... before or it is disabled" is the sentence somebody
            # needs to read, and without it a 403 is indistinguishable from a
            # rejected key.
            try:
                detail = str((response.json() or {}).get("error", {}).get("message", ""))[:200]
            except ValueError:
                detail = response.text[:200]
            raise GeocodingError(
                f"Google Places refused {path}: {response.status_code} {detail}",
                # 403 is a key, billing or not-enabled problem and fails
                # identically forever.
                retryable=response.status_code >= 500,
            )
        try:
            return response.json() or {}
        except ValueError as error:
            raise GeocodingError(f"Google Places sent a non-JSON reply: {error}") from error

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

        Returns `place_id` plus the two-part label the API formats for a list —
        "12, MG Road" above "Navrangpura, Ahmedabad" — because a single joined
        string reads badly in a dropdown and every client would split it again.

        `latitude`/`longitude` bias results toward the restaurant's own city.
        Without a bias, three characters of an Indian street name return matches
        from four states and the customer scrolls past their own neighbourhood.

        **No type filter, deliberately.** Restricting to street addresses would
        drop exactly the results that matter here: a great many Indian addresses
        are a society, a complex or a mall, which the API classes as
        establishments rather than addresses. That restriction is what the
        legacy version of this method had, and it was wrong for this market.
        """

        if not text.strip():
            return []
        body: dict[str, Any] = {"input": text.strip(), "languageCode": self._language}
        if session_token:
            body["sessionToken"] = session_token
        if self._countries:
            # Five is their limit, and more than this platform deploys into.
            body["includedRegionCodes"] = self._countries[:5]
        if latitude is not None and longitude is not None:
            # 30 km covers a city and its suburbs without excluding the customer
            # who lives one town over.
            body["locationBias"] = {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": 30000.0,
                }
            }

        payload = self._places_call(
            "POST",
            "/places:autocomplete",
            field_mask=(
                "suggestions.placePrediction.placeId,"
                "suggestions.placePrediction.text,"
                "suggestions.placePrediction.structuredFormat"
            ),
            timeout=timeout,
            json=body,
        )

        out: list[dict[str, str]] = []
        for entry in payload.get("suggestions") or []:
            prediction = entry.get("placePrediction") if isinstance(entry, dict) else None
            if not isinstance(prediction, dict):
                # A query prediction rather than a place — a search term, not
                # somewhere a rider can deliver to. Skipped rather than shown.
                continue
            place_id = str(prediction.get("placeId") or "")
            if not place_id:
                continue
            structured = prediction.get("structuredFormat")
            structured = structured if isinstance(structured, dict) else {}
            description = _text_of(prediction.get("text"))
            out.append(
                {
                    "place_id": place_id,
                    "primary": _text_of(structured.get("mainText")) or description,
                    "secondary": _text_of(structured.get("secondaryText")),
                    "description": description,
                }
            )
        return out

    def resolve(
        self, place_id: str, *, session_token: str, timeout: float | None = None
    ) -> tuple[GeocodedPoint, dict[str, str]] | None:
        """The coordinates and address parts of a place the customer picked.

        This is the accurate path and the reason Places is worth having. The
        point is Google's own record of that address, not an interpretation of
        a string somebody typed — so the confidence is ROOFTOP because the
        customer chose a building, and the structured parts come back filled in
        rather than parsed out of a blob.

        The session token belongs here too. It is what makes the whole typing
        run plus this lookup one billable session rather than one charge per
        keystroke.
        """

        place_id = place_id.strip()
        if not place_id:
            return None
        # The id may arrive bare or already as "places/ChIJ...".
        resource = place_id if place_id.startswith("places/") else f"places/{place_id}"

        payload = self._places_call(
            "GET",
            f"/{resource}",
            field_mask="id,formattedAddress,location,addressComponents,displayName",
            timeout=timeout,
            params={"sessionToken": session_token} if session_token else None,
        )
        location = payload.get("location")
        location = location if isinstance(location, dict) else {}
        try:
            latitude = float(location["latitude"])
            longitude = float(location["longitude"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Google Places returned a place with no coordinates: %r", payload)
            return None

        point = GeocodedPoint(
            latitude=latitude,
            longitude=longitude,
            # The customer chose this building from a list. There is no more
            # precise statement available, and the new API offers no
            # `location_type` to second-guess it with.
            confidence=GeocodeConfidence.ROOFTOP,
            matched=str(payload.get("formattedAddress") or ""),
            provider=self.name,
            raw=payload,
        )
        return point, address_parts_v1(payload)


def _text_of(value: Any) -> str:
    """A `{text, languageCode}` block, flattened.

    The new API wraps every display string this way and half of them are
    optional, so this is the one place that has to know.
    """

    if isinstance(value, dict):
        return str(value.get("text") or "")
    return str(value or "")


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


def address_parts_v1(place: dict[str, Any]) -> dict[str, str]:
    """The same flattening, for the new API's component shape.

    `longText` rather than `long_name`, and the building's own name under
    `displayName` rather than `name`. The mapping table above is reused
    unchanged, because their component TYPES did not change between versions —
    only the envelope around them.
    """

    return address_parts(
        {
            "formatted_address": place.get("formattedAddress") or "",
            "name": _text_of(place.get("displayName")),
            "address_components": [
                {
                    "long_name": component.get("longText") or "",
                    "types": component.get("types") or [],
                }
                for component in place.get("addressComponents") or []
                if isinstance(component, dict)
            ],
        }
    )


__all__ = [
    "PROVIDER_NAME",
    "GoogleGeocoder",
    "address_parts",
    "address_parts_v1",
    "confidence_for",
]
