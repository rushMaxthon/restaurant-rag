"""Hiring, editing and letting go of riders, and a rider's shift: status and location.

Deactivation (and a password reset) bumps `token_version` - as kitchen staff
and the Users page do - so the app is signed out on its next request rather
than when its token expires, and a revoke goes out over the socket. A rider
taken off shift has any open offer withdrawn, so the offer loop moves to the
next rider immediately instead of letting 30 seconds tick away on a phone
that will never answer.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import OfferOutcome, RiderStatus, UserRole, VehicleType
from app.models.rider import Rider, RiderOffer, RiderTrip
from app.models.user import User
from app.services.auth import hash_password, normalize_phone_number

logger = logging.getLogger(__name__)

MIN_PASSWORD = 8


def _now() -> datetime:
    return datetime.now(UTC)


def _placeholder_email(phone: str) -> str:
    # `users.email` is NOT NULL and platform-unique, and riders sign in by
    # phone. `.invalid` is reserved (RFC 2606): nothing is ever sent there.
    digits = "".join(ch for ch in phone if ch.isdigit())
    return f"rider.{digits}@riders.invalid"


def canonical_phone(raw: str) -> str | None:
    """A rider's number in ONE form, +91 and ten digits, whatever the admin typed.

    The app always signs in with +91XXXXXXXXXX and login matches the stored
    number exactly, so "98765 43210" saved as typed would be a rider who can
    never sign in.
    """

    phone = normalize_phone_number(raw)
    if not phone:
        return None
    digits = phone.lstrip("+")
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return phone


def _phone_taken(db: Session, phone: str, *, except_id: uuid.UUID | None = None) -> bool:
    # Checked here as well as by `uq_users_phone_number_platform`: the index
    # lives in migrations only, and a friendly 409 beats an IntegrityError.
    query = select(User.id).where(User.phone_number == phone, User.role != UserRole.CUSTOMER)
    if except_id is not None:
        query = query.where(User.id != except_id)
    return db.scalar(query.limit(1)) is not None


def create_rider(
    db: Session,
    admin: User,
    *,
    full_name: str,
    phone_number: str,
    password: str,
    vehicle_type: VehicleType,
    vehicle_number: str = "",
    city: str = "",
    notes: str = "",
    email: str | None = None,
) -> User:
    phone = canonical_phone(phone_number)
    if not phone:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter a valid phone number")
    if len(password) < MIN_PASSWORD:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Password must be at least {MIN_PASSWORD} characters"
        )
    if _phone_taken(db, phone):
        raise HTTPException(status.HTTP_409_CONFLICT, "A staff account already uses this phone number")
    user = User(
        full_name=full_name.strip(),
        phone_number=phone,
        email=(email or _placeholder_email(phone)).strip().lower(),
        hashed_password=hash_password(password),
        role=UserRole.RIDER,
        app_client_id=None,
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A staff account already uses this phone or email") from None
    db.add(
        Rider(
            user_id=user.id,
            vehicle_type=vehicle_type,
            vehicle_number=vehicle_number.strip().upper(),
            city=city.strip(),
            notes=notes,
            status=RiderStatus.OFFLINE,
            status_at=_now(),
        )
    )
    db.commit()
    logger.info("Rider %s created by %s", user.id, admin.id)
    return user


def get_rider(db: Session, user_id: uuid.UUID) -> tuple[User, Rider]:
    user = db.get(User, user_id)
    rider = db.get(Rider, user_id)
    if user is None or rider is None or user.role != UserRole.RIDER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rider not found")
    return user, rider


def withdraw_open_offers(db: Session, rider_user_id: uuid.UUID) -> list[uuid.UUID]:
    """Withdraw this rider's open offers; returns the deliveries that must move on."""

    rows = db.execute(
        update(RiderOffer)
        .where(RiderOffer.rider_user_id == rider_user_id, RiderOffer.outcome == OfferOutcome.PENDING)
        .values(outcome=OfferOutcome.WITHDRAWN, responded_at=_now())
        .returning(RiderOffer.order_delivery_id)
    ).scalars().all()
    return list(rows)


def go_offline(db: Session, rider_user_id: uuid.UUID, reason: str) -> list[uuid.UUID]:
    """Take a rider off shift. The caller commits, then queues the returned deliveries.

    Never takes a rider on a trip off it - that food is in their hands; the
    sweep raises an alert for a silent rider on a trip instead.
    """

    rider = db.get(Rider, rider_user_id)
    if rider is None:
        return []
    released = withdraw_open_offers(db, rider_user_id)
    if rider.status != RiderStatus.ON_TRIP:
        rider.status = RiderStatus.OFFLINE
        rider.status_at = _now()
    logger.info("Rider %s off shift: %s", rider_user_id, reason)
    return released


def _move_on(delivery_ids: list[uuid.UUID]) -> None:
    if not delivery_ids:
        return
    from app.services.fleet import offers

    for delivery_id in delivery_ids:
        offers.queue_advance(delivery_id)


