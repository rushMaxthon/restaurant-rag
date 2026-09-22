from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus


class PaymentConfigResponse(BaseModel):
    """Client bootstrap. The secret key is never part of this payload."""

    publishable_key: str
    stripe_enabled: bool
    currency: str
    supported_methods: list[PaymentMethod]
    # The PUBLIC key of each gateway this restaurant can settle through,
    # keyed by gateway name — Razorpay needs its `key_id` in the browser to
    # open Checkout at all.
    #
    # Public by design: every one of these appears in the page source of the
    # checkout that uses it. The matching secrets are encrypted server-side
    # and are not reachable from any endpoint.
    gateway_keys: dict[str, str] = Field(default_factory=dict)


class PaymentIntentResponse(BaseModel):
    order_id: uuid.UUID
    payment_intent_id: str
    client_secret: str
    amount: Decimal
    currency: str
    publishable_key: str


class PaymentLinkResponse(BaseModel):
    """A hosted page to pay one order on. No key, no secret, no card field:
    everything sensitive stays on Stripe's side of the link."""

    order_id: uuid.UUID
    url: str
    amount: Decimal
    currency: str
    expires_at: datetime | None = None


class PaymentStatusResponse(BaseModel):
    order_id: uuid.UUID
    order_status: OrderStatus
    payment_status: PaymentStatus
    payment_method: PaymentMethod
    payment_reference: str | None
    amount: Decimal
    currency: str
    failure_code: str | None = None
    failure_message: str | None = None
    # True when the app may open a payment sheet for this order.
    is_payable: bool = False
