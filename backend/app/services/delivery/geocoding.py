"""Turning places into coordinates — the one part that is not real yet.

Every courier prices a trip off two points, not two addresses. This module is
where an address becomes a point, and it is deliberately the ONLY place in the
codebase that knows a coordinate can be stood in for.

**What is real.** `RestaurantLocation` has `latitude`/`longitude` columns, and
when a branch has them they are used. That is the pickup end solved for any
branch whose owner has filled them in.

**What is not.** No branch in this database has them filled in yet, and a
customer's address is a free-text block with nowhere to put a coordinate at
all — `user_saved_addresses` has no columns for one. Until a geocoding
provider is chosen (Google, Mapbox or Nominatim; the trade is licence terms
against accuracy in Indian cities), both ends fall back to a fixed point.

**Why a fixed point and not a refusal.** A quote has to be provably end to end
before a geocoder is worth paying for: without this, nobody can see whether
the courier's price is sane, whether the checkout renders it, or what happens
when they say a street is unserviceable. The stand-in makes the whole path
run today, and swapping it for a real geocoder changes this file and nothing
else.

**What it must never become.** A stand-in coordinate is honest; a stand-in
PRICE is not. Nothing here invents a fee. The coordinates are approximate and
the number that comes back is the courier's own — and `Coordinates.exact`
says which end was guessed, so a caller can refuse to bill a customer off a
guess even while showing them a figure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models.restaurant_location import RestaurantLocation

logger = logging.getLogger(__name__)

#: The stand-in, and the reason it is this particular spot: Bodakdev in
#: Ahmedabad, which is where the pilot restaurant's branch actually is. A
#: coordinate in the right city returns a plausible distance and a real price
#: band from the courier, where a (0, 0) placeholder returns nothing useful
#: and an unserviceable answer that means nothing.
_FALLBACK_PICKUP = (23.0395, 72.5066)
#: About 7 km away, still inside Ahmedabad — far enough that the quote is not
#: the courier's minimum fare, so a wrong distance shows up as a wrong price
#: instead of hiding inside the floor.
_FALLBACK_DROP = (23.0395, 72.5600)


@dataclass(frozen=True, slots=True)
class Coordinates:
    """A point, and whether anyone actually knows it.

    `exact` is the whole reason this is a type rather than a tuple. A quote
    built from a guessed point is a real price for the wrong trip, and the
    difference has to survive all the way to whoever decides to charge it.
    """

    latitude: float
    longitude: float
    exact: bool


def for_branch(location: RestaurantLocation) -> Coordinates:
    """Where the food is collected."""

    if location.latitude is not None and location.longitude is not None:
        return Coordinates(float(location.latitude), float(location.longitude), exact=True)
    logger.info(
        "Branch %s has no coordinates; quoting from the stand-in pickup point", location.id
    )
    return Coordinates(*_FALLBACK_PICKUP, exact=False)


def for_address(address: str) -> Coordinates:
    """Where the food is going.

    Always a stand-in today. This is the function a geocoder replaces, and the
    signature is the one it will have: text in, a point out.
    """

    logger.info("No geocoder configured; quoting to the stand-in drop point")
    return Coordinates(*_FALLBACK_DROP, exact=False)


__all__ = ["Coordinates", "for_address", "for_branch"]
