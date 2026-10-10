"""Telling a rider something changed: a Socket.IO hint and, for offers, an FCM push.

A rider's socket sits in its own `user:{id}` room only (RIDER is not a staff
role, so `server._staff_room_for` gives it nothing else) - which is exactly
the audience for these events. Payloads carry ids, never data: the app
refetches over REST, whose scope is the only thing that decides what a rider
may see.

The offer goes out as a high-priority, DATA-only FCM message as well,
because the socket is closed whenever Android has put the app to sleep; the
app's background handler draws the full-screen alert itself. Every function
here is called after the commit and never raises - a push that fails must
not roll back an offer or cost an order.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.config import get_settings

logger = logging.getLogger(__name__)

OFFER_EVENT = "rider:offer"
OFFER_WITHDRAWN_EVENT = "rider:offer_withdrawn"
TRIP_UPDATED_EVENT = "rider:trip_updated"
TRIP_CANCELLED_EVENT = "rider:trip_cancelled"
SHIFT_ENDED_EVENT = "rider:shift_ended"
#: To the admin room: a rider moved or changed state - the live map refetches.
RIDERS_CHANGED_EVENT = "fleet:riders_changed"

#: Android channel the rider app creates for offers (loud, full-screen).
OFFER_CHANNEL = "rider-offers"
#: The customer's map refreshes at most this often per delivery.
MOVED_THROTTLE_SECONDS = 10
#: The admin's live map hears about one rider at most this often. Short: the
#: map is where a dispatcher decides who is nearest, so a pin should follow
#: the rider, and the admin client coalesces a burst into one refetch anyway.
RIDER_HINT_THROTTLE_SECONDS = 3


def _emit(event: str, payload: dict[str, Any], *, room: Any) -> None:
    if not get_settings().enable_realtime:
        return
    try:
        from app.services.realtime.outbox import _emitter

        _emitter().emit(event, payload, room=room)
    except Exception:  # noqa: BLE001 - the app refetches on reconnect anyway
        logger.warning("Rider realtime emit failed event=%s", event, exc_info=True)


def _to_rider(event: str, rider_user_id: uuid.UUID, payload: dict[str, Any]) -> None:
    from app.services.realtime.rooms import user_room

    _emit(event, payload, room=user_room(rider_user_id))


def _push(db: Session, rider_user_id: uuid.UUID, data: dict[str, str], *, ttl_seconds: int) -> str:
    """One data-only, high-priority message to the rider's phone. Returns what happened."""

    from app.models.rider import Rider

    try:
        rider = db.get(Rider, rider_user_id)
    except Exception:  # noqa: BLE001 - a push must never fail the work that sent it
        logger.warning("Rider push could not read the device rider=%s", rider_user_id, exc_info=True)
        return "failed"
    if rider is None or not rider.fcm_token:
        return "no_device"
    try:
        from firebase_admin import messaging

        from app.services.notifications import NotificationDeliveryError, _get_firebase_app, _should_deactivate_token

        try:
            app = _get_firebase_app()
        except NotificationDeliveryError:
            return "firebase_not_configured"
        message = messaging.Message(
            token=rider.fcm_token,
            data=data,
            android=messaging.AndroidConfig(priority="high", ttl=ttl_seconds),
        )
        try:
            messaging.send(message, app=app)
        except Exception as error:  # noqa: BLE001
            if _should_deactivate_token(error):
                _forget_token(rider_user_id, rider.fcm_token)
                rider.fcm_token = ""
                return "token_removed"
            raise
        return "sent"
    except Exception:  # noqa: BLE001 - never into the caller
        logger.warning("Rider push failed rider=%s type=%s", rider_user_id, data.get("type"), exc_info=True)
        return "failed"


def _forget_token(rider_user_id: uuid.UUID, token: str) -> None:
    """Clear a dead token in its OWN session: committing the caller's could
    publish half of whatever it was in the middle of (review finding)."""

    try:
        from sqlalchemy import update

        from app.config.database import SessionLocal
        from app.models.rider import Rider

        with SessionLocal() as own:
            own.execute(
                update(Rider).where(Rider.user_id == rider_user_id, Rider.fcm_token == token).values(fcm_token="")
            )
            own.commit()
    except Exception:  # noqa: BLE001
        logger.warning("Could not clear a dead push token for rider %s", rider_user_id, exc_info=True)


