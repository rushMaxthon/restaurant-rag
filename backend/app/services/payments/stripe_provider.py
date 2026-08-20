"""Stripe implementation of :class:`PaymentProvider`.

Amounts arrive as decimal major units (₹13.84) and are converted to the minor
units Stripe charges in (1384). Zero-decimal currencies are handled explicitly
because dividing by 100 would silently overcharge them by 100x.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import stripe

from app.config import get_settings
from app.services.payments.base import (
    PaymentIntentResult,
    PaymentProviderError,
    WebhookEvent,
    WebhookVerificationError,
)

logger = logging.getLogger(__name__)
settings = get_settings()

PROVIDER_NAME = "stripe"

# https://docs.stripe.com/currencies#zero-decimal
ZERO_DECIMAL_CURRENCIES = {
    "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
    "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
}


def to_minor_units(amount: Decimal, currency: str) -> int:
    if currency.lower() in ZERO_DECIMAL_CURRENCIES:
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_minor_units(amount: int, currency: str) -> Decimal:
    if currency.lower() in ZERO_DECIMAL_CURRENCIES:
        return Decimal(amount)
    return (Decimal(amount) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class StripeProvider:
    """Thin adapter over the Stripe SDK. Holds no request state."""

    name = PROVIDER_NAME

    def __init__(self, *, secret_key: str | None = None, webhook_secret: str | None = None) -> None:
        self._secret_key = secret_key if secret_key is not None else settings.stripe_secret_key
        self._webhook_secret = (
            webhook_secret if webhook_secret is not None else settings.stripe_webhook_secret
        )

    def is_configured(self) -> bool:
        return settings.stripe_is_configured

    def _client_kwargs(self) -> dict[str, Any]:
        return {"api_key": self._secret_key}

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
    ) -> PaymentIntentResult:
        payload_metadata = {
            "order_id": str(order_id),
            "customer_id": str(customer_id),
            "restaurant_id": str(restaurant_id),
            **(metadata or {}),
        }
        try:
            intent = stripe.PaymentIntent.create(
                amount=to_minor_units(amount, currency),
                currency=currency.lower(),
                metadata=payload_metadata,
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
                idempotency_key=idempotency_key,
                **self._client_kwargs(),
            )
        except stripe.StripeError as error:  # pragma: no cover - network failure path
            logger.exception("Stripe payment intent creation failed order_id=%s", order_id)
            raise PaymentProviderError(str(error.user_message or error)) from error

        return PaymentIntentResult(
            intent_id=intent["id"],
            client_secret=intent["client_secret"],
            amount=from_minor_units(int(intent["amount"]), intent["currency"]),
            currency=str(intent["currency"]).upper(),
            status=str(intent["status"]),
        )

    def retrieve_intent(self, intent_id: str) -> PaymentIntentResult:
        try:
            intent = stripe.PaymentIntent.retrieve(intent_id, **self._client_kwargs())
        except stripe.StripeError as error:  # pragma: no cover - network failure path
            raise PaymentProviderError(str(error.user_message or error)) from error

        return PaymentIntentResult(
            intent_id=intent["id"],
            client_secret=intent.get("client_secret") or "",
            amount=from_minor_units(int(intent["amount"]), intent["currency"]),
            currency=str(intent["currency"]).upper(),
            status=str(intent["status"]),
        )

    def cancel_intent(self, intent_id: str) -> None:
        try:
            stripe.PaymentIntent.cancel(intent_id, **self._client_kwargs())
        except stripe.StripeError as error:
            # A already-succeeded or already-cancelled intent is not an error we
            # want to propagate to a customer dismissing a sheet.
            logger.warning("Stripe intent cancel failed intent_id=%s error=%s", intent_id, error)

    def parse_webhook(self, *, payload: bytes, signature: str | None) -> WebhookEvent:
        if not self._webhook_secret:
            raise WebhookVerificationError("Stripe webhook secret is not configured")
        if not signature:
            raise WebhookVerificationError("Missing Stripe-Signature header")

        try:
            event = stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        except ValueError as error:
            raise WebhookVerificationError("Malformed webhook payload") from error
        except stripe.SignatureVerificationError as error:
            raise WebhookVerificationError() from error

        data_object = (event.get("data") or {}).get("object") or {}
        intent_id: str | None = None
        amount: Decimal | None = None
        currency: str | None = None
        failure_code: str | None = None
        failure_message: str | None = None

        object_type = data_object.get("object")
        if object_type == "payment_intent":
            intent_id = data_object.get("id")
            currency = data_object.get("currency")
            raw_amount = data_object.get("amount_received") or data_object.get("amount")
            if raw_amount is not None and currency:
                amount = from_minor_units(int(raw_amount), currency)
            last_error = data_object.get("last_payment_error") or {}
            failure_code = last_error.get("code")
            failure_message = last_error.get("message")
        elif object_type == "charge":
            intent_id = data_object.get("payment_intent")
            currency = data_object.get("currency")
            raw_amount = data_object.get("amount_refunded") or data_object.get("amount")
            if raw_amount is not None and currency:
                amount = from_minor_units(int(raw_amount), currency)

        return WebhookEvent(
            event_id=str(event["id"]),
            event_type=str(event["type"]),
            intent_id=intent_id,
            amount=amount,
            currency=currency.upper() if currency else None,
            failure_code=failure_code,
            failure_message=failure_message,
            payload=dict(event),
        )
