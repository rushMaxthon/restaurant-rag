"""An accepted delivery order is never left without a courier because one
job went missing.

Dispatch is a Celery job queued after the kitchen's accept. A worker that is
down, a broker that blinks, or a deploy at the wrong second loses it - and
nothing asked again: the offers had a safety-net beat, dispatch did not. Found
2026-10-09, when orders accepted while no worker ran sat at ACCEPTED with no
delivery row and no rider ever heard of them. `dispatch_missed` is the net:
it re-asks for every recently accepted delivery order that has no row.

Recently, on purpose: an order accepted hours ago and never dispatched has
been dealt with some other way (the kitchen's own rider, the customer
collected), and booking a courier for it now would send somebody to a
restaurant for food that left long ago.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.enums import OrderFulfillmentType, OrderStatus  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.services.delivery import registry, service  # noqa: E402
from app.services.order_events import record_order_status_event  # noqa: E402

LOCAL_DISPATCH = {
    "ENABLE_DELIVERY_DISPATCH": "true",
    "ENABLE_OWN_FLEET": "true",
    "PIDGE_BASE_URL": "https://store.dev.pidge.in",
}


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class DispatchMissedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_dispatch_missed_test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def setUp(self) -> None:
        self.env(LOCAL_DISPATCH)
        self.addCleanup(get_settings.cache_clear)
        self.addCleanup(registry.reset_delivery_provider)
        advance = mock.patch("app.services.fleet.offers.queue_advance")
        advance.start()
        self.addCleanup(advance.stop)
        self.now = datetime.now(UTC)

    def env(self, values: dict[str, str]) -> None:
        patcher = mock.patch.dict(os.environ, values)
        patcher.start()
        self.addCleanup(patcher.stop)
        get_settings.cache_clear()
        registry.reset_delivery_provider()

    def accepted(self, minutes_ago: float, **kwargs):
        with self.fdb.session() as db:
            order = self.fdb.make_order(db, **kwargs)
            record_order_status_event(
                db, order=order, from_status=OrderStatus.PLACED, to_status=OrderStatus.ACCEPTED,
                occurred_at=self.now - timedelta(minutes=minutes_ago),
            )
            db.commit()
            return order.id

    def rows(self, order_id) -> list[OrderDelivery]:
        with self.fdb.session() as db:
            return list(db.scalars(select(OrderDelivery).where(OrderDelivery.order_id == order_id)))

    def run_net(self) -> list:
        with self.fdb.session() as db:
            done = service.dispatch_missed(db, now=self.now)
            db.commit()
            return done

    def test_an_order_whose_dispatch_job_was_lost_is_dispatched(self) -> None:
        order_id = self.accepted(2)
        self.assertIn(order_id, self.run_net())
        rows = self.rows(order_id)
        self.assertEqual([r.provider for r in rows], ["own_fleet"])

    def test_still_preparing_counts_too(self) -> None:
        # The kitchen moved on to PREPARING before anybody noticed: the food
        # still needs carrying.
        order_id = self.accepted(5, status=OrderStatus.PREPARING)
        self.assertIn(order_id, self.run_net())

    def test_an_order_accepted_long_ago_is_left_alone(self) -> None:
        order_id = self.accepted(service.DISPATCH_RETRY_WINDOW.total_seconds() / 60 + 5)
        self.assertNotIn(order_id, self.run_net())
        self.assertEqual(self.rows(order_id), [])

    def test_an_order_already_dispatched_is_not_dispatched_twice(self) -> None:
        order_id = self.accepted(2)
        self.run_net()
        self.assertNotIn(order_id, self.run_net())
        self.assertEqual(len(self.rows(order_id)), 1)

    def test_an_order_already_on_its_way_is_left_alone(self) -> None:
        # Out for delivery means somebody already has the food.
        order_id = self.accepted(2, status=OrderStatus.OUT_FOR_DELIVERY)
        self.assertNotIn(order_id, self.run_net())

    def test_a_pickup_order_is_never_dispatched(self) -> None:
        order_id = self.accepted(2)
        with self.fdb.session() as db:
            from app.models.order import Order

            db.get(Order, order_id).fulfillment_type = OrderFulfillmentType.PICKUP
            db.commit()
        self.assertNotIn(order_id, self.run_net())

    def test_dispatch_switched_off_dispatches_nothing(self) -> None:
        self.env({"ENABLE_DELIVERY_DISPATCH": "false"})
        order_id = self.accepted(2)
        self.assertEqual(self.run_net(), [])
        self.assertEqual(self.rows(order_id), [])


if __name__ == "__main__":
    unittest.main()
