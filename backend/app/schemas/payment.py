from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus


class PaymentConfigResponse(BaseModel):
    """Client bootstrap. The secret key is never part of this payload."""

    publishable_key: str
    stripe_enabled: bool
    currency: str
    supported_methods: list[PaymentMethod]


class PaymentIntentResponse(BaseModel):
    order_id: uuid.UUID
    payment_intent_id: str
    client_secret: str
    amount: Decimal
    currency: str
    publishable_key: str


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
