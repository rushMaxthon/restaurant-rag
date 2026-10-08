"""The super admin's rider roster.

ADMIN only: the fleet is the platform's, shared by every restaurant, and an
owner who could read it could see other restaurants' deliveries and riders.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.enums import RiderStatus
from app.models.order_delivery import OrderDelivery
from app.models.rider import Rider, RiderOffer, RiderTrip
from app.models.user import User
from app.schemas.rider import (
    ConfirmDeliveredIn,
    FleetConfigIn,
    FleetDeliveryView,
    FleetOfferRow,
    FleetSettings,
    PayoutIn,
    PayoutOut,
    ReassignIn,
    RiderCreate,
    RiderPayIn,
    RiderResponse,
    RiderUpdate,
    TripView,
    UnpaidRow,
    WaitingOrder,
)
from app.services.auth import require_admin
from app.services.fleet import config as fleet_config
from app.services.fleet import offers, payouts, trips
from app.services.fleet import riders as svc

router = APIRouter(prefix="/admin/riders", tags=["admin-riders"])
Admin = Annotated[User, Depends(require_admin)]
Db = Annotated[Session, Depends(get_db)]


def _active_orders(db: Session) -> dict[uuid.UUID, uuid.UUID]:
    rows = db.execute(
        select(RiderTrip.rider_user_id, OrderDelivery.order_id)
        .join(OrderDelivery, OrderDelivery.id == RiderTrip.order_delivery_id)
        .where(RiderTrip.ended_at.is_(None))
    ).tuples().all()
    return dict(rows)


def serialize(user: User, rider: Rider, active: dict[uuid.UUID, uuid.UUID]) -> RiderResponse:
    return RiderResponse(
        user_id=user.id,
        full_name=user.full_name,
        phone_number=user.phone_number,
        is_active=user.is_active,
        vehicle_type=rider.vehicle_type,
        vehicle_number=rider.vehicle_number,
        city=rider.city,
        status=rider.status,
        last_latitude=rider.last_latitude,
        last_longitude=rider.last_longitude,
        last_location_at=rider.last_location_at,
        active_order_id=active.get(user.id),
        notes=rider.notes,
    )


@router.get("", response_model=list[RiderResponse])
def list_riders(_: Admin, db: Db) -> list[RiderResponse]:
    active = _active_orders(db)
    return [serialize(u, r, active) for u, r in svc.list_riders(db)]


@router.get("/live", response_model=list[RiderResponse])
def live_riders(_: Admin, db: Db) -> list[RiderResponse]:
    active = _active_orders(db)
    return [
        serialize(u, r, active)
        for u, r in svc.list_riders(db)
        if u.is_active and r.status != RiderStatus.OFFLINE
    ]


@router.get("/waiting", response_model=list[WaitingOrder])
def waiting(_: Admin, db: Db) -> list[WaitingOrder]:
    """Orders that need a rider, for the live map: assign from here with `reassign`."""

    return [WaitingOrder(**row) for row in offers.waiting_orders(db)]


@router.post("", response_model=RiderResponse, status_code=status.HTTP_201_CREATED)
def create_rider(body: RiderCreate, admin: Admin, db: Db) -> RiderResponse:
    user = svc.create_rider(db, admin, **body.model_dump())
    user, rider = svc.get_rider(db, user.id)
    return serialize(user, rider, {})


@router.get("/settings", response_model=FleetSettings)
def get_settings_(_: Admin, db: Db) -> FleetSettings:
    return _settings_out(db)


@router.put("/settings/pay", response_model=FleetSettings)
def put_pay(body: RiderPayIn, admin: Admin, db: Db) -> FleetSettings:
    fleet_config.save_pay(db, admin, body.model_dump(mode="json"))
    return _settings_out(db)


@router.put("/settings/fleet", response_model=FleetSettings)
def put_fleet(body: FleetConfigIn, admin: Admin, db: Db) -> FleetSettings:
    fleet_config.save_fleet(db, admin, body.model_dump(mode="json"))
    return _settings_out(db)


def _settings_out(db: Session) -> FleetSettings:
    from app.config import get_settings as app_settings

    pay = fleet_config.load_pay(db)
    fleet = fleet_config.load_fleet(db)
    return FleetSettings(
        enabled=app_settings().enable_own_fleet,
        pay=RiderPayIn(base=pay.base, per_km=pay.per_km, minimum=pay.minimum),
        fleet=FleetConfigIn(**asdict(fleet)),
    )


def _delivery_for(db: Session, order_id: uuid.UUID) -> OrderDelivery:
    delivery = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order_id))
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No delivery for this order")
    return delivery


@router.get("/deliveries/{order_id}", response_model=FleetDeliveryView)
def delivery_detail(order_id: uuid.UUID, _: Admin, db: Db) -> FleetDeliveryView:
    delivery = _delivery_for(db, order_id)
    rows = db.execute(
        select(RiderOffer, User.full_name)
        .join(User, User.id == RiderOffer.rider_user_id)
        .where(RiderOffer.order_delivery_id == delivery.id)
        .order_by(RiderOffer.offered_at)
    ).tuples().all()
    trip = db.scalar(
        select(RiderTrip).where(RiderTrip.order_delivery_id == delivery.id).order_by(RiderTrip.accepted_at.desc())
    )
    fallback = next((e.get("reason") for e in reversed(delivery.timeline or []) if e.get("event") == "fallback"), None)
    return FleetDeliveryView(
        provider=delivery.provider,
        state=delivery.state,
        attempt=delivery.attempt,
        otp_locked=delivery.otp_locked,
        fallback_reason=fallback,
        offers=[
            FleetOfferRow(
                rider_user_id=o.rider_user_id, rider_name=name, outcome=o.outcome.value,
                offered_at=o.offered_at, responded_at=o.responded_at, metres=o.distance_to_pickup_m,
            )
            for o, name in rows
        ],
        trip=TripView(**trips.trip_view(db, trip)) if trip is not None else None,
    )


@router.post("/deliveries/{order_id}/reassign", response_model=FleetDeliveryView)
def reassign(order_id: uuid.UUID, body: ReassignIn, admin: Admin, db: Db) -> FleetDeliveryView:
    offers.reassign(db, admin, _delivery_for(db, order_id), body.rider_user_id)
    return delivery_detail(order_id, admin, db)


@router.post("/deliveries/{order_id}/confirm-delivered", response_model=FleetDeliveryView)
def confirm_delivered(order_id: uuid.UUID, body: ConfirmDeliveredIn, admin: Admin, db: Db) -> FleetDeliveryView:
    trips.admin_confirm_delivered(db, admin, _delivery_for(db, order_id), body.reason)
    return delivery_detail(order_id, admin, db)


@router.get("/payouts/unpaid", response_model=list[UnpaidRow])
def unpaid(_: Admin, db: Db) -> list[UnpaidRow]:
    return [UnpaidRow(**row) for row in payouts.unpaid_summary(db)]


@router.post("/{user_id}/payouts", response_model=PayoutOut, status_code=status.HTTP_201_CREATED)
def pay(user_id: uuid.UUID, body: PayoutIn, admin: Admin, db: Db) -> PayoutOut:
    svc.get_rider(db, user_id)
    payout = payouts.pay_rider(db, admin, user_id, period_to=body.period_to, reference=body.reference)
    return PayoutOut.model_validate(payout, from_attributes=True)


@router.get("/{user_id}/trips", response_model=list[TripView])
def rider_trips(user_id: uuid.UUID, _: Admin, db: Db, limit: int = Query(default=50, ge=1, le=200)) -> list[TripView]:
    svc.get_rider(db, user_id)
    rows = db.scalars(
        select(RiderTrip).where(RiderTrip.rider_user_id == user_id).order_by(RiderTrip.accepted_at.desc()).limit(limit)
    )
    return [TripView(**trips.trip_view(db, trip)) for trip in rows]


@router.patch("/{user_id}", response_model=RiderResponse)
def update_rider(user_id: uuid.UUID, body: RiderUpdate, admin: Admin, db: Db) -> RiderResponse:
    svc.update_rider(db, admin, user_id, **body.model_dump(exclude_unset=True))
    user, rider = svc.get_rider(db, user_id)
    return serialize(user, rider, _active_orders(db))
