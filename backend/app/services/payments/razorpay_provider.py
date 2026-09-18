"""Razorpay, against the same contract Stripe already satisfies.

Built on `httpx` rather than the `razorpay` SDK. The SDK is a thin wrapper
over four REST calls and an HMAC, `httpx` is already a dependency, and a
gateway integration that can be read end to end in one file is worth more
here than the two lines it would save.

**Razorpay's flow is not Stripe's, and the difference matters.** Stripe has a
PaymentIntent with a client secret the browser exchanges directly. Razorpay
has an *Order* created server-side; the browser opens Razorpay Checkout with
the public `key_id` and that order id, and hands back a signature the server
verifies. So `intent_id` here is a Razorpay order id, and `client_secret`
carries the same value — it is not secret, and the name comes from the
contract rather than from Razorpay.

Amounts are integer paise. Razorpay has no decimal amounts at all, and
sending 240.5 where 24050 is meant is the mistake this module exists to make
impossible: the conversion happens once, here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from decimal import Decimal
from typing import Any

import httpx

from app.services.payments.base import (
    PaymentIntentResult,
    PaymentProviderError,
    WebhookEvent,
    WebhookVerificationError,
)

PROVIDER_NAME = "razorpay"
API_BASE = "https://api.razorpay.com/v1"

logger = logging.getLogger(__name__)

# Razorpay order states, mapped onto the vocabulary the rest of the app
# already speaks — `payments/service.py` reads these, not Razorpay's.
_ORDER_STATUS = {
    "created": "requires_payment_method",
    "attempted": "processing",
    "paid": "succeeded",
}

# The events worth acting on. Razorpay sends many more; anything not here is
# parsed and ignored rather than treated as a payment outcome.
_EVENT_STATUS = {
    "payment.captured": "succeeded",
    "order.paid": "succeeded",
    "payment.failed": "failed",
}


def _to_minor_units(amount: Decimal) -> int:
    """Rupees to paise, exactly once and in one place.

    `int(amount * 100)` truncates — 240.55 becomes 24054 and a customer is
    undercharged by a paisa on every order, which reconciles wrong forever.
    Quantizing first is the difference.
    """

    return int((Decimal(amount) * 100).quantize(Decimal("1")))


def _from_minor_units(minor: Any) -> Decimal | None:
    try:
        return (Decimal(int(minor)) / 100).quantize(Decimal("0.01"))
    except (TypeError, ValueError, ArithmeticError):
        return None


class RazorpayProvider:
    """One restaurant's Razorpay account.

    Constructed per request from that restaurant's stored credentials — never
    a module-level singleton, which is what made the Stripe integration unable
    to serve more than one account.
    """

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        key_id: str,
        key_secret: str,
        webhook_secret: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._key_id = (key_id or "").strip()
        self._key_secret = (key_secret or "").strip()
        self._webhook_secret = (webhook_secret or "").strip()
        self._timeout = timeout

    def is_configured(self) -> bool:
        return bool(self._key_id and self._key_secret)

    # --- HTTP ---------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.is_configured():
            raise PaymentProviderError("This restaurant's Razorpay account is not configured", retryable=False)

        try:
            response = httpx.request(
                method,
                f"{API_BASE}{path}",
                auth=(self._key_id, self._key_secret),
                timeout=self._timeout,
                **kwargs,
            )
        except httpx.HTTPError as error:
            # Network trouble is worth retrying; a rejected request is not.
            raise PaymentProviderError(f"Could not reach Razorpay: {error}", retryable=True) from error

        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("error", {}).get("description", "")
            except ValueError:
                detail = response.text[:200]
            # 4xx is our request being wrong — bad key, bad amount, wrong
            # currency for the account. Retrying sends the same wrong request.
            retryable = response.status_code >= 500
            logger.warning("Razorpay %s %s -> %s %s", method, path, response.status_code, detail)
            raise PaymentProviderError(
                f"Razorpay refused this request: {detail or response.status_code}",
                retryable=retryable,
            )

        try:
            return response.json()
        except ValueError as error:
            raise PaymentProviderError("Razorpay returned a response that was not JSON") from error

    # --- The contract -------------------------------------------------------

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
        """Create the Razorpay order the browser's checkout will settle.

        `receipt` carries our own order id, which is what makes a webhook
        traceable back to an order here without trusting anything the client
        sent.
        """

        payload = {
            "amount": _to_minor_units(amount),
            "currency": (currency or "INR").upper(),
            "receipt": str(order_id),
            # Razorpay caps notes at 15 keys and 256 chars each; these are
            # the three that make a payment dashboard readable.
            "notes": {
                "order_id": str(order_id),
                "customer_id": str(customer_id),
                "restaurant_id": str(restaurant_id),
                **{k: str(v)[:256] for k, v in (metadata or {}).items()},
            },
        }
        created = self._request(
            "POST",
            "/orders",
            json=payload,
            # Razorpay keys idempotency off the receipt rather than a header,
            # which is why our order id is the receipt above.
            headers={"Content-Type": "application/json"},
        )

        return PaymentIntentResult(
            intent_id=created["id"],
            # Razorpay has no client secret. The browser needs the order id
            # and the public key; the key comes from `/payments/config`, so
            # this field carries the order id rather than inventing a second
            # one. Nothing secret travels in it.
            client_secret=created["id"],
            amount=_from_minor_units(created.get("amount")) or Decimal(amount),
            currency=(created.get("currency") or currency).upper(),
            status=_ORDER_STATUS.get(created.get("status", ""), "processing"),
        )

    def retrieve_intent(self, intent_id: str) -> PaymentIntentResult:
        order = self._request("GET", f"/orders/{intent_id}")
        return PaymentIntentResult(
            intent_id=order["id"],
            client_secret=order["id"],
            amount=_from_minor_units(order.get("amount")) or Decimal("0.00"),
            currency=(order.get("currency") or "INR").upper(),
            status=_ORDER_STATUS.get(order.get("status", ""), "processing"),
        )

    def cancel_intent(self, intent_id: str) -> None:
        """Razorpay orders cannot be cancelled, and pretending otherwise lies.

        Stripe has `PaymentIntent.cancel`; Razorpay has no equivalent — an
        unpaid order simply stays unpaid and is never charged. So this is a
        deliberate no-op rather than a call that would 404, and the order's
        own status in our database is what marks it abandoned.
        """

        logger.info("Razorpay order %s left unpaid; Razorpay has no cancel call", intent_id)

    def parse_webhook(self, *, payload: bytes, signature: str | None) -> WebhookEvent:
        """Verify and normalise a Razorpay webhook.

        The signature is an HMAC-SHA256 of the **raw body** with the webhook
        secret — a different secret from the API key, and rotated separately.
        Comparison is constant-time: `==` on a signature leaks its bytes to
        anyone willing to measure, which is the whole reason `compare_digest`
        exists.
        """

        if not self._webhook_secret:
            raise WebhookVerificationError("No Razorpay webhook secret is configured for this restaurant")
        if not signature:
            raise WebhookVerificationError("Missing X-Razorpay-Signature header")

        expected = hmac.new(
            self._webhook_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature.strip()):
            raise WebhookVerificationError()

        try:
            body = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise WebhookVerificationError("Razorpay webhook body was not JSON") from error

        event_type = body.get("event", "")
        entities = body.get("payload", {})
        payment = entities.get("payment", {}).get("entity", {}) or {}
        order = entities.get("order", {}).get("entity", {}) or {}

        # The Razorpay ORDER id, not the payment id: that is what
        # `create_intent` stored as the intent, and what the order row here
        # can be found by. A payment id would match nothing.
        intent_id = payment.get("order_id") or order.get("id")

        return WebhookEvent(
            event_id=body.get("id") or f"{event_type}:{intent_id}",
            event_type=_EVENT_STATUS.get(event_type, event_type),
            intent_id=intent_id,
            amount=_from_minor_units(payment.get("amount") or order.get("amount")),
            currency=(payment.get("currency") or order.get("currency") or "").upper() or None,
            failure_code=payment.get("error_code"),
            failure_message=payment.get("error_description"),
            payload=body,
        )

    def verify_checkout_signature(
        self,
        *,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> bool:
        """Confirm a success the browser reported.

        Razorpay Checkout hands the browser three values on success and the
        browser posts them back. They are only worth anything once verified
        here: without this, a customer could post a made-up payment id and
        have an order marked paid.

        HMAC-SHA256 of `order_id|payment_id` with the API secret — the API
        secret, not the webhook secret, which is a genuinely easy mistake and
        fails closed rather than loudly.
        """

        if not self._key_secret:
            return False
        expected = hmac.new(
            self._key_secret.encode("utf-8"),
            f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, (razorpay_signature or "").strip())


__all__ = ["PROVIDER_NAME", "RazorpayProvider"]