def update_rider(db: Session, admin: User, user_id: uuid.UUID, **fields: Any) -> User:
    user, rider = get_rider(db, user_id)
    released: list[uuid.UUID] = []
    revoke = False
    for name in ("vehicle_type", "city", "notes"):
        if fields.get(name) is not None:
            setattr(rider, name, fields[name])
    if fields.get("vehicle_number") is not None:
        rider.vehicle_number = str(fields["vehicle_number"]).strip().upper()
    if fields.get("full_name"):
        user.full_name = str(fields["full_name"]).strip()
    if fields.get("password"):
        if len(fields["password"]) < MIN_PASSWORD:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Password must be at least {MIN_PASSWORD} characters"
            )
        user.hashed_password = hash_password(fields["password"])
        revoke = True
    if fields.get("is_active") is not None and fields["is_active"] != user.is_active:
        user.is_active = bool(fields["is_active"])
        revoke = True
        if not user.is_active:
            released = go_offline(db, user.id, "deactivated by admin")
    if revoke:
        user.token_version += 1
        from app.services.realtime.outbox import queue_session_revoked

        queue_session_revoked(db, user_id=user.id)
    db.commit()
    logger.info("Rider %s updated by %s: %s", user.id, admin.id, sorted(k for k in fields if k != "password"))
    _move_on(released)
    return user


def list_riders(db: Session) -> list[tuple[User, Rider]]:
    return list(
        db.execute(select(User, Rider).join(Rider, Rider.user_id == User.id).order_by(User.full_name)).tuples().all()
    )


# --- the shift ---------------------------------------------------------------


@dataclass(slots=True)
class LocationFix:
    lat: float
    lng: float
    at: datetime
    accuracy_m: float | None = None


def set_status(db: Session, user: User, online: bool) -> Rider:
    rider = db.get(Rider, user.id)
    if rider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rider not found")
    released: list[uuid.UUID] = []
    if online:
        if rider.status == RiderStatus.OFFLINE:
            rider.status, rider.status_at = RiderStatus.ONLINE, _now()
    else:
        if rider.status == RiderStatus.ON_TRIP:
            raise HTTPException(status.HTTP_409_CONFLICT, "on_trip")
        released = go_offline(db, user.id, "rider went offline")
    db.commit()
    _move_on(released)
    from app.services.fleet import notify

    # A pin appears or disappears on the admin map now, not at the next poll.
    notify.riders_changed(user.id)
    return rider


def record_locations(db: Session, user: User, fixes: list[LocationFix]) -> Rider:
    """Keep the newest fix; on a trip, copy it to the delivery the customer watches."""

    rider = db.get(Rider, user.id)
    if rider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rider not found")
    now = _now()
    newest = max(fixes, key=lambda f: f.at)
    # A phone clock ahead of ours must not pin "seen just now" into the future.
    at = min(newest.at if newest.at.tzinfo else newest.at.replace(tzinfo=UTC), now)
    if rider.last_location_at is not None and at <= rider.last_location_at:
        return rider  # a late batch never moves the rider backwards
    rider.last_latitude, rider.last_longitude, rider.last_location_at = newest.lat, newest.lng, at
    trip = db.scalar(select(RiderTrip).where(RiderTrip.rider_user_id == user.id, RiderTrip.ended_at.is_(None)))
    delivery = None
    if trip is not None:
        from app.models.order_delivery import OrderDelivery

        delivery = db.get(OrderDelivery, trip.order_delivery_id)
        if delivery is not None:
            delivery.rider_latitude = newest.lat
            delivery.rider_longitude = newest.lng
            delivery.rider_location_at = at
    db.commit()
    from app.services.fleet import notify

    notify.riders_changed(user.id)
    if delivery is not None:
        notify.order_moved(db, delivery)
    return rider


def sweep_silent(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """Riders who stopped reporting: off shift if idle, an alert if on a trip."""

    from app.services.fleet.config import load_fleet

    now = now or _now()
    cutoff = now - timedelta(minutes=load_fleet(db).silent_minutes)
    silent = db.scalars(
        select(Rider).where(
            Rider.status != RiderStatus.OFFLINE,
            (Rider.last_location_at.is_(None)) | (Rider.last_location_at < cutoff),
        )
    ).all()
    offline, alerts, released = 0, [], []
    for rider in silent:
        if rider.status == RiderStatus.ON_TRIP:
            alerts.append(str(rider.user_id))
            continue
        released += go_offline(db, rider.user_id, "no location for too long")
        offline += 1
    db.commit()
    _move_on(released)
    return {"offline": offline, "alerts": alerts}


def today_summary(db: Session, user_id: uuid.UUID, since: datetime) -> tuple[int, Any]:
    from decimal import Decimal

    trips, amount = db.execute(
        select(func.count(RiderTrip.id), func.coalesce(func.sum(RiderTrip.earning_amount), 0)).where(
            RiderTrip.rider_user_id == user_id, RiderTrip.ended_at >= since, RiderTrip.earning_amount.is_not(None)
        )
    ).one()
    return int(trips), Decimal(amount or 0)


__all__ = [
    "LocationFix", "create_rider", "get_rider", "go_offline", "list_riders", "record_locations",
    "set_status", "sweep_silent", "today_summary", "update_rider", "withdraw_open_offers",
]
