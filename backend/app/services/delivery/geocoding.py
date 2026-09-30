"""Turning the two ends of a delivery into the points a courier prices from.

The seam between the delivery integration and the geocoder. A courier quotes
between coordinates, and this is where a branch and a customer's address become
coordinates — in that order of preference:

1. **A coordinate already on the row.** A branch with `latitude`/`longitude`
   filled in, or a saved address the customer picked from the autocomplete.
   Free, exact, and no provider is called.
2. **A geocoder lookup**, cached durably, for an address typed fresh.
3. **A stand-in point**, and only then, marked `exact=False`.

The stand-in is what remains of the placeholder this file used to be entirely,
and it is now the last resort rather than the only behaviour. It stays for one
reason: a quote that cannot be produced is a checkout that cannot show a
delivery fee, and falling back to the branch's flat fee with `exact=False`
attached is more honest than either failing or pretending.

**The stand-in is in the COORDINATES, never in the price.** Nothing in this
package invents a fee. `Coordinates.exact` travels with the point all the way to
the checkout so a caller can see that the price is a real quote for an
approximate trip — which is a different thing from a made-up number, and the
distinction has to survive the whole call chain to be worth anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.restaurant_location import RestaurantLocation
from app.services.geocoding.base import AddressQuery, GeocodeConfidence
from app.services.geocoding.service import locate

logger = logging.getLogger(__name__)

#: The stand-in, and why this spot: Bodakdev in Ahmedabad, where the pilot
#: restaurant's branch actually is. A coordinate in the right city returns a
#: plausible distance and a real price band, where a (0, 0) placeholder returns
#: an unserviceable answer that means nothing and teaches nobody anything.
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
    difference has to reach whoever decides to charge it.

    A geocoder never refuses — ask for a street that does not exist and it
    returns a city centroid with no complaint. So `exact` requires more than
    "something answered": it requires a point precise enough to price, which is
    `GeocodeConfidence.is_precise`. A locality-level match is a coordinate and
    not an address.
    """

    latitude: float
    longitude: float
    exact: bool
    #: Where the point came from: "row", "geocoder" or "stand-in". Logged, and
    #: surfaced in the admin when a quote looks wrong.
    source: str = ""
    #: What the geocoder thought it found, when one was asked. The only way to
    #: notice that a flat number resolved to the middle of a state.
    matched: str = ""
    #: The `GeocodeConfidence` behind the point, when there is one.
    confidence: str = ""

    @property
    def usable(self) -> bool:
        """Whether a courier may be asked to price a trip from this point.

        Three tiers, not two, and the middle one is the useful part:

        * **Exact** — a door. Priced, and trusted.
        * **Usable but not exact** — a neighbourhood. Priced, flagged. It is
          right to within a kilometre or two, which is a real answer for a
          delivery fee, and refusing it would throw away the only point most
          branches have.
        * **Neither** — a stand-in, or a district or state centroid. Not
          priced at all.

        A stand-in is a constant with no relationship to the order. A REGION
        match is a real coordinate for the wrong scale of thing: "somewhere in
        this taluka" can be ten kilometres from the branch, and a delivery fee
        built on it is wrong by more than the fee itself.
        """

        if self.source == "stand-in":
            return False
        if self.confidence == GeocodeConfidence.REGION.value:
            return False
        return True


