"""Offering a delivery to the platform's riders, one at a time, nearest first.

`advance` is one step of a small state machine and is safe to call any number
of times from anywhere: the API after a decline, a Celery countdown when an
offer's 30 seconds run out, the 10-second beat as a safety net. It locks the
delivery row, so two callers at once take turns instead of offering twice.

    PENDING delivery
      -> no trip, no open offer, a candidate   -> offer to the nearest   "offered"
      -> open offer still inside its window    -> nothing                "waiting"
      -> open offer past its window            -> EXPIRED, then again
      -> cash / branch not served / window over / max offers / nobody near
                                               -> Pidge, with the reason "fallback"
      -> a live trip exists                    -> nothing                "assigned"

`accept` takes the same row lock, so the race between two taps (or two
phones) ends with exactly one trip; `uq_rider_trips_one_live` is the second
guard if anything slips past the lock.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import OfferOutcome, OrderStatus, PaymentMethod, RiderStatus
from app.models.order import Order
from app.models.order_delivery import OrderDelivery
from app.models.rider import Rider, RiderOffer, RiderTrip
from app.models.user import User
from app.services.delivery.base import DeliveryState
from app.services.fleet.config import FleetConfig, load_fleet

logger = logging.getLogger(__name__)

PROVIDER = "own_fleet"


def _now() -> datetime:
    return datetime.now(UTC)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line metres. Good enough to rank riders; trips are priced elsewhere."""

    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


#: What each fleet event reads as in the admin's delivery timeline.
_REMARKS = {
    "offered": "Offered to a rider",
    "offer_expired": "Rider did not answer in time",
    "offer_declined": "Rider declined",
    "assigned": "Rider accepted",
    "reassigned": "Reassigned by the platform",
    "fallback": "Handed to the courier",
    "arrived_pickup": "Rider at the restaurant",
    "call_logged": "Rider called the customer",
    "otp_locked": "Delivery code locked after wrong tries",
    "confirmed_by_admin": "Delivered, confirmed by the platform",
}


def timeline(delivery: OrderDelivery, event: str, **data: Any) -> None:
    """Append a step in the SAME shape a courier's steps have (`status`, `at`,
    `remark`), so the admin's delivery timeline renders both couriers alike;
    `event` and the extra keys are ours."""

    remark = _REMARKS.get(event, event.replace("_", " ").capitalize())
    if data.get("reason"):
        remark = f"{remark}: {data['reason']}"
    entries = list(delivery.timeline or [])
    entries.append({"status": event.upper(), "at": _now().isoformat(), "remark": remark, "event": event, **data})
    delivery.timeline = entries


def _branch_point(db: Session, delivery: OrderDelivery) -> tuple[Order, float | None, float | None]:
    order = db.get(Order, delivery.order_id)
    branch = order.restaurant_location
    lat = float(branch.latitude) if branch.latitude is not None else None
    lng = float(branch.longitude) if branch.longitude is not None else None
    return order, lat, lng


def candidates(
    db: Session, delivery: OrderDelivery, fleet: FleetConfig, now: datetime
) -> list[tuple[Rider, float]]:
    """Online, recently seen, within the radius, not tried yet, not looking at
    another offer - nearest first."""

    _, lat, lng = _branch_point(db, delivery)
    if lat is None or lng is None:
        return []
    tried = set(db.scalars(select(RiderOffer.rider_user_id).where(RiderOffer.order_delivery_id == delivery.id)))
    busy = set(db.scalars(select(RiderOffer.rider_user_id).where(RiderOffer.outcome == OfferOutcome.PENDING)))
    fresh_after = now - timedelta(minutes=fleet.silent_minutes)
    rows = db.scalars(
        select(Rider)
        .join(User, User.id == Rider.user_id)
        .where(
            Rider.status == RiderStatus.ONLINE,
            User.is_active.is_(True),
            Rider.last_location_at >= fresh_after,
            Rider.last_latitude.is_not(None),
            Rider.last_longitude.is_not(None),
        )
    ).all()
    limit = fleet.radius_km * 1000
    found: list[tuple[Rider, float]] = []
    for rider in rows:
        if rider.user_id in tried or rider.user_id in busy:
            continue
        metres = haversine_m(rider.last_latitude, rider.last_longitude, lat, lng)
        if metres <= limit:
            found.append((rider, metres))
    return sorted(found, key=lambda pair: pair[1])


