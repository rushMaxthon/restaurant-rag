"""Payment flow tests: COD, card intents, webhooks, and the reaper.

These use in-memory fakes rather than a database or a Stripe account, matching
the style of the other test modules in this package.
"""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401  (imported first to settle import order)
from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.models.order import Order
from app.models.payment import PaymentTransaction
from app.models.user import User
from app.services.payments import base as payments_base
from app.services.payments import service as payments_service
from app.services.payments.registry import (
    SUPPORTED_PAYMENT_METHODS,
    available_payment_methods,
    is_method_supported,
    provider_name_for,
    resolve_provider,
)
from app.services.payments.stripe_provider import (
    StripeProvider,
    from_minor_units,
    to_minor_units,
)
from fastapi import HTTPException


# --- fakes -----------------------------------------------------------------


class FakeProvider:
    """Stands in for Stripe. Records calls, returns canned intents."""

    name = "stripe"

    def __init__(self, *, configured: bool = True) -> None:
        self._configured = configured
        self.created: list[dict] = []
        self.cancelled: list[str] = []
        self.retrieve_result: payments_base.PaymentIntentResult | None = None

    def is_configured(self) -> bool:
        return self._configured

    def create_intent(self, **kwargs) -> payments_base.PaymentIntentResult:
        self.created.append(kwargs)
        return payments_base.PaymentIntentResult(
            intent_id=f"pi_test_{len(self.created)}",
            client_secret=f"pi_test_{len(self.created)}_secret",
            amount=kwargs["amount"],
            currency=kwargs["currency"],
            status="requires_payment_method",
        )

    def retrieve_intent(self, intent_id: str) -> payments_base.PaymentIntentResult:
        if self.retrieve_result is None:
            raise payments_base.PaymentProviderError("not found")
        return self.retrieve_result

    def cancel_intent(self, intent_id: str) -> None:
        self.cancelled.append(intent_id)

    def parse_webhook(self, *, payload: bytes, signature: str | None):  # pragma: no cover
        raise NotImplementedError


class FakeSession:
    """Minimal Session: holds orders and transactions in lists."""

    def __init__(self, orders=None, transactions=None) -> None:
        self.orders = list(orders or [])
        self.transactions = list(transactions or [])
        self.webhook_events: list = []
        self.commits = 0
        self.duplicate_event_ids: set[str] = set()

    # -- SQLAlchemy-ish surface used by the payment service ------------------

    def add(self, obj) -> None:
        if isinstance(obj, PaymentTransaction) and obj not in self.transactions:
            self.transactions.append(obj)

    def add_all(self, objs) -> None:
        for obj in objs:
            self.add(obj)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def get(self, model, key):
        if model is Order:
            return next((order for order in self.orders if order.id == key), None)
        if model is User:
            return None
        return None

    def scalar(self, statement):
        return _FakeQueryResolver(self).scalar(statement)

    def scalars(self, statement):
        return _FakeQueryResolver(self).scalars(statement)


class _FakeQueryResolver:
    """Interprets the few select() shapes the payment service builds."""

    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def _entity(self, statement) -> str:
        return str(statement).split("FROM ")[-1].split()[0] if "FROM" in str(statement) else ""

    def scalar(self, statement):
        text = str(statement)
        if "payment_transactions" in text:
            matches = self._transactions(text)
            return matches[0] if matches else None
        if "payment_webhook_events" in text:
            return self.session.webhook_events[0] if self.session.webhook_events else None
        if "orders" in text:
            matches = self.session.orders
            return matches[0] if matches else None
        return None

    def scalars(self, statement):
        text = str(statement)
        if "payment_transactions" in text:
            return list(self._transactions(text))
        if "orders" in text:
            return list(self.session.orders)
        return []

    def _transactions(self, text: str):
        rows = self.session.transactions
        # Newest first, matching the service's ORDER BY created_at DESC.
        return sorted(rows, key=lambda row: row.created_at, reverse=True)


