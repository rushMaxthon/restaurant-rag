"""The rider app's API.

RIDER only. Every row a route returns is the caller's own - their offer,
their trip, their earnings - and anything else is 404, not 403, so a rider
learns nothing about another rider's work (the kitchen board's rule).

The shift routes are NOT behind `enable_own_fleet`: riders must be able to
sign in, go online and be trained before the platform starts offering them
orders. Only the offer loop and dispatch read the flag.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config.database import get_db
from app.models.rider import Rider, RiderOffer, RiderTrip
from app.models.user import User
from app.schemas.rider import (
    DeviceToken,
    Earnings,
    LocationBatch,
    OfferView,
    OpenOrderView,
    PayoutOut,
    RiderMe,
    StatusUpdate,
    TripAction,
    TripView,
)
from app.services.auth import require_rider
from app.services.fleet import offers, trips
from app.services.fleet import riders as svc

router = APIRouter(prefix="/rider", tags=["rider"])
RiderUser = Annotated[User, Depends(require_rider)]
Db = Annotated[Session, Depends(get_db)]

#: The platform's riders work in India; "today" is an Indian day.
LOCAL_TZ = ZoneInfo("Asia/Kolkata")


def start_of_today() -> datetime:
    local = datetime.now(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(UTC)


def me_response(db: Session, user: User) -> RiderMe:
    from app.services.fleet.config import load_pay

    from app.models.rider_application import RiderApplication

    rider = db.get(Rider, user.id)
    application = db.get(RiderApplication, user.id)
    trips, amount = svc.today_summary(db, user.id, start_of_today())
    pay = load_pay(db)
    return RiderMe(
        user_id=user.id,
        full_name=user.full_name,
        phone_number=user.phone_number,
        vehicle_type=rider.vehicle_type,
        vehicle_number=rider.vehicle_number,
        city=rider.city,
        status=rider.status,
        today_trips=trips,
        today_earnings=amount,
        fleet_enabled=get_settings().enable_own_fleet,
        pay={"base": pay.base, "per_km": pay.per_km, "minimum": pay.minimum},
        onboarding=rider.onboarding,
        application_status=application.status if application is not None else None,
    )


@router.get("/me", response_model=RiderMe)
def me(user: RiderUser, db: Db) -> RiderMe:
    return me_response(db, user)


@router.post("/status", response_model=RiderMe)
def set_status(body: StatusUpdate, user: RiderUser, db: Db) -> RiderMe:
    svc.set_status(db, user, body.online)
    return me_response(db, user)


@router.post("/location", status_code=status.HTTP_204_NO_CONTENT)
def post_location(body: LocationBatch, user: RiderUser, db: Db) -> Response:
    from app.services import rate_limit

    # ~10 s per batch on a trip; 30 a minute leaves room for a reconnect
    # flushing its queue, and stops a looping client from hammering the DB.
    rate_limit.hit("rider-location", str(user.id), limit=30, window_seconds=60)
    fixes = [svc.LocationFix(lat=f.lat, lng=f.lng, at=f.at, accuracy_m=f.accuracy_m) for f in body.fixes]
    svc.record_locations(db, user, fixes)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


#: URL spelling of each trip action (the app posts to /rider/trip/{id}/{slug}).
_ACTION_SLUGS = {
    "arrived-pickup": "arrived_pickup",
    "picked-up": "picked_up",
    "arrived-drop": "arrived_drop",
    "delivered": "delivered",
    "unavailable": "unavailable",
    "call-logged": "call_logged",
}


def _summary(order) -> dict:
    """What a rider is told about an order before taking it: where from, roughly
    where to (the area, never the door - that comes with the trip), how big."""

    location = order.restaurant_location
    parts = [p.strip() for p in (order.delivery_address or "").split(",") if p.strip()]
    items = list(getattr(order, "items", None) or [])
    return {
        "restaurant_name": order.restaurant.name if order.restaurant is not None else location.branch_name,
        "branch": location.branch_name,
        "pickup_address": ", ".join(p for p in (location.address_line_1, location.city) if p),
        "drop_area": ", ".join(parts[-3:-1]) if len(parts) >= 3 else (parts[-1] if parts else ""),
        "item_count": sum(item.quantity for item in items),
    }


def _offer_view(db: Session, offer: RiderOffer) -> OfferView:
    from app.models.order_delivery import OrderDelivery
    from app.services.fleet.config import load_fleet, load_pay
    from app.services.fleet.earnings import earning_for
    from app.services.fleet.trips import trip_km

    delivery = db.get(OrderDelivery, offer.order_delivery_id)
    order = delivery.order
    km = trip_km(db, delivery)
    estimate, _ = earning_for(km, load_pay(db))
    expires = offer.expires_at if offer.expires_at.tzinfo else offer.expires_at.replace(tzinfo=UTC)
    return OfferView(
        id=offer.id,
        expires_at=expires,
        seconds_left=max(0, int((expires - datetime.now(UTC)).total_seconds())),
        total_seconds=load_fleet(db).offer_seconds,
        pickup_distance_m=offer.distance_to_pickup_m,
        trip_distance_km=round(km, 1),
        earning_estimate=estimate,
        ready_at=offers.ready_time(db, delivery),
        **_summary(order),
    )


@router.get("/offers/current", response_model=OfferView, responses={204: {"description": "No offer"}})
def current_offer(user: RiderUser, db: Db):
    offer = offers.current_offer(db, user)
    if offer is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return _offer_view(db, offer)


@router.post("/offers/{offer_id}/accept", response_model=TripView)
def accept_offer(offer_id: uuid.UUID, user: RiderUser, db: Db) -> TripView:
    trip = offers.accept(db, user, offer_id)
    return TripView(**trips.trip_view(db, trip))


@router.post("/offers/{offer_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
def decline_offer(offer_id: uuid.UUID, user: RiderUser, db: Db) -> Response:
    offers.decline(db, user, offer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/open-orders", response_model=list[OpenOrderView])
def open_orders(user: RiderUser, db: Db) -> list[OpenOrderView]:
    """Orders this rider could take now - including one whose offer they missed."""

    return [
        OpenOrderView(
            order_id=row["order_id"],
            pickup_distance_m=row["pickup_distance_m"],
            trip_distance_km=row["trip_distance_km"],
            earning_estimate=row["earning_estimate"],
            minutes_left=row["minutes_left"],
            missed=row["missed"],
            ready_at=row["ready_at"],
            **_summary(row["order"]),
        )
        for row in offers.open_orders(db, user)
    ]


@router.post("/open-orders/{order_id}/claim", response_model=TripView)
def claim_open_order(order_id: uuid.UUID, user: RiderUser, db: Db) -> TripView:
    trip = offers.claim(db, user, order_id)
    return TripView(**trips.trip_view(db, trip))


@router.get("/trip", response_model=TripView, responses={204: {"description": "No active trip"}})
def active_trip(user: RiderUser, db: Db):
    trip = trips.active_trip(db, user)
    if trip is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return TripView(**trips.trip_view(db, trip))


@router.post("/trip/{trip_id}/{action}", response_model=TripView)
def trip_action(trip_id: uuid.UUID, action: str, body: TripAction, user: RiderUser, db: Db) -> TripView:
    name = _ACTION_SLUGS.get(action)
    if name is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown action")
    trip = trips.act(db, user, trip_id, name, body.action_id, otp_code=body.otp)
    return TripView(**trips.trip_view(db, trip))


@router.get("/earnings", response_model=Earnings)
def earnings(user: RiderUser, db: Db, days: int = Query(default=7, ge=1, le=62)) -> Earnings:
    from app.services.fleet import payouts

    return Earnings(**payouts.rider_earnings(db, user.id, days=days, tz=LOCAL_TZ))


@router.get("/payouts", response_model=list[PayoutOut])
def my_payouts(user: RiderUser, db: Db) -> list[PayoutOut]:
    """Every payment this rider has received, newest first. The money moves by
    bank transfer outside the app; this is the record the rider checks it
    against, with the admin's reference (UTR) on each row."""
    from app.services.fleet import payouts

    return [PayoutOut.model_validate(p, from_attributes=True) for p in payouts.rider_payouts(db, user.id)]


