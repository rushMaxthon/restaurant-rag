"""Offers reach the rider by socket and by push - and only the rider.

The push is DATA-only and high priority: Android has usually put the app to
sleep, and the app's own handler draws the full-screen alert. A push that
fails, or a Firebase that is not configured, must never raise into the
offer loop.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from app.models.enums import UserRole  # noqa: E402
from app.services.fleet import notify  # noqa: E402
from app.services.realtime.rooms import is_staff_role, user_room  # noqa: E402


def _offer(**over):
    fields = {"id": uuid.uuid4(), "rider_user_id": uuid.uuid4(), "expires_at": datetime.now(UTC) + timedelta(seconds=30)}
    fields.update(over)
    return SimpleNamespace(**fields)


class RiderEventsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = mock.patch.object(notify, "get_settings", return_value=SimpleNamespace(enable_realtime=True))
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def test_offer_goes_to_the_riders_own_room_only(self) -> None:
        offer = _offer()
        emitter = mock.Mock()
        with mock.patch("app.services.realtime.outbox._emitter", return_value=emitter), \
                mock.patch.object(notify, "_push") as push:
            notify.offer_made(mock.Mock(), offer)
        emitter.emit.assert_called_once_with(notify.OFFER_EVENT, {"offer_id": str(offer.id)}, room=user_room(offer.rider_user_id))
        data = push.call_args.args[2]
        self.assertEqual(data["type"], "rider_offer")
        self.assertLessEqual(push.call_args.kwargs["ttl_seconds"], 30)

    def test_a_rider_is_not_a_staff_socket(self) -> None:
        # A rider must never be put in a restaurant or admin room.
        self.assertFalse(is_staff_role(UserRole.RIDER))

    def test_push_is_data_only_and_high_priority(self) -> None:
        db = mock.Mock()
        db.get.return_value = SimpleNamespace(fcm_token="tok-" + "x" * 20)
        sent = {}

        def capture(message, app=None):
            sent["message"] = message
            return "ok"

        with mock.patch("app.services.notifications._get_firebase_app", return_value=object()), \
                mock.patch("firebase_admin.messaging.send", side_effect=capture):
            result = notify._push(db, uuid.uuid4(), {"type": "rider_offer"}, ttl_seconds=20)
        self.assertEqual(result, "sent")
        message = sent["message"]
        self.assertIsNone(message.notification)
        self.assertEqual(message.android.priority, "high")

    def test_an_unregistered_token_is_cleared(self) -> None:
        rider = SimpleNamespace(fcm_token="tok-" + "x" * 20)
        db = mock.Mock()
        db.get.return_value = rider
        with mock.patch("app.services.notifications._get_firebase_app", return_value=object()), \
                mock.patch("firebase_admin.messaging.send", side_effect=RuntimeError("unregistered")), \
                mock.patch("app.services.notifications._should_deactivate_token", return_value=True), \
                mock.patch.object(notify, "_forget_token") as forget:
            self.assertEqual(notify._push(db, uuid.uuid4(), {"type": "x"}, ttl_seconds=5), "token_removed")
        self.assertEqual(rider.fcm_token, "")
        forget.assert_called_once()

    def test_no_firebase_never_raises(self) -> None:
        from app.services.notifications import NotificationDeliveryError

        db = mock.Mock()
        db.get.return_value = SimpleNamespace(fcm_token="tok-" + "x" * 20)
        with mock.patch("app.services.notifications._get_firebase_app", side_effect=NotificationDeliveryError("off")):
            self.assertEqual(notify._push(db, uuid.uuid4(), {"type": "x"}, ttl_seconds=5), "firebase_not_configured")

    def test_rider_moved_is_throttled(self) -> None:
        delivery = SimpleNamespace(
            id=uuid.uuid4(),
            order=SimpleNamespace(id=uuid.uuid4(), restaurant_id=uuid.uuid4(), restaurant_location_id=uuid.uuid4(),
                                  customer_id=uuid.uuid4(), status="OUT_FOR_DELIVERY"),
        )
        emitter = mock.Mock()
        seen = set()

        def setnx(key, value, nx, ex):
            if key in seen:
                return None
            seen.add(key)
            return True

        redis = mock.Mock(set=mock.Mock(side_effect=setnx))
        with mock.patch("app.services.realtime.outbox._emitter", return_value=emitter), \
                mock.patch("app.services.cache.get_redis_client", return_value=redis):
            notify.order_moved(mock.Mock(), delivery)
            notify.order_moved(mock.Mock(), delivery)
        self.assertEqual(emitter.emit.call_count, 1)

    def test_realtime_off_emits_nothing(self) -> None:
        self.settings.stop()
        emitter = mock.Mock()
        with mock.patch.object(notify, "get_settings", return_value=SimpleNamespace(enable_realtime=False)), \
                mock.patch("app.services.realtime.outbox._emitter", return_value=emitter), \
                mock.patch.object(notify, "_push"):
            notify.offer_made(mock.Mock(), _offer())
        emitter.emit.assert_not_called()
        self.settings.start()


if __name__ == "__main__":
    unittest.main()