def make_order(
    *,
    payment_method: PaymentMethod = PaymentMethod.CARD,
    payment_status: PaymentStatus = PaymentStatus.PENDING,
    order_status: OrderStatus = OrderStatus.PAYMENT_PENDING,
    total: str = "250.00",
    placed_at: datetime | None = None,
) -> Order:
    order = Order(
        id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        restaurant_location_id=uuid.uuid4(),
        status=order_status,
        payment_status=payment_status,
        payment_method=payment_method,
        payment_provider="stripe" if payment_method == PaymentMethod.CARD else "cod",
        subtotal=Decimal(total),
        delivery_fee=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        total_amount=Decimal(total),
        currency="INR",
        delivery_address="1 Test Street",
    )
    order.payment_reference = None
    order.placed_at = placed_at or datetime.now(UTC)
    # Deliberately NOT setting app_client_id / order_number: those columns exist
    # in the database but are not mapped on the model, and setting them here
    # once hid an AttributeError that only surfaced against a real order.
    return order


def make_customer(order: Order) -> User:
    return User(
        id=order.customer_id,
        full_name="Pay Tester",
        email="pay-tester@example.com",
        phone_number=None,
        hashed_password="hash",
        role="CUSTOMER",
        is_active=True,
        is_verified=True,
        default_address=None,
    )


def make_transaction(
    order: Order,
    *,
    intent_id: str = "pi_test_1",
    status: PaymentStatus = PaymentStatus.PENDING,
) -> PaymentTransaction:
    transaction = PaymentTransaction(
        id=uuid.uuid4(),
        order_id=order.id,
        provider="stripe",
        provider_intent_id=intent_id,
        status=status,
        amount=order.total_amount,
        currency=order.currency,
    )
    transaction.created_at = datetime.now(UTC)
    return transaction


def make_event(
    event_type: str,
    *,
    intent_id: str = "pi_test_1",
    amount: Decimal | None = Decimal("250.00"),
    event_id: str = "evt_test_1",
) -> payments_base.WebhookEvent:
    return payments_base.WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        intent_id=intent_id,
        amount=amount,
        currency="INR",
        payload={"id": event_id, "type": event_type},
    )


# --- registry --------------------------------------------------------------


class PaymentRegistryTests(unittest.TestCase):
    def test_only_card_and_cod_are_supported(self) -> None:
        self.assertEqual(
            SUPPORTED_PAYMENT_METHODS,
            frozenset({PaymentMethod.CARD, PaymentMethod.COD}),
        )
        self.assertTrue(is_method_supported(PaymentMethod.CARD))
        self.assertTrue(is_method_supported(PaymentMethod.COD))
        self.assertFalse(is_method_supported(PaymentMethod.GOOGLE_PAY))
        self.assertFalse(is_method_supported(PaymentMethod.RAZORPAY))

    def test_cod_resolves_to_no_provider(self) -> None:
        self.assertIsNone(resolve_provider(PaymentMethod.COD))
        self.assertEqual(provider_name_for(PaymentMethod.COD), "cod")
        self.assertEqual(provider_name_for(PaymentMethod.CARD), "stripe")

    def test_unsupported_method_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_provider(PaymentMethod.RAZORPAY)

    def test_card_drops_out_when_stripe_is_unconfigured(self) -> None:
        with patch(
            "app.services.payments.registry.get_stripe_provider",
            return_value=FakeProvider(configured=False),
        ):
            self.assertEqual(available_payment_methods(), [PaymentMethod.COD])
        with patch(
            "app.services.payments.registry.get_stripe_provider",
            return_value=FakeProvider(configured=True),
        ):
            self.assertEqual(
                available_payment_methods(),
                [PaymentMethod.CARD, PaymentMethod.COD],
            )


class StripeAmountConversionTests(unittest.TestCase):
    def test_two_decimal_currency_round_trips(self) -> None:
        self.assertEqual(to_minor_units(Decimal("13.84"), "inr"), 1384)
        self.assertEqual(from_minor_units(1384, "inr"), Decimal("13.84"))

    def test_zero_decimal_currency_is_not_multiplied(self) -> None:
        self.assertEqual(to_minor_units(Decimal("500"), "jpy"), 500)
        self.assertEqual(from_minor_units(500, "jpy"), Decimal("500"))

    def test_rounding_is_half_up(self) -> None:
        self.assertEqual(to_minor_units(Decimal("0.005"), "inr"), 1)


# --- intent creation -------------------------------------------------------


