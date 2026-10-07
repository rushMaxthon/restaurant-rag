"""Delivery priced by the platform, from the distance alone.

Until 2026-10-07 the checkout printed the courier's estimate. Pidge
auto-allocates on this account, and its estimate did not survive allocation:
two trips quoted at Rs 57 were handed to a network that charged Rs 285.61, and
the customer had already paid the smaller figure. The platform owner decided
the price should be ours instead - a number a customer can predict from how
far away they live:

    up to 2 km  Rs 68     over 2 up to 5 km  Rs 78     over 5 km  Rs 100

before GST (`delivery_fee_slabs`), with `delivery_gst_percent` added on top by
`order_charges`, and refused past the branch's radius or
`delivery_max_distance_km`.

**The courier is still asked - for its road distance, not its price.** A
straight line undercounts every bend; a customer 1.9 km away as the crow flies
can be 2.8 km by road, which is a different slab. When the courier does not
answer, or answers without a distance, the straight line is stretched by
`delivery_road_factor`. Pidge's estimate is the free endpoint; nothing here
calls the charged `fulfillment/services` one.

**The platform admin edits it, and every restaurant follows.** The list, the
limit and the GST rate live in one `platform_settings` row ("delivery_pricing"),
edited on the admin's Delivery pricing page. With no row the settings defaults
above apply, so a database that has never been edited prices as before.
`load_pricing` reads it; `save_pricing` is the only writer and validates first.

**Every figure comes from one function.** `price_trip` is called by the quote
the checkout shows and by the order that charges it, with the same points, so
the two cannot disagree - the same rule `quoting.py` was built around.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.delivery import geocoding, quoting
from app.services.delivery.base import DeliveryQuote
from app.services.geocoding.base import AddressQuery

logger = logging.getLogger(__name__)

#: The list agreed on 2026-10-07, and what an unparseable setting falls back to.
DEFAULT_SLABS = "2:68,5:78,*:100"

_EARTH_RADIUS_M = 6_371_000.0


def slab_pricing_on() -> bool:
    return (get_settings().delivery_pricing or "slabs").strip().lower() == "slabs"


def _parse(raw: str) -> list[tuple[float | None, Decimal]]:
    """("2:68,5:78,*:100") -> [(2.0, 68), (5.0, 78), (None, 100)], sorted."""

    bounded: list[tuple[float, Decimal]] = []
    open_end: Decimal | None = None
    for part in (raw or "").split(","):
        if not part.strip():
            continue
        km, _, fee = part.partition(":")
        km, fee = km.strip(), fee.strip()
        price = Decimal(fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if price < 0:
            raise ValueError("a delivery fee cannot be negative")
        if km == "*":
            open_end = price
        else:
            bounded.append((float(km), price))
    if not bounded and open_end is None:
        raise ValueError("no slabs")
    rows: list[tuple[float | None, Decimal]] = sorted(bounded, key=lambda row: row[0])
    if open_end is not None:
        rows.append((None, open_end))
    return rows


def slabs() -> list[tuple[float | None, Decimal]]:
    raw = get_settings().delivery_fee_slabs
    try:
        return _parse(raw)
    except (ValueError, ArithmeticError):
        # A typo in an environment variable must not make delivery free or
        # take the checkout down; the agreed list is a real price.
        logger.error("DELIVERY_FEE_SLABS %r does not parse; using %s", raw, DEFAULT_SLABS)
        return _parse(DEFAULT_SLABS)


#: The `platform_settings` key the admin's page writes.
SETTING_KEY = "delivery_pricing"

_MAX_GST_PERCENT = Decimal("28")


@dataclass(frozen=True)
class Pricing:
    """The slabs, how far the platform delivers, and the GST on delivery."""

    slabs: list[tuple[float | None, Decimal]]
    max_distance_km: float
    gst_percent: Decimal
    #: False while nothing is saved and these are the settings defaults.
    saved: bool = False
    updated_at: datetime | None = None
    updated_by: uuid.UUID | None = field(default=None)


def default_pricing() -> Pricing:
    settings = get_settings()
    return Pricing(
        slabs=slabs(),
        max_distance_km=float(settings.delivery_max_distance_km),
        gst_percent=Decimal(str(settings.delivery_gst_percent)),
    )


def load_pricing(db: Session | None) -> Pricing:
    """What the admin saved, or the defaults when nothing is saved.

    Read inside a savepoint, because this runs in the middle of placing an
    order: a database that has not run `0086` yet must cost that order
    nothing, and a failed statement outside a savepoint would poison the rest
    of its transaction.
    """

    if db is None:
        return default_pricing()
    from app.models.platform_setting import PlatformSetting

    try:
        with db.begin_nested():
            row = db.get(PlatformSetting, SETTING_KEY)
    except SQLAlchemyError:
        logger.warning("platform_settings is not readable; using the default delivery pricing")
        return default_pricing()
    if row is None:
        return default_pricing()
    try:
        value = row.value or {}
        parsed = [
            (
                None if slab.get("up_to_km") is None else float(slab["up_to_km"]),
                Decimal(str(slab["fee"])),
            )
            for slab in value["slabs"]
        ]
        return Pricing(
            slabs=parsed,
            max_distance_km=float(value["max_distance_km"]),
            gst_percent=Decimal(str(value["gst_percent"])),
            saved=True,
            updated_at=row.updated_at,
            updated_by=row.updated_by_user_id,
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        # Only `save_pricing` writes this row, and it validates. A row that
        # does not parse was edited by hand; the defaults are a real price.
        logger.error("The saved delivery pricing does not parse; using the defaults")
        return default_pricing()


def validate_update(update) -> Pricing:
    """A `DeliveryPricingUpdate` as `Pricing`, or a 422 saying what is wrong.

    Refused rather than repaired: a saved mistake is a price every customer
    on the platform pays at once.
    """

    def refuse(message: str) -> HTTPException:
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)

    rows = list(update.slabs)
    if not rows:
        raise refuse("Add at least one delivery slab.")
    if rows[-1].up_to_km is not None:
        raise refuse("The last slab must have no upper distance: it prices everything further.")
    previous = 0.0
    parsed: list[tuple[float | None, Decimal]] = []
    for index, row in enumerate(rows):
        fee = Decimal(row.fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if fee < 0:
            raise refuse("A delivery fee cannot be negative.")
        if index < len(rows) - 1:
            if row.up_to_km is None:
                raise refuse("Only the last slab may be open-ended.")
            if row.up_to_km <= previous:
                raise refuse("Each slab must go further than the one before it.")
            if row.up_to_km >= update.max_distance_km:
                raise refuse(
                    f"A slab up to {row.up_to_km:g} km is past the {update.max_distance_km:g} km "
                    "delivery limit, so nobody could be charged it."
                )
            previous = float(row.up_to_km)
        parsed.append((None if row.up_to_km is None else float(row.up_to_km), fee))
    gst = Decimal(update.gst_percent)
    if gst < 0 or gst > _MAX_GST_PERCENT:
        raise refuse(f"GST on delivery must be between 0% and {_MAX_GST_PERCENT}%.")
    return Pricing(slabs=parsed, max_distance_km=float(update.max_distance_km), gst_percent=gst)


def save_pricing(db: Session, user, update) -> Pricing:
    """Validate and store the admin's delivery pricing. The only writer."""

    from app.models.platform_setting import PlatformSetting

    pricing = validate_update(update)
    value = {
        "slabs": [{"up_to_km": limit, "fee": str(fee)} for limit, fee in pricing.slabs],
        "max_distance_km": pricing.max_distance_km,
        "gst_percent": str(pricing.gst_percent),
    }
    row = db.get(PlatformSetting, SETTING_KEY)
    if row is None:
        row = PlatformSetting(key=SETTING_KEY, value=value, updated_by_user_id=user.id)
        db.add(row)
    else:
        row.value = value
        row.updated_by_user_id = user.id
    db.commit()
    logger.info("Delivery pricing changed by %s: %s", user.id, value)
    return load_pricing(db)


