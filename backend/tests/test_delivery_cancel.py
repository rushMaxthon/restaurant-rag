"""Calling a rider off.

The fourth of Pidge's core calls, and the one this integration shipped
without: login, create and status were all here, and nothing could un-book a
rider once one was sent. Nothing needed to — every cancellation on this
platform is of an unpaid order, and an unpaid order is never dispatched — so
the gap was invisible. It stops being invisible the day somebody adds a
cancellation that can land after the kitchen has accepted.

Three ways this goes wrong, each pinned below:

**The wrong path.** Every other Pidge call is `/vendor/order/...`; cancel is
`/vendor/{id}/cancel`, with no `order` segment. Written by analogy it 404s,
and a 404 reads like "no such order" rather than "no such route".

**A row that lies.** Pidge refuses a cancel once the food is collected. If
that refusal were swallowed the admin would say CANCELLED while a rider was
on the way to a door.

**A rider sent home for an order that still stands.** The cancel is queued
from inside the transaction that cancels the order, and a transaction can
roll back. The task therefore re-reads the order and acts only if it really
is cancelled.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.enums import OrderCancellationReason, OrderStatus
from app.services.delivery import pidge_provider as pidge_module
from app.services.delivery import service
from app.services.delivery.base import DeliveryProvider, DeliveryProviderError, DeliveryState
from app.services.delivery.pidge_provider import PidgeProvider
from app.services.delivery.rehearsal_provider import RehearsalProvider


def a_pidge() -> PidgeProvider:
    provider = PidgeProvider(base_url="https://pidge.test", username="u", password="p")
    provider._token = "Bearer already-logged-in"
    return provider


def a_row(**over):
    fields = {
        "provider_order_id": "PIDGE-1",
        "state": DeliveryState.ASSIGNED.value,
        "provider_status": "out_for_pickup",
        "last_error": "",
    }
    fields.update(over)
    return SimpleNamespace(**fields)


class WhatPidgeIsAskedTests(unittest.TestCase):
    def test_the_path_has_no_order_segment(self) -> None:
        reply = mock.Mock(status_code=200)
        reply.json.return_value = {"data": "Order Cancelled"}
        with mock.patch.object(pidge_module.httpx, "request", return_value=reply) as call:
            a_pidge().cancel("PIDGE-1")
        method, url = call.call_args.args[:2]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://pidge.test/v1.0/store/channel/vendor/PIDGE-1/cancel")

    def test_too_late_is_a_refusal_that_is_not_retried(self) -> None:
        # Their own example: 400 once a rider has the food. Asking again will
        # not put it back in the kitchen.
        reply = mock.Mock(
            status_code=400,
            text='{"error":{"code":"order.action.cancel.not-allowed"}}',
        )
        with mock.patch.object(pidge_module.httpx, "request", return_value=reply):
            with self.assertRaises(DeliveryProviderError) as caught:
                a_pidge().cancel("PIDGE-1")
        self.assertFalse(caught.exception.retryable)
        self.assertIn("cancel.not-allowed", str(caught.exception))

    def test_their_outage_is_worth_another_go(self) -> None:
        reply = mock.Mock(status_code=502, text="bad gateway")
        with mock.patch.object(pidge_module.httpx, "request", return_value=reply):
            with self.assertRaises(DeliveryProviderError) as caught:
                a_pidge().cancel("PIDGE-1")
        self.assertTrue(caught.exception.retryable)

    def test_nothing_is_sent_for_a_delivery_with_no_id(self) -> None:
        # An empty id would POST to `/vendor//cancel`.
        with mock.patch.object(pidge_module.httpx, "request") as call:
            with self.assertRaises(DeliveryProviderError):
                a_pidge().cancel("")
        call.assert_not_called()

    def test_every_courier_can_be_called_off(self) -> None:
        # The protocol is runtime-checkable precisely so a provider that
        # forgot a method fails here rather than on the first cancelled order.
        self.assertIsInstance(a_pidge(), DeliveryProvider)
        self.assertIsInstance(RehearsalProvider(), DeliveryProvider)
        RehearsalProvider().cancel("REHEARSAL-anything")


class WhatTheRowSaysAfterwardsTests(unittest.TestCase):
    def cancel(self, row, provider):
        db = mock.Mock()
        db.scalar.return_value = row
        order = SimpleNamespace(id=uuid.uuid4())
        with mock.patch.object(service, "delivery_provider", return_value=provider):
            return service.cancel(db, order)

    def test_an_accepted_cancel_ends_the_delivery(self) -> None:
        row, provider = a_row(last_error="an old complaint"), mock.Mock()
        self.assertIs(self.cancel(row, provider), row)
        provider.cancel.assert_called_once_with("PIDGE-1")
        self.assertEqual(row.state, DeliveryState.CANCELLED.value)
        self.assertEqual(row.last_error, "")

    def test_a_refused_cancel_leaves_the_row_telling_the_truth(self) -> None:
        row, provider = a_row(state=DeliveryState.PICKED_UP.value), mock.Mock()
        provider.cancel.side_effect = DeliveryProviderError("too late", retryable=False)
        with self.assertRaises(DeliveryProviderError):
            self.cancel(row, provider)
        self.assertEqual(row.state, DeliveryState.PICKED_UP.value, "the rider still has it")
        self.assertEqual(row.last_error, "too late")

    def test_an_order_nobody_was_sent_for_calls_nobody(self) -> None:
        provider = mock.Mock()
        self.assertIsNone(self.cancel(None, provider))
        self.assertIsNone(self.cancel(a_row(provider_order_id=""), provider))
        provider.cancel.assert_not_called()

    def test_a_finished_delivery_is_left_alone(self) -> None:
        # Idempotent: a retried task must not ask Pidge to cancel something it
        # already cancelled, which they answer with a 400.
        for state in (DeliveryState.CANCELLED, DeliveryState.DELIVERED, DeliveryState.FAILED):
            with self.subTest(state=state):
                row, provider = a_row(state=state.value), mock.Mock()
                self.assertIs(self.cancel(row, provider), row)
                provider.cancel.assert_not_called()
                self.assertEqual(row.state, state.value)

    def test_the_dispatch_flag_does_not_gate_calling_a_rider_off(self) -> None:
        # The flag stops riders being BOOKED. Turned off after one was sent,
        # it must not also stop them being recalled.
        row, provider = a_row(), mock.Mock()
        with mock.patch.object(service, "should_dispatch", return_value=False):
            self.cancel(row, provider)
        provider.cancel.assert_called_once()


class OnlyACancelledOrderLosesItsRiderTests(unittest.TestCase):
    def run_task(self, order):
        from app.tasks import delivery as task

        class FakeSession:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def get(self_inner, model, key):
                return order

            def commit(self_inner):
                pass

        with mock.patch.object(task, "SessionLocal", FakeSession):
            with mock.patch.object(task, "cancel") as cancel:
                cancel.return_value = a_row(state=DeliveryState.CANCELLED.value)
                result = task.cancel_order_delivery_task.run(str(uuid.uuid4()))
        return result, cancel

    def test_a_cancelled_order_has_its_rider_called_off(self) -> None:
        result, cancel = self.run_task(SimpleNamespace(status=OrderStatus.CANCELLED))
        cancel.assert_called_once()
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["provider_order_id"], "PIDGE-1")

    def test_an_order_that_still_stands_keeps_its_rider(self) -> None:
        # The rollback case: the cancel was queued, the cancellation was not
        # committed.
        for status in (OrderStatus.ACCEPTED, OrderStatus.PREPARING, OrderStatus.OUT_FOR_DELIVERY):
            with self.subTest(status=status):
                result, cancel = self.run_task(SimpleNamespace(status=status))
                cancel.assert_not_called()
                self.assertEqual(result["status"], "skipped")

    def test_an_order_that_does_not_exist_is_not_an_error(self) -> None:
        result, cancel = self.run_task(None)
        cancel.assert_not_called()
        self.assertEqual(result["status"], "missing")


class CancellingAnOrderRemembersItsRiderTests(unittest.TestCase):
    def cancel_order(self, delivery):
        from app.services import order_events

        order = SimpleNamespace(
            id=uuid.uuid4(),
            status=OrderStatus.ACCEPTED,
            delivery=delivery,
            cancellation_reason=None,
            cancelled_by=None,
            cancelled_at=None,
        )
        db = mock.Mock()
        with mock.patch.object(order_events, "record_order_status_event"):
            with mock.patch.object(order_events.event, "listen") as listen:
                order_events.mark_order_cancelled(
                    db, order=order, reason=OrderCancellationReason.PAYMENT_FAILED
                )
        return order, db, listen

    def test_a_dispatched_order_queues_the_cancel_for_after_the_commit(self) -> None:
        order, db, listen = self.cancel_order(a_row())
        listen.assert_called_once()
        target, name, send = listen.call_args.args
        self.assertIs(target, db)
        self.assertEqual(name, "after_commit")
        self.assertTrue(listen.call_args.kwargs.get("once"))

        with mock.patch("app.config.celery.celery_app.send_task") as send_task:
            send(db)
        send_task.assert_called_once_with(
            "app.tasks.delivery.cancel_order_delivery_task",
            kwargs={"order_id": str(order.id)},
        )

    def test_an_order_with_no_rider_queues_nothing(self) -> None:
        # Every cancellation that exists today: unpaid, so never dispatched.
        for delivery in (None, a_row(provider_order_id="")):
            with self.subTest(delivery=delivery):
                _, _, listen = self.cancel_order(delivery)
                listen.assert_not_called()

    def test_a_broker_that_is_down_does_not_undo_the_cancellation(self) -> None:
        _, db, listen = self.cancel_order(a_row())
        send = listen.call_args.args[2]
        with mock.patch("app.config.celery.celery_app.send_task", side_effect=RuntimeError("down")):
            send(db)  # must not raise: this runs inside the session's commit


if __name__ == "__main__":
    unittest.main()
