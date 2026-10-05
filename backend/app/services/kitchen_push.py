"""New-order pushes to the kitchen app.

The board already finds a new order on its own — by realtime when that is on,
by polling otherwise — but only while it is open and awake. A tablet that has
gone to sleep, or a phone with the app in the background, hears nothing. This
module is the page that reaches it.

Three decisions, each of which was the obvious wrong answer first:

* **Who.** The recipients are exactly the board's scope for the order —
  KITCHEN accounts assigned to its restaurant (and to its branch, or to no
  branch), plus the restaurant's OWNER — so a push can never announce an order
  the recipient could not then open. A pinned cook at the Airport branch is
  not woken for Downtown's lunch rush.
* **When.** On the transition INTO `PLACED`, from `record_order_status_event`,
  which every order path goes through: a COD order is created PLACED, a card
  order becomes PLACED when the payment confirms. Never on PAYMENT_PENDING — an
  unpaid order is not work, and is not on the board.
* **After the commit.** Queued on the session and handed to Celery by an
  `after_commit` listener, the same shape as `realtime/outbox.py`, so a
  rolled-back order pages nobody and the worker never reads a row that is not
  there yet. Queueing never raises: a push must never cost an order.

The worker re-reads the order and sends nothing if it is no longer PLACED —
an order accepted on another tablet in the seconds before the worker ran is
not "new" any more.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from firebase_admin import messaging
from sqlalchemy import event, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models.enums import OrderFulfillmentType, OrderScheduleType, OrderStatus, UserRole
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.user_device_token import UserDeviceToken

logger = logging.getLogger(__name__)

TASK_NAME = "app.tasks.notifications.send_kitchen_new_order_notification"
NOTIFICATION_TYPE = "kitchen_new_order"

# Must match the kitchen app (kitchen/src/services/pushNotifications.ts). The
# Android channel is created by the app with the chime as its sound; the sound
# files ship in the app as res/raw/new_order.wav and the iOS bundle's
# new_order.wav. A name the app does not have falls back to the default sound.
ANDROID_CHANNEL_ID = "kitchen-new-orders"
ANDROID_SOUND = "new_order"
IOS_SOUND = "new_order.wav"

_OUTBOX_KEY = "kitchen_push_outbox"
_MULTICAST_LIMIT = 500


# --- queueing (request side) ---------------------------------------------------


def queue_kitchen_new_order(db: Session, *, order_id: uuid.UUID) -> None:
    """Ask for the kitchen to be paged about this order once the caller commits."""

    if not get_settings().enable_kitchen_push:
        return
    try:
        # Tie the queue to a transaction, exactly as the realtime outbox does:
        # with none begun, a rollback fires no event and the queue would leak
        # into the session's next commit.
        if not db.in_transaction():
            db.begin()
        db.info.setdefault(_OUTBOX_KEY, []).append(str(order_id))
    except Exception:  # noqa: BLE001 - a push must never fail the write it describes
        logger.exception("Could not queue kitchen push order_id=%s", order_id)


def _enqueue(order_ids: list[str]) -> None:
    from app.config.celery import celery_app

    for order_id in dict.fromkeys(order_ids):
        try:
            celery_app.send_task(TASK_NAME, kwargs={"order_id": order_id})
        except Exception:  # noqa: BLE001 - Redis down costs a page, never an order
            logger.warning("Could not enqueue kitchen push order_id=%s", order_id, exc_info=True)


@event.listens_for(Session, "after_commit")
def _enqueue_after_commit(session: Session) -> None:
    order_ids = session.info.pop(_OUTBOX_KEY, None)
    if order_ids:
        _enqueue(order_ids)


# `after_soft_rollback`, not `after_rollback` — see realtime/outbox.py for the
# leak the latter caused.
@event.listens_for(Session, "after_soft_rollback")
def _discard_after_rollback(session: Session, previous_transaction: object) -> None:
    session.info.pop(_OUTBOX_KEY, None)


# --- recipients and message (worker side) -------------------------------------


def kitchen_recipients(db: Session, order: Order) -> list[User]:
    """Everyone whose board shows this order, and only them.

    Mirrors `resolve_order_board_scope`: a KITCHEN account sees its restaurant,
    narrowed to its branch when it has one; an OWNER sees all of their own.
    ADMINs are not paged — they have no kitchen.
    """

    owner_id = db.scalar(select(Restaurant.owner_id).where(Restaurant.id == order.restaurant_id))
    kitchen = (User.role == UserRole.KITCHEN) & (User.staff_restaurant_id == order.restaurant_id) & or_(
        User.staff_restaurant_location_id.is_(None),
        User.staff_restaurant_location_id == order.restaurant_location_id,
    )
    owner = (User.role == UserRole.OWNER) & (User.id == owner_id)
    return list(
        db.scalars(select(User).where(User.is_active.is_(True), or_(kitchen, owner))).all()
    )


def order_code(order: Order) -> str:
    """The receipt's eight characters — what the board and the customer call it."""

    return f"#{str(order.id)[:8].upper()}"