def _refusal(db: Session, delivery: OrderDelivery, fleet: FleetConfig, now: datetime) -> str | None:
    """Why this delivery should go to Pidge rather than to another rider, if it should."""

    order, _, _ = _branch_point(db, delivery)
    if order.payment_method == PaymentMethod.COD:
        # The fleet carries no cash (decided 2026-10-08): nobody to reconcile it.
        return "cash order"
    if fleet.location_ids and str(order.restaurant_location_id) not in fleet.location_ids:
        return "branch not on the fleet"
    started = delivery.created_at or now
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    if now - started > timedelta(minutes=fleet.window_minutes):
        return f"no rider within {fleet.window_minutes} minutes"
    tried = db.scalar(select(func.count(RiderOffer.id)).where(RiderOffer.order_delivery_id == delivery.id)) or 0
    if tried >= fleet.max_offers:
        return "no rider accepted"
    return None


def _lock(db: Session, delivery_id: uuid.UUID) -> OrderDelivery | None:
    return db.scalar(select(OrderDelivery).where(OrderDelivery.id == delivery_id).with_for_update())


#: The order is finished: nothing for a rider to carry.
_ORDER_CLOSED = {OrderStatus.CANCELLED, OrderStatus.DELIVERED}


def _offerable(db: Session, delivery: OrderDelivery) -> bool:
    """Still ours, still waiting for a rider, and the food still needs carrying."""

    if delivery.provider != PROVIDER or delivery.state != DeliveryState.PENDING.value:
        return False
    order = db.get(Order, delivery.order_id)
    return order is not None and order.status not in _ORDER_CLOSED


def advance(db: Session, delivery_id: uuid.UUID, now: datetime | None = None) -> str:
    """One step of the loop. Commits. See the module docstring for the outcomes."""

    from app.services.delivery import service as delivery_service
    from app.services.fleet import notify

    now = now or _now()
    delivery = _lock(db, delivery_id)
    if delivery is None or delivery.provider != PROVIDER or DeliveryState(delivery.state).is_terminal:
        db.rollback()
        return "closed"
    order = db.get(Order, delivery.order_id)
    if order is None or order.status in _ORDER_CLOSED:
        # A cancel whose task was lost must not keep riders (or the courier)
        # being offered food nobody wants (review finding, 2026-10-08).
        db.rollback()
        return "closed"
    live = db.scalar(
        select(RiderTrip.id).where(RiderTrip.order_delivery_id == delivery.id, RiderTrip.ended_at.is_(None))
    )
    if live is not None:
        db.rollback()
        return "assigned"
    fleet = load_fleet(db)
    expired: RiderOffer | None = None
    open_offer = db.scalar(
        select(RiderOffer).where(
            RiderOffer.order_delivery_id == delivery.id, RiderOffer.outcome == OfferOutcome.PENDING
        )
    )
    if open_offer is not None:
        expires = open_offer.expires_at if open_offer.expires_at.tzinfo else open_offer.expires_at.replace(tzinfo=UTC)
        if expires > now:
            db.rollback()
            return "waiting"
        open_offer.outcome, open_offer.responded_at = OfferOutcome.EXPIRED, now
        timeline(delivery, "offer_expired", rider=str(open_offer.rider_user_id))
        db.flush()
        expired = open_offer

    reason = _refusal(db, delivery, fleet, now)
    pool = [] if reason else candidates(db, delivery, fleet, now)
    if not reason and not pool:
        reason = "no rider online nearby"
    if reason:
        timeline(delivery, "fallback", reason=reason)
        delivery_service.fallback_to_pidge(db, delivery, reason)
        db.commit()
        if expired is not None:
            notify.offer_withdrawn(db, expired)
        logger.info("Delivery %s goes to the courier: %s", delivery.id, reason)
        return "fallback"

    rider, metres = pool[0]
    offer = RiderOffer(
        order_delivery_id=delivery.id,
        rider_user_id=rider.user_id,
        offered_at=now,
        expires_at=now + timedelta(seconds=fleet.offer_seconds),
        distance_to_pickup_m=round(metres, 1),
    )
    db.add(offer)
    timeline(delivery, "offered", rider=str(rider.user_id), metres=round(metres))
    db.commit()
    if expired is not None:
        notify.offer_withdrawn(db, expired)
    notify.offer_made(db, offer)
    schedule_expiry(delivery.id, fleet.offer_seconds)
    return "offered"