def offer_made(db: Session, offer: Any) -> None:
    """A rider has a new offer: socket hint now, and a push that wakes the phone."""

    payload = {"offer_id": str(offer.id)}
    _to_rider(OFFER_EVENT, offer.rider_user_id, payload)
    expires = offer.expires_at if offer.expires_at.tzinfo else offer.expires_at.replace(tzinfo=UTC)
    ttl = max(1, int((expires - datetime.now(UTC)).total_seconds()))
    _push(
        db,
        offer.rider_user_id,
        {"type": "rider_offer", "offer_id": str(offer.id), "expires_at": expires.isoformat(), "channel": OFFER_CHANNEL},
        # An offer that arrives after it expired is worse than none.
        ttl_seconds=ttl,
    )
    # The admin map's waiting list says who is being asked right now.
    riders_changed(offer.rider_user_id, force=True)


def offer_withdrawn(db: Session, offer: Any) -> None:
    _to_rider(OFFER_WITHDRAWN_EVENT, offer.rider_user_id, {"offer_id": str(offer.id)})
    riders_changed(offer.rider_user_id, force=True)


def shift_ended(db: Session, rider_user_id: uuid.UUID) -> None:
    """Taken off shift because the phone stopped answering (`riders.sweep_silent`).
    Pushed: the app is most likely killed, and a rider who does not know waits
    for orders that will never come."""

    _to_rider(SHIFT_ENDED_EVENT, rider_user_id, {})
    _push(db, rider_user_id, {"type": "rider_shift_ended"}, ttl_seconds=3_600)


def application_decided(rider_user_id: uuid.UUID, status: str) -> None:
    """An admin approved, sent back or rejected a sign-up. The rider is
    probably not looking at the app, so it is pushed as well as emitted; the
    app refetches the application either way. Its own session: called after
    the decision committed, and a failure here must never undo it."""

    _to_rider("rider:application", rider_user_id, {"status": status})
    from app.config.database import SessionLocal

    try:
        with SessionLocal() as db:
            _push(db, rider_user_id, {"type": "rider_application", "status": status}, ttl_seconds=86_400)
            db.commit()
    except Exception:  # noqa: BLE001 - never into the caller
        logger.warning("Application push failed rider=%s", rider_user_id, exc_info=True)


def trip_changed(db: Session, trip: Any) -> None:
    _to_rider(TRIP_UPDATED_EVENT, trip.rider_user_id, {"trip_id": str(trip.id)})


def trip_cancelled(db: Session, trip: Any) -> None:
    """The order behind the trip was cancelled. Pushed too: the rider may be riding."""

    _to_rider(TRIP_CANCELLED_EVENT, trip.rider_user_id, {"trip_id": str(trip.id)})
    _push(db, trip.rider_user_id, {"type": "rider_trip_cancelled", "trip_id": str(trip.id)}, ttl_seconds=600)


def _throttled(delivery_id: uuid.UUID) -> bool:
    """True when this delivery was announced inside the throttle window."""

    try:
        from app.services.cache import get_redis_client

        fresh = get_redis_client().set(f"fleet:moved:{delivery_id}", "1", nx=True, ex=MOVED_THROTTLE_SECONDS)
        return not fresh
    except Exception:  # noqa: BLE001 - Redis down: announce rather than go silent
        return False


def riders_changed(rider_user_id: uuid.UUID, *, force: bool = False) -> None:
    """Tell the admin's rider list and live map a rider changed. An id, never
    a position: they refetch over REST, whose ADMIN-only rule decides who sees it.

    Throttled per rider for location pings, which arrive every few seconds.
    `force` is for a STATUS change (online, offline, on a trip, free again,
    deactivated) and skips the throttle: going online a second after a
    location ping must still reach the screen, not wait for its next poll.
    """

    from app.services.realtime.rooms import ADMIN_ALL_ROOM

    if not get_settings().enable_realtime:
        return
    if not force:
        try:
            from app.services.cache import get_redis_client

            if not get_redis_client().set(
                f"fleet:rider_hint:{rider_user_id}", "1", nx=True, ex=RIDER_HINT_THROTTLE_SECONDS
            ):
                return
        except Exception:  # noqa: BLE001 - Redis down: announce rather than go silent
            pass
    _emit(RIDERS_CHANGED_EVENT, {"rider_id": str(rider_user_id)}, room=ADMIN_ALL_ROOM)


