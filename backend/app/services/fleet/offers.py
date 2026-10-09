"""Offering a delivery to the platform's riders, one at a time, nearest first.

`advance` is one step of a small state machine and is safe to call any number
of times from anywhere: the API after a decline, a Celery countdown when an
offer's 30 seconds run out, the 10-second beat as a safety net. It locks the
delivery row, so two callers at once take turns instead of offering twice.

    PENDING delivery
      -> no trip, no open offer, a candidate   -> offer to the nearest   "offered"
      -> open offer still inside its window    -> nothing                "waiting"
      -> open offer past its window            -> EXPIRED, then again
      -> nobody free, or max_offers pinged     -> stays open to all      "open"
      -> cash / branch not served / window over
                                               -> Pidge, with the reason "fallback"

An OPEN delivery is on every free nearby rider's list (`open_orders`) and any
of them may `claim` it; our riders get the whole window before Pidge does.
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

from app.models.enums import OfferOutcome, OrderStatus, PaymentMethod, RiderOnboarding, RiderStatus
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
    "claimed": "Rider took it from the open orders",
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
            # Belt and braces: a pending rider cannot go online, but a rider
            # rejected while online must not be offered the next order.
            Rider.onboarding == RiderOnboarding.APPROVED,
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


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def ready_time(db: Session, delivery: OrderDelivery) -> datetime | None:
    """When the food should be ready (`fleet.ready`); None if the branch has no prep time."""

    from app.services.fleet.ready import ready_at

    order = db.get(Order, delivery.order_id)
    if order is None:
        return None
    return ready_at(db, order, accepted_fallback=delivery.created_at)


def opens_at(db: Session, delivery: OrderDelivery, fleet: FleetConfig, now: datetime) -> datetime:
    """When riders hear of this order: `ready_lead_minutes` before the food is ready.

    The owner's rule (2026-10-10): a rider told at the moment of acceptance
    and riding over at once waits at the counter. Ready sooner than the lead,
    or with no preparation time known, it is the moment the row was made - as
    before. The waves and the courier window both count from here, and the
    board, the one-by-one pings and `claim` all ask this one function.
    """

    created = _aware(delivery.created_at or now)
    ready = ready_time(db, delivery)
    if ready is None:
        return created
    return max(created, ready - timedelta(minutes=fleet.ready_lead_minutes))


def reach_m(db: Session, delivery: OrderDelivery, fleet: FleetConfig, now: datetime) -> float:
    """How far from the branch a rider may be to see - and take - this order now.

    The nearest riders first (the owner's rule, 2026-10-09): `first_wave_km`
    to begin with, one ring further every `wave_minutes`, never past
    `radius_km`. A ring with nobody free in it is skipped at once - waiting
    two minutes on an empty ring helps no one - and so is a rider who already
    said no to this order (declined, or let the offer run out). A rider
    still being ASKED does count: their 30 seconds are what the wave is for.
    """

    full = fleet.radius_km * 1000
    step = min(fleet.first_wave_km, fleet.radius_km) * 1000
    started = opens_at(db, delivery, fleet, now)
    wave = int(max(0.0, (now - started).total_seconds()) // (fleet.wave_minutes * 60))
    ring = min(full, step * (wave + 1))
    if ring >= full:
        return full
    _, lat, lng = _branch_point(db, delivery)
    if lat is None or lng is None:
        return full
    said_no = set(
        db.scalars(
            select(RiderOffer.rider_user_id).where(
                RiderOffer.order_delivery_id == delivery.id,
                RiderOffer.outcome.in_([OfferOutcome.DECLINED, OfferOutcome.EXPIRED]),
            )
        )
    )
    fresh_after = now - timedelta(minutes=fleet.silent_minutes)
    free = db.execute(
        select(Rider.user_id, Rider.last_latitude, Rider.last_longitude)
        .join(User, User.id == Rider.user_id)
        .where(
            Rider.status == RiderStatus.ONLINE,
            Rider.onboarding == RiderOnboarding.APPROVED,
            User.is_active.is_(True),
            Rider.last_location_at >= fresh_after,
            Rider.last_latitude.is_not(None),
            Rider.last_longitude.is_not(None),
        )
    ).all()
    nearest = min(
        (haversine_m(r_lat, r_lng, lat, lng) for uid, r_lat, r_lng in free if uid not in said_no),
        default=None,
    )
    if nearest is not None and nearest > ring:
        ring = min(full, math.ceil(nearest / step) * step)
    return ring


def _refusal(db: Session, delivery: OrderDelivery, fleet: FleetConfig, now: datetime) -> str | None:
    """Why this delivery should go to Pidge rather than to another rider, if it should."""

    order, _, _ = _branch_point(db, delivery)
    if order.payment_method == PaymentMethod.COD:
        # The fleet carries no cash (decided 2026-10-08): nobody to reconcile it.
        return "cash order"
    if fleet.location_ids and str(order.restaurant_location_id) not in fleet.location_ids:
        return "branch not on the fleet"
    if now - opens_at(db, delivery, fleet, now) > timedelta(minutes=fleet.window_minutes):
        return f"no rider within {fleet.window_minutes} minutes"
    # Nobody free, nobody accepting, max_offers spent: none of these is a
    # reason any more. Our riders come first (2026-10-08) - the order stays
    # open to them until the window above closes.
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
    if reason:
        timeline(delivery, "fallback", reason=reason)
        delivery_service.fallback_to_pidge(db, delivery, reason)
        db.commit()
        if expired is not None:
            notify.offer_withdrawn(db, expired)
        logger.info("Delivery %s goes to the courier: %s", delivery.id, reason)
        return "fallback"

    # The food is not near ready yet: nobody is rung, and the beat comes back.
    if now < opens_at(db, delivery, fleet, now):
        db.commit()
        if expired is not None:
            notify.offer_withdrawn(db, expired)
        return "holding"

    # Riders are pinged one by one up to max_offers; after that, or with
    # nobody free right now, the order simply stays OPEN: on every free
    # rider's list (`open_orders`) and re-tried by the beat every 10 s, so a
    # rider who comes online is offered it.
    tried = db.scalar(select(func.count(RiderOffer.id)).where(RiderOffer.order_delivery_id == delivery.id)) or 0
    pool = candidates(db, delivery, fleet, now) if tried < fleet.max_offers else []
    if not pool:
        db.commit()
        if expired is not None:
            notify.offer_withdrawn(db, expired)
        return "open"

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
    return _start_trip(db, delivery, rider_user, now, conflict="offer_taken")


def _start_trip(
    db: Session, delivery: OrderDelivery, rider_user: User, now: datetime, *, conflict: str
) -> RiderTrip:
    """The one place a trip begins, for an accepted offer and a claimed open order alike.

    Caller holds the delivery row lock. `uq_rider_trips_one_live` is the second
    guard: if another trip committed first, this one rolls back with `conflict`.
    """

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
        raise HTTPException(status.HTTP_409_CONFLICT, conflict) from None
    from app.services.fleet import notify

    notify.trip_changed(db, trip)
    # Online -> on a trip on the admin's list and map; a rider's name on the
    # customer's order page and the restaurant's boards.
    notify.riders_changed(rider_user.id, force=True)
    notify.delivery_changed(db, delivery, "rider_assigned")
    logger.info("Rider %s took delivery %s", rider_user.id, delivery.id)
    return trip


def _window_left(started: datetime, fleet: FleetConfig, now: datetime) -> timedelta:
    """Time left before the courier takes it, counted from `opens_at`."""

    return started + timedelta(minutes=fleet.window_minutes) - now


def _why_not_free(db: Session, rider_user_id: uuid.UUID) -> str | None:
    """Why this rider cannot take an order right now, or None if they can."""

    rider = db.get(Rider, rider_user_id)
    if rider is not None and rider.onboarding != RiderOnboarding.APPROVED:
        return "rider_not_approved"
    if rider is None or rider.status == RiderStatus.OFFLINE:
        return "rider_offline"
    live = db.scalar(select(RiderTrip.id).where(RiderTrip.rider_user_id == rider_user_id, RiderTrip.ended_at.is_(None)))
    if live is not None or rider.status == RiderStatus.ON_TRIP:
        return "rider_busy"
    return None


def open_orders(db: Session, rider_user: User, now: datetime | None = None) -> list[dict[str, Any]]:
    """The Orders board: what our fleet still holds near this rider, nearest first.

    Visible to any active rider within the order's current wave
    (`reach_m`, at most `radius_km`) of where they last reported - offline, mid-trip or free - because it is a board they check
    any time (2026-10-08). TAKING one is what needs them online and free, and
    `claim` enforces that. It includes an order being offered to someone else
    (first come, first served) and one whose offer to THIS rider ran out while
    they were not looking, flagged `missed`.
    """

    # The board is for riders who may take what is on it: an applicant
    # still under review sees an empty list, not orders they cannot claim.
    me = db.get(Rider, rider_user.id)
    if me is None or me.onboarding != RiderOnboarding.APPROVED:
        return []

    from app.services.fleet.earnings import earning_for
    from app.services.fleet.trips import trip_km

    now = now or _now()
    rider = db.get(Rider, rider_user.id)
    if rider is None or not rider_user.is_active:
        return []
    fleet = load_fleet(db)
    missed = set(
        db.scalars(
            select(RiderOffer.order_delivery_id).where(
                RiderOffer.rider_user_id == rider_user.id,
                RiderOffer.outcome.in_([OfferOutcome.EXPIRED, OfferOutcome.DECLINED]),
            )
        )
    )
    from app.services.fleet.config import load_pay

    pay = load_pay(db)
    live = select(RiderTrip.order_delivery_id).where(RiderTrip.ended_at.is_(None))
    rows = db.scalars(
        select(OrderDelivery)
        .join(Order, Order.id == OrderDelivery.order_id)
        .where(
            OrderDelivery.provider == PROVIDER,
            OrderDelivery.state == DeliveryState.PENDING.value,
            Order.status.not_in(list(_ORDER_CLOSED)),
            OrderDelivery.id.not_in(live),
        )
    ).all()
    out: list[dict[str, Any]] = []
    for delivery in rows:
        opens = opens_at(db, delivery, fleet, now)
        if now < opens:
            # Not near ready yet: riders hear of it a little before it is.
            continue
        left = _window_left(opens, fleet, now)
        if left.total_seconds() <= 0:
            continue
        order, lat, lng = _branch_point(db, delivery)
        metres = None
        if None not in (lat, lng, rider.last_latitude, rider.last_longitude):
            metres = haversine_m(rider.last_latitude, rider.last_longitude, lat, lng)
            # Nearest riders first: further out it appears wave by wave.
            if metres > reach_m(db, delivery, fleet, now):
                continue
        km = trip_km(db, delivery)
        estimate, _ = earning_for(km, pay)
        out.append({
            "order_id": order.id,
            "delivery": delivery,
            "order": order,
            "pickup_distance_m": round(metres, 1) if metres is not None else None,
            "trip_distance_km": round(km, 1),
            "earning_estimate": estimate,
            "minutes_left": max(1, int(left.total_seconds() // 60)),
            "missed": delivery.id in missed,
            "ready_at": ready_time(db, delivery),
        })
    out.sort(key=lambda r: (r["pickup_distance_m"] is None, r["pickup_distance_m"] or 0))
    return out


def claim(db: Session, rider_user: User, order_id: uuid.UUID, now: datetime | None = None) -> RiderTrip:
    """A free rider takes an open order from the list. Same lock as `accept`.

    Refused with `order_taken` once anyone else has it - another rider, the
    courier, or nobody because the window closed and it is on its way to
    Pidge - so the app can say one plain thing and refresh the list.
    """

    from app.services.fleet import notify

    now = now or _now()
    delivery_id = db.scalar(select(OrderDelivery.id).where(OrderDelivery.order_id == order_id))
    if delivery_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    delivery = _lock(db, delivery_id)
    blocked = _why_not_free(db, rider_user.id)
    if blocked is not None:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, blocked)
    fleet = load_fleet(db)
    if delivery is None or delivery.provider != PROVIDER or not _offerable(db, delivery):
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "order_taken")
    opens = opens_at(db, delivery, fleet, now)
    if now < opens:
        # The board does not show it yet; a stale one must not take it early.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "order_not_open")
    if _window_left(opens, fleet, now).total_seconds() <= 0:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "order_taken")
    # The board hides an order from riders outside its wave; a stale board
    # (or a moved rider) must not take it ahead of the riders it is for.
    me = db.get(Rider, rider_user.id)
    _, lat, lng = _branch_point(db, delivery)
    if None not in (lat, lng, me.last_latitude, me.last_longitude):
        if haversine_m(me.last_latitude, me.last_longitude, lat, lng) > reach_m(db, delivery, fleet, now):
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "order_not_near")
    withdrawn = list(
        db.scalars(
            select(RiderOffer).where(
                RiderOffer.order_delivery_id == delivery.id, RiderOffer.outcome == OfferOutcome.PENDING
            )
        )
    )
    for other in withdrawn:
        other.outcome, other.responded_at = OfferOutcome.WITHDRAWN, now
    # Recorded as an accepted offer so the admin's offer history and the
    # one-offer-per-rider rules read a claim the same way as an accept.
    db.add(RiderOffer(
        order_delivery_id=delivery.id,
        rider_user_id=rider_user.id,
        offered_at=now,
        expires_at=now,
        responded_at=now,
        outcome=OfferOutcome.ACCEPTED,
    ))
    timeline(delivery, "claimed", rider=str(rider_user.id))
    db.flush()
    trip = _start_trip(db, delivery, rider_user, now, conflict="order_taken")
    for other in withdrawn:
        notify.offer_withdrawn(db, other)
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
    # One order, one rider (2026-10-08). This used to take the order from its
    # rider with no question asked - even with the food already on their bike.
    live = db.scalar(
        select(RiderTrip).where(RiderTrip.order_delivery_id == delivery.id, RiderTrip.ended_at.is_(None))
    )
    if live is not None:
        if live.picked_up_at is not None or delivery.state in {
            DeliveryState.PICKED_UP.value,
            DeliveryState.IN_TRANSIT.value,
        }:
            # The bag is physically with that rider: nobody else can carry it.
            raise HTTPException(status.HTTP_409_CONFLICT, "food_picked_up")
        holder = db.get(Rider, live.rider_user_id)
        seen = holder.last_location_at if holder is not None else None
        if seen is not None and seen.tzinfo is None:
            seen = seen.replace(tzinfo=UTC)
        if seen is not None and _now() - seen <= timedelta(minutes=load_fleet(db).silent_minutes):
            raise HTTPException(status.HTTP_409_CONFLICT, "rider_has_it")
        # Before pickup and silent past silent_minutes: a dead phone or a
        # breakdown. Rescuing it is the one reassign of a held order allowed.
    from app.services.fleet import notify, trips

    taken_from = trips.end_live_trip(db, delivery, reason="REASSIGNED")
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
    if taken_from is not None:
        # The rider it was taken from is free again, and the order has no rider.
        notify.trip_changed(db, taken_from)
        notify.riders_changed(taken_from.rider_user_id, force=True)
        notify.delivery_changed(db, delivery, "rider_reassigned")
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
    "PROVIDER", "accept", "advance", "candidates", "claim", "current_offer", "decline", "haversine_m",
    "open_orders", "opens_at", "reach_m", "ready_time",
    "queue_advance", "queue_advance_after_commit", "reassign", "schedule_expiry", "timeline",
]


def waiting_orders(db: Session) -> list[dict]:
    """Orders our fleet holds that no rider is carrying: what the admin assigns from.

    Exactly the set `reassign` would accept - own_fleet or unassigned, the
    delivery not finished, the order not closed - minus anything with a live
    trip, which is already moving. A Pidge booking is left out on purpose: it
    has its own rider coming, and offering it to ours would send two riders
    to one bag (the review finding `reassign` already guards).
    """

    from app.models.restaurant import Restaurant
    from app.models.restaurant_location import RestaurantLocation
    from app.services.kitchen_push import order_code

    live = select(RiderTrip.order_delivery_id).where(RiderTrip.ended_at.is_(None))
    rows = db.execute(
        select(OrderDelivery, Order, Restaurant.name, RestaurantLocation.latitude, RestaurantLocation.longitude)
        .join(Order, Order.id == OrderDelivery.order_id)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .join(RestaurantLocation, RestaurantLocation.id == Order.restaurant_location_id)
        .where(
            OrderDelivery.provider.in_([PROVIDER, "unassigned"]),
            Order.status.not_in(list(_ORDER_CLOSED)),
            OrderDelivery.id.not_in(live),
        )
        .order_by(Order.created_at)
    ).tuples().all()
    pending = dict(
        db.execute(
            select(RiderOffer.order_delivery_id, User.full_name)
            .join(User, User.id == RiderOffer.rider_user_id)
            # Past its deadline it is asking nobody, even if the expiry task
            # has not run yet - a late worker must not leave "Asking ..." up.
            .where(RiderOffer.outcome == OfferOutcome.PENDING, RiderOffer.expires_at > _now())
        ).tuples().all()
    )
    fleet = load_fleet(db)
    now = _now()
    out = []
    for delivery, order, name, lat, lng in rows:
        if DeliveryState(delivery.state).is_terminal:
            continue
        reach = None
        opens = None
        if delivery.provider == PROVIDER:
            opens = opens_at(db, delivery, fleet, now)
            if lat is not None and lng is not None:
                reach = round(reach_m(db, delivery, fleet, now) / 1000, 2)
        out.append({
            "order_id": order.id,
            "order_code": order_code(order),
            "restaurant_name": name,
            "provider": delivery.provider,
            "pickup_lat": float(lat) if lat is not None else None,
            "pickup_lng": float(lng) if lng is not None else None,
            "drop_lat": order.delivery_latitude,
            "drop_lng": order.delivery_longitude,
            "ordered_at": order.created_at,
            "offered_to": pending.get(delivery.id),
            "reach_km": reach,
            "ready_at": ready_time(db, delivery),
            "opens_at": opens if opens is not None and opens > now else None,
        })
    return out
