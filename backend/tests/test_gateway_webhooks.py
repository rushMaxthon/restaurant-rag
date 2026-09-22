"""Webhooks for a restaurant that holds its own gateway account.

The hard part of per-restaurant webhooks is not the HMAC, it is knowing
*whose* secret to check it with before believing anything. Each restaurant has
its own webhook secret, so the identification has to come from somewhere
outside the payload — and the only thing outside the payload is the address
the request arrived at.

That is why the restaurant is in the URL. The alternative, reading the order
id out of the body and looking up the restaurant from it, works and is the
shape to avoid: it puts a database lookup driven by attacker-controlled input
*before* the check that decides whether the input can be trusted at all.

What is tested here is that the boundary holds:

- a genuine delivery is verified with that restaurant's secret and applied;
- the same delivery posted to a different restaurant's URL is refused;
- a tampered body is refused even with a real signature attached;
- a restaurant with no webhook secret refuses rather than trusts;
- and a paused gateway still accepts confirmations for money it already took,
  because refusing them would leave paid orders sitting unpaid here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.main import app  # noqa: F401 - imported first to settle import order
from app.models.enums import PaymentGateway
from app.services.payments import service as payments_service

WEBHOOK_SECRET = "not-a-real-webhook-secret"
OTHER_SECRET = "a-different-restaurants-secret"


def a_body(order_id: str = "order_1", event: str = "payment.captured") -> bytes:
    return json.dumps(
        {
            "id": f"evt_{order_id}",
            "event": event,
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_1",
                        "order_id": order_id,
                        "amount": 24000,
                        "currency": "INR",
                    }
                }
            },
        }
    ).encode()


def sign(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def credentials_for(secret: str | None):
    return SimpleNamespace(
        gateway=PaymentGateway.RAZORPAY,
        public_key="rzp_test_publickey",
        secret_key="not-a-real-api-secret",
        webhook_secret=secret,
    )


class WebhookVerificationTests(unittest.TestCase):
    """Whose secret, and whether the body survived the trip."""

    def deliver(self, *, payload: bytes, signature: str | None, stored_secret=WEBHOOK_SECRET):
        applied: dict = {}

        def fake_apply(db, *, provider_name, event):
            applied["provider"] = provider_name
            applied["event"] = event
            return {"status": "paid", "event_id": event.event_id}

        with (
            patch.object(
                payments_service,
                "read_credentials",
                lambda db, *, restaurant_id, gateway, require_enabled=True: (
                    credentials_for(stored_secret)
                ),
            ),
            patch.object(payments_service, "_apply_webhook_event", fake_apply),
        ):
            result = payments_service.handle_gateway_webhook(
                None,
                gateway=PaymentGateway.RAZORPAY,
                restaurant_id=uuid.uuid4(),
                payload=payload,
                signature=signature,
            )
        return result, applied

    def test_a_genuine_delivery_is_verified_and_applied(self) -> None:
        payload = a_body()
        result, applied = self.deliver(payload=payload, signature=sign(payload))

        self.assertEqual(result["status"], "paid")
        self.assertEqual(applied["provider"], "razorpay")
        # The Razorpay ORDER id, which is what `create_intent` stored as the
        # intent — a payment id would match no order here.
        self.assertEqual(applied["event"].intent_id, "order_1")

    def test_another_restaurants_signature_is_refused(self) -> None:
        """The boundary, stated.

        Posting a perfectly genuine delivery to the wrong restaurant's URL
        fails, because it is checked against the secret belonging to the
        restaurant in the URL.
        """

        payload = a_body()
        with self.assertRaises(HTTPException) as caught:
            self.deliver(payload=payload, signature=sign(payload, OTHER_SECRET))

        self.assertEqual(caught.exception.status_code, 400)

    def test_a_tampered_body_is_refused(self) -> None:
        payload = a_body()
        signature = sign(payload)
        with self.assertRaises(HTTPException) as caught:
            self.deliver(payload=payload.replace(b"24000", b"1"), signature=signature)

        self.assertEqual(caught.exception.status_code, 400)

    def test_a_missing_signature_is_refused(self) -> None:
        with self.assertRaises(HTTPException):
            self.deliver(payload=a_body(), signature=None)

    def test_a_restaurant_with_no_webhook_secret_refuses_rather_than_trusts(self) -> None:
        payload = a_body()
        with self.assertRaises(HTTPException) as caught:
            self.deliver(payload=payload, signature=sign(payload), stored_secret=None)

        self.assertEqual(caught.exception.status_code, 400)

    def test_a_restaurant_with_no_account_is_refused(self) -> None:
        payload = a_body()
        with (
            patch.object(
                payments_service,
                "read_credentials",
                lambda db, *, restaurant_id, gateway, require_enabled=True: None,
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            payments_service.handle_gateway_webhook(
                None,
                gateway=PaymentGateway.RAZORPAY,
                restaurant_id=uuid.uuid4(),
                payload=payload,
                signature=sign(payload),
            )

        self.assertEqual(caught.exception.status_code, 400)


class APausedGatewayStillGetsItsConfirmationsTests(unittest.TestCase):
    def test_credentials_are_read_without_the_enabled_check(self) -> None:
        """Money already taken still has to be reconciled.

        A gateway paused five minutes ago may have payments in flight. If the
        webhook refused them, those orders would sit unpaid in this database
        while the customer's card had been charged.
        """

        seen: dict = {}

        def fake_read(db, *, restaurant_id, gateway, require_enabled=True):
            seen["require_enabled"] = require_enabled
            return credentials_for(WEBHOOK_SECRET)

        payload = a_body()
        with (
            patch.object(payments_service, "read_credentials", fake_read),
            patch.object(
                payments_service,
                "_apply_webhook_event",
                lambda db, *, provider_name, event: {"status": "paid", "event_id": "e"},
            ),
        ):
            payments_service.handle_gateway_webhook(
                None,
                gateway=PaymentGateway.RAZORPAY,
                restaurant_id=uuid.uuid4(),
                payload=payload,
                signature=sign(payload),
            )

        self.assertFalse(seen["require_enabled"])


class BothGatewaysSpeakTheSameOutcomesTests(unittest.TestCase):
    """Stripe and Razorpay name events differently; the applier knows both.

    Forcing one gateway to emit the other's vocabulary is how a mapping
    quietly stops matching after somebody renames a constant, so the applier
    accepts both sets and this pins that it does.
    """

    def test_every_outcome_is_recognised_in_both_vocabularies(self) -> None:
        pairs = [
            (payments_service._PAID_EVENTS, "payment_intent.succeeded", "succeeded"),
            (payments_service._FAILED_EVENTS, "payment_intent.payment_failed", "failed"),
            (payments_service._CANCELLED_EVENTS, "payment_intent.canceled", "cancelled"),
            (payments_service._REFUNDED_EVENTS, "charge.refunded", "refunded"),
        ]
        for events, stripe_name, normalised in pairs:
            self.assertIn(stripe_name, events, stripe_name)
            self.assertIn(normalised, events, normalised)

    def test_the_four_outcome_sets_do_not_overlap(self) -> None:
        # An event that meant two things would apply whichever branch came
        # first, which is the kind of bug that only shows up on a refund.
        sets = [
            payments_service._PAID_EVENTS,
            payments_service._FAILED_EVENTS,
            payments_service._CANCELLED_EVENTS,
            payments_service._REFUNDED_EVENTS,
        ]
        for index, first in enumerate(sets):
            for second in sets[index + 1 :]:
                self.assertEqual(first & second, frozenset())


if __name__ == "__main__":
    unittest.main()
