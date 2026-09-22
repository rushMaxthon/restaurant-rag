"""A payment this platform took can be found again, to refund it.

`provider_intent_id` is what this app ASKED the gateway for: a Stripe
PaymentIntent, a Razorpay order, or — since chat ordering — a Razorpay
payment link. A refund is issued against none of those. Razorpay's refund
endpoint is `/payments/{payment_id}/refund`, and a `plink_...` there matches
nothing.

That payment id was arriving in the `payment_link.paid` webhook all along,
in `payload.payment.entity.id`. It was read into a local, used to decide
nothing, and dropped — so a Razorpay payment could not be refunded from this
system at all; somebody had to find it by hand in Razorpay's dashboard.

Nothing issues refunds yet. These tests exist because the id has to be
captured from the first payment onward: one that lands unrecorded is lost for
good, and no later feature can go back for it.
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
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.enums import OrderStatus, PaymentStatus
from app.models.payment import PaymentTransaction
from app.services.payments import service
from app.services.payments.base import WebhookEvent
from app.services.payments.razorpay_provider import RazorpayProvider

SECRET = "not-a-real-webhook-secret"


def signed(body: dict) -> tuple[bytes, str]:
    payload = json.dumps(body).encode()
    return payload, hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()


def a_provider() -> RazorpayProvider:
    return RazorpayProvider(
        key_id="rzp_test_key", key_secret="not-a-real-api-secret", webhook_secret=SECRET
    )


class RazorpayReportsThePaymentTests(unittest.TestCase):
    def test_a_paid_link_carries_the_payment_id(self) -> None:
        # The link identifies the ORDER; `pay_...` identifies the money, and
        # only the second one can be refunded.
        payload, signature = signed({
            "id": "evt_1",
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {"entity": {"id": "plink_ABC", "amount": 14500,
                                            "currency": "INR"}},
                "payment": {"entity": {"id": "pay_LIVE1", "order_id": "order_X",
                                       "amount": 14500, "currency": "INR"}},
            },
        })
        event = a_provider().parse_webhook(payload=payload, signature=signature)
        self.assertEqual(event.intent_id, "plink_ABC", "still finds the order")
        self.assertEqual(event.payment_id, "pay_LIVE1", "and now the money too")

    def test_a_checkout_payment_carries_it_as_well(self) -> None:
        payload, signature = signed({
            "id": "evt_2",
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_LIVE2", "order_id": "order_X",
                                               "amount": 14500, "currency": "INR"}}},
        })
        event = a_provider().parse_webhook(payload=payload, signature=signature)
        self.assertEqual(event.payment_id, "pay_LIVE2")

    def test_an_event_with_no_payment_carries_none(self) -> None:
        # An expiry is not a payment. None is the honest answer; an empty
        # string would be stored and look like a real id later.
        payload, signature = signed({
            "id": "evt_3",
            "event": "payment_link.expired",
            "payload": {"payment_link": {"entity": {"id": "plink_OLD"}}},
        })
        event = a_provider().parse_webhook(payload=payload, signature=signature)
        self.assertIsNone(event.payment_id)


class ItIsStoredWhenTheOrderIsMarkedPaidTests(unittest.TestCase):
    """`_mark_paid` is the one place every payment path converges on."""

    def setUp(self) -> None:
        self.committed = 0

        class FakeSession:
            def add(_self, _row): pass
            def add_all(_self, _rows): pass
            def commit(_self): self.committed += 1
            # `_mark_paid` looks the customer up to run the order-placed
            # side effects. None is a real case — a deleted customer — and
            # skips them, which is exactly what this test wants.
            def get(_self, _model, _pk): return None

        self.db = FakeSession()
        self.order = SimpleNamespace(
            id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            total_amount=Decimal("145.00"),
            currency="INR",
            payment_status=PaymentStatus.PENDING,
            status=OrderStatus.PLACED,
            payment_reference=None,
        )
        self.transaction = PaymentTransaction(
            order_id=self.order.id,
            provider="razorpay",
            provider_intent_id="plink_ABC",
            status=PaymentStatus.PENDING,
            amount=Decimal("145.00"),
            currency="INR",
        )

    def paid(self, payment_id: str | None) -> None:
        service._mark_paid(
            self.db,
            self.order,
            self.transaction,
            WebhookEvent(
                event_id="evt",
                event_type="succeeded",
                intent_id="plink_ABC",
                amount=Decimal("145.00"),
                currency="INR",
                payment_id=payment_id,
            ),
        )

    def test_the_payment_id_is_kept(self) -> None:
        self.paid("pay_LIVE1")
        self.assertEqual(self.transaction.provider_payment_id, "pay_LIVE1")

    def test_the_intent_is_still_what_the_order_references(self) -> None:
        # The order's own reference is unchanged; this is an addition, not a
        # replacement, and anything matching on the intent keeps working.
        self.paid("pay_LIVE1")
        self.assertEqual(self.order.payment_reference, "plink_ABC")

    def test_an_event_without_one_does_not_erase_what_is_there(self) -> None:
        # Razorpay sends several events for one payment and not all carry it.
        self.transaction.provider_payment_id = "pay_LIVE1"
        self.order.payment_status = PaymentStatus.PENDING
        self.paid(None)
        self.assertEqual(self.transaction.provider_payment_id, "pay_LIVE1")

    def test_a_short_payment_is_still_refused(self) -> None:
        # The amount check runs before any of this, and must keep running:
        # recording an id is not a reason to accept less than the order costs.
        service._mark_paid(
            self.db,
            self.order,
            self.transaction,
            WebhookEvent(
                event_id="evt",
                event_type="succeeded",
                intent_id="plink_ABC",
                amount=Decimal("1.00"),
                currency="INR",
                payment_id="pay_LIVE1",
            ),
        )
        self.assertEqual(self.order.payment_status, PaymentStatus.FAILED)


class TheColumnExistsTests(unittest.TestCase):
    def test_the_model_has_it_and_it_is_nullable(self) -> None:
        # Nullable on purpose: rows written before this genuinely lost the id,
        # and a refund path should say so rather than invent one.
        column = PaymentTransaction.__table__.columns["provider_payment_id"]
        self.assertTrue(column.nullable)

    def test_it_is_indexed(self) -> None:
        # A refund event names the payment, not the intent, so this is what a
        # lookup would have to search on.
        column = PaymentTransaction.__table__.columns["provider_payment_id"]
        self.assertTrue(column.index)


if __name__ == "__main__":
    unittest.main()
