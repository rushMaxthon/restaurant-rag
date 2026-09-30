"""Emit realtime events only once the transaction that caused them has committed.

An order route, the payment webhook, the unpaid-order reaper (Celery) and the
WhatsApp agent (Celery again) all change an order the same way: add rows, then
the CALLER commits. Emitting at the point of change would be wrong twice over:

* before the commit, a board that refetches on the push reads the OLD row — the
  push arrives, the refetch runs, and nothing changes on screen;
* a rolled-back transaction would announce a transition that never happened.

So a change is queued on the session (`session.info`) and a class-level
`after_commit` listener emits the queue; a rollback discards it. Nested
savepoints do not fire `after_commit`, so only the outermost commit emits.

Emitting goes through python-socketio's write-only `RedisManager`: the
documented way for a process that holds no sockets — a Celery worker, or a sync
route running in a threadpool — to reach sockets held by the API processes.

Two rules this module keeps, because the code that calls it is the most
correctness-critical in the platform:

* It never raises. A Redis outage costs a push, which the client's fallback
  poll recovers; it must never cost an order.
* It does nothing at all while `enable_realtime` is off: no queue, no Redis.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.config import get_settings

logger = logging.getLogger(__name__)

_OUTBOX_KEY = "realtime_outbox"

ORDER_UPDATED_EVENT = "order:updated"
SESSION_REVOKED_EVENT = "session:revoked"
# A plain Redis channel, separate from the Socket.IO one. A write-only manager
# cannot disconnect a socket — it needs a live server and the socket's sid,
# neither of which a route bumping `token_version` has (confirmed in the spike:
# `RedisManager(write_only=True).disconnect` raises). Each API process listens
# here and disconnects its own sockets for the named account.
CONTROL_CHANNEL_SUFFIX = ":control"


class _Emitter(Protocol):
    def emit(self, event: str, data: Any, *, room: Any = None) -> None: ...


def control_channel() -> str:
    return get_settings().realtime_redis_channel + CONTROL_CHANNEL_SUFFIX


@lru_cache(maxsize=1)
def _default_manager() -> Any:
    """The process-wide write-only manager, built on first use.

    The timeouts are the cache's, not redis-py's defaults (none): this runs
    inside `commit()` on a request thread, and a Redis that has stopped
    answering must cost a missed push rather than a hung order write.
    """

    import socketio

    settings = get_settings()
    return socketio.RedisManager(
        settings.redis_url,
        channel=settings.realtime_redis_channel,
        write_only=True,
        redis_options={
            "socket_connect_timeout": settings.redis_socket_connect_timeout_seconds,
            "socket_timeout": settings.redis_socket_timeout_seconds,
        },
    )


# Swapped by tests for a recording fake. None means "use the real manager".
_emitter_override: _Emitter | None = None
_publisher_override: Any = None


def set_emitter_for_tests(emitter: _Emitter | None, publisher: Any = None) -> None:
    global _emitter_override, _publisher_override
    _emitter_override = emitter
    _publisher_override = publisher


def _emitter() -> _Emitter:
    return _emitter_override if _emitter_override is not None else _default_manager()


def _publish_control(message: dict[str, Any]) -> None:
    import json

    if _publisher_override is not None:
        _publisher_override(control_channel(), json.dumps(message))
        return
    from app.services.cache import get_redis_client

    get_redis_client().publish(control_channel(), json.dumps(message))


def _queue(db: Session, item: dict[str, Any]) -> None:
    if not get_settings().enable_realtime:
        return
    try:
        # Tie the queue to a transaction. With none begun yet, `rollback()` is
        # a no-op that fires no event while `commit()` autobegins and fires
        # `after_commit` — so a queue made before any SQL would survive the
        # rollback that disowned it. Beginning issues no SQL.
        if not db.in_transaction():
            db.begin()
        db.info.setdefault(_OUTBOX_KEY, []).append(item)
    except Exception:  # noqa: BLE001 - a push must never fail the write it describes
        logger.exception("Could not queue realtime event kind=%s", item.get("kind"))


def queue_order_updated(
    db: Session,
    *,
    order_id: uuid.UUID,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    to_status: Any,
    from_status: Any,
    occurred_at: datetime | None,
) -> None:
    """Queue "this order changed" for after the commit.

    Values are copied NOW rather than read off the order later: attributes can
    be expired by the commit, and reloading them from inside `after_commit`
    would mean SQL on a session that has just finished its transaction.

    The payload is deliberately thin. It says which order and what it became —
    never the order itself — so a client always refetches through the REST
    route, whose scope rules are the only ones that decide what anyone sees.
    """

    if not get_settings().enable_realtime:
        return
    try:
        from app.services.realtime.rooms import order_event_rooms

        item = {
            "kind": "order",
            "rooms": order_event_rooms(
                restaurant_id=restaurant_id,
                restaurant_location_id=restaurant_location_id,
                customer_id=customer_id,
            ),
            "payload": {
                "order_id": str(order_id),
                "restaurant_id": str(restaurant_id),
                "restaurant_location_id": str(restaurant_location_id),
                "status": _enum_value(to_status),
                "from_status": _enum_value(from_status),
                "occurred_at": (occurred_at or datetime.now(UTC)).isoformat(),
            },
        }
    except Exception:  # noqa: BLE001 - a push must never fail the write it describes
        logger.exception("Could not build realtime order event order_id=%s", order_id)
        return
    _queue(db, item)


def queue_session_revoked(db: Session, *, user_id: uuid.UUID) -> None:
    """Queue "end this account's sockets" for after the commit.

    After, not before: a client told its session is over reconnects straight
    away, and if the `token_version` bump were not yet committed that
    reconnect would pass the version check with the old token.
    """

    _queue(db, {"kind": "revoke", "user_id": str(user_id)})


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _flush(items: list[dict[str, Any]]) -> None:
    from app.services.realtime.rooms import user_room

    for item in items:
        try:
            if item["kind"] == "order":
                _emitter().emit(ORDER_UPDATED_EVENT, item["payload"], room=item["rooms"])
            elif item["kind"] == "revoke":
                # The event tells a well-behaved client to sign out now; the
                # control message is what makes it true for one that does not.
                _emitter().emit(
                    SESSION_REVOKED_EVENT,
                    {"reason": "session_revoked"},
                    room=user_room(uuid.UUID(item["user_id"])),
                )
                _publish_control({"type": "revoke", "user_id": item["user_id"]})
        except Exception:  # noqa: BLE001 - see module docstring
            logger.warning(
                "Realtime emit failed kind=%s; clients will catch up on their next refetch",
                item.get("kind"),
                exc_info=True,
            )


@event.listens_for(Session, "after_commit")
def _emit_after_commit(session: Session) -> None:
    items = session.info.pop(_OUTBOX_KEY, None)
    if items:
        _flush(items)


# `after_soft_rollback`, not `after_rollback`: the latter fires only when a
# real DBAPI rollback happens, so a queue built before the transaction had run
# any SQL survived `rollback()` and went out with the NEXT commit on the same
# session — caught by `test_rolled_back_transition_is_never_pushed`. This one
# fires on every `Session.rollback()`, which is the moment the caller disowned
# the write.
@event.listens_for(Session, "after_soft_rollback")
def _discard_after_rollback(session: Session, previous_transaction: object) -> None:
    session.info.pop(_OUTBOX_KEY, None)
