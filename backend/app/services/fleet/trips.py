"""A rider's trip: the steps, the delivery code, how it ends and what it pays.

Every step a rider takes is written to the shared delivery row through
`delivery.service.record`, the same function Pidge's webhook feeds - so the
order's status moves by ONE rule for both couriers (`advance_order`, forward
only), and the admin panel and the customer's order page need no fleet code.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.enums import OfferOutcome, RiderStatus, TripEndReason
from app.models.order_delivery import OrderDelivery
from app.models.rider import Rider, RiderOffer, RiderTrip

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def live_trip(db: Session, delivery_id: uuid.UUID) -> RiderTrip | None:
    return db.scalar(
        select(RiderTrip).where(RiderTrip.order_delivery_id == delivery_id, RiderTrip.ended_at.is_(None))
    )


def trip_km(db: Session, delivery: OrderDelivery) -> float:
    """Pickup to drop, in km: the courier-style figure if we have one, else a road estimate."""

    if delivery.distance_metres:
        return float(delivery.distance_metres) / 1000
    from app.config import get_settings
    from app.models.order import Order
    from app.services.fleet.offers import haversine_m

    order = db.get(Order, delivery.order_id)
    branch = order.restaurant_location
    if None in (branch.latitude, branch.longitude, order.delivery_latitude, order.delivery_longitude):
        return 0.0
    straight = haversine_m(
        float(branch.latitude), float(branch.longitude), float(order.delivery_latitude), float(order.delivery_longitude)
    )
    return straight * float(get_settings().delivery_road_factor) / 1000


#: A two-wheeler's typical average through city traffic; the rider app uses
#: the same figure (`rider/src/utils/geo.ts`) so both screens agree.
CITY_KMH = 18.0


def rider_eta(order: Any, delivery: OrderDelivery) -> tuple[float, int] | None:
    """(road metres, minutes) from the rider to the customer's door, or None.

    Before pickup the rider still has to reach the restaurant, so the trip is
    rider -> restaurant -> door; after pickup, rider -> door. Straight lines x
    the road factor the platform prices with - an estimate, said as "about".
    """

    from app.config import get_settings
    from app.services.fleet.offers import haversine_m

    if delivery.rider_latitude is None or delivery.rider_longitude is None:
        return None
    if order.delivery_latitude is None or order.delivery_longitude is None:
        return None
    rider = (float(delivery.rider_latitude), float(delivery.rider_longitude))
    door = (float(order.delivery_latitude), float(order.delivery_longitude))
    if delivery.state == "ASSIGNED":
        branch = order.restaurant_location
        if branch.latitude is None or branch.longitude is None:
            return None
        shop = (float(branch.latitude), float(branch.longitude))
        straight = haversine_m(*rider, *shop) + haversine_m(*shop, *door)
    elif delivery.state in {"PICKED_UP", "IN_TRANSIT"}:
        straight = haversine_m(*rider, *door)
    else:
        return None
    road = straight * float(get_settings().delivery_road_factor)
    minutes = max(1, round(road / 1000 / CITY_KMH * 60))
    return road, minutes


def _pay(db: Session, trip: RiderTrip, delivery: OrderDelivery, *, full: bool, delivered: bool = False) -> None:
    """Full pay for a carried trip; the minimum for a wasted ride to the restaurant.

    Past the rate card the amount stays None until the admin prices it
    (`set_manual_pay`); payouts already skip a trip with no amount.
    """

    from app.services.fleet.config import load_pay
    from app.services.fleet.earnings import earning_for

    pay = load_pay(db)
    km = trip_km(db, delivery)
    trip.distance_km = round(km, 2)
    if full:
        trip.earning_amount, trip.earning_breakdown = earning_for(km, pay, delivered=delivered)
    else:
        trip.earning_amount = pay.minimum
        trip.earning_breakdown = {"minimum": str(pay.minimum), "reason": "cancelled after reaching the restaurant"}


def _free_rider(db: Session, rider_user_id: uuid.UUID) -> None:
    rider = db.get(Rider, rider_user_id)
    if rider is not None and rider.status == RiderStatus.ON_TRIP:
        rider.status, rider.status_at = RiderStatus.ONLINE, _now()


def end_live_trip(db: Session, delivery: OrderDelivery, *, reason: str) -> RiderTrip | None:
    """End whatever trip is live on this delivery, paying by the cancellation rule.

    Not delivered: nothing if the rider never reached the restaurant, the
    minimum if they did, a full trip if they already had the food. The caller
    commits.
    """

    trip = live_trip(db, delivery.id)
    if trip is None:
        return None
    now = _now()
    if trip.picked_up_at is not None:
        _pay(db, trip, delivery, full=True)
        end = TripEndReason.CANCELLED_AFTER_PICKUP
    else:
        if trip.arrived_pickup_at is not None:
            _pay(db, trip, delivery, full=False)
        else:
            trip.earning_amount = Decimal("0.00")
        end = TripEndReason.CANCELLED_BEFORE_PICKUP
    trip.ended_at = now
    trip.end_reason = TripEndReason.REASSIGNED if reason == "REASSIGNED" else end
    _free_rider(db, trip.rider_user_id)
    db.flush()
    return trip


def on_order_cancelled(db: Session, delivery: OrderDelivery) -> None:
    """The restaurant or the system cancelled: withdraw offers, end the trip, tell the rider."""

    withdrawn = list(
        db.scalars(
            update(RiderOffer)
            .where(RiderOffer.order_delivery_id == delivery.id, RiderOffer.outcome == OfferOutcome.PENDING)
            .values(outcome=OfferOutcome.WITHDRAWN, responded_at=_now())
            .returning(RiderOffer)
        )
    )
    trip = end_live_trip(db, delivery, reason="CANCELLED")

    # Told only once the cancel is COMMITTED: a rider told "cancelled" about a
    # trip whose cancel then rolled back would ride home with the food
    # (review finding, 2026-10-08).
    from sqlalchemy import event

    def _tell(session: Session) -> None:
        from app.services.fleet import notify

        # A FRESH session on the same database: the one that just committed
        # refuses SQL inside `after_commit`, and the push has to read the
        # rider's phone token. Passing it along lost every "trip cancelled"
        # push and raised out of the caller's commit (found on the emulator,
        # 2026-10-10, `test_fleet_push_after_commit`).
        with Session(bind=session.get_bind()) as fresh:
            for offer in withdrawn:
                notify.offer_withdrawn(fresh, offer)
            if trip is not None:
                notify.trip_cancelled(fresh, trip)
                # Free again on the admin's screens; the order's own CANCELLED
                # event already tells everyone watching the order.
                notify.riders_changed(trip.rider_user_id, force=True)

    event.listen(db, "after_commit", _tell, once=True)


# --- the rider's steps ---------------------------------------------------------

ACTIONS = ("arrived_pickup", "picked_up", "arrived_drop", "delivered", "unavailable", "call_logged")

#: Waiting at the door before "customer unavailable" may be pressed, and calls made.
UNAVAILABLE_AFTER_MINUTES = 10
UNAVAILABLE_MIN_CALLS = 2


def step_of(trip: RiderTrip) -> str:
    """Where the rider is, in the words the app shows."""

    if trip.ended_at is not None:
        return "done"
    if trip.arrived_pickup_at is None:
        return "to_pickup"
    if trip.picked_up_at is None:
        return "at_pickup"
    if trip.arrived_drop_at is None:
        return "to_drop"
    return "at_drop"


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _record(db: Session, delivery: OrderDelivery, rider_user: Any, state: Any, **fields: Any) -> None:
    from app.services.delivery.base import DeliveryResult
    from app.services.delivery.service import record

    record(
        db,
        delivery,
        DeliveryResult(
            provider_order_id=delivery.provider_order_id,
            state=state,
            provider_status=state.value.lower(),
            rider_name=delivery.rider_name,
            rider_mobile=delivery.rider_mobile,
            **fields,
        ),
        actor_user=rider_user,
    )


def timeline_event(delivery: OrderDelivery, event: str, **data: Any) -> None:
    from app.services.fleet.offers import timeline

    timeline(delivery, event, **data)


def _finish(db: Session, trip: RiderTrip, delivery: OrderDelivery, reason: TripEndReason) -> None:
    """The rider carried it, or waited at the door: full pay, back on shift."""

    _pay(db, trip, delivery, full=True, delivered=reason == TripEndReason.DELIVERED)
    trip.ended_at = _now()
    trip.end_reason = reason
    _free_rider(db, trip.rider_user_id)


def act(
    db: Session, rider_user: Any, trip_id: uuid.UUID, action: str, action_id: str, otp_code: str | None = None
) -> RiderTrip:
    """Apply one step. Idempotent per `action_id`; a step out of order is refused.

    A rider on a bad network taps once and the app retries with the same
    action id: the second request is answered with the trip as it is, so
    nothing is recorded twice and nobody is paid twice.
    """

    from app.services.delivery.base import DeliveryState
    from app.services.fleet import notify, otp

    if action not in ACTIONS:
        raise HTTPException(404, "Unknown action")
    trip = db.scalar(select(RiderTrip).where(RiderTrip.id == trip_id).with_for_update())
    if trip is None or trip.rider_user_id != rider_user.id:
        raise HTTPException(404, "Trip not found")
    if action_id in (trip.applied_actions or []):
        db.rollback()
        return trip
    if trip.ended_at is not None:
        raise HTTPException(409, "trip_ended")
    delivery = db.scalar(
        select(OrderDelivery).where(OrderDelivery.id == trip.order_delivery_id).with_for_update()
    )
    now = _now()

    if action == "call_logged":
        trip.call_attempts = (trip.call_attempts or 0) + 1
        timeline_event(delivery, "call_logged")
    elif action == "arrived_pickup":
        if trip.arrived_pickup_at is None:
            trip.arrived_pickup_at = now
            timeline_event(delivery, "arrived_pickup")
    elif action == "picked_up":
        if trip.arrived_pickup_at is None:
            raise HTTPException(409, "out_of_order")
        if trip.picked_up_at is None:
            trip.picked_up_at = now
            _record(db, delivery, rider_user, DeliveryState.PICKED_UP, picked_up_at=now)
    elif action == "arrived_drop":
        if trip.picked_up_at is None:
            raise HTTPException(409, "out_of_order")
        if trip.arrived_drop_at is None:
            trip.arrived_drop_at = now
            _record(db, delivery, rider_user, DeliveryState.IN_TRANSIT)
    elif action == "delivered":
        if trip.arrived_drop_at is None:
            raise HTTPException(409, "out_of_order")
        if delivery.otp_locked:
            raise HTTPException(409, "otp_locked")
        if not otp.matches(delivery.order_id, otp_code):
            delivery.otp_attempts = (delivery.otp_attempts or 0) + 1
            left = max(0, otp.MAX_ATTEMPTS - delivery.otp_attempts)
            if left == 0:
                delivery.otp_locked = True
                timeline_event(delivery, "otp_locked")
            db.commit()
            raise HTTPException(422, {"code": "otp_wrong", "attempts_left": left})
        trip.delivered_at = now
        _record(db, delivery, rider_user, DeliveryState.DELIVERED, delivered_at=now)
        _finish(db, trip, delivery, TripEndReason.DELIVERED)
    elif action == "unavailable":
        if trip.arrived_drop_at is None:
            raise HTTPException(409, "out_of_order")
        waited = (now - _aware(trip.arrived_drop_at)).total_seconds()
        if waited < UNAVAILABLE_AFTER_MINUTES * 60 or (trip.call_attempts or 0) < UNAVAILABLE_MIN_CALLS:
            raise HTTPException(409, "too_early")
        reason = "Customer unavailable at the door"
        _record(db, delivery, rider_user, DeliveryState.FAILED, failure_reason=reason)
        _finish(db, trip, delivery, TripEndReason.CUSTOMER_UNAVAILABLE)

    trip.applied_actions = [*(trip.applied_actions or []), action_id][-50:]
    db.commit()
    notify.trip_changed(db, trip)
    # Everyone watching this order hears the step (a logged call is the
    # rider's own record, not news), and a finished trip puts the rider back
    # to "Online" on the admin's screens.
    if action != "call_logged":
        notify.delivery_changed(db, delivery, f"rider_{action}")
    if trip.ended_at is not None:
        notify.riders_changed(trip.rider_user_id, force=True)
    return trip


def admin_confirm_delivered(db: Session, admin: Any, delivery: OrderDelivery, reason: str) -> RiderTrip:
    """A locked or disputed code: the admin confirms the hand-over, with the reason on record."""

    from app.services.delivery.base import DeliveryState

    trip = db.scalar(
        select(RiderTrip)
        .where(RiderTrip.order_delivery_id == delivery.id, RiderTrip.ended_at.is_(None))
        .with_for_update()
    )
    if trip is None:
        raise HTTPException(409, "no_live_trip")
    now = _now()
    trip.picked_up_at = trip.picked_up_at or now
    trip.arrived_drop_at = trip.arrived_drop_at or now
    trip.delivered_at = now
    _record(db, delivery, None, DeliveryState.DELIVERED, delivered_at=now)
    timeline_event(delivery, "confirmed_by_admin", by=str(admin.id), reason=reason[:500])
    delivery.otp_locked = False
    _finish(db, trip, delivery, TripEndReason.DELIVERED)
    db.commit()
    from app.services.fleet import notify

    notify.trip_changed(db, trip)
    notify.delivery_changed(db, delivery, "confirmed_by_admin")
    notify.riders_changed(trip.rider_user_id, force=True)
    return trip


def trips_to_price(db: Session) -> list[dict[str, Any]]:
    """Ended trips past the rate card that nobody has priced yet, oldest first."""

    from app.models.user import User
    from app.services.kitchen_push import order_code

    rows = db.execute(
        select(RiderTrip, User.full_name)
        .join(User, User.id == RiderTrip.rider_user_id)
        .where(
            RiderTrip.ended_at.is_not(None),
            RiderTrip.earning_amount.is_(None),
            RiderTrip.earning_breakdown["manual"].as_boolean().is_(True),
        )
        .order_by(RiderTrip.ended_at)
    ).all()
    out = []
    for trip, name in rows:
        delivery = db.get(OrderDelivery, trip.order_delivery_id)
        parts = trip.earning_breakdown or {}
        out.append({
            "trip_id": trip.id,
            "rider_user_id": trip.rider_user_id,
            "rider_name": name,
            "order_id": delivery.order_id,
            "order_code": order_code(delivery.order),
            "distance_km": parts.get("km", trip.distance_km),
            "over_km": parts.get("over_km"),
            "incentive": Decimal(str(parts.get("incentive", "0"))),
            "delivered": trip.end_reason == TripEndReason.DELIVERED,
            "end_reason": trip.end_reason,
            "ended_at": trip.ended_at,
        })
    return out


def set_manual_pay(db: Session, admin: Any, trip_id: uuid.UUID, amount: Decimal) -> RiderTrip:
    """The admin's price for a trip past the rate card, plus the incentive it earned.

    Only such a trip, and only while unpaid: a payout is a record of money
    that has moved, so its trips never change after it.
    """

    trip = db.scalar(select(RiderTrip).where(RiderTrip.id == trip_id).with_for_update())
    if trip is None:
        raise HTTPException(404, "trip_not_found")
    parts = dict(trip.earning_breakdown or {})
    if trip.ended_at is None or not parts.get("manual"):
        raise HTTPException(409, "not_manual")
    if trip.payout_id is not None:
        raise HTTPException(409, "already_paid")
    amount = Decimal(amount)
    incentive = Decimal(str(parts.get("incentive", "0")))
    trip.earning_amount = (amount + incentive).quantize(Decimal("0.01"))
    parts.update({"manual_amount": str(amount), "priced_by": str(admin.id), "priced_at": _now().isoformat()})
    trip.earning_breakdown = parts
    db.commit()
    logger.info("Trip %s priced by hand by %s: %s + %s incentive", trip.id, admin.id, amount, incentive)
    from app.services.fleet import notify

    notify.trip_changed(db, trip)
    return trip


def active_trip(db: Session, rider_user: Any) -> RiderTrip | None:
    return db.scalar(
        select(RiderTrip).where(RiderTrip.rider_user_id == rider_user.id, RiderTrip.ended_at.is_(None))
    )


def trip_view(db: Session, trip: RiderTrip) -> dict[str, Any]:
    """Everything the trip screen draws, in one response - never the delivery code."""

    from app.services.fleet.config import load_pay
    from app.services.fleet.earnings import earning_for
    from app.services.fleet.ready import ready_at
    from app.services.kitchen_push import order_code

    delivery = db.get(OrderDelivery, trip.order_delivery_id)
    order = delivery.order
    location = order.restaurant_location
    restaurant = order.restaurant
    km = trip_km(db, delivery)
    estimate, _ = earning_for(km, load_pay(db))
    items = list(getattr(order, "items", None) or [])
    return {
        "id": trip.id,
        "order_id": order.id,
        "order_code": order_code(order),
        "step": step_of(trip),
        "accepted_at": trip.accepted_at,
        "arrived_pickup_at": trip.arrived_pickup_at,
        "picked_up_at": trip.picked_up_at,
        "arrived_drop_at": trip.arrived_drop_at,
        "delivered_at": trip.delivered_at,
        "ended_at": trip.ended_at,
        "end_reason": trip.end_reason.value if trip.end_reason else None,
        "call_attempts": trip.call_attempts or 0,
        "distance_km": round(km, 1),
        "earning": trip.earning_amount if trip.earning_amount is not None else estimate,
        "otp_locked": bool(delivery.otp_locked),
        "otp_attempts_left": max(0, 5 - (delivery.otp_attempts or 0)),
        "pickup": {
            "name": restaurant.name if restaurant is not None else location.branch_name,
            "branch": location.branch_name,
            "address": ", ".join(p for p in (location.address_line_1, location.city) if p),
            "phone": location.phone_number or "",
            "lat": float(location.latitude) if location.latitude is not None else None,
            "lng": float(location.longitude) if location.longitude is not None else None,
        },
        "drop": {
            "name": (order.contact_name or "Customer").split()[0],
            "address": order.delivery_address,
            "phone": order.contact_phone or "",
            "lat": order.delivery_latitude,
            "lng": order.delivery_longitude,
            "instructions": order.special_instructions or "",
        },
        "items": [{"name": item.item_name_snapshot, "quantity": item.quantity} for item in items],
        "item_count": sum(item.quantity for item in items),
        "ready_at": ready_at(db, order, accepted_fallback=delivery.created_at),
    }


__all__ = [
    "ACTIONS", "act", "active_trip", "admin_confirm_delivered", "end_live_trip", "live_trip",
    "on_order_cancelled", "step_of", "trip_km", "trip_view",
]


