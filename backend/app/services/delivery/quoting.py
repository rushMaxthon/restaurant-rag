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


def quote_for(
    location: RestaurantLocation,
    delivery_address: AddressQuery | str,
    *,
    db: Session | None = None,
    known_drop: tuple[float, float, str] | None = None,
    points: tuple[geocoding.Coordinates, geocoding.Coordinates] | None = None,
) -> DeliveryQuote | None:
    """Ask the courier what this trip would cost. None if nobody answered.

    None covers every way this can decline to produce a figure, and they are
    deliberately indistinguishable to the caller: the answer to all of them is
    the branch's own fee.

    `points` lets a caller that has already located both ends pass them in
    rather than have them looked up again.
    """

    settings = get_settings()
    if not settings.enable_delivery_quotes:
        return None
    provider = delivery_provider()
    if provider is None:
        return None
    quoter = getattr(provider, "quote", None)
    if quoter is None:
        # A courier added later may not price ahead of time. That is a missing
        # feature, not a broken checkout.
        logger.info("Courier %s cannot quote; falling back to the branch fee", provider.name)
        return None

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
        return None

    try:
        return quoter(
            pickup_lat=pickup.latitude,
            pickup_lng=pickup.longitude,
            drop_lat=drop.latitude,
            drop_lng=drop.longitude,
            timeout=settings.delivery_quote_timeout_seconds,
        )
    except DeliveryProviderError as error:
        logger.warning("Courier could not quote this trip: %s", error)
        return None
    except Exception:  # noqa: BLE001 - a checkout must survive any courier bug
        logger.exception("Quoting the courier raised; charging the branch fee instead")
        return None


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
    return fee


__all__ = ["delivery_fee_for", "fee_from", "points_for", "quote_for", "usable_in"]