def fee_for_distance(metres: float, pricing: Pricing | None = None) -> Decimal:
    """The slab fee, before GST, for a trip this long. Inclusive at the top."""

    km = max(0.0, float(metres)) / 1000
    rows = (pricing or default_pricing()).slabs
    for limit, fee in rows:
        if limit is None or km <= limit:
            return fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # No open end and further than the last slab: its price, rather than none.
    # How far the platform delivers at all is the limit's rule, not this one.
    return rows[-1][1].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def straight_line_metres(a: geocoding.Coordinates, b: geocoding.Coordinates) -> float:
    """Great-circle distance between two points."""

    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlng = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(h))


def limit_km_for(location, pricing: Pricing | None = None) -> float:
    radius = getattr(location, "service_radius_km", None)
    if radius:
        return float(radius)
    return (pricing or default_pricing()).max_distance_km


@dataclass(frozen=True, slots=True)
class TripPrice:
    """The slab fee for a trip, or the reason there is none.

    `fee` is None when `reason` is `coarse_point` (we do not know where one end
    is, so the branch's own fee stands, as it always has) or `out_of_range`
    (too far - the order is refused).
    """

    fee: Decimal | None
    distance_metres: float | None = None
    #: "road" when the courier measured it, "straight_line" when we did.
    measured_by: str = ""
    reason: str = ""
    limit_km: float | None = None
    #: False when the courier said no rider serves this address. The price
    #: does not change; the checkout warns, as it did before.
    serviceable: bool = True
    #: The courier's own reply, for its travel and assignment times.
    quote: DeliveryQuote | None = None


