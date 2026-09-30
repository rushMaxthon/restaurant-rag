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

from app.models.enums import OrderFulfillmentType, OrderStatus
from app.models.order import Order
from app.models.order_delivery import OrderDelivery
from app.services.delivery.base import (
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


def should_dispatch(order: Order) -> bool:
    """Whether this order is one a courier should be asked about at all."""

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
