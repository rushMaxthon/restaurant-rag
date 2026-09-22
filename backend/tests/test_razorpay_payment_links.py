"""A Razorpay restaurant can be sent a link to pay on.

The browser has a payment sheet; a chat thread does not. An order placed over
WhatsApp is paid by tapping a URL, and `create_payment_link` is what makes
one — except it refused anything but CARD, and only Stripe carried a
`create_checkout_session`. So the one channel where a link is the ONLY way to
pay was the one channel a Razorpay restaurant could not be paid on.

Razorpay's Payment Link is Stripe's Checkout Session under another name: a
hosted page with an id and a short URL. Storing the LINK's id is what lets
the webhook, the transaction row and `order.payment_reference` carry on
unchanged — but it also means the webhook has to read the link's id back out,
which is what most of this file is about.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.payments.base import PaymentProviderError
from app.services.payments.razorpay_provider import RazorpayProvider

SECRET = "not-a-real-webhook-secret"
ORDER_ID = uuid.uuid4()


def a_provider(**over):
    provider = RazorpayProvider(
        key_id="rzp_test_key",
        key_secret="not-a-real-api-secret",
        webhook_secret=SECRET,
    )
    return provider


class CreatingTheLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = a_provider()
        self.sent: dict = {}

        def fake_request(method, path, **kwargs):
            self.sent["method"], self.sent["path"] = method, path
            self.sent["json"] = kwargs.get("json")
            return {
                "id": "plink_ABC123",
                "short_url": "https://rzp.io/i/ABC123",
                "amount": 14500,
                "currency": "INR",
                "expire_by": 1790000000,
            }

        self.provider._request = fake_request  # type: ignore[assignment]

    def _make(self, **over):
        kwargs = {
            "order_id": ORDER_ID,
            "customer_id": uuid.uuid4(),
            "restaurant_id": uuid.uuid4(),
            "amount": Decimal("145.00"),
            "currency": "INR",
            "description": "Order 1234",
            "customer_email": "vishal@example.com",
            "success_url": "https://example.test/orders/1",
            "cancel_url": "https://example.test/orders/1",
            "idempotency_key": f"order:{ORDER_ID}:checkout",
            "metadata": {"contact_phone": "+919876500099"},
        }
        kwargs.update(over)
        return self.provider.create_checkout_session(**kwargs)

    def test_it_asks_razorpay_for_a_payment_link(self) -> None:
        self._make()
        self.assertEqual((self.sent["method"], self.sent["path"]), ("POST", "/payment_links"))

    def test_the_amount_is_in_paise_and_exact(self) -> None:
        # `int(amount * 100)` truncates: 240.55 becomes 24054 and every order
        # is a paisa short, for ever.
        self._make(amount=Decimal("240.55"))
        self.assertEqual(self.sent["json"]["amount"], 24055)

    def test_the_order_is_the_reference(self) -> None:
        # Razorpay enforces `reference_id` as unique, which is this API's
        # idempotency: a second call for one order is refused rather than
        # quietly issuing a second payable link.
        self._make()
        self.assertEqual(self.sent["json"]["reference_id"], f"order:{ORDER_ID}")

    def test_razorpay_does_not_also_message_the_customer(self) -> None:
        # It would SMS and email the link itself, so the customer would get
        # it twice — the channel that asked for it is already sending it.
        self._make()
        self.assertEqual(self.sent["json"]["notify"], {"sms": False, "email": False})
        self.assertFalse(self.sent["json"]["reminder_enable"])

    def test_the_link_id_is_what_is_stored_as_the_intent(self) -> None:
        # The webhook for a link carries the LINK's id, not an order's, so
        # anything else here would match no order when it arrives.
        result = self._make()
        self.assertEqual(result.intent_id, "plink_ABC123")
        self.assertEqual(result.url, "https://rzp.io/i/ABC123")

    def test_a_reply_with_no_url_is_an_error_not_a_dead_link(self) -> None:
        self.provider._request = lambda *a, **k: {"id": "plink_X"}  # type: ignore[assignment]
        with self.assertRaises(PaymentProviderError):
            self._make()


class TheWebhookFindsTheOrderTests(unittest.TestCase):
    """Which id an event carries depends on how the payment was started."""

    def signed(self, body: dict) -> tuple[bytes, str]:
        payload = json.dumps(body).encode()
        signature = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
        return payload, signature

    def test_a_link_payment_reports_the_link(self) -> None:
        payload, signature = self.signed({
            "id": "evt_1",
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {"entity": {"id": "plink_ABC123", "amount": 14500,
                                            "currency": "INR"}},
                "payment": {"entity": {"id": "pay_1", "order_id": "order_XYZ",
                                       "amount": 14500, "currency": "INR"}},
            },
        })
        event = a_provider().parse_webhook(payload=payload, signature=signature)
        self.assertEqual(event.intent_id, "plink_ABC123")
        self.assertEqual(event.event_type, "succeeded")

    def test_a_checkout_payment_still_reports_the_order(self) -> None:
        # The browser flow is unchanged: `create_intent` stores a Razorpay
        # ORDER id, and that is what has to come back.
        payload, signature = self.signed({
            "id": "evt_2",
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_2", "order_id": "order_XYZ",
                                               "amount": 14500, "currency": "INR"}}},
        })
        event = a_provider().parse_webhook(payload=payload, signature=signature)
        self.assertEqual(event.intent_id, "order_XYZ")
        self.assertEqual(event.event_type, "succeeded")

    def test_a_link_that_expired_is_not_a_payment(self) -> None:
        payload, signature = self.signed({
            "id": "evt_3",
            "event": "payment_link.expired",
            "payload": {"payment_link": {"entity": {"id": "plink_OLD"}}},
        })
        event = a_provider().parse_webhook(payload=payload, signature=signature)
        self.assertEqual(event.intent_id, "plink_OLD")
        self.assertEqual(event.event_type, "cancelled")

    def test_a_forged_signature_is_still_refused(self) -> None:
        from app.services.payments.base import WebhookVerificationError

        payload, _ = self.signed({"id": "e", "event": "payment_link.paid",
                                  "payload": {"payment_link": {"entity": {"id": "p"}}}})
        with self.assertRaises(WebhookVerificationError):
            a_provider().parse_webhook(payload=payload, signature="deadbeef")


if __name__ == "__main__":
    unittest.main()
