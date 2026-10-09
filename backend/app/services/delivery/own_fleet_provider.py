"""The platform's own riders, behind the courier contract.

Unlike Pidge, booking here calls nobody: `create` hands back a PENDING
delivery and the offer loop (`services/fleet/offers.py`) finds the rider.
Riders' actions are written back through `delivery.service.record`, exactly
as a Pidge webhook is, so the order moves by one rule for both couriers.

Quotes are not this provider's job. The customer is charged by the
platform's slabs (`delivery/slabs.py`) whoever carries the food.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.services.delivery.base import (
    DeliveryProviderError,
    DeliveryQuote,
    DeliveryRequest,
    DeliveryResult,
    DeliveryState,
)

PROVIDER_NAME = "own_fleet"


class OwnFleetProvider:
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
        raise DeliveryProviderError("The own fleet does not quote; slabs price the trip", retryable=False)

    def create(self, request: DeliveryRequest) -> DeliveryResult:
        return DeliveryResult(
            provider_order_id=f"fleet-{uuid.uuid4().hex[:12]}",
            state=DeliveryState.PENDING,
            reference=request.reference,
            provider_status="finding_rider",
            raw={"provider": PROVIDER_NAME},
        )

    def fetch(self, provider_order_id: str) -> DeliveryResult:
        # The row IS the truth for our own riders; nothing outside to ask.
        raise DeliveryProviderError("The own fleet is read from its rows, not fetched", retryable=False)

    def parse_webhook(self, payload: dict[str, Any]) -> DeliveryResult:
        raise DeliveryProviderError("The own fleet has no webhook", retryable=False)

    def cancel(self, provider_order_id: str) -> None:
        """Nothing to call; `service.cancel` ends the trip and withdraws offers."""


__all__ = ["OwnFleetProvider", "PROVIDER_NAME"]