@router.get("/trips", response_model=list[TripView])
def history(
    user: RiderUser,
    db: Db,
    limit: int = Query(default=20, ge=1, le=50),
    before: datetime | None = None,
) -> list[TripView]:
    query = (
        select(RiderTrip)
        .where(RiderTrip.rider_user_id == user.id, RiderTrip.ended_at.is_not(None))
        .order_by(RiderTrip.ended_at.desc())
        .limit(limit)
    )
    if before is not None:
        query = query.where(RiderTrip.ended_at < before)
    return [TripView(**trips.trip_view(db, trip)) for trip in db.scalars(query)]


@router.post("/device-token", status_code=status.HTTP_204_NO_CONTENT)
def device_token(body: DeviceToken, user: RiderUser, db: Db) -> Response:
    rider = db.get(Rider, user.id)
    # One phone, one rider: the last to sign in on it. Every rider who signed
    # in on this phone before kept its token, so their offers and cancelled
    # trips rang for whoever held the phone now (found on the emulator,
    # 2026-10-10, `test_a_phone_belongs_to_the_last_rider_who_signed_in_on_it`).
    db.execute(
        update(Rider).where(Rider.fcm_token == body.token, Rider.user_id != user.id).values(fcm_token="")
    )
    rider.fcm_token = body.token
    if body.app_version:
        rider.app_version = body.app_version
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
