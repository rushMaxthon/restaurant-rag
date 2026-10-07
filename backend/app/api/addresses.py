"""Address autocomplete, proxied through our own server.

The accurate way to get a customer's coordinates is not to geocode what they
typed — it is to have them pick a real place, and take the coordinates from that
place's record. Nothing is parsed, interpolated or guessed, and a flat in a
society Google knows about resolves to the building rather than to the
neighbourhood.

**Why this is an endpoint and not a client library.** The usual way to build
this is to load the map provider's JavaScript in the browser with an API key in
the bundle. That works, and referrer restrictions make it defensible, but it
puts a credential with a billing quota in public. Proxying gives the same
dropdown with the key server-side, and it also means:

* **The session token is ours to manage.** Providers bill autocomplete per
  SESSION when the keystrokes and the final details lookup share a token, and
  per REQUEST when they do not. A client that forgets the token turns one
  charge into one per character typed.
* **Coordinates are written where they belong.** Resolving a place saves the
  point onto the customer's saved address, so their next order is priced with no
  provider call at all.
* **One provider swap, one file.** No client rebuild, no key redistribution.

`/suggest` returning an empty list is the honest answer when no provider is
configured. The checkout then shows plain text boxes and the backend geocoder
still prices the order — a missing dropdown degrades the experience, never the
correctness.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.models.user_saved_address import UserSavedAddress
from app.services.auth import require_customer
from app.services.geocoding.base import GeocodingError
from app.services.geocoding.registry import places_geocoder
from app.services.rate_limit import per_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/addresses", tags=["Addresses"])


class SuggestRequest(BaseModel):
    """What the customer has typed so far."""

    text: str = Field(default="", max_length=200)
    #: Held by the client across one typing session and sent again with the
    #: resolve call. Providers bill a session rather than each keystroke when
    #: the token matches, so this is a cost control, not bookkeeping.
    session_token: str = Field(default="", max_length=64)
    #: Bias suggestions toward the branch being ordered from. Without it, three
    #: characters of an Indian street name return matches from four states and
    #: the customer scrolls past their own neighbourhood.
    restaurant_location_id: uuid.UUID | None = None


class Suggestion(BaseModel):
    place_id: str
    #: The two-part label a dropdown wants: "12, MG Road" above
    #: "Navrangpura, Ahmedabad". Split by the provider, not by us.
    primary: str
    secondary: str = ""
    description: str = ""


class SuggestResponse(BaseModel):
    suggestions: list[Suggestion] = Field(default_factory=list)
    #: False when no provider is configured. The client shows plain text boxes
    #: instead of an empty dropdown that looks broken.
    available: bool = True


class ResolveRequest(BaseModel):
    place_id: str = Field(min_length=1, max_length=400)
    session_token: str = Field(default="", max_length=64)
    #: When given, the resolved coordinates are stored on that saved address so
    #: the customer's next order needs no lookup at all.
    saved_address_id: uuid.UUID | None = None


class ResolvedAddress(BaseModel):
    """A place the customer chose, in the shape the checkout form uses."""

    line1: str = ""
    line2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""
    formatted: str = ""
    latitude: float
    longitude: float
    #: `GeocodeConfidence`. ROOFTOP for a picked place, which is the point of
    #: picking one.
    confidence: str = ""


@router.post("/suggest", response_model=SuggestResponse)
def suggest_addresses(
    # Counted before anything else runs (`services/rate_limit.py`).
    _rate_limited: Annotated[None, Depends(per_ip("address-suggest", limit=60, window_seconds=60))],
    payload: SuggestRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
) -> SuggestResponse:
    """Address suggestions for a partly typed address."""

    provider = places_geocoder()
    if provider is None:
        # Not an error. No key configured means no dropdown, and the form
        # behind it still works.
        return SuggestResponse(suggestions=[], available=False)
    if not payload.text.strip():
        return SuggestResponse(suggestions=[])

    latitude = longitude = None
    if payload.restaurant_location_id is not None:
        from app.models.restaurant_location import RestaurantLocation

        branch = db.get(RestaurantLocation, payload.restaurant_location_id)
        if branch is not None and branch.latitude is not None and branch.longitude is not None:
            latitude, longitude = float(branch.latitude), float(branch.longitude)

    try:
        found = provider.suggest(
            payload.text,
            session_token=payload.session_token,
            latitude=latitude,
            longitude=longitude,
        )
    except GeocodingError as error:
        # A typing box must not throw. An empty list reads as "no matches yet",
        # which is what a customer mid-word expects anyway.
        logger.warning("Address suggestions failed: %s", error)
        if not error.retryable:
            # The key itself was refused (billing off, restrictions): shown on
            # Platform watch, not left for a customer to discover.
            from app.services.geocoding import health

            health.record_refusal("places", str(error))
        return SuggestResponse(suggestions=[])

    from app.services.geocoding import health

    health.record_success()
    return SuggestResponse(suggestions=[Suggestion(**entry) for entry in found])


@router.post("/resolve", response_model=ResolvedAddress)
def resolve_address(
    # Counted before anything else runs (`services/rate_limit.py`).
    _rate_limited: Annotated[None, Depends(per_ip("address-resolve", limit=30, window_seconds=60))],
    payload: ResolveRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
) -> ResolvedAddress:
    """The coordinates and address parts of a place the customer picked.

    This is the accurate path. The point comes from the provider's own record
    of that address rather than from an interpretation of typed text, which is
    why the confidence that comes back is a rooftop rather than a guess.
    """

    provider = places_geocoder()
    if provider is None:
        raise HTTPException(status_code=503, detail="Address lookup is not configured")

    try:
        resolved = provider.resolve(payload.place_id, session_token=payload.session_token)
    except GeocodingError as error:
        logger.warning("Resolving place %s failed: %s", payload.place_id[:40], error)
        raise HTTPException(status_code=502, detail="Could not look up that address") from error
    if resolved is None:
        raise HTTPException(status_code=404, detail="That address could not be found")

    point, parts = resolved

    if payload.saved_address_id is not None:
        saved = db.get(UserSavedAddress, payload.saved_address_id)
        # Scoped to the caller. An address id is a guessable handle, and
        # writing a coordinate onto somebody else's row would be both wrong and
        # a way to learn where they live.
        if saved is not None and saved.user_id == current_user.id:
            saved.latitude = point.latitude
            saved.longitude = point.longitude
            saved.geocode_confidence = point.confidence.value
            db.commit()

    return ResolvedAddress(
        **parts,
        latitude=point.latitude,
        longitude=point.longitude,
        confidence=point.confidence.value,
    )


__all__ = ["router"]