def accept(db: Session, rider_user: User, offer_id: uuid.UUID, now: datetime | None = None) -> RiderTrip:
    now = now or _now()
    offer = db.get(RiderOffer, offer_id)
    if offer is None or offer.rider_user_id != rider_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")
    delivery = _lock(db, offer.order_delivery_id)
    db.refresh(offer)
    if delivery is None or offer.outcome != OfferOutcome.PENDING:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "offer_taken")
    if not _offerable(db, delivery):
        # Cancelled, handed to the courier, or already carried since the
        # offer went out: the offer is void even if it never got withdrawn.
        offer.outcome, offer.responded_at = OfferOutcome.WITHDRAWN, now
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "offer_withdrawn")
    expires = offer.expires_at if offer.expires_at.tzinfo else offer.expires_at.replace(tzinfo=UTC)
    if expires <= now:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "offer_expired")
    offer.outcome, offer.responded_at = OfferOutcome.ACCEPTED, now
    trip = RiderTrip(order_delivery_id=delivery.id, rider_user_id=rider_user.id, accepted_at=now)
    db.add(trip)
    rider = db.get(Rider, rider_user.id)
    rider.status, rider.status_at = RiderStatus.ON_TRIP, now
    delivery.state = DeliveryState.ASSIGNED.value
    delivery.rider_name = rider_user.full_name or "Rider"
    delivery.rider_mobile = rider_user.phone_number or ""
    delivery.allocated_at = now
    if not delivery.provider_order_id:
        delivery.provider_order_id = f"fleet-{delivery.id}"
    timeline(delivery, "assigned", rider=str(rider_user.id))
    try:
        db.commit()
    except IntegrityError:
        # uq_rider_trips_one_live: another accept committed first.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "offer_taken") from None
    from app.services.fleet import notify

    notify.trip_changed(db, trip)
    logger.info("Rider %s accepted delivery %s", rider_user.id, delivery.id)
    return trip


def decline(db: Session, rider_user: User, offer_id: uuid.UUID) -> None:
    offer = db.get(RiderOffer, offer_id)
    if offer is None or offer.rider_user_id != rider_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")
    delivery = _lock(db, offer.order_delivery_id)
    db.refresh(offer)
    if offer.outcome == OfferOutcome.PENDING:
        offer.outcome, offer.responded_at = OfferOutcome.DECLINED, _now()
        if delivery is not None:
            timeline(delivery, "offer_declined", rider=str(rider_user.id))
        db.commit()
    queue_advance(offer.order_delivery_id)


def current_offer(db: Session, rider_user: User) -> RiderOffer | None:
    return db.scalar(
        select(RiderOffer)
        .where(
            RiderOffer.rider_user_id == rider_user.id,
            RiderOffer.outcome == OfferOutcome.PENDING,
            RiderOffer.expires_at > _now(),
        )
        .order_by(RiderOffer.offered_at.desc())
    )