def for_branch(location: RestaurantLocation, db: Session | None = None) -> Coordinates:
    """Where the food is collected.

    A branch address is written once by its owner and then used by every order
    that branch ever takes, so it is worth locating properly and worth storing.
    When a lookup succeeds, the coordinates are written back onto the row — the
    next order reads them for free.
    """

    if location.latitude is not None and location.longitude is not None:
        # An EMPTY confidence means a person typed these in, which is the most
        # trustworthy source available — better than any geocoder, because they
        # pointed at their own front door. A stored confidence is whatever the
        # provider actually said, and a locality-level one is a real coordinate
        # that is not the door.
        stored = (getattr(location, "geocode_confidence", "") or "").strip()
        trusted = True
        if stored:
            try:
                trusted = GeocodeConfidence(stored).is_precise
            except ValueError:
                trusted = False
        return Coordinates(
            float(location.latitude),
            float(location.longitude),
            exact=trusted,
            source="row",
            confidence=stored,
        )

    if db is not None:
        from app.services.geocoding.branches import locate_branch

        found = locate_branch(db, location)
        point = found.point if found is not None else None
        if point is not None and point.is_precise:
            # Written back rather than looked up again on every order. The
            # caller commits; a failure to commit costs one repeat lookup and
            # nothing else, which is why this does not commit itself.
            location.latitude = point.latitude
            location.longitude = point.longitude
            location.geocode_confidence = point.confidence.value
            logger.info(
                "Located branch %s at %.5f,%.5f via %s (%s)",
                location.id,
                point.latitude,
                point.longitude,
                point.provider,
                point.confidence,
            )
            return Coordinates(
                point.latitude,
                point.longitude,
                exact=True,
                source="geocoder",
                matched=point.matched,
                confidence=point.confidence.value,
            )
        if point is not None:
            # A real coordinate, too coarse to price from. Used anyway, because
            # a city-level pickup still produces a more honest distance than a
            # hardcoded one, but never marked exact.
            logger.info(
                "Branch %s only resolved to %s (%s); pricing from it but not trusting it",
                location.id,
                point.confidence,
                point.matched[:80],
            )
            return Coordinates(
                point.latitude,
                point.longitude,
                exact=False,
                source="geocoder",
                matched=point.matched,
                confidence=point.confidence.value,
            )

    logger.info("Branch %s could not be located; using the stand-in pickup point", location.id)
    return Coordinates(*_FALLBACK_PICKUP, exact=False, source="stand-in")


def for_address(
    query: AddressQuery | str,
    db: Session | None = None,
    *,
    known: tuple[float, float, str] | None = None,
) -> Coordinates:
    """Where the food is going.

    `known` short-circuits everything: a saved address the customer picked from
    the autocomplete already carries the map provider's own coordinates for that
    building, and re-geocoding it would be a paid call to get a worse answer
    than the one already stored.
    """

    if known is not None:
        latitude, longitude, confidence = known
        try:
            precise = GeocodeConfidence(confidence).is_precise
        except ValueError:
            precise = False
        return Coordinates(
            float(latitude),
            float(longitude),
            exact=precise,
            source="row",
            confidence=confidence,
        )

    if isinstance(query, str):
        # Every address stored before the structured form existed. A single
        # block is a worse thing to geocode than separate fields, but it is
        # what those rows hold.
        query = AddressQuery(freeform=query)

    if db is not None and not query.is_empty:
        from app.services.geocoding.branches import locate_delivery_address

        # The same cascade a branch gets, because a customer's address has the
        # same shape: "A-31, Rangdarshan Soc, Near Dhanmora, Katargam" names a
        # society no map knows, with a real neighbourhood and a real PIN code
        # attached. Asking only the whole address left real customers with no
        # delivery quote at all — which is how this was found.
        found = locate_delivery_address(db, query)
        point = found.point if found is not None else None
        if point is not None:
            if not point.is_precise:
                logger.info(
                    "Address only resolved to %s (%s); pricing from it but not trusting it",
                    point.confidence,
                    point.matched[:80],
                )
            return Coordinates(
                point.latitude,
                point.longitude,
                exact=point.is_precise,
                source="geocoder",
                matched=point.matched,
                confidence=point.confidence.value,
            )

    logger.info("No coordinates for this address; using the stand-in drop point")
    return Coordinates(*_FALLBACK_DROP, exact=False, source="stand-in")


__all__ = ["Coordinates", "for_address", "for_branch"]
