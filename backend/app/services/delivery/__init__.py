"""Courier integrations, behind one contract.

`base` holds the types every caller is written against; a provider module
implements them; `registry` decides which one answers. Same arrangement as
`services/payments`, for the same reason — a second courier should be a new
module, not a change to the order flow.
"""

from app.services.delivery.base import (
    DeliveryAddress,
    DeliveryItem,
    DeliveryProvider,
    DeliveryProviderError,
    DeliveryRequest,
    DeliveryResult,
    DeliveryState,
)

__all__ = [
    "DeliveryAddress",
    "DeliveryItem",
    "DeliveryProvider",
    "DeliveryProviderError",
    "DeliveryRequest",
    "DeliveryResult",
    "DeliveryState",
]