class CreatePaymentIntentTests(unittest.TestCase):
    def test_amount_comes_from_the_order_not_the_caller(self) -> None:
        order = make_order(total="412.50")
        session = FakeSession(orders=[order])
        provider = FakeProvider()

        with patch.object(payments_service, "resolve_provider", return_value=provider):
            result = payments_service.create_payment_intent(
                session, make_customer(order), order.id
            )

        self.assertEqual(provider.created[0]["amount"], Decimal("412.50"))
        self.assertEqual(result.amount, Decimal("412.50"))
        self.assertEqual(order.payment_reference, result.payment_intent_id)
        self.assertEqual(len(session.transactions), 1)
        self.assertEqual(session.transactions[0].status, PaymentStatus.PENDING)

    def test_idempotency_key_is_per_attempt(self) -> None:
        order = make_order()
        existing = make_transaction(order, status=PaymentStatus.FAILED)
        session = FakeSession(orders=[order], transactions=[existing])
        order.payment_status = PaymentStatus.FAILED
        provider = FakeProvider()

        with patch.object(payments_service, "resolve_provider", return_value=provider):
            payments_service.create_payment_intent(session, make_customer(order), order.id)

        self.assertEqual(
            provider.created[0]["idempotency_key"], f"order:{order.id}:attempt:2"
        )

    def test_reusable_intent_is_not_duplicated(self) -> None:
        order = make_order()
        existing = make_transaction(order)
        session = FakeSession(orders=[order], transactions=[existing])
        provider = FakeProvider()
        provider.retrieve_result = payments_base.PaymentIntentResult(
            intent_id=existing.provider_intent_id,
            client_secret="pi_test_1_secret",
            amount=order.total_amount,
            currency=order.currency,
            status="requires_payment_method",
        )

        with patch.object(payments_service, "resolve_provider", return_value=provider):
            result = payments_service.create_payment_intent(
                session, make_customer(order), order.id
            )

        self.assertEqual(result.payment_intent_id, existing.provider_intent_id)
        self.assertEqual(provider.created, [])
        self.assertEqual(len(session.transactions), 1)

    def test_paid_order_cannot_be_paid_again(self) -> None:
        order = make_order(payment_status=PaymentStatus.PAID, order_status=OrderStatus.PLACED)
        session = FakeSession(orders=[order])

        with patch.object(payments_service, "resolve_provider", return_value=FakeProvider()):
            with self.assertRaises(HTTPException) as ctx:
                payments_service.create_payment_intent(session, make_customer(order), order.id)

        self.assertEqual(ctx.exception.status_code, 409)

    def test_cod_order_cannot_create_an_intent(self) -> None:
        order = make_order(
            payment_method=PaymentMethod.COD,
            payment_status=PaymentStatus.COD,
            order_status=OrderStatus.PLACED,
        )
        session = FakeSession(orders=[order])

        with self.assertRaises(HTTPException) as ctx:
            payments_service.create_payment_intent(session, make_customer(order), order.id)

        self.assertEqual(ctx.exception.status_code, 400)

    def test_branded_app_cannot_pay_another_restaurants_order(self) -> None:
        order = make_order()
        session = FakeSession(orders=[order])

        with patch.object(payments_service, "resolve_provider", return_value=FakeProvider()):
            with self.assertRaises(HTTPException) as ctx:
                payments_service.create_payment_intent(
                    session,
                    make_customer(order),
                    order.id,
                    app_scope_restaurant_id=uuid.uuid4(),
                )

        # 404, not 403: a branded build must not learn that the order exists.
        self.assertEqual(ctx.exception.status_code, 404)

    def test_unconfigured_stripe_is_unavailable_not_a_crash(self) -> None:
        order = make_order()
        session = FakeSession(orders=[order])

        with patch.object(
            payments_service, "resolve_provider", return_value=FakeProvider(configured=False)
        ):
            with self.assertRaises(HTTPException) as ctx:
                payments_service.create_payment_intent(session, make_customer(order), order.id)

        self.assertEqual(ctx.exception.status_code, 503)


# --- cancellation ----------------------------------------------------------


