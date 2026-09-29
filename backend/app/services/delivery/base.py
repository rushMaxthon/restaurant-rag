"""Provider-neutral delivery contracts.

The same arrangement `payments/base.py` uses, and for the same reason:
everything above this layer is written against these types, so a second
courier later is a module and a registry entry rather than a change to the
order flow.

A courier is not a payment gateway in one important way. A payment either
happens or it does not; a delivery has a long middle — assigned, picked up,
in transit — and it can END BADLY in ways that are not "cancelled": the
customer is out, the address is wrong, the food comes back. `DeliveryState`
keeps those distinct, because "the rider brought it back" and "nobody ever
dispatched" have different answers to the question of who pays for the food.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class DeliveryState(StrEnum):
    """Where a delivery is, in terms this app can act on.

    Deliberately smaller than any courier's own vocabulary. Pidge alone has
    sixteen fulfillment statuses; mapping them one-for-one would put the
    courier's model inside our order flow, and the next courier would not
    agree with it.
    """

    #: Accepted by the courier, nobody assigned yet.
    PENDING = "PENDING"
    #: A rider is on the way to the restaurant.
    ASSIGNED = "ASSIGNED"
    #: The rider has the food.
    PICKED_UP = "PICKED_UP"
    #: On the way to the customer.
    IN_TRANSIT = "IN_TRANSIT"
    #: Handed over. Terminal, and the happy one.
    DELIVERED = "DELIVERED"
    #: Called off before anything was collected. Terminal.
    CANCELLED = "CANCELLED"
    #: Dispatched and did not arrive — nobody in, wrong address, refused.
    #: Terminal, and NOT the same as cancelled: the food was made and is now
    #: somewhere. Who pays for it is a commercial question, and it cannot be
    #: asked if this state is folded into CANCELLED.
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in {DeliveryState.DELIVERED, DeliveryState.CANCELLED, DeliveryState.FAILED}


@dataclass(slots=True)
class DeliveryAddress:
    """One end of a trip.

    `latitude`/`longitude` are optional because our own checkout does not
    collect them — the courier geocodes the lines. Sent when we have them,
    because a geocode we supply is one the courier cannot get wrong.
    """

    address_line_1: str
    city: str
    state: str
    pincode: str
    name: str
    mobile: str
    address_line_2: str = ""
    email: str = ""
    country: str = "India"
    latitude: float | None = None
    longitude: float | None = None
    instructions: str = ""


@dataclass(slots=True)
class DeliveryItem:
    """One line of the order, as the courier needs it named."""

    name: str
    quantity: int
    price: Decimal
    sku: str = ""


@dataclass(slots=True)
class DeliveryRequest:
    """Everything a courier needs to come and fetch an order.

    `reference` is OUR order number and travels both ways: Pidge returns its
    create response keyed by it rather than by its own id, and the webhook
    carries it back. It is how a status update finds the order it belongs to.
    """

    reference: str
    pickup: DeliveryAddress
    drop: DeliveryAddress
    items: list[DeliveryItem]
    bill_amount: Decimal
    #: What the rider must collect at the door. Zero for a prepaid order, and
    #: zero is not None — a courier that is told nothing may decide for itself.
    cod_amount: Decimal = Decimal("0")
    ready_at: datetime | None = None
    deliver_by: datetime | None = None
    notes: str = ""


@dataclass(slots=True)
class DeliveryResult:
    """What came back, normalized.

    `raw` is kept whole. A courier's own payload carries proof-of-delivery
    URLs, rider phone numbers and timestamps that no interface should try to
    anticipate, and the support question "what did they actually say" is
    unanswerable without it.
    """

    provider_order_id: str
    state: DeliveryState
    reference: str = ""
    rider_name: str = ""
    rider_mobile: str = ""
    tracking_url: str = ""
    #: Metres between pickup and drop, as the courier measured it. Pidge
    #: returns this on every order and it is the only distance figure anyone
    #: here has, so it is what a distance-based delivery fee is priced off.
    distance_metres: float | None = None
    picked_up_at: datetime | None = None
    delivered_at: datetime | None = None
    #: The courier's own status string, unmapped. Logged and stored so a
    #: surprise in production can be diagnosed without a replay.
    provider_status: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DeliveryQuote:
    """What a courier would charge to take this trip, before it exists.

    The thing that lets a checkout show a real delivery fee and refuse an
    address nobody will drive to — rather than taking the money first and
    finding out afterwards.

    `min_cost`/`max_cost` are a RANGE, because that is what couriers quote: a
    rider has not been found yet and the price moves with demand. What the
    customer is charged is a separate decision — most food apps show one
    rounded number and absorb the spread, because "delivery ₹71.26 to ₹91.26"
    is not a thing anyone wants to read at a checkout.

    `serviceable` False means there is no price at all, not a price of zero.
    """

    serviceable: bool
    min_cost: Decimal | None = None
    max_cost: Decimal | None = None
    currency: str = ""
    distance_metres: float | None = None
    #: Seconds from pickup to drop, as the courier reckons it.
    travel_seconds: int | None = None
    #: Seconds they expect to take finding a rider at all. Worth showing: on
    #: the sandbox this was 18 minutes, which dwarfs the drive and is the
    #: difference between an honest ETA and an optimistic one.
    assign_seconds: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class DeliveryProviderError(RuntimeError):
    """A courier call failed in a way worth surfacing.

    `retryable` distinguishes "their API blinked" from "this order will never
    be accepted". A Celery task retries the first and gives up on the second;
    without the flag it would hammer a permanent validation failure.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@runtime_checkable
class DeliveryProvider(Protocol):
    """What every courier must do."""

    name: str

    def is_configured(self) -> bool:
        """Whether this provider has what it needs to be called at all."""
        ...

    def quote(
        self,
        *,
        pickup_lat: float,
        pickup_lng: float,
        drop_lat: float,
        drop_lng: float,
        timeout: float | None = None,
    ) -> DeliveryQuote:
        """What this trip would cost, and whether anyone will drive it.

        Coordinates, not addresses — every courier prices off a point, and
        turning a customer's typed address into one is the caller's problem.
        """
        ...

    def create(self, request: DeliveryRequest) -> DeliveryResult:
        """Ask for a pickup. Raises `DeliveryProviderError` if it is refused."""
        ...

    def fetch(self, provider_order_id: str) -> DeliveryResult:
        """Where that delivery has got to."""
        ...

    def parse_webhook(self, payload: dict[str, Any]) -> DeliveryResult:
        """A pushed status update, in the same shape as `fetch`."""
        ...


__all__ = [
    "DeliveryAddress",
    "DeliveryItem",
    "DeliveryProvider",
    "DeliveryProviderError",
    "DeliveryQuote",
    "DeliveryRequest",
    "DeliveryResult",
    "DeliveryState",
]
