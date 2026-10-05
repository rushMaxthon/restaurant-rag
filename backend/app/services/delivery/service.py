"""Turning an order into a courier job, and a courier's answer back into a row.

Two rules hold this together, and both exist because a delivery costs real
food:

**Dispatch once.** `order_deliveries.order_id` is unique, so a retried task
cannot put a second rider on the same order. The check here is the fast path;
the constraint is what makes it correct when two workers run at the same
moment.

**A courier may not move an order backwards.** `Order.status` is strictly
linear. A status push that arrives late — and they do, out of order — must
not drag a DELIVERED order back to OUT_FOR_DELIVERY, so `advance_order` only
ever moves forward along the flow.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import OrderFulfillmentType, OrderStatus
from app.models.order import Order
from app.models.order_delivery import OrderDelivery
from app.services.delivery.base import (
    LOCAL_ENVIRONMENTS,
    DeliveryAddress,
    DeliveryItem,
    DeliveryProviderError,
    DeliveryRequest,
    DeliveryResult,
    DeliveryState,
)
from app.services.delivery.registry import delivery_provider

logger = logging.getLogger(__name__)

#: Which delivery states move the order, and where to.
#:
#: FAILED is deliberately absent. A delivery that was dispatched and came back
#: leaves the order exactly where it was: nothing was cancelled and nothing was
#: delivered, and the honest record is that the courier failed while the order
#: still stands. Somebody decides what happens next; a status machine should
#: not decide it by itself.
_ORDER_STATUS_FOR = {
    # The rider has the food, so it has left the kitchen. This used to wait
    # for IN_TRANSIT, and Pidge reports PICKED_UP and OUT_FOR_DELIVERY a few
    # seconds apart - except when the second push is lost, when the order sat
    # in "Being prepared" while a rider rode it across town.
    DeliveryState.PICKED_UP: OrderStatus.OUT_FOR_DELIVERY,
    DeliveryState.IN_TRANSIT: OrderStatus.OUT_FOR_DELIVERY,
    DeliveryState.DELIVERED: OrderStatus.DELIVERED,
}

#: The order of `ORDER_STATUS_FLOW`, for the "never backwards" check.
_FORWARD = [
    OrderStatus.PLACED,
    OrderStatus.ACCEPTED,
    OrderStatus.PREPARING,
    OrderStatus.OUT_FOR_DELIVERY,
    OrderStatus.DELIVERED,
]


def _split_address(order: Order) -> tuple[str, str, str, str]:
    """The customer's address, as four fields a courier will accept.

    We store one free-text block; Pidge wants line/city/state/pincode. The
    pincode is pulled out by shape because it is the field a courier actually
    routes on, and the rest is sent as the line rather than guessed at — a
    wrong city is worse than a long address line.
    """

    import re

    raw = (order.delivery_address or "").strip()
    pincode = ""
    found = re.search(r"\b(\d{6})\b", raw)
    if found:
        pincode = found.group(1)
    location = order.restaurant_location
    return (
        raw or "Address not given",
        getattr(location, "city", "") or "",
        getattr(location, "state", "") or "",
        # Falls back to the branch's own pincode: a courier refuses an order
        # with none at all, and the branch's is nearer than nothing.
        pincode or (getattr(location, "postal_code", "") or ""),
    )


def build_request(order: Order) -> DeliveryRequest:
    """One order, as a courier needs to hear it."""

    location = order.restaurant_location
    line, city, state, pincode = _split_address(order)

    pickup = DeliveryAddress(
        address_line_1=(getattr(location, "address_line_1", "") or "").strip() or "Restaurant",
        city=getattr(location, "city", "") or "",
        state=getattr(location, "state", "") or "",
        pincode=getattr(location, "postal_code", "") or "",
        name=getattr(location, "branch_name", "") or "Restaurant",
        mobile=(getattr(location, "phone_number", "") or "").strip(),
        latitude=_coord(getattr(location, "latitude", None)),
        longitude=_coord(getattr(location, "longitude", None)),
    )
    drop = DeliveryAddress(
        address_line_1=line,
        city=city,
        state=state,
        pincode=pincode,
        name=order.contact_name or "Customer",
        mobile=(order.contact_phone or "").strip(),
        instructions=order.special_instructions or "",
    )
    items = [
        DeliveryItem(
            name=item.item_name_snapshot,
            quantity=int(item.quantity or 1),
            price=Decimal(str(item.unit_price or 0)),
            sku=str(item.menu_item_id),
        )
        for item in (order.items or [])
    ]
    # Prepaid unless the money is still to be collected at the door.
    cod = Decimal("0")
    if str(getattr(order, "payment_method", "")) == "COD":
        cod = Decimal(str(order.total_amount or 0))

    ready_at = order.scheduled_at or datetime.now(tz=None)
    return DeliveryRequest(
        reference=str(order.id),
        pickup=pickup,
        drop=drop,
        items=items,
        bill_amount=Decimal(str(order.total_amount or 0)),
        cod_amount=cod,
        ready_at=ready_at,
        deliver_by=ready_at + timedelta(minutes=45) if ready_at else None,
        notes=order.special_instructions or "",
    )


def _coord(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


#: Hosts a booking may be sent to from somebody's laptop.
#:
#: Matched on the hostname rather than the whole URL so a path or a port does
#: not defeat it, and by substring because every courier names its sandbox
#: differently — Pidge uses `store.dev.pidge.in`.
_SANDBOX_HOST_MARKERS = ("dev.", "sandbox", "staging", "localhost", "127.0.0.1", ".test")


def _is_sandbox_host(base_url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or base_url).strip().lower()
    return any(marker in host for marker in _SANDBOX_HOST_MARKERS)


def live_dispatch_blocked_reason() -> str:
    """Why a real rider must not be booked from here, or "" if one may be.

    A development machine books real riders through exactly the same code path
    as production — same task, same provider, same credentials if somebody
    pastes live ones into a local `.env` to try a quote. The failure is not
    hypothetical and it is not recoverable: a human being is sent to a real
    address, and "it was a test order" is not something the rider can be told
    afterwards.

    So pointing a local environment at a courier's PRODUCTION host is refused,
    whatever `enable_delivery_dispatch` says. Quoting against that host stays
    allowed — it costs nothing and books nobody, which is the entire reason
    the quote and dispatch flags are separate.

    `allow_live_dispatch_from_local` is the way out, for the one occasion
    somebody genuinely wants a real delivery from their desk. It is named so
    that turning it on cannot be mistaken for anything else.
    """

    settings = get_settings()
    if settings.allow_live_dispatch_from_local:
        return ""
    if settings.environment.strip().lower() not in LOCAL_ENVIRONMENTS:
        return ""
    if _is_sandbox_host(settings.pidge_base_url):
        return ""
    return (
        f"environment={settings.environment} is local and "
        f"{settings.pidge_base_url} is not a sandbox host"
    )


def should_dispatch(order: Order) -> bool:
    """Whether this order is one a courier should be asked about at all.

    The `enable_delivery_dispatch` check lives HERE rather than only at the
    call site, and that is deliberate. It used to be enforced further out — by
    the registry refusing to build a courier at all — and loosening that so a
    checkout could quote a fee without also booking riders would have left
    dispatch ungated for anything reaching the task directly: a retry, a
    replay, a console call. Booking a rider costs real money, so the guard
    belongs on the function that decides to book one.

    The live-host interlock is here for the same reason, and is deliberately
    NOT a flag somebody can flip by accident: `enable_delivery_dispatch` is a
    rollout dial that gets turned on early and left on, so it is the wrong
    thing to be relying on the day a live credential lands in a local `.env`.
    """

    settings = get_settings()
    if not settings.enable_delivery_dispatch:
        return False
    blocked = live_dispatch_blocked_reason()
    if blocked:
        logger.error(
            "Refusing to book a real rider for order %s: %s. "
            "Quoting still works. Set allow_live_dispatch_from_local to override.",
            order.id,
            blocked,
        )
        return False
    if order.fulfillment_type != OrderFulfillmentType.DELIVERY:
        return False
    if order.status in {OrderStatus.CANCELLED, OrderStatus.DELIVERED, OrderStatus.PAYMENT_PENDING}:
        return False
    return True


def dispatch(db: Session, order: Order) -> OrderDelivery | None:
    """Ask the courier to collect this order. Idempotent.

    Returns the delivery row, or None when there is nothing to do — no
    courier configured, a pickup order, or one already dispatched. The caller
    commits.
    """

    if not should_dispatch(order):
        return None
    existing = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))
    if existing is not None and existing.provider_order_id:
        logger.info("Order %s already has delivery %s", order.id, existing.provider_order_id)
        return existing

    provider = delivery_provider()
    if provider is None:
        return None

    row = existing or OrderDelivery(
        order_id=order.id, provider=provider.name, state=DeliveryState.PENDING.value
    )
    if existing is None:
        db.add(row)
        try:
            # Claim the order before calling out, so a second worker that got
            # here at the same moment loses on the constraint rather than
            # booking a second rider.
            db.flush()
        except IntegrityError:
            db.rollback()
            logger.info("Another worker is already dispatching order %s", order.id)
            return db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))

    try:
        result = provider.create(build_request(order))
    except DeliveryProviderError as error:
        # The row stays, carrying why. "No rider came" then has an answer that
        # is not "read the logs".
        row.last_error = str(error)[:2000]
        logger.warning("Courier refused order %s: %s", order.id, error)
        raise
    row.last_error = ""
    record(db, row, result)
    logger.info(
        "Dispatched order %s to %s as %s", order.id, provider.name, result.provider_order_id
    )
    return row


def cancel(db: Session, order: Order) -> OrderDelivery | None:
    """Call off the rider booked for this order. Idempotent.

    Returns the delivery row, or None when no rider was ever booked. The
    caller commits.

    Not behind `enable_delivery_dispatch` or the live-host interlock, and that
    is deliberate. Both exist to stop a rider being BOOKED; this un-books one,
    and it can only ever act on a row that carries a courier's own id — which
    means a booking that really happened. Gating it would leave the one
    failure those guards cannot produce: a real rider riding to a cancelled
    order because the flag was turned off after they were sent.

    A refusal is recorded and re-raised rather than swallowed. Pidge refuses
    once the food is collected, and "the rider still has it" is something a
    person has to deal with — the row must not say CANCELLED when a bike is
    on its way to somebody's door.
    """

    row = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))
    if row is None or not row.provider_order_id:
        return None
    try:
        if DeliveryState(row.state).is_terminal:
            return row
    except ValueError:
        # A state this code has never seen is not known to be finished, so
        # the courier is still asked.
        pass

    provider = delivery_provider()
    if provider is None:
        return None
    try:
        provider.cancel(row.provider_order_id)
    except DeliveryProviderError as error:
        row.last_error = str(error)[:2000]
        logger.warning(
            "Courier would not cancel delivery %s for order %s: %s",
            row.provider_order_id,
            order.id,
            error,
        )
        raise
    row.state = DeliveryState.CANCELLED.value
    row.provider_status = "cancelled"
    row.last_error = ""
    logger.info("Cancelled delivery %s for order %s", row.provider_order_id, order.id)
    return row


#: Courier states a person can do nothing more about, as statuses Pidge
#: reports. Read by `can_rebook`.
_REBOOKABLE = {DeliveryState.FAILED.value, DeliveryState.CANCELLED.value}


def _notify_after_commit(db: Session, order: Order, status: OrderStatus) -> None:
    """Tell the customer their order moved, once the move is committed.

    The same task a kitchen tap sends (`update_order_status`). Queued from
    `after_commit` so a rolled-back record announces nothing, and swallowed
    there because a broker that is down must not undo a delivery update.
    """

    from app.config.celery import celery_app

    kwargs = {
        "order_id": str(order.id),
        "customer_id": str(order.customer_id),
        "restaurant_id": str(order.restaurant_id),
        "new_status": status.value,
    }

    def _send(_session: Session) -> None:
        try:
            celery_app.send_task("app.tasks.notifications.send_order_status_notification", kwargs=kwargs)
        except Exception:  # noqa: BLE001
            logger.warning("Could not queue the status notification for order %s", order.id, exc_info=True)

    event.listen(db, "after_commit", _send, once=True)


def record(db: Session, row: OrderDelivery, result: DeliveryResult) -> OrderDelivery:
    """Write a courier's answer onto the delivery, and move the order if it should.

    A move is made the way a kitchen tap makes one: an order status event
    in the same transaction (history, the live boards, "Done today"), and a
    notification to the customer after the commit. It used to set
    `order.status` and nothing else, so a delivered order had no DELIVERED
    event - it never appeared under Done today - and its customer was never
    told the food had arrived.
    """

    if result.provider_order_id:
        row.provider_order_id = result.provider_order_id
    row.state = result.state.value
    row.provider_status = result.provider_status or ""
    if result.rider_name:
        row.rider_name = result.rider_name
    if result.rider_mobile:
        row.rider_mobile = result.rider_mobile
    if result.tracking_url:
        row.tracking_url = result.tracking_url
    if result.distance_metres is not None:
        row.distance_metres = result.distance_metres
    if result.picked_up_at is not None:
        row.picked_up_at = result.picked_up_at
    if result.delivered_at is not None:
        row.delivered_at = result.delivered_at
    if result.raw:
        row.raw = result.raw
    # Kept once learned: a later answer without them (the sandbox's, or a
    # finished trip's) must not blank what the screen already showed.
    if result.pickup_eta is not None:
        row.pickup_eta = result.pickup_eta
    if result.drop_eta is not None:
        row.drop_eta = result.drop_eta
    if result.courier_charge is not None:
        row.courier_charge = result.courier_charge
    if result.rider_latitude is not None and result.rider_longitude is not None:
        if row.rider_location_at is None or result.rider_location_at is None or (
            result.rider_location_at >= row.rider_location_at
        ):
            row.rider_latitude = result.rider_latitude
            row.rider_longitude = result.rider_longitude
            row.rider_location_at = result.rider_location_at
    if result.timeline:
        row.timeline = result.timeline
    if result.failure_reason:
        row.failure_reason = result.failure_reason
    order = row.order
    if order is not None:
        before = order.status
        if advance_order(order, result.state):
            from app.services.order_events import record_order_status_event
            from app.models.enums import OrderEventActor

            record_order_status_event(
                db,
                order=order,
                from_status=before,
                to_status=order.status,
                actor=OrderEventActor.SYSTEM,
                note=f"courier: {(result.provider_status or result.state.value).lower()}",
                metadata={"source": "courier", "provider": row.provider, "courier_status": result.provider_status},
                occurred_at=(
                    result.delivered_at
                    if order.status == OrderStatus.DELIVERED and result.delivered_at
                    else None
                ),
            )
            _notify_after_commit(db, order, order.status)
    return row


def can_cancel(order: Order, row: OrderDelivery | None) -> bool:
    """Whether a person may call this rider off.

    Narrower than `cancel` itself, which the system path also uses for an
    order it has just cancelled. A person is offered it only while the order
    still stands and the food has not been collected - Pidge refuses after
    that. Without the order check, an order closed by hand whose courier row
    never moved past PENDING offered "Cancel rider" on a finished delivery.
    """

    if row is None or not row.provider_order_id:
        return False
    if row.state not in {DeliveryState.PENDING.value, DeliveryState.ASSIGNED.value}:
        return False
    return order.status not in {OrderStatus.DELIVERED, OrderStatus.CANCELLED}


def can_rebook(order: Order, row: OrderDelivery | None) -> bool:
    """Whether a new rider may be asked for: the last trip is over and the food is not."""

    if row is None or row.state not in _REBOOKABLE:
        return False
    return order.status in {OrderStatus.ACCEPTED, OrderStatus.PREPARING, OrderStatus.OUT_FOR_DELIVERY}


def rebook(db: Session, order: Order) -> OrderDelivery:
    """Book another rider for an order whose delivery failed or was called off.

    The row is reused - `order_id` is unique, which is what stops two riders
    being booked by accident - and its attempt number goes up, because Pidge
    refuses a reference it has seen before. The old trip's id is kept in
    `raw` history only through the courier's own records; this row now
    describes the new one.

    Every guard on a first booking applies: the dispatch flag, the live-host
    interlock, a delivery order that is still standing. The caller commits.
    """

    row = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))
    if not can_rebook(order, row):
        raise DeliveryProviderError("This order's delivery cannot be re-booked now.", retryable=False)
    if not should_dispatch(order):
        raise DeliveryProviderError(
            "Rider booking is switched off on this server, so no rider can be booked.", retryable=False
        )
    provider = delivery_provider()
    if provider is None:
        raise DeliveryProviderError("No delivery partner is configured.", retryable=False)

    attempt = (row.attempt or 1) + 1
    request = build_request(order)
    request.reference = f"{order.id}-{attempt}"
    try:
        result = provider.create(request)
    except DeliveryProviderError as error:
        row.last_error = str(error)[:2000]
        raise
    row.attempt = attempt
    row.state = DeliveryState.PENDING.value
    row.rider_name = row.rider_mobile = row.tracking_url = row.failure_reason = row.last_error = ""
    row.rider_latitude = row.rider_longitude = row.rider_location_at = None
    row.picked_up_at = row.delivered_at = row.pickup_eta = row.drop_eta = None
    row.courier_charge = None
    row.timeline = []
    record(db, row, result)
    logger.info("Re-booked order %s as %s (attempt %s)", order.id, result.provider_order_id, attempt)
    return row


def simulate_allowed() -> bool:
    """Only against the courier's sandbox, where nothing reaches a rider."""

    return _is_sandbox_host(get_settings().pidge_base_url)


