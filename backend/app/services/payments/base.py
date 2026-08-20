"""Provider-neutral payment contracts.

Everything above this layer (order service, API, webhook handling) is written
against these types, so adding a second gateway later means adding a module and
a registry entry rather than touching the order flow.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class PaymentIntentResult:
    """What the client needs to present a payment sheet."""

    intent_id: str
    client_secret: str
    amount: Decimal
    currency: str
    status: str


@dataclass(slots=True)
class WebhookEvent:
    """A verified provider event, normalized."""

    event_id: str
    event_type: str
    intent_id: str | None
    amount: Decimal | None
    currency: str | None
    failure_code: str | None = None
    failure_message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class PaymentProviderError(RuntimeError):
    """Raised when a provider call fails for a reason worth surfacing."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class WebhookVerificationError(PaymentProviderError):
    """Raised when a webhook payload fails signature verification."""

    def __init__(self, message: str = "Invalid webhook signature") -> None:
        super().__init__(message, retryable=False)


@runtime_checkable
class PaymentProvider(Protocol):
    """Contract every gateway implements. COD is deliberately not a provider."""

    name: str

    def is_configured(self) -> bool: ...

    def create_intent(
        self,
        *,
        order_id: uuid.UUID,
        customer_id: uuid.UUID,
        restaurant_id: uuid.UUID,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        metadata: dict[str, str] | None = None,
    ) -> PaymentIntentResult: ...

    def retrieve_intent(self, intent_id: str) -> PaymentIntentResult: ...

    def cancel_intent(self, intent_id: str) -> None: ...

    def parse_webhook(self, *, payload: bytes, signature: str | None) -> WebhookEvent: ...