def order_moved(db: Session, delivery: Any) -> None:
    """The rider moved: the existing `order:updated` hint, so maps refetch.
    Throttled: a position is worth one refetch per window, not one per fix."""

    if not get_settings().enable_realtime or _throttled(delivery.id):
        return
    _order_hint(delivery, "rider_moved")


def delivery_changed(db: Session | None, delivery: Any, reason: str) -> None:
    """A delivery step that the order's status does not show - a rider was
    assigned, reached the restaurant, reached the door - told to everyone
    watching the order: its branch, its restaurant, the admin and the
    customer, as the same `order:updated` hint a status change sends.

    Never throttled: each one is a real step, and they come seconds apart at
    most. "Picked up" and "delivered" also move the order and send their own
    hint; the clients coalesce, so the second is free.
    """

    if not get_settings().enable_realtime:
        return
    _order_hint(delivery, reason)


def _order_hint(delivery: Any, reason: str) -> None:
    try:
        from app.services.realtime.outbox import ORDER_UPDATED_EVENT
        from app.services.realtime.rooms import order_event_rooms

        order = delivery.order
        payload = {
            "order_id": str(order.id),
            "restaurant_id": str(order.restaurant_id),
            "restaurant_location_id": str(order.restaurant_location_id),
            "status": getattr(order.status, "value", order.status),
            "from_status": getattr(order.status, "value", order.status),
            "occurred_at": datetime.now(UTC).isoformat(),
            "reason": reason,
        }
        rooms = order_event_rooms(
            restaurant_id=order.restaurant_id,
            restaurant_location_id=order.restaurant_location_id,
            customer_id=order.customer_id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Could not build delivery event reason=%s", reason, exc_info=True)
        return
    _emit(ORDER_UPDATED_EVENT, payload, room=rooms)


# --- referral pushes, after the commit -------------------------------------------
#
# The `realtime/outbox.py` pattern: queued on the session, sent by a
# class-level after_commit listener in a FRESH session (a committed one
# refuses SQL - the trip-cancelled bug), dropped when the outermost
# transaction rolls back, so a referral that never happened is never told.

_REFERRAL_QUEUE = "referral_pushes"


def queue_referral_push(db: Session, rider_user_id: uuid.UUID, event: str, **fields: Any) -> None:
    data = {"type": "rider_referral", "event": event}
    data.update({k: str(v) for k, v in fields.items() if v is not None})
    db.info.setdefault(_REFERRAL_QUEUE, []).append((rider_user_id, data))


def _send_referral_pushes(session: Session) -> None:
    queued = session.info.pop(_REFERRAL_QUEUE, None)
    if not queued:
        return
    from app.config.database import SessionLocal

    try:
        with SessionLocal() as fresh:
            for rider_user_id, data in queued:
                _push(fresh, rider_user_id, data, ttl_seconds=86_400)
            fresh.commit()
    except Exception:  # noqa: BLE001 - a push must never fail the commit that caused it
        logger.warning("Referral pushes failed (%d queued)", len(queued), exc_info=True)


def _drop_referral_pushes(session: Session, previous_transaction: Any) -> None:
    if previous_transaction.parent is None:  # the outermost transaction, not a savepoint
        session.info.pop(_REFERRAL_QUEUE, None)


event.listen(Session, "after_commit", _send_referral_pushes)
event.listen(Session, "after_soft_rollback", _drop_referral_pushes)


__all__ = [
    "queue_referral_push",
    "OFFER_CHANNEL", "OFFER_EVENT", "OFFER_WITHDRAWN_EVENT", "SHIFT_ENDED_EVENT", "TRIP_CANCELLED_EVENT",
    "TRIP_UPDATED_EVENT",
    "delivery_changed", "offer_made", "offer_withdrawn", "order_moved", "riders_changed",
    "shift_ended", "trip_cancelled", "trip_changed",
]