class CancelPaymentTests(unittest.TestCase):
    def test_cancel_marks_attempt_and_order_cancelled(self) -> None:
        order = make_order()
        transaction = make_transaction(order)
        session = FakeSession(orders=[order], transactions=[transaction])
        provider = FakeProvider()

        with patch.object(payments_service, "resolve_provider", return_value=provider):
            payments_service.cancel_payment(session, make_customer(order), order.id)

        self.assertEqual(order.payment_status, PaymentStatus.CANCELLED)
        # The order itself survives so it stays retryable.
        self.assertEqual(order.status, OrderStatus.PAYMENT_PENDING)
        self.assertEqual(transaction.status, PaymentStatus.CANCELLED)
        self.assertEqual(provider.cancelled, [transaction.provider_intent_id])

    def test_cancel_never_unpays_a_paid_order(self) -> None:
        order = make_order(payment_status=PaymentStatus.PAID, order_status=OrderStatus.PLACED)
        transaction = make_transaction(order, status=PaymentStatus.PAID)
        session = FakeSession(orders=[order], transactions=[transaction])

        payments_service.cancel_payment(session, make_customer(order), order.id)

        self.assertEqual(order.payment_status, PaymentStatus.PAID)
        self.assertEqual(order.status, OrderStatus.PLACED)


# --- webhooks --------------------------------------------------------------


class WebhookTests(unittest.TestCase):
    def _handle(self, session: FakeSession, event: payments_base.WebhookEvent, *, duplicate=False):
        provider = FakeProvider()
        provider.parse_webhook = lambda **_: event  # type: ignore[assignment]
        with patch.object(payments_service, "get_stripe_provider", return_value=provider), patch.object(
            payments_service, "_record_webhook_event", return_value=not duplicate
        ), patch("app.services.orders.run_order_placed_side_effects") as side_effects:
            result = payments_service.handle_stripe_webhook(
                session, payload=b"{}", signature="sig"
            )
        return result, side_effects

    def test_succeeded_marks_paid_and_releases_order_to_the_kitchen(self) -> None:
        order = make_order()
        transaction = make_transaction(order)
        session = FakeSession(orders=[order], transactions=[transaction])

        result, side_effects = self._handle(session, make_event("payment_intent.succeeded"))

        self.assertEqual(result["status"], "paid")
        self.assertEqual(order.payment_status, PaymentStatus.PAID)
        self.assertEqual(order.status, OrderStatus.PLACED)
        self.assertEqual(order.payment_reference, transaction.provider_intent_id)
        self.assertEqual(transaction.status, PaymentStatus.PAID)

    def test_underpayment_is_refused(self) -> None:
        order = make_order(total="250.00")
        transaction = make_transaction(order)
        session = FakeSession(orders=[order], transactions=[transaction])

        self._handle(
            session,
            make_event("payment_intent.succeeded", amount=Decimal("1.00")),
        )

        self.assertEqual(order.payment_status, PaymentStatus.FAILED)
        self.assertEqual(order.status, OrderStatus.PAYMENT_PENDING)
        self.assertEqual(transaction.failure_code, "amount_mismatch")

    def test_failure_keeps_order_retryable(self) -> None:
        order = make_order()
        transaction = make_transaction(order)
        session = FakeSession(orders=[order], transactions=[transaction])

        self._handle(session, make_event("payment_intent.payment_failed"))

        self.assertEqual(order.payment_status, PaymentStatus.FAILED)
        self.assertEqual(order.status, OrderStatus.PAYMENT_PENDING)

    def test_late_failure_does_not_unpay_a_paid_order(self) -> None:
        order = make_order(payment_status=PaymentStatus.PAID, order_status=OrderStatus.PLACED)
        transaction = make_transaction(order, status=PaymentStatus.PAID)
        session = FakeSession(orders=[order], transactions=[transaction])

        self._handle(session, make_event("payment_intent.payment_failed"))

        self.assertEqual(order.payment_status, PaymentStatus.PAID)
        self.assertEqual(order.status, OrderStatus.PLACED)

    def test_duplicate_event_is_a_no_op(self) -> None:
        order = make_order()
        transaction = make_transaction(order)
        session = FakeSession(orders=[order], transactions=[transaction])

        result, _ = self._handle(
            session, make_event("payment_intent.succeeded"), duplicate=True
        )

        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(order.payment_status, PaymentStatus.PENDING)

    def test_refund_marks_order_refunded(self) -> None:
        order = make_order(payment_status=PaymentStatus.PAID, order_status=OrderStatus.PLACED)
        transaction = make_transaction(order, status=PaymentStatus.PAID)
        session = FakeSession(orders=[order], transactions=[transaction])

        self._handle(session, make_event("charge.refunded"))

        self.assertEqual(order.payment_status, PaymentStatus.REFUNDED)

    def test_bad_signature_is_rejected(self) -> None:
        session = FakeSession()
        provider = FakeProvider()

        def _raise(**_):
            raise payments_base.WebhookVerificationError()

        provider.parse_webhook = _raise  # type: ignore[assignment]
        with patch.object(payments_service, "get_stripe_provider", return_value=provider):
            with self.assertRaises(HTTPException) as ctx:
                payments_service.handle_stripe_webhook(session, payload=b"{}", signature="bad")

        self.assertEqual(ctx.exception.status_code, 400)


