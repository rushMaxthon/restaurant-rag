"""A courier that always says yes, for showing the flow end to end.

Pidge's sandbox accepts a booking and then stops: the order sits at `pending`
forever and no rider is ever assigned. Every screen downstream of that —
the Courier panel in the admin, the rider card on the customer's order, the
tracking link — is therefore unreachable without a live Pidge contract, which
makes the one thing you most want to demonstrate the one thing you cannot.

This provider fills that gap. It accepts every booking and then walks the
delivery along the happy path on a clock, so the whole chain can be watched
working on a laptop with nothing external running.

**It is not a test double and it is not a stub.** It implements the real
`DeliveryProvider` protocol and is driven by the real machinery: the booking
goes through `dispatch_order_task` like any other, and the states are read
back by the same `refresh_deliveries_task` the beat already runs every minute.
Nothing downstream knows it is talking to this rather than to Pidge, which is
the point — if the admin panel renders a rider from this, it will render one
from Pidge.

**What it does NOT prove.** Pidge's own field names, their auth, their
serviceability rules, their webhook shape, and whether any of it survives a
real network. Those are exactly what the sandbox DOES test, so this replaces
nothing: it is for showing the product, and Pidge is for proving the
integration. Keep both.

Guarded twice over, because a courier that invents riders must never be
reachable in production: `enable_delivery_rehearsal` defaults off, and the
registry refuses to build this unless `app_env` is a local one.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.services.delivery.base import (
    DeliveryProviderError,
    DeliveryQuote,
    DeliveryRequest,
    DeliveryResult,
    DeliveryState,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "rehearsal"

#: Seconds after booking at which each state is reached. Tuned so a whole
#: delivery completes inside a few minutes — long enough to watch each stage
#: land on a screen, short enough to sit through twice while demonstrating.
#:
#: The beat refreshes every minute, so these are the instants a state becomes
#: TRUE, not the instants a screen updates; a stage set below 60s would be
#: skipped past rather than seen.
_STAGES: tuple[tuple[int, DeliveryState], ...] = (
    (0, DeliveryState.PENDING),
    (60, DeliveryState.ASSIGNED),
    (120, DeliveryState.PICKED_UP),
    (180, DeliveryState.IN_TRANSIT),
    (300, DeliveryState.DELIVERED),
)

#: Riders, so a demo is not always the same name. Chosen from the booking id
#: rather than at random: `fetch` is called repeatedly for one delivery and a
#: rider who changed name every minute would look like a bug.
_RIDERS: tuple[tuple[str, str], ...] = (
    ("Imran Shaikh", "+919812000111"),
    ("Priya Nair", "+919812000222"),
    ("Devendra Patil", "+919812000333"),
    ("Anjali Rao", "+919812000444"),
)


def _booked_at(provider_order_id: str) -> datetime:
    """When this delivery was created, read back out of its own id.

    The id carries the timestamp precisely so this provider can be stateless.
    A dict of bookings would not survive the worker restarting, and a delivery
    that forgets its own age mid-demo is worse than no demo.
    """

    _, _, stamp = provider_order_id.partition("-")
    try:
        return datetime.fromtimestamp(int(stamp) / 1000, tz=UTC)
    except (TypeError, ValueError):
        # An id this provider did not mint. Treat it as brand new rather than
        # raising: the caller wants a status, not an argument.
        return datetime.now(tz=UTC)


def _rider_for(provider_order_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(provider_order_id.encode()).digest()
    return _RIDERS[digest[0] % len(_RIDERS)]


def _state_at(elapsed_seconds: float) -> DeliveryState:
    reached = _STAGES[0][1]
    for after, state in _STAGES:
        if elapsed_seconds >= after:
            reached = state
    return reached


class RehearsalProvider:
    """A courier that accepts everything and delivers on a schedule."""

    name = PROVIDER_NAME

    def is_configured(self) -> bool:
        return True

    def quote(
        self,
        *,
        pickup_lat: float,
        pickup_lng: float,
        drop_lat: float,
        drop_lng: float,
        timeout: float | None = None,
    ) -> DeliveryQuote:
        """A plausible price for the distance, so a checkout has a real figure.

        Straight-line metres via the haversine formula and a flat per-km rate.
        NOT an attempt to model Pidge's pricing — it is a number that moves
        with distance so a demo can show two addresses costing different
        amounts, which is the behaviour being shown.
        """

        from math import asin, cos, radians, sin, sqrt

        lat1, lon1, lat2, lon2 = map(
            radians, (pickup_lat, pickup_lng, drop_lat, drop_lng)
        )
        h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
        metres = 2 * 6371000 * asin(sqrt(h))

        settings = get_settings()
        base = Decimal(str(settings.delivery_rehearsal_base_fee))
        per_km = Decimal(str(settings.delivery_rehearsal_per_km_fee))
        fee = base + (per_km * Decimal(str(round(metres / 1000, 2))))
        fee = fee.quantize(Decimal("0.01"))

        return DeliveryQuote(
            serviceable=True,
            min_cost=fee,
            max_cost=fee,
            currency=settings.delivery_rehearsal_currency,
            distance_metres=round(metres, 2),
            # Roughly 18 km/h through traffic, plus a minute of faff.
            travel_seconds=int(metres / 5) + 60,
            assign_seconds=_STAGES[1][0],
            raw={"provider": PROVIDER_NAME, "simulated": True},
        )

    def create(self, request: DeliveryRequest) -> DeliveryResult:
        """Accept the booking, and stamp the id with the time it happened."""

        now = datetime.now(tz=UTC)
        provider_order_id = f"{PROVIDER_NAME}-{int(now.timestamp() * 1000)}"
        logger.info(
            "Rehearsal courier accepted %s as %s — NOT a real delivery",
            request.reference,
            provider_order_id,
        )
        return DeliveryResult(
            provider_order_id=provider_order_id,
            state=DeliveryState.PENDING,
            reference=request.reference,
            provider_status="pending",
            tracking_url=f"https://example.invalid/rehearsal/{provider_order_id}",
            raw={"provider": PROVIDER_NAME, "simulated": True},
        )

    def fetch(self, provider_order_id: str) -> DeliveryResult:
        """Where it has got to, worked out from how long ago it was booked."""

        if not provider_order_id:
            raise DeliveryProviderError("No delivery named", retryable=False)

        booked = _booked_at(provider_order_id)
        elapsed = (datetime.now(tz=UTC) - booked).total_seconds()
        state = _state_at(elapsed)
        rider_name, rider_mobile = _rider_for(provider_order_id)

        # A rider only exists once one has been assigned. Showing a name during
        # PENDING is the exact thing that made a stale test rider look real.
        assigned = state is not DeliveryState.PENDING

        return DeliveryResult(
            provider_order_id=provider_order_id,
            state=state,
            rider_name=rider_name if assigned else "",
            rider_mobile=rider_mobile if assigned else "",
            tracking_url=f"https://example.invalid/rehearsal/{provider_order_id}",
            provider_status=state.value.lower(),
            picked_up_at=(
                booked + timedelta(seconds=_STAGES[2][0])
                if elapsed >= _STAGES[2][0]
                else None
            ),
            delivered_at=(
                booked + timedelta(seconds=_STAGES[4][0])
                if state is DeliveryState.DELIVERED
                else None
            ),
            raw={"provider": PROVIDER_NAME, "simulated": True, "elapsed_seconds": int(elapsed)},
        )

    def parse_webhook(self, payload: dict[str, Any]) -> DeliveryResult:
        """Nothing pushes here, so a push is read as a request to re-read."""

        provider_order_id = str(payload.get("provider_order_id") or payload.get("id") or "")
        return self.fetch(provider_order_id)


__all__ = ["PROVIDER_NAME", "RehearsalProvider"]
