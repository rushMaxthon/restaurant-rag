"""What delivery costs on this order, asked of the courier before it is placed.

The flat `restaurant_location.delivery_fee` charged every customer the same
whether they lived next door or across the city. A courier prices by distance,
so a flat fee is either subsidising the far customer or overcharging the near
one, and the restaurant carries the difference without ever seeing it.

This asks the courier instead. Three rules hold it together:

**The flat fee is the fallback, never a blend.** No courier, no credentials,
an unserviceable address, a slow API, a switched-off flag — every one of them
lands on `restaurant_location.delivery_fee`, which is what every order has
charged until now. Falling back is therefore a change of nothing, and that is
what makes switching this on safe.

**Nothing here invents a number.** If the courier prices nothing, this returns
nothing. There is no default courier fee, no distance formula of our own and
no rounding-up "just in case" — the only figures that reach a customer are the
branch's own fee or the courier's own quote.

**A failure costs the checkout nothing.** Every error is caught and logged,
because a customer holding a card should not be blocked by a courier having a
bad minute. Quoting is an improvement on the fee, not a precondition for
ordering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.restaurant_location import RestaurantLocation
from app.services.delivery import geocoding
from app.services.delivery.base import DeliveryProviderError, DeliveryQuote
from app.services.delivery.registry import delivery_provider
from app.services.geocoding.base import AddressQuery

logger = logging.getLogger(__name__)


def fee_from(quote: DeliveryQuote) -> Decimal | None:
    """The single number to print, out of the range a courier quotes.

    Couriers answer with a band because no rider has been assigned yet.
    Somebody must still choose one figure for the checkout, and which end is
    a commercial decision rather than a technical one — so it is a setting,
    and `max` is the default because the ceiling is the only end that cannot
    leave the platform paying the difference on a busy evening.
    """

    if not quote.serviceable:
        return None
    low, high = quote.min_cost, quote.max_cost
    if low is None and high is None:
        return None
    basis = (get_settings().delivery_quote_basis or "max").strip().lower()
    if basis == "min":
        chosen = low if low is not None else high
    elif basis == "mid" and low is not None and high is not None:
        chosen = (low + high) / 2
    else:
        chosen = high if high is not None else low
    if chosen is None:
        return None
    # Two places, the same as every other money column here. ROUND_HALF_UP
    # rather than banker's rounding because this figure is shown to a customer
    # beside a total they will add up themselves.
    return Decimal(chosen).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def before_delivery_tax(courier_fee: Decimal, location) -> Decimal:
    """The courier's figure with the delivery tax taken back out of it.

    A courier quotes what it will invoice, and the invoice includes GST. The
    bill then adds its own "GST on delivery fee" at the branch's rate
    (`order_charges.compute`), so charging the courier's figure as the fee
    taxed one delivery twice: a trip Pidge prices at 59.00 reached the
    customer as 59.00 plus 10.62.

    So the fee is the part before tax, and the tax line puts the rest back.
    The customer pays the courier's figure; the two rows show what it is made
    of. The rate is the branch's own, the same one the tax line will use —
    which is what makes the two add back up, and why a branch that adds no
    delivery tax (the default) has nothing taken out: it would be handing the
    customer a tax the platform then pays.

    **To the paisa, where there is one.** Dividing by 1.18 and multiplying
    back does not always return the figure started from, so the neighbouring
    paisa is tried and the one that adds back exactly is kept. Some figures
    cannot be reached at all — a fee and 18% of it, each rounded, make 9.99
    or 10.01 and never 10.00 — and there the nearest stands, a paisa out.

    Only ever applied to a courier's quote. The branch's flat fee is a number
    an owner typed, and what it includes is theirs to say.
    """

    rate = getattr(location, "delivery_tax_percent", None)
    rate = Decimal(str(rate)) if rate is not None else Decimal("0")
    if rate <= 0 or courier_fee <= 0:
        return courier_fee

    paisa = Decimal("0.01")

    def tax_on(fee: Decimal) -> Decimal:
        return (fee * rate / Decimal("100")).quantize(paisa, rounding=ROUND_HALF_UP)

    nearest = (courier_fee * Decimal("100") / (Decimal("100") + rate)).quantize(
        paisa, rounding=ROUND_HALF_UP
    )
    for candidate in (nearest, nearest - paisa, nearest + paisa):
        if candidate + tax_on(candidate) == courier_fee:
            return candidate
    return nearest


def points_for(
    location: RestaurantLocation,
    delivery_address: AddressQuery | str,
    *,
    db: Session | None = None,
    known_drop: tuple[float, float, str] | None = None,
) -> tuple[geocoding.Coordinates, geocoding.Coordinates]:
    """The two ends of the trip, located as well as they can be.

    Separated out because both the quote and the response need them, and
    geocoding twice would double every paid lookup — which caching hides in
    development and a bill exposes in production.
    """

    return (
        geocoding.for_branch(location, db),
        geocoding.for_address(delivery_address, db, known=known_drop),
    )


def within_reach(location: RestaurantLocation, metres: float | None) -> bool:
    """Whether a distance is one a food delivery could plausibly cover.

    The branch's own `service_radius_km` when it has one, because that is the
    restaurant's actual answer, and a platform bound otherwise.

    Unknown distance passes: a courier that priced the trip without saying how
    far it is has still answered the question, and refusing on a missing field
    would throw away good quotes.
    """

    if metres is None:
        return True
    radius = getattr(location, "service_radius_km", None)
    limit_km = float(radius) if radius else get_settings().delivery_max_distance_km
    if limit_km <= 0:
        return True
    return metres <= limit_km * 1000


@dataclass(frozen=True, slots=True)
class QuoteAttempt:
    """A quote, or the reason there is not one.

    The reason exists because the checkout shows the customer a sentence about
    it, and the sentence has to be true. `quote_for` collapses every failure
    into `None` — which was defended on the grounds that the answer to all of
    them is the branch's flat fee, and that is right about the FEE and wrong
    about the PAGE. The API could not tell a courier outage from a bad address,
    so it guessed from whether the address geocoded precisely, and a customer
    whose society resolved to a sublocality was told to "check the street and
    PIN code" while the real cause was the courier's login returning 503. They
    could have retyped that address all afternoon.
    """

    quote: DeliveryQuote | None
    #: `""` when `quote` is set. Otherwise one of `quotes_disabled`,
    #: `no_courier`, `cannot_quote`, `coarse_point`, `courier_unavailable`,
    #: `out_of_range` or `declined`.
    reason: str = ""
    #: How far the courier measured the trip it refused as `out_of_range`.
    #: Slab pricing needs it: the quote is thrown away past the limit, and a
    #: customer told "too far" deserves to be told how far.
    distance_metres: float | None = None


def quote_for(
    location: RestaurantLocation,
    delivery_address: AddressQuery | str,
    *,
    db: Session | None = None,
    known_drop: tuple[float, float, str] | None = None,
    points: tuple[geocoding.Coordinates, geocoding.Coordinates] | None = None,
) -> DeliveryQuote | None:
    """Ask the courier what this trip would cost. None if nobody answered.

    Kept for callers that only need the figure. One that has to EXPLAIN the
    figure wants `attempt_quote`, which is this function with the reason still
    attached.
    """

    return attempt_quote(
        location, delivery_address, db=db, known_drop=known_drop, points=points
    ).quote


def attempt_quote(
    location: RestaurantLocation,
    delivery_address: AddressQuery | str,
    *,
    db: Session | None = None,
    known_drop: tuple[float, float, str] | None = None,
    points: tuple[geocoding.Coordinates, geocoding.Coordinates] | None = None,
) -> QuoteAttempt:
    """Ask the courier what this trip would cost, and say what happened.

    `points` lets a caller that has already located both ends pass them in
    rather than have them looked up again.
    """

    settings = get_settings()
    if not settings.enable_delivery_quotes:
        return QuoteAttempt(None, "quotes_disabled")
    provider = delivery_provider()
    if provider is None:
        return QuoteAttempt(None, "no_courier")
    quoter = getattr(provider, "quote", None)
    if quoter is None:
        # A courier added later may not price ahead of time. That is a missing
        # feature, not a broken checkout.
        logger.info("Courier %s cannot quote; falling back to the branch fee", provider.name)
        return QuoteAttempt(None, "cannot_quote")

    pickup, drop = points or points_for(
        location, delivery_address, db=db, known_drop=known_drop
    )

    # A STAND-IN at either end means there is no trip to price.
    #
    # This is the difference between a vague point and a made-up one, and it is
    # not a fine distinction. A geocoder that only resolved to a suburb still
    # answered about the real address: the distance is roughly right and the
    # price is roughly right. A stand-in is a hardcoded constant with no
    # relationship to this order at all.
    #
    # Caught in the browser: a branch with no coordinates fell back to the
    # Ahmedabad stand-in while the customer was in Surat, and the courier
    # honestly priced 258 km — ₹2,601.48 delivery on a ₹50 loaf of bread,
    # displayed as the fee. The courier was not wrong; it was asked about a
    # journey nobody was making.
    #
    # Pidge's estimate endpoint takes coordinates only — there is no address
    # form of it — so there is no way to ask them to work the pickup out for
    # themselves. Without a real pickup point the only honest fee is the
    # branch's own.
    if pickup.usable is False or drop.usable is False:
        logger.warning(
            "Not quoting: pickup=%s/%s drop=%s/%s. A point this coarse prices "
            "the wrong journey; charging the branch fee instead.",
            pickup.source,
            pickup.confidence or "-",
            drop.source,
            drop.confidence or "-",
        )
        return QuoteAttempt(None, "coarse_point")

    try:
        quote = quoter(
            pickup_lat=pickup.latitude,
            pickup_lng=pickup.longitude,
            drop_lat=drop.latitude,
            drop_lng=drop.longitude,
            timeout=settings.delivery_quote_timeout_seconds,
        )
    except DeliveryProviderError as error:
        logger.warning("Courier could not quote this trip: %s", error)
        return QuoteAttempt(None, "courier_unavailable")
    except Exception:  # noqa: BLE001 - a checkout must survive any courier bug
        logger.exception("Quoting the courier raised; charging the branch fee instead")
        return QuoteAttempt(None, "courier_unavailable")

    if quote is not None and not within_reach(location, quote.distance_metres):
        # A real price for a journey nobody would make. The courier cannot be
        # expected to catch this — Pidge quoted 1,605 km without complaint when
        # a typo'd address resolved to the middle of the country — so the
        # backstop lives here, where the order is.
        logger.warning(
            "Not quoting: %.1f km is further than this branch delivers; "
            "the address almost certainly resolved to the wrong place.",
            (quote.distance_metres or 0) / 1000,
        )
        return QuoteAttempt(None, "out_of_range", distance_metres=quote.distance_metres)
    # A courier that answered with nothing has declined the trip, which is a
    # different thing from one that could not be reached.
    return QuoteAttempt(quote, "" if quote is not None else "declined")


def usable_in(quote: DeliveryQuote, currency: str) -> bool:
    """Whether this quote can be added to a total in `currency`.

    Found by running it: an Indian courier quoted ₹87.04 for a branch that
    bills in CAD. Adding those produces a number that is not money in any
    currency, and it would have gone straight onto a customer's bill — the
    subtotal, the tax and the delivery fee all summed as though the symbols
    agreed.

    A courier who prices in a currency the order is not in has not answered
    the question, so the branch's own fee stands. Converting it here would be
    worse: it would need an exchange rate nobody chose, applied to a figure
    the restaurant never agreed to charge.
    """

    theirs = (quote.currency or "").strip().upper()
    ours = (currency or "").strip().upper()
    return not theirs or not ours or theirs == ours


def delivery_fee_for(
    location: RestaurantLocation,
    delivery_address: AddressQuery | str,
    *,
    currency: str = "",
    db: Session | None = None,
    known_drop: tuple[float, float, str] | None = None,
) -> Decimal | None:
    """The courier's fee for this trip, or None to use the branch's own.

    `currency` is what the order will be charged in. A quote in anything else
    is discarded rather than converted.
    """

    quote = quote_for(location, delivery_address, db=db, known_drop=known_drop)
    if quote is None:
        return None
    if not usable_in(quote, currency):
        logger.warning(
            "Courier quoted %s but this order is in %s; charging the branch fee",
            quote.currency,
            currency,
        )
        return None
    fee = fee_from(quote)
    if fee is None:
        logger.info("Courier will not serve this address; charging the branch fee")
        return None
    return before_delivery_tax(fee, location)


__all__ = [
    "QuoteAttempt",
    "attempt_quote",
    "before_delivery_tax",
    "delivery_fee_for",
    "fee_from",
    "points_for",
    "quote_for",
    "usable_in",
    "within_reach",
]