def reassign(db: Session, admin: User, delivery: OrderDelivery, rider_user_id: uuid.UUID) -> RiderOffer:
    """Admin: take the delivery from our current rider (or nobody) and offer it to this one.

    Never from the courier: a Pidge booking would keep its rider coming and
    its webhook writing onto our trip (review finding). Cancel it there first.
    """

    delivery = _lock(db, delivery.id)
    if delivery.provider not in {PROVIDER, "unassigned"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "courier_has_it")
    order = db.get(Order, delivery.order_id)
    if order is None or order.status in _ORDER_CLOSED:
        raise HTTPException(status.HTTP_409_CONFLICT, "delivery_finished")
    rider = db.get(Rider, rider_user_id)
    rider_account = db.get(User, rider_user_id)
    if rider is None or rider_account is None or not rider_account.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rider not found")
    if rider.status != RiderStatus.ONLINE:
        raise HTTPException(status.HTTP_409_CONFLICT, "rider_offline")
    busy = db.scalar(
        select(RiderOffer.id).where(
            RiderOffer.rider_user_id == rider_user_id,
            RiderOffer.outcome == OfferOutcome.PENDING,
            RiderOffer.order_delivery_id != delivery.id,
        )
    )
    if busy is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "rider_busy")
    if DeliveryState(delivery.state).is_terminal:
        raise HTTPException(status.HTTP_409_CONFLICT, "delivery_finished")
    from app.services.fleet import notify, trips

    trips.end_live_trip(db, delivery, reason="REASSIGNED")
    withdrawn = list(
        db.scalars(
            select(RiderOffer).where(
                RiderOffer.order_delivery_id == delivery.id, RiderOffer.outcome == OfferOutcome.PENDING
            )
        )
    )
    now = _now()
    for old in withdrawn:
        old.outcome, old.responded_at = OfferOutcome.WITHDRAWN, now
    db.flush()
    delivery.provider = PROVIDER
    delivery.state = DeliveryState.PENDING.value
    fleet = load_fleet(db)
    offer = RiderOffer(
        order_delivery_id=delivery.id,
        rider_user_id=rider_user_id,
        offered_at=now,
        expires_at=now + timedelta(seconds=fleet.offer_seconds),
    )
    db.add(offer)
    timeline(delivery, "reassigned", by=str(admin.id), rider=str(rider_user_id))
    db.commit()
    for old in withdrawn:
        notify.offer_withdrawn(db, old)
    notify.offer_made(db, offer)
    schedule_expiry(delivery.id, fleet.offer_seconds)
    return offer


def queue_advance(delivery_id: uuid.UUID) -> None:
    """Take the next step soon, on a worker. Never raises: the beat is the backstop."""

    try:
        from app.tasks.fleet import advance_delivery_task

        advance_delivery_task.delay(str(delivery_id))
    except Exception:  # noqa: BLE001
        logger.warning("Could not queue the offer loop for %s; the beat will pick it up", delivery_id)


def queue_advance_after_commit(db: Session, delivery_id: uuid.UUID) -> None:
    """`queue_advance`, but only once the caller's transaction is committed.

    A worker that ran before the commit would not see the new delivery row
    and would close the loop on it.
    """

    from sqlalchemy import event

    def _go(_session: Session) -> None:
        queue_advance(delivery_id)

    event.listen(db, "after_commit", _go, once=True)


def schedule_expiry(delivery_id: uuid.UUID, seconds: int) -> None:
    """Re-run the loop the moment this offer's window closes."""

    try:
        from app.tasks.fleet import advance_delivery_task

        advance_delivery_task.apply_async((str(delivery_id),), countdown=seconds + 1)
    except Exception:  # noqa: BLE001
        logger.warning("Could not schedule offer expiry for %s; the beat will pick it up", delivery_id)


__all__ = [
    "PROVIDER", "accept", "advance", "candidates", "current_offer", "decline", "haversine_m",
    "queue_advance", "queue_advance_after_commit", "reassign", "schedule_expiry", "timeline",
]
