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

from sqlalchemy import select
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


def record(db: Session, row: OrderDelivery, result: DeliveryResult) -> OrderDelivery:
    """Write a courier's answer onto the delivery, and move the order if it should."""

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
    if row.order is not None:
        advance_order(row.order, result.state)
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


__all__ = ["advance_order", "build_request", "dispatch", "record", "should_dispatch"]