def build_kitchen_message(order: Order) -> tuple[str, str, dict[str, str]]:
    """Title, body and data for one order.

    The body is what a cook needs to decide whether to walk over now: how it
    leaves the kitchen, how much there is, and for whom. No prices, no address
    — the same things the board itself leaves off a ticket.
    """

    is_delivery = order.fulfillment_type == OrderFulfillmentType.DELIVERY
    count = sum(item.quantity for item in (order.items or []))
    parts = ["Delivery" if is_delivery else "Pickup", f"{count} {'item' if count == 1 else 'items'}"]
    who = (order.contact_name or "").strip() or (getattr(order.customer, "full_name", "") or "").strip()
    if who:
        parts.append(who)
    if order.schedule_type == OrderScheduleType.SCHEDULED:
        parts.append("Scheduled")
    data = {
        "notification_type": NOTIFICATION_TYPE,
        "order_id": str(order.id),
        "restaurant_id": str(order.restaurant_id),
        "restaurant_location_id": str(order.restaurant_location_id),
    }
    return f"New order {order_code(order)}", " · ".join(parts), data


def _multicast(tokens: list[str], title: str, body: str, data: dict[str, str]) -> messaging.MulticastMessage:
    return messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        data=data,
        # High priority so a dozing Android tablet wakes for it; the channel
        # carries the chime and the vibration the app configured.
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id=ANDROID_CHANNEL_ID,
                sound=ANDROID_SOUND,
            ),
        ),
        apns=messaging.APNSConfig(
            headers={"apns-priority": "10"},
            payload=messaging.APNSPayload(aps=messaging.Aps(sound=IOS_SOUND)),
        ),
    )


def send_kitchen_new_order_push(db: Session, *, order_id: uuid.UUID) -> dict[str, Any]:
    """Page the kitchen about one order. Returns a summary; never raises.

    Not recorded as a notification campaign: these are operational pages, one
    per order, and would bury the admin panel's history of real sends.
    """

    from app.services.notifications import (
        NotificationDeliveryError,
        _chunked,
        _get_firebase_app,
        _should_deactivate_token,
    )

    order = db.scalar(
        select(Order).options(selectinload(Order.items), selectinload(Order.customer)).where(Order.id == order_id)
    )
    if order is None:
        return {"status": "skipped", "reason": "order_not_found"}
    if order.status != OrderStatus.PLACED:
        return {"status": "skipped", "reason": f"order_is_{order.status.value.lower()}"}

    recipients = kitchen_recipients(db, order)
    tokens = list(
        db.scalars(
            select(UserDeviceToken).where(
                UserDeviceToken.user_id.in_([user.id for user in recipients]),
                UserDeviceToken.is_active.is_(True),
            )
        ).all()
    ) if recipients else []
    token_values = list(dict.fromkeys(token.fcm_token for token in tokens))
    if not token_values:
        return {"status": "skipped", "reason": "no_devices", "recipients": len(recipients)}

    try:
        firebase_app = _get_firebase_app()
    except NotificationDeliveryError as error:
        logger.warning("Kitchen push not sent order_id=%s: %s", order_id, error)
        return {"status": "failed", "reason": "firebase_not_configured"}

    title, body, data = build_kitchen_message(order)
    sent = failed = 0
    dead: set[str] = set()
    try:
        for batch in _chunked(token_values, _MULTICAST_LIMIT):
            response = messaging.send_each_for_multicast(_multicast(batch, title, body, data), app=firebase_app)
            sent += response.success_count
            failed += response.failure_count
            for token_value, result in zip(batch, response.responses, strict=False):
                if not result.success and _should_deactivate_token(result.exception):
                    dead.add(token_value)
    except Exception:  # noqa: BLE001 - a failed page is logged, never retried into a storm
        logger.exception("Kitchen push send failed order_id=%s", order_id)
        return {"status": "failed", "reason": "send_error", "sent": sent}

    # A token Firebase says is gone (app uninstalled, reinstalled) is switched
    # off so the next order does not try it again.
    for token in tokens:
        if token.fcm_token in dead:
            token.is_active = False
    if dead:
        db.commit()

    logger.info(
        "Kitchen push order_id=%s recipients=%s devices=%s sent=%s failed=%s deactivated=%s",
        order_id, len(recipients), len(token_values), sent, failed, len(dead),
    )
    return {"status": "sent", "devices": len(token_values), "sent": sent, "failed": failed}
