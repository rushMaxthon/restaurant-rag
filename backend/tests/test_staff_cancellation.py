"""Staff cancelling an order: the first cancellation a person makes.

Until 2026-10-06 every cancellation was system-derived (an unpaid checkout
reaped), so an owner whose kitchen ran out of something had no way to call an
order off at all. The rules, as decided with the platform owner:

- the platform admin and the restaurant's owner may cancel; a cook may not;
- only before the rider has the food (PLACED, ACCEPTED, PREPARING);
- a reason is required, from a fixed list, with an optional note;
- an order paid online is refunded in full, through the account that took it;
- one cancellation moves everything: the rider is called off, the payout is
  reversed, stock comes back, screens update - all already wired to the
  CANCELLED transition, and used here for the first time.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import HTTPException  # noqa: E402

from test_payout_ledger import D, LedgerDatabase, postgres_available  # noqa: E402

from app.models.enums import (  # noqa: E402
    OrderCancellationReason,
    OrderEventActor,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.order import Order  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.payment import PaymentTransaction  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import order_cancellation  # noqa: E402
from app.services.payments.base import PaymentProviderError  # noqa: E402

REASON = OrderCancellationReason.OUT_OF_STOCK


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class StaffCancellationTests(LedgerDatabase):
    def queued(self) -> list[str]:
        return [call.args[0] for call in self.sent.call_args_list]

    def cancel(self, order, user=None, *, reason=REASON, note="Paneer finished"):
        return order_cancellation.cancel_by_staff(
            self.db, user or self.owner, order_id=order.id,
            scope_restaurant_id=self.restaurant.id if (user or self.owner).role != UserRole.ADMIN else None,
            reason=reason, note=note,
        )

    def fresh(self, order) -> Order:
        self.db.expire_all()
        return self.db.get(Order, order.id)

    def test_an_owner_cancels_a_paid_order_and_everything_follows(self) -> None:
        order = self.make_order(status=OrderStatus.PREPARING)
        self.cancel(order)
        order = self.fresh(order)
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(order.cancellation_reason, REASON)
        self.assertEqual(order.cancelled_by, OrderEventActor.OWNER)
        self.assertEqual(order.cancellation_note, "Paneer finished")
        self.assertEqual(order.refund_status, "PENDING")
        queued = self.queued()
        self.assertIn("app.tasks.payments.refund_cancelled_order_task", queued)
        self.assertIn("app.tasks.payouts.reverse_payout_task", queued)
        self.assertIn("app.tasks.notifications.send_order_status_notification", queued)

    def test_cash_is_not_refunded(self) -> None:
        order = self.make_order(method=PaymentMethod.COD, paid=False, status=OrderStatus.ACCEPTED)
        self.cancel(order)
        order = self.fresh(order)
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertIsNone(order.refund_status)
        self.assertNotIn("app.tasks.payments.refund_cancelled_order_task", self.queued())

    def test_a_booked_rider_is_called_off(self) -> None:
        order = self.make_order(status=OrderStatus.ACCEPTED)
        self.db.add(OrderDelivery(order_id=order.id, provider="pidge", provider_order_id="P1", state="ASSIGNED"))
        self.db.commit()
        self.cancel(order)
        self.assertIn("app.tasks.delivery.cancel_order_delivery_task", self.queued())

    def test_food_with_the_rider_cannot_be_cancelled(self) -> None:
        for status in (OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED):
            order = self.make_order(status=status)
            with self.assertRaises(HTTPException) as raised:
                self.cancel(order)
            self.assertEqual(raised.exception.status_code, 409)

    def test_a_rider_who_has_collected_it_blocks_the_cancel_even_if_the_kitchen_is_behind(self) -> None:
        order = self.make_order(status=OrderStatus.PREPARING)
        self.db.add(OrderDelivery(order_id=order.id, provider="pidge", provider_order_id="P2", state="PICKED_UP"))
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            self.cancel(order)
        self.assertEqual(raised.exception.status_code, 409)

    def test_cancelling_twice_changes_nothing(self) -> None:
        order = self.make_order(status=OrderStatus.PLACED)
        self.cancel(order)
        before = len(self.queued())
        with self.assertRaises(HTTPException) as raised:
            self.cancel(order)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(len(self.queued()), before)

    def test_a_cook_cannot_cancel(self) -> None:
        cook = User(id=uuid.uuid4(), email=f"k{uuid.uuid4().hex[:6]}@x.in", full_name="Cook",
                    hashed_password="x", role=UserRole.KITCHEN, staff_restaurant_id=self.restaurant.id)
        self.db.add(cook)
        self.db.commit()
        order = self.make_order(status=OrderStatus.PLACED)
        with self.assertRaises(HTTPException) as raised:
            self.cancel(order, cook)
        self.assertEqual(raised.exception.status_code, 403)

    def test_another_restaurants_order_is_not_found(self) -> None:
        order = self.make_order(status=OrderStatus.PLACED)
        with self.assertRaises(HTTPException) as raised:
            order_cancellation.cancel_by_staff(
                self.db, self.owner, order_id=order.id, scope_restaurant_id=uuid.uuid4(),
                reason=REASON, note="",
            )
        self.assertEqual(raised.exception.status_code, 404)

    def test_only_a_staff_reason_is_accepted(self) -> None:
        order = self.make_order(status=OrderStatus.PLACED)
        with self.assertRaises(HTTPException) as raised:
            self.cancel(order, reason=OrderCancellationReason.PAYMENT_FAILED)
        self.assertEqual(raised.exception.status_code, 422)

    def test_other_needs_a_note(self) -> None:
        order = self.make_order(status=OrderStatus.PLACED)
        with self.assertRaises(HTTPException) as raised:
            self.cancel(order, reason=OrderCancellationReason.OTHER_BY_STAFF, note="  ")
        self.assertEqual(raised.exception.status_code, 422)

    def test_the_screen_is_told_whether_cancel_is_offered(self) -> None:
        self.assertTrue(order_cancellation.can_be_cancelled(self.make_order(status=OrderStatus.PREPARING)))
        self.assertFalse(order_cancellation.can_be_cancelled(self.make_order(status=OrderStatus.OUT_FOR_DELIVERY)))


class FakeRefunds:
    def __init__(self, error: PaymentProviderError | None = None) -> None:
        self.calls: list[dict] = []
        self.error = error

    def refund(self, **kwargs) -> str:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return "rfnd_1"


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class RefundTests(LedgerDatabase):
    def cancelled(self, **kwargs) -> Order:
        order = self.make_order(status=OrderStatus.PREPARING, **kwargs)
        order_cancellation.cancel_by_staff(
            self.db, self.owner, order_id=order.id, scope_restaurant_id=self.restaurant.id,
            reason=REASON, note="",
        )
        return order

    def refund(self, order, provider):
        with mock.patch.object(order_cancellation, "_refund_provider", return_value=provider):
            return order_cancellation.refund_cancelled_order(self.db, order.id)

    def test_the_whole_amount_goes_back_on_the_account_that_took_it(self) -> None:
        order = self.cancelled()
        provider = FakeRefunds()
        self.refund(order, provider)
        self.assertEqual(provider.calls[0]["payment_id"], "pay_123")
        self.assertEqual(provider.calls[0]["amount"], D("598.20"))
        self.db.expire_all()
        order = self.db.get(Order, order.id)
        self.assertEqual((order.payment_status, order.refund_status), (PaymentStatus.REFUNDED, "REFUNDED"))
        transaction = self.db.query(PaymentTransaction).filter_by(order_id=order.id).one()
        self.assertEqual(transaction.status, PaymentStatus.REFUNDED)

    def test_refunding_twice_refunds_once(self) -> None:
        order = self.cancelled()
        provider = FakeRefunds()
        self.refund(order, provider)
        self.refund(order, provider)
        self.assertEqual(len(provider.calls), 1)

    def test_a_refusal_is_failed_with_the_gateways_words(self) -> None:
        order = self.cancelled()
        self.refund(order, FakeRefunds(PaymentProviderError("Razorpay refused this request: insufficient balance",
                                                            retryable=False)))
        self.db.expire_all()
        order = self.db.get(Order, order.id)
        self.assertEqual(order.refund_status, "FAILED")
        self.assertIn("insufficient balance", order.refund_error)
        self.assertEqual(order.payment_status, PaymentStatus.PAID)

    def test_a_network_error_is_retried(self) -> None:
        order = self.cancelled()
        with self.assertRaises(PaymentProviderError):
            self.refund(order, FakeRefunds(PaymentProviderError("Could not reach Razorpay", retryable=True)))
        self.db.expire_all()
        self.assertEqual(self.db.get(Order, order.id).refund_status, "PENDING")

    def test_a_failed_refund_can_be_tried_again(self) -> None:
        order = self.cancelled()
        self.refund(order, FakeRefunds(PaymentProviderError("refused", retryable=False)))
        order_cancellation.retry_refund(self.db, self.owner, order_id=order.id,
                                        scope_restaurant_id=self.restaurant.id)
        self.db.expire_all()
        self.assertEqual(self.db.get(Order, order.id).refund_status, "PENDING")
        self.assertIn("app.tasks.payments.refund_cancelled_order_task",
                      [call.args[0] for call in self.sent.call_args_list])


class GatewayRefundTests(unittest.TestCase):
    """The request each gateway receives. Paise and cents, never rupees."""

    def test_razorpay_refunds_the_payment_in_paise(self) -> None:
        from app.services.payments.razorpay_provider import RazorpayProvider

        provider = RazorpayProvider(key_id="rzp_test_x", key_secret="s")
        order_id = uuid.uuid4()
        with mock.patch.object(provider, "_request", return_value={"id": "rfnd_9"}) as request:
            refund_id = provider.refund(intent_id="order_1", payment_id="pay_1", amount=D("598.20"),
                                        currency="INR", order_id=order_id)
        self.assertEqual(refund_id, "rfnd_9")
        self.assertEqual(request.call_args.args, ("POST", "/payments/pay_1/refund"))
        self.assertEqual(request.call_args.kwargs["json"]["amount"], 59820)

    def test_razorpay_finds_the_payment_when_only_the_order_is_known(self) -> None:
        from app.services.payments.razorpay_provider import RazorpayProvider

        provider = RazorpayProvider(key_id="rzp_test_x", key_secret="s")
        replies = [{"items": [{"id": "pay_failed", "status": "failed"}, {"id": "pay_ok", "status": "captured"}]},
                   {"id": "rfnd_9"}]
        with mock.patch.object(provider, "_request", side_effect=replies) as request:
            provider.refund(intent_id="order_1", payment_id="", amount=D("10"), currency="INR", order_id=uuid.uuid4())
        self.assertEqual(request.call_args_list[0].args, ("GET", "/orders/order_1/payments"))
        self.assertEqual(request.call_args_list[1].args, ("POST", "/payments/pay_ok/refund"))

    def test_stripe_refunds_the_intent_once_per_order(self) -> None:
        from app.services.payments.stripe_provider import StripeProvider

        provider = StripeProvider(secret_key="sk_test_x", publishable_key="pk_test_x")
        order_id = uuid.uuid4()
        with mock.patch("stripe.Refund.create", return_value={"id": "re_1"}) as create:
            provider.refund(intent_id="pi_1", payment_id="", amount=D("12.50"), currency="USD", order_id=order_id)
        kwargs = create.call_args.kwargs
        self.assertEqual((kwargs["payment_intent"], kwargs["amount"]), ("pi_1", 1250))
        self.assertEqual(kwargs["idempotency_key"], f"refund:{order_id}")


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class CancelRouteTests(LedgerDatabase):
    def setUp(self) -> None:
        super().setUp()
        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.config.database import get_db
        from app.main import app
        from app.services.auth import get_current_user

        self.app, self.get_current_user = app, get_current_user
        app.dependency_overrides[get_db] = lambda: self.db
        self.addCleanup(app.dependency_overrides.clear)
        self.http = TestClient(app)
        self.prefix = get_settings().api_v1_prefix.rstrip("/")

    def as_user(self, user) -> None:
        self.app.dependency_overrides[self.get_current_user] = lambda: user

    def test_an_owner_cancels_and_reads_back_the_reason(self) -> None:
        order = self.make_order(status=OrderStatus.ACCEPTED)
        self.as_user(self.owner)
        response = self.http.post(f"{self.prefix}/orders/{order.id}/cancel",
                                  json={"reason": "CUSTOMER_REQUEST", "note": "Called the shop"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["status"], body["cancellation_reason"], body["cancellation_note"]),
                         ("CANCELLED", "CUSTOMER_REQUEST", "Called the shop"))
        self.assertEqual(body["refund_status"], "PENDING")
        self.assertFalse(body["can_be_cancelled"])

    def test_a_live_order_says_it_can_be_cancelled(self) -> None:
        order = self.make_order(status=OrderStatus.PREPARING)
        self.as_user(self.owner)
        body = self.http.get(f"{self.prefix}/orders/{order.id}").json()
        self.assertTrue(body["can_be_cancelled"])

    def test_a_refusal_says_why(self) -> None:
        order = self.make_order(status=OrderStatus.OUT_FOR_DELIVERY)
        self.as_user(self.owner)
        response = self.http.post(f"{self.prefix}/orders/{order.id}/cancel", json={"reason": "OUT_OF_STOCK"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("rider", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