def price_trip(
    location,
    delivery_address: AddressQuery | str,
    *,
    db: Session | None = None,
    known_drop: tuple[float, float, str] | None = None,
    points: tuple[geocoding.Coordinates, geocoding.Coordinates] | None = None,
) -> TripPrice:
    pickup, drop = points or quoting.points_for(
        location, delivery_address, db=db, known_drop=known_drop
    )
    if pickup.usable is False or drop.usable is False:
        # A stand-in at either end is not a trip; see `quoting.attempt_quote`.
        return TripPrice(None, reason="coarse_point")

    pricing = load_pricing(db)
    limit_km = limit_km_for(location, pricing)
    attempt = quoting.attempt_quote(location, delivery_address, db=db, points=(pickup, drop))
    quote = attempt.quote
    if attempt.reason == "out_of_range" and attempt.distance_metres is not None:
        distance, measured_by = attempt.distance_metres, "road"
    elif quote is not None and quote.distance_metres:
        distance, measured_by = float(quote.distance_metres), "road"
    else:
        distance = straight_line_metres(pickup, drop) * get_settings().delivery_road_factor
        measured_by = "straight_line"

    if limit_km > 0 and distance > limit_km * 1000:
        logger.info(
            "Refusing delivery: %.1f km (%s) is past this branch's %.1f km",
            distance / 1000,
            measured_by,
            limit_km,
        )
        return TripPrice(
            None,
            distance_metres=distance,
            measured_by=measured_by,
            reason="out_of_range",
            limit_km=limit_km,
            quote=quote,
        )

    return TripPrice(
        fee_for_distance(distance, pricing),
        distance_metres=distance,
        measured_by=measured_by,
        limit_km=limit_km,
        serviceable=quote.serviceable if quote is not None else True,
        quote=quote,
    )


__all__ = [
    "DEFAULT_SLABS",
    "Pricing",
    "SETTING_KEY",
    "TripPrice",
    "default_pricing",
    "fee_for_distance",
    "limit_km_for",
    "load_pricing",
    "price_trip",
    "save_pricing",
    "validate_update",
    "slab_pricing_on",
    "slabs",
    "straight_line_metres",
]