def simulate(db: Session, order: Order, courier_status: str) -> OrderDelivery:
    """Make the sandbox say a trip reached `courier_status`, and record it.

    For testing and demonstrating the whole flow without a rider: it goes
    through `record` exactly as a real update does, so the order moves, the
    history is written and the customer is notified. Refused on any host but
    the sandbox. The caller commits.
    """

    if not simulate_allowed():
        raise DeliveryProviderError("Simulating is only possible on the courier's sandbox.", retryable=False)
    row = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))
    provider = delivery_provider()
    if row is None or not row.provider_order_id or provider is None or not hasattr(provider, "fetch"):
        raise DeliveryProviderError("This order has no courier booking to simulate.", retryable=False)
    result = provider.fetch(row.provider_order_id, simulate=courier_status)
    record(db, row, result)
    return row


def advance_order(order: Order, state: DeliveryState) -> bool:
    """Move the order to where this delivery state says it is — forward only.

    Status pushes arrive late and out of order. Without this, a delayed
    IN_TRANSIT landing after DELIVERED would drag a finished order back onto
    the road, and the customer would be told their delivered dinner is on its
    way.
    """

    wanted = _ORDER_STATUS_FOR.get(state)
    if wanted is None or order.status == wanted:
        return False
    if order.status in {OrderStatus.CANCELLED, OrderStatus.PAYMENT_PENDING}:
        return False
    try:
        if _FORWARD.index(wanted) <= _FORWARD.index(order.status):
            return False
    except ValueError:
        return False
    order.status = wanted
    return True


__all__ = [
    "advance_order", "build_request", "can_rebook", "cancel", "dispatch", "rebook",
    "record", "should_dispatch", "simulate", "simulate_allowed",
]
