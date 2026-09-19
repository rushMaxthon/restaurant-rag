"""The unpaid-order lifecycle is not Stripe-only.

Four things named CARD, and each cost money the day a restaurant settled
through Razorpay instead:

1. `reap_expired_unpaid_orders` selected `payment_method == CARD`, so a
   Razorpay order that was never paid was never reaped. It stayed
   PAYMENT_PENDING for ever — and its payment LINK stayed payable, so a
   customer tapping yesterday's link would be charged for an order nobody
   was cooking.
2. `_reconcile_with_provider` returned early for anything but CARD. That read
   is the safety net for a lost webhook, so Razorpay had none: the reaper
   would cancel an order the customer had already paid for.
3. `RazorpayProvider.cancel_intent` was a deliberate no-op, correctly, when
   the only thing it could be handed was a Razorpay ORDER. Payment links
   changed that and the no-op stayed.
4. `retrieve_intent` asked `/orders/{id}`, which 404s for a `plink_` id — so
   even asking Razorpay about a link failed.

The tests below drive the real functions. Razorpay's HTTP layer is stubbed
(these must not call a gateway), but nothing above it is: the branch that
picks the endpoint, the status mapping and the reaper's own ordering are the
code under test.

The ordering is the part worth stating plainly: the reaper must confirm the
attempt was NOT paid before it cancels anything. Cancelling first and asking
afterwards is how a paid customer loses their order.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.enums import PaymentMethod
from app.services.payments import service
from app.services.payments.base import PaymentProviderError
from app.services.payments.razorpay_provider import RazorpayProvider
from app.services.payments.registry import GATEWAY_FOR_METHOD

LINK_ID = "plink_ABC123"
ORDER_ID = "order_XYZ789"


def a_provider() -> RazorpayProvider:
    return RazorpayProvider(
        key_id="rzp_test_key",
        key_secret="not-a-real-api-secret",
        webhook_secret="not-a-real-webhook-secret",
    )


class AskingRazorpayWhatHappenedTests(unittest.TestCase):
    """`retrieve_intent`, for both kinds of id this app stores."""

    def setUp(self) -> None:
        self.provider = a_provider()
        self.sent: list[tuple[str, str]] = []

    def answering(self, body: dict):
        def fake_request(method, path, **kwargs):
            self.sent.append((method, path))
            return body

        return patch.object(self.provider, "_request", fake_request)

    def test_a_link_is_read_from_the_payment_links_endpoint(self) -> None:
        # `/orders/plink_...` is a 404. This was the whole reason reconciling
        # a chat order could never have worked.
        with self.answering({"id": LINK_ID, "status": "paid", "amount": 14500,
                             "currency": "INR", "short_url": "https://rzp.io/i/x"}):
            self.provider.retrieve_intent(LINK_ID)
        self.assertEqual(self.sent, [("GET", f"/payment_links/{LINK_ID}")])

    def test_an_order_is_still_read_from_the_orders_endpoint(self) -> None:
        # The browser checkout flow is untouched.
        with self.answering({"id": ORDER_ID, "status": "paid", "amount": 14500,
                             "currency": "INR"}):
            self.provider.retrieve_intent(ORDER_ID)
        self.assertEqual(self.sent, [("GET", f"/orders/{ORDER_ID}")])

    def test_a_paid_link_reports_succeeded(self) -> None:
        # "succeeded" is the one status the reconciler acts on, so this is the
        # assertion that decides whether a paid customer keeps their order.
        with self.answering({"id": LINK_ID, "status": "paid", "amount": 14500,
                             "currency": "INR", "short_url": "https://rzp.io/i/x"}):
            result = self.provider.retrieve_intent(LINK_ID)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.amount, Decimal("145.00"))
        self.assertEqual(result.currency, "INR")

    def test_an_unpaid_link_does_not_report_succeeded(self) -> None:
        with self.answering({"id": LINK_ID, "status": "created", "amount": 14500,
                             "currency": "INR", "short_url": "https://rzp.io/i/x"}):
            self.assertNotEqual(self.provider.retrieve_intent(LINK_ID).status, "succeeded")

    def test_an_expired_link_is_reported_as_cancelled(self) -> None:
        with self.answering({"id": LINK_ID, "status": "expired", "amount": 14500,
                             "currency": "INR", "short_url": "https://rzp.io/i/x"}):
            self.assertEqual(self.provider.retrieve_intent(LINK_ID).status, "cancelled")

    def test_a_status_razorpay_invents_later_is_not_read_as_paid(self) -> None:
        # An unknown status must never fall through to "succeeded"; the
        # default is "processing", which acts on nothing.
        with self.answering({"id": LINK_ID, "status": "something_new", "amount": 14500,
                             "currency": "INR", "short_url": "https://rzp.io/i/x"}):
            self.assertEqual(self.provider.retrieve_intent(LINK_ID).status, "processing")


class CancellingWhatIsStillPayableTests(unittest.TestCase):
    """`cancel_intent`, which now has something real to do."""

    def setUp(self) -> None:
        self.provider = a_provider()
        self.sent: list[tuple[str, str]] = []

    def recording(self, error: Exception | None = None):
        def fake_request(method, path, **kwargs):
            self.sent.append((method, path))
            if error is not None:
                raise error
            return {"id": LINK_ID, "status": "cancelled"}

        return patch.object(self.provider, "_request", fake_request)

    def test_a_link_is_cancelled_at_razorpay(self) -> None:
        # The order is cancelled here; without this the hosted page stays up
        # and stays payable.
        with self.recording():
            self.provider.cancel_intent(LINK_ID)
        self.assertEqual(self.sent, [("POST", f"/payment_links/{LINK_ID}/cancel")])

    def test_an_order_is_still_left_alone(self) -> None:
        # Razorpay has no cancel for an order, and calling one would 404.
        with self.recording():
            self.provider.cancel_intent(ORDER_ID)
        self.assertEqual(self.sent, [])

    def test_a_refusal_never_escapes(self) -> None:
        # The reaper loops over every restaurant's stale orders. One gateway
        # refusing one cancellation — already paid, already cancelled, already
        # expired — must not stop the rest of the batch being cleaned up.
        with self.recording(error=PaymentProviderError("already paid")):
            self.provider.cancel_intent(LINK_ID)  # must not raise
        self.assertEqual(len(self.sent), 1)


class TheReaperTests(unittest.TestCase):
    """Which orders are swept, in which order, against which provider."""

    def setUp(self) -> None:
        self.selected: list = []

        class FakeSession:
            def scalars(_self, statement):
                self.selected.append(statement)
                return iter([])

            def commit(_self):
                pass

        self.db = FakeSession()

    def test_every_gateway_settled_method_is_swept(self) -> None:
        # Previously `== CARD`, so a Razorpay order was never swept at all:
        # it sat in PAYMENT_PENDING for ever with a payable link attached.
        service.reap_expired_unpaid_orders(self.db)
        where = str(
            self.selected[0].compile(compile_kwargs={"literal_binds": True})
        ).rsplit("WHERE", 1)[-1]
        self.assertIn("'RAZORPAY'", where)
        self.assertIn("'CARD'", where)
        self.assertNotIn("'COD'", where, "cash has nothing to reap at a gateway")

    def test_the_methods_come_from_the_registry_not_a_list_here(self) -> None:
        # Spelled `in GATEWAY_FOR_METHOD` rather than `!= COD`: GOOGLE_PAY is
        # in the enum with no gateway behind it, and `provider_for` raises on
        # a method it cannot place.
        self.assertIn(PaymentMethod.CARD, GATEWAY_FOR_METHOD)
        self.assertIn(PaymentMethod.RAZORPAY, GATEWAY_FOR_METHOD)
        self.assertNotIn(PaymentMethod.COD, GATEWAY_FOR_METHOD)
        self.assertNotIn(PaymentMethod.GOOGLE_PAY, GATEWAY_FOR_METHOD)

    def test_it_asks_for_the_provider_of_the_order_s_own_method(self) -> None:
        # It asked for CARD's provider for every order, which for a Razorpay
        # restaurant is a different gateway's account or nothing at all.
        import inspect

        source = inspect.getsource(service.reap_expired_unpaid_orders)
        self.assertIn("method=order.payment_method", source)
        self.assertNotIn("method=PaymentMethod.CARD", source)


class TheSafetyNetTests(unittest.TestCase):
    """`_reconcile_with_provider` — the read that stands between a paid
    customer and an automatic cancellation."""

    def a_transaction(self):
        return SimpleNamespace(provider_intent_id=LINK_ID, status="PENDING")

    def an_order(self, method=PaymentMethod.RAZORPAY):
        from app.models.enums import PaymentStatus

        return SimpleNamespace(
            id=uuid.uuid4(),
            restaurant_id=uuid.uuid4(),
            payment_method=method,
            payment_status=PaymentStatus.PENDING,
            currency="INR",
        )

    def test_a_razorpay_order_is_reconciled(self) -> None:
        asked: list = []

        def provider_for(db, *, restaurant_id, method):
            asked.append(method)
            return SimpleNamespace(
                is_configured=lambda: True,
                retrieve_intent=lambda intent_id: SimpleNamespace(
                    status="requires_payment_method",
                    intent_id=intent_id,
                    amount=Decimal("145.00"),
                    currency="INR",
                ),
            )

        with patch.object(service, "provider_for", provider_for), patch.object(
            service, "_latest_transaction", lambda db, order_id: self.a_transaction()
        ):
            service._reconcile_with_provider(None, self.an_order())

        self.assertEqual(asked, [PaymentMethod.RAZORPAY], "and against its own gateway")

    def test_a_cash_order_is_not_reconciled(self) -> None:
        # Nothing to ask a gateway about.
        asked: list = []

        def provider_for(db, *, restaurant_id, method):
            asked.append(method)
            return None

        with patch.object(service, "provider_for", provider_for):
            service._reconcile_with_provider(None, self.an_order(method=PaymentMethod.COD))
        self.assertEqual(asked, [])

    def test_a_link_razorpay_reports_paid_marks_the_order_paid(self) -> None:
        marked: list = []

        def provider_for(db, *, restaurant_id, method):
            return SimpleNamespace(
                is_configured=lambda: True,
                retrieve_intent=lambda intent_id: SimpleNamespace(
                    status="succeeded",
                    intent_id=intent_id,
                    amount=Decimal("145.00"),
                    currency="INR",
                ),
            )

        with patch.object(service, "provider_for", provider_for), patch.object(
            service, "_latest_transaction", lambda db, order_id: self.a_transaction()
        ), patch.object(service, "_mark_paid", lambda *a, **k: marked.append(a[1])):
            order = self.an_order()
            service._reconcile_with_provider(None, order)

        self.assertEqual(marked, [order], "a paid order is rescued, not cancelled")


if __name__ == "__main__":
    unittest.main()
