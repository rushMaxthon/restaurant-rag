"""The rider's "trip cancelled" push, run for real rather than mocked (2026-10-10).

Every other fleet test patches `notify.trip_cancelled` out, so nothing ever ran
it. On the emulator it failed: the push is sent from `after_commit`, and it
looked the rider's phone token up on the session that had just committed -
which refuses SQL at that point. The rider was never told, and the error
escaped `commit()`, so a cancel that HAD gone through reported a failure.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.enums import RiderStatus  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.rider import Rider, RiderTrip  # noqa: E402
from app.services.delivery import service  # noqa: E402

LOCAL_DISPATCH = {"ENABLE_DELIVERY_DISPATCH": "true", "PIDGE_BASE_URL": "https://store.dev.pidge.in"}


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class TripCancelledPushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_push_test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, LOCAL_DISPATCH)
        env.start()
        self.addCleanup(env.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        # The socket half is not under test; the push half is, down to Firebase.
        for target in ("_emit", "riders_changed"):
            p = mock.patch(f"app.services.fleet.notify.{target}")
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("app.services.notifications._get_firebase_app", return_value=object())
        p.start()
        self.addCleanup(p.stop)
        self.send = mock.patch("firebase_admin.messaging.send").start()
        self.addCleanup(mock.patch.stopall)

    def _rider_on_a_trip(self, db):
        rider = self.fdb.make_rider(db, status=RiderStatus.ON_TRIP)
        db.get(Rider, rider.id).fcm_token = "device-token-1"
        order = self.fdb.make_order(db)
        row = self.fdb.make_fleet_delivery(db, order, state="ASSIGNED")
        db.add(RiderTrip(order_delivery_id=row.id, rider_user_id=rider.id, accepted_at=datetime.now(UTC)))
        db.commit()
        return order

    def test_the_rider_is_pushed_when_their_order_is_cancelled(self) -> None:
        with self.fdb.session() as db:
            order = self._rider_on_a_trip(db)
            service.cancel(db, db.get(Order, order.id))
            db.commit()  # must not raise: the cancel is already committed
        self.send.assert_called_once()
        message = self.send.call_args.args[0]
        self.assertEqual(message.data["type"], "rider_trip_cancelled")
        self.assertEqual(message.token, "device-token-1")

    def test_a_push_that_cannot_be_sent_never_fails_the_cancel(self) -> None:
        self.send.side_effect = RuntimeError("firebase is down")
        with self.fdb.session() as db:
            order = self._rider_on_a_trip(db)
            service.cancel(db, db.get(Order, order.id))
            db.commit()


if __name__ == "__main__":
    unittest.main()
