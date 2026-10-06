"""Turning an order into a courier job, and a courier's answer back into a row.

Three things here can cost real money, and each has a test that fails loudly:

**A second rider.** A retried task must not dispatch twice. The unique
constraint on `order_deliveries.order_id` is the guarantee; `dispatch`
checking first is the fast path.

**A rider asking for money that was already paid.** `cod_amount` must be zero
for a card order and the total only for a COD one. Getting this backwards
means a customer is asked to pay twice at their own door.

**An order dragged backwards.** Courier status pushes arrive late and out of
order. A stale IN_TRANSIT landing after DELIVERED must not put a finished
order back on the road.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.models.enums import OrderFulfillmentType, OrderStatus, PaymentMethod
from app.services.delivery.base import DeliveryState
from app.services.delivery.service import advance_order, build_request, should_dispatch


def a_location(**over):
    fields = {
        "address_line_1": "Commerce Avenue, C.G. Road",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "postal_code": "380006",
        "branch_name": "Dragon Wok CG Road",
        "phone_number": "9876500000",
        "latitude": Decimal("23.0225"),
        "longitude": Decimal("72.5714"),
    }
    fields.update(over)
    return SimpleNamespace(**fields)


def an_order(**over):
    fields = {
        "id": uuid.uuid4(),
        "status": OrderStatus.ACCEPTED,
        "fulfillment_type": OrderFulfillmentType.DELIVERY,
        "payment_method": PaymentMethod.CARD,
        "delivery_address": "102 Demo Street, Ahmedabad, Gujarat, 380015",
        "contact_name": "Test Customer",
        "contact_phone": "9876511111",
        "special_instructions": "",
        "total_amount": Decimal("23.57"),
        "currency": "INR",
        "scheduled_at": None,
        "restaurant_location": a_location(),
        "items": [
            SimpleNamespace(
                item_name_snapshot="Chicken Hakka Noodles",
                quantity=1,
                unit_price=Decimal("12.00"),
                menu_item_id=uuid.uuid4(),
            )
        ],
    }
    fields.update(over)
    return SimpleNamespace(**fields)


# The environment `should_dispatch` is asked to answer in.
#
# Both entries are part of the answer, so these tests state them rather than
# inherit them. The flag was always pinned; the courier HOST was not, and that
# cost a real debugging round. Live Pidge credentials were put into
# `backend/.env` on 2026-10-03 to test production dispatch, and three subtests
# here started failing — `live_dispatch_blocked_reason()` was refusing to book
# a rider from a local environment pointed at a production host, which is
# precisely its job. The suite went red because of an untracked file, and the
# interlock looked like the bug when it was the only thing behaving correctly.
#
# The interlock itself is tested in `test_delivery_live_interlock.py`, where
# the host is the subject rather than a precondition.
DISPATCH_ENABLED_LOCALLY = {
    "ENABLE_DELIVERY_DISPATCH": "true",
    "PIDGE_BASE_URL": "https://store.dev.pidge.in",
}


class WhichOrdersGoToACourierTests(unittest.TestCase):
    """`should_dispatch` is the last gate before real money is spent.

    Every test here runs with `ENABLE_DELIVERY_DISPATCH` on, because that is
    now part of the answer rather than a condition checked somewhere else.
    The flag used to be enforced by the registry refusing to build a courier
    at all; once a checkout needed to quote a fee WITHOUT booking riders, that
    could no longer be the guard, so it moved onto the function that decides
    to book one.
    """

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, DISPATCH_ENABLED_LOCALLY)
        patcher.start()
        self.addCleanup(patcher.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)

    def test_the_flag_being_off_dispatches_nobody(self) -> None:
        # Not a UI guard and not the caller's job: a retry, a replay or a
        # console call reaching the task directly must still book no rider.
        with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_DISPATCH": "false"}):
            get_settings.cache_clear()
            self.assertFalse(should_dispatch(an_order()))

    def test_a_delivery_order_in_flight_does(self) -> None:
        for status in (OrderStatus.PLACED, OrderStatus.ACCEPTED, OrderStatus.PREPARING):
            with self.subTest(status=status):
                self.assertTrue(should_dispatch(an_order(status=status)))

    def test_a_pickup_order_never_does(self) -> None:
        self.assertFalse(
            should_dispatch(an_order(fulfillment_type=OrderFulfillmentType.PICKUP))
        )

    def test_a_finished_or_unpaid_order_does_not(self) -> None:
        # DELIVERED and CANCELLED are over; PAYMENT_PENDING has not been paid
        # for, and the kitchen has not even seen it.
        for status in (
            OrderStatus.DELIVERED,
            OrderStatus.CANCELLED,
            OrderStatus.PAYMENT_PENDING,
        ):
            with self.subTest(status=status):
                self.assertFalse(should_dispatch(an_order(status=status)))


class WhatTheCourierIsToldTests(unittest.TestCase):
    def test_a_card_order_asks_the_rider_for_nothing(self) -> None:
        # The money is already taken. A non-zero cod_amount here has a rider
        # demanding payment at the door for an order that is paid for.
        request = build_request(an_order(payment_method=PaymentMethod.CARD))
        self.assertEqual(request.cod_amount, Decimal("0"))

    def test_a_cod_order_asks_for_the_total(self) -> None:
        request = build_request(
            an_order(payment_method=PaymentMethod.COD, total_amount=Decimal("450.00"))
        )
        self.assertEqual(request.cod_amount, Decimal("450.00"))

    def test_the_pincode_is_read_out_of_the_address_we_store(self) -> None:
        # One free-text block in, four fields out. The pincode is what a
        # courier routes on.
        request = build_request(an_order())
        self.assertEqual(request.drop.pincode, "380015")

    def test_an_address_with_no_pincode_falls_back_to_the_branch(self) -> None:
        # A courier refuses an order with no pincode at all, and the branch's
        # own is nearer than nothing.
        request = build_request(an_order(delivery_address="Somewhere with no code"))
        self.assertEqual(request.drop.pincode, "380006")

    def test_the_order_id_is_the_reference_both_ways(self) -> None:
        order = an_order()
        self.assertEqual(build_request(order).reference, str(order.id))

    def test_the_restaurant_is_the_pickup(self) -> None:
        request = build_request(an_order())
        self.assertEqual(request.pickup.address_line_1, "Commerce Avenue, C.G. Road")
        self.assertEqual(request.pickup.pincode, "380006")
        self.assertEqual(request.pickup.latitude, 23.0225)

    def test_every_item_is_named_for_the_courier(self) -> None:
        request = build_request(an_order())
        self.assertEqual([i.name for i in request.items], ["Chicken Hakka Noodles"])


class ACourierMayNotRewindAnOrderTests(unittest.TestCase):
    def test_in_transit_puts_the_order_on_the_road(self) -> None:
        order = an_order(status=OrderStatus.PREPARING)
        self.assertTrue(advance_order(order, DeliveryState.IN_TRANSIT))
        self.assertEqual(order.status, OrderStatus.OUT_FOR_DELIVERY)

    def test_delivered_finishes_it(self) -> None:
        order = an_order(status=OrderStatus.OUT_FOR_DELIVERY)
        self.assertTrue(advance_order(order, DeliveryState.DELIVERED))
        self.assertEqual(order.status, OrderStatus.DELIVERED)

    def test_a_late_update_cannot_undo_a_delivered_order(self) -> None:
        # The failure this exists for: pushes arrive out of order, and a
        # customer told their delivered dinner is on its way has been lied to.
        order = an_order(status=OrderStatus.DELIVERED)
        self.assertFalse(advance_order(order, DeliveryState.IN_TRANSIT))
        self.assertEqual(order.status, OrderStatus.DELIVERED)

    def test_a_failed_delivery_moves_nothing(self) -> None:
        # The food was cooked and came back. That is neither cancelled nor
        # delivered, and who pays for it is not a decision for a status
        # machine — so the order is left exactly where it was.
        order = an_order(status=OrderStatus.OUT_FOR_DELIVERY)
        self.assertFalse(advance_order(order, DeliveryState.FAILED))
        self.assertEqual(order.status, OrderStatus.OUT_FOR_DELIVERY)

    def test_a_cancelled_order_is_never_revived(self) -> None:
        order = an_order(status=OrderStatus.CANCELLED)
        self.assertFalse(advance_order(order, DeliveryState.DELIVERED))
        self.assertEqual(order.status, OrderStatus.CANCELLED)

    def test_the_early_states_move_nothing(self) -> None:
        # A rider being assigned is not the order leaving the kitchen.
        for state in (DeliveryState.PENDING, DeliveryState.ASSIGNED):
            with self.subTest(state=state):
                order = an_order(status=OrderStatus.ACCEPTED)
                self.assertFalse(advance_order(order, state))
                self.assertEqual(order.status, OrderStatus.ACCEPTED)

    def test_picked_up_is_the_food_leaving_the_kitchen(self) -> None:
        # It used to wait for IN_TRANSIT. Pidge sends PICKED_UP and then
        # OUT_FOR_DELIVERY seconds apart, and when the second push was lost the
        # order sat in the kitchen column while a rider rode it across town.
        order = an_order(status=OrderStatus.PREPARING)
        self.assertTrue(advance_order(order, DeliveryState.PICKED_UP))
        self.assertEqual(order.status, OrderStatus.OUT_FOR_DELIVERY)


if __name__ == "__main__":
    unittest.main()


class PullingTheStatusRatherThanWaitingForIt(unittest.TestCase):
    """The sweep that keeps the admin honest without a webhook.

    Pidge offers no API to register a push URL — it is configured on their
    side — so a deployment that has not arranged that yet would show every
    rider as PENDING forever. And even once it is arranged, a push that is
    dropped, retried into a closed port, or sent while this service restarts is
    simply lost, with nothing to correct it.

    So the status is PULLED on a schedule and pushed as a bonus. Both paths go
    through the same `record`, so a delivery's state changes one way however the
    news arrived.
    """

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, DISPATCH_ENABLED_LOCALLY)
        patcher.start()
        self.addCleanup(patcher.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)

    def test_only_unfinished_deliveries_are_asked_about(self) -> None:
        # A terminal delivery cannot change. Re-asking forever would turn a
        # fixed cost into one that grows with every order ever completed.
        from app.tasks import delivery as task

        captured: dict[str, object] = {}

        class FakeQuery:
            def where(self, clause):
                captured.setdefault("clauses", []).append(str(clause))
                return self

            def limit(self, n):
                return self

        class FakeSession:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def scalars(self_inner, q):
                return SimpleNamespace(all=lambda: [])

            def commit(self_inner):
                pass

        with mock.patch.object(task, "delivery_provider", return_value=mock.Mock()):
            with mock.patch.object(task, "SessionLocal", FakeSession):
                with mock.patch.object(task, "select", return_value=FakeQuery()):
                    result = task.refresh_deliveries_task()

        self.assertEqual(result, {"checked": 0, "changed": 0})
        joined = " ".join(str(c) for c in captured.get("clauses", []))
        # The filter has to be IN the query rather than applied afterwards, or
        # every delivered order is fetched from the courier before being
        # ignored — one HTTP call per finished order, forever.
        self.assertIn("state", joined)
        self.assertIn("provider_order_id", joined)

    def test_no_courier_configured_does_nothing_quietly(self) -> None:
        from app.tasks import delivery as task

        with mock.patch.object(task, "delivery_provider", return_value=None):
            self.assertEqual(task.refresh_deliveries_task(), {"checked": 0, "changed": 0})

    def test_one_courier_failure_does_not_stop_the_sweep(self) -> None:
        # A bad minute on one delivery must not leave every other one stale.
        from app.tasks import delivery as task
        from app.services.delivery.base import DeliveryProviderError, DeliveryState

        rows = [
            SimpleNamespace(id=1, provider_order_id="a", state=DeliveryState.PENDING),
            SimpleNamespace(id=2, provider_order_id="b", state=DeliveryState.PENDING),
        ]
        provider = mock.Mock()
        provider.fetch.side_effect = [DeliveryProviderError("down"), mock.Mock()]

        class FakeSession:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def scalars(self_inner, q):
                return SimpleNamespace(all=lambda: rows)

            def commit(self_inner):
                pass

        with mock.patch.object(task, "delivery_provider", return_value=provider):
            with mock.patch.object(task, "SessionLocal", FakeSession):
                with mock.patch.object(task, "record") as recorded:
                    result = task.refresh_deliveries_task()

        # Both were attempted; only the one that answered was recorded.
        self.assertEqual(result["checked"], 2)
        self.assertEqual(recorded.call_count, 1)
