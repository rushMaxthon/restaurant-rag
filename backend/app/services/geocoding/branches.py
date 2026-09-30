"""Finding a branch, by asking progressively less.

A branch address here looks like "Shop 12, Maple Trade Center, Bopal" or
"Radhe Shyam Society, Singanpor". The building name is real and no map has
heard of it; the NEIGHBOURHOOD on the end is real and every map knows it. Asking
for the whole string returns nothing, and the useful answer was sitting in the
last comma-separated fragment all along.

So this asks four times, each less specific than the last, and stops at the
first answer:

1. **The whole address.** A rooftop when the building is mapped.
2. **The last fragment of line 1**, plus the city — usually the locality.
3. **The branch's own name**, plus the city. Branches here are named after
   where they are: "Bangkok Bowl Bodakdev", "Momo Mountain Gota", and every
   Radhe Dhokla branch is simply its neighbourhood.
4. **The postcode**, plus the city. The last resort and the coarsest — an
   Indian PIN code can span kilometres.

**Each step is a real lookup and the confidence that comes back is recorded
as-is.** Nothing here upgrades a locality match into a rooftop because it was
the best available. A neighbourhood-level point is genuinely useful — it puts
the branch within a kilometre or two, which is the difference between a delivery
quote that is roughly right and one computed from a stand-in in another city —
but it is not the door, and the stored confidence is what stops anything
pretending otherwise.

Every lookup is cached durably, so the cascade costs at most four calls once per
branch, ever.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.geocoding.base import AddressQuery, GeocodedPoint
from app.services.geocoding.service import locate

logger = logging.getLogger(__name__)

#: Fragments that are a direction to a human, not a place on a map. An Indian
#: address routinely ends with one, and geocoding "Opp. Patel Pragati Mandal"
#: finds nothing while the fragment before it is a real neighbourhood.
_NOT_A_PLACE = re.compile(
    r"^(opp\.?|opposite|near|nr\.?|behind|beside|next to|above|below|b/h|"
    r"shop|shops|gd-?\d*|no\.?|unit|plot|flat|first floor|second floor|"
    r"ground floor|\d+[a-z]?([/-]\d+[a-z]?)*)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class BranchLocation:
    """Where a branch is, and which question found it."""

    point: GeocodedPoint
    #: Which attempt answered: "address", "locality", "branch name" or
    #: "postcode". Shown to whoever is deciding whether to save it, because
    #: "found via the postcode" and "found via the address" deserve very
    #: different amounts of trust.
    matched_on: str


def _locality_from(line: str) -> str:
    """The neighbourhood at the end of an address line, if there is one.

    Reads the comma-separated fragments from the right and returns the first
    that names a place rather than pointing at one. "Shop 12, Maple Trade
    Center, Bopal" gives "Bopal"; "Darshan Park Society, Opp. Patel Pragati
    Mandal" skips the landmark and gives "Darshan Park Society", which is at
    least a society a map may know.
    """

    for fragment in reversed([part.strip() for part in (line or "").split(",")]):
        if fragment and not _NOT_A_PLACE.match(fragment):
            return fragment
    return ""


def locate_branch(db: Session, location) -> BranchLocation | None:
    """Find this branch, by the most specific question that gets an answer."""

    city = (location.city or "").strip()
    state = (getattr(location, "state", "") or "").strip()

    attempts: list[tuple[str, AddressQuery]] = [
        (
            "address",
            AddressQuery(
                line1=location.address_line_1 or "",
                line2=location.address_line_2 or "",
                city=city,
                state=state,
                postal_code=(location.postal_code or "").strip(),
            ),
        )
    ]

    locality = _locality_from(location.address_line_1 or "")
    if locality:
        attempts.append(("locality", AddressQuery(line1=locality, city=city, state=state)))

    # Branches here are named after where they are, and the restaurant's name is
    # usually glued to the front of it — "Momo Mountain Gota". Sending the whole
    # thing finds nothing, so the restaurant name is stripped off first.
    branch = (location.branch_name or "").strip()
    brand = (getattr(getattr(location, "restaurant", None), "name", "") or "").strip()
    if brand and branch.lower().startswith(brand.lower()):
        branch = branch[len(brand) :].strip()
    if branch and branch.lower() != locality.lower():
        attempts.append(("branch name", AddressQuery(line1=branch, city=city, state=state)))

    postcode = (location.postal_code or "").strip()
    if postcode:
        attempts.append(("postcode", AddressQuery(postal_code=postcode, city=city, state=state)))

    for matched_on, query in attempts:
        if query.is_empty:
            continue
        point = locate(db, query)
        if point is not None:
            logger.info(
                "Located branch %s via its %s: %s (%s)",
                getattr(location, "id", "?"),
                matched_on,
                point.matched[:70],
                point.confidence,
            )
            return BranchLocation(point=point, matched_on=matched_on)

    logger.info("Nothing could locate branch %s", getattr(location, "id", "?"))
    return None


__all__ = ["BranchLocation", "locate_branch"]