class StripeSignatureVerificationTests(unittest.TestCase):
    def test_tampered_payload_fails_verification(self) -> None:
        provider = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_test")
        with self.assertRaises(payments_base.WebhookVerificationError):
            provider.parse_webhook(payload=json.dumps({"id": "evt_1"}).encode(), signature="t=1,v1=deadbeef")

    def test_missing_secret_refuses_to_verify(self) -> None:
        provider = StripeProvider(secret_key="sk_test_x", webhook_secret="")
        with self.assertRaises(payments_base.WebhookVerificationError):
            provider.parse_webhook(payload=b"{}", signature="t=1,v1=x")

    def test_missing_signature_header_is_rejected(self) -> None:
        provider = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_test")
        with self.assertRaises(payments_base.WebhookVerificationError):
            provider.parse_webhook(payload=b"{}", signature=None)


# --- reaper ----------------------------------------------------------------


class ReaperTests(unittest.TestCase):
    def test_expired_unpaid_order_is_cancelled(self) -> None:
        order = make_order(placed_at=datetime.now(UTC) - timedelta(hours=2))
        transaction = make_transaction(order)
        session = FakeSession(orders=[order], transactions=[transaction])
        provider = FakeProvider()

        with patch.object(payments_service, "resolve_provider", return_value=provider):
            cancelled = payments_service.reap_expired_unpaid_orders(session)

        self.assertEqual(cancelled, 1)
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(order.payment_status, PaymentStatus.CANCELLED)
        self.assertEqual(provider.cancelled, [transaction.provider_intent_id])

    def test_paid_order_is_never_reaped(self) -> None:
        order = make_order(
            payment_status=PaymentStatus.PAID,
            placed_at=datetime.now(UTC) - timedelta(hours=2),
        )
        session = FakeSession(orders=[order], transactions=[])

        with patch.object(payments_service, "resolve_provider", return_value=FakeProvider()):
            cancelled = payments_service.reap_expired_unpaid_orders(session)

        self.assertEqual(cancelled, 0)
        self.assertEqual(order.payment_status, PaymentStatus.PAID)


# --- order service wiring --------------------------------------------------


class OrderPaymentWiringTests(unittest.TestCase):
    def test_settled_statuses_exclude_pending(self) -> None:
        from app.services.orders import SETTLED_PAYMENT_STATUSES

        self.assertIn(PaymentStatus.PAID, SETTLED_PAYMENT_STATUSES)
        self.assertIn(PaymentStatus.COD, SETTLED_PAYMENT_STATUSES)
        self.assertNotIn(PaymentStatus.PENDING, SETTLED_PAYMENT_STATUSES)
        self.assertNotIn(PaymentStatus.FAILED, SETTLED_PAYMENT_STATUSES)

    def test_payment_pending_has_no_forward_transition(self) -> None:
        from app.services.orders import ORDER_STATUS_FLOW

        self.assertNotIn(OrderStatus.PAYMENT_PENDING, ORDER_STATUS_FLOW)
        self.assertNotIn(OrderStatus.CANCELLED, ORDER_STATUS_FLOW)

    def test_unpaid_order_cannot_be_advanced_by_the_restaurant(self) -> None:
        from app.services import orders as order_service

        order = make_order()
        session = SimpleNamespace(scalar=lambda *_: order)

        with self.assertRaises(HTTPException) as ctx:
            order_service.update_order_status(
                session,
                make_customer(order),
                order_id=order.id,
                new_status=OrderStatus.ACCEPTED,
                owner_restaurant_id=order.restaurant_id,
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not been paid", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
