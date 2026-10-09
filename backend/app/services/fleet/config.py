"""The fleet's two admin-set records in `platform_settings`: rider pay and dispatch dials.

Same shape as `delivery/slabs.py`, deliberately: defaults in code so nothing
needs saving before the first trip, an admin row overrides, a savepoint read
so a database without the row (or the table) costs nothing, and validation
that refuses a value which would be wrong for every trip at once.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PAY_KEY = "rider_pay"
FLEET_KEY = "own_fleet"


@dataclass(frozen=True, slots=True)
class RiderPay:
    base: Decimal
    per_km: Decimal
    minimum: Decimal


@dataclass(frozen=True, slots=True)
class FleetConfig:
    #: How long one rider has to accept before the next is asked.
    offer_seconds: int = 30
    #: Riders pinged one by one. After that the order stays open on every free
    #: rider's list until the window closes - it no longer goes to Pidge early.
    max_offers: int = 5
    #: Total time our fleet gets before Pidge takes over, whatever happened.
    #: 5, not 4: our riders are the first choice (decided 2026-10-08).
    window_minutes: int = 5
    #: Straight-line distance from the branch within which a rider is asked.
    radius_km: float = 6.0
    #: No location for this long and a rider is no longer "online".
    silent_minutes: int = 3
    #: Waves (the owner's rule, 2026-10-09): an order is shown to the riders
    #: nearest the restaurant first - within `first_wave_km` - and every
    #: `wave_minutes` nobody takes it, it reaches one ring further out, up to
    #: `radius_km`. `offers.reach_m` is the one place that reads them.
    wave_minutes: int = 2
    first_wave_km: float = 2.0
    #: Food-ready time (2026-10-10): an order reaches riders this many minutes
    #: before the branch's preparation time says it is ready - at once when it
    #: is ready sooner. Ten is about a ride to the restaurant. `fleet.ready`.
    ready_lead_minutes: int = 10
    #: Branches the fleet serves; empty means every branch. A visible list on
    #: the admin page, never a constant in code - the AI allowlist that was
    #: deleted from this codebase is the warning.
    location_ids: list[str] = field(default_factory=list)


def default_pay() -> RiderPay:
    return RiderPay(base=Decimal("25"), per_km=Decimal("6"), minimum=Decimal("30"))


def _read(db: Session | None, key: str) -> dict[str, Any] | None:
    if db is None:
        return None
    from app.models.platform_setting import PlatformSetting

    try:
        with db.begin_nested():
            row = db.get(PlatformSetting, key)
    except SQLAlchemyError:
        logger.warning("platform_settings unreadable; using fleet defaults for %s", key)
        return None
    return dict(row.value or {}) if row is not None else None


def _write(db: Session, user: Any, key: str, value: dict[str, Any]) -> None:
    from app.models.platform_setting import PlatformSetting

    row = db.get(PlatformSetting, key)
    if row is None:
        db.add(PlatformSetting(key=key, value=value, updated_by_user_id=user.id))
    else:
        row.value = value
        row.updated_by_user_id = user.id
    db.commit()
    logger.info("%s changed by %s: %s", key, user.id, value)


def _refuse(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


def _money(value: Any, name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise _refuse(f"{name} must be a number") from None
    if not amount.is_finite() or amount < 0 or amount > 1000:
        raise _refuse(f"{name} must be between 0 and 1000")
    return amount


def validate_pay(data: dict[str, Any]) -> RiderPay:
    pay = RiderPay(
        base=_money(data.get("base"), "Base pay"),
        per_km=_money(data.get("per_km"), "Pay per km"),
        minimum=_money(data.get("minimum"), "Minimum per trip"),
    )
    if pay.base == 0 and pay.per_km == 0 and pay.minimum == 0:
        raise _refuse("A trip must pay the rider something")
    return pay


def load_pay(db: Session | None) -> RiderPay:
    raw = _read(db, PAY_KEY)
    if not raw:
        return default_pay()
    try:
        return validate_pay(raw)
    except HTTPException:
        logger.error("Saved rider pay is invalid; using defaults: %s", raw)
        return default_pay()


def save_pay(db: Session, user: Any, data: dict[str, Any]) -> RiderPay:
    pay = validate_pay(data)
    _write(db, user, PAY_KEY, {"base": str(pay.base), "per_km": str(pay.per_km), "minimum": str(pay.minimum)})
    return load_pay(db)


def _whole(data: dict[str, Any], name: str, low: int, high: int, default: int) -> int:
    value = data.get(name, default)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise _refuse(f"{name} must be a whole number") from None
    if not low <= number <= high:
        raise _refuse(f"{name} must be between {low} and {high}")
    return number


def validate_fleet(data: dict[str, Any]) -> FleetConfig:
    base = FleetConfig()
    try:
        radius = float(data.get("radius_km", base.radius_km))
    except (TypeError, ValueError):
        raise _refuse("radius_km must be a number") from None
    if not 0.5 <= radius <= 25:
        raise _refuse("radius_km must be between 0.5 and 25")
    try:
        first_wave = float(data.get("first_wave_km", base.first_wave_km))
    except (TypeError, ValueError):
        raise _refuse("first_wave_km must be a number") from None
    if not 0.5 <= first_wave <= 25:
        raise _refuse("first_wave_km must be between 0.5 and 25")
    ids = data.get("location_ids", [])
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise _refuse("location_ids must be a list of branch ids")
    return FleetConfig(
        offer_seconds=_whole(data, "offer_seconds", 10, 120, base.offer_seconds),
        max_offers=_whole(data, "max_offers", 1, 20, base.max_offers),
        window_minutes=_whole(data, "window_minutes", 1, 30, base.window_minutes),
        radius_km=radius,
        silent_minutes=_whole(data, "silent_minutes", 1, 30, base.silent_minutes),
        wave_minutes=_whole(data, "wave_minutes", 1, 10, base.wave_minutes),
        first_wave_km=first_wave,
        ready_lead_minutes=_whole(data, "ready_lead_minutes", 0, 60, base.ready_lead_minutes),
        location_ids=list(ids),
    )


def load_fleet(db: Session | None) -> FleetConfig:
    raw = _read(db, FLEET_KEY)
    if not raw:
        return FleetConfig()
    try:
        return validate_fleet(raw)
    except HTTPException:
        logger.error("Saved fleet config is invalid; using defaults: %s", raw)
        return FleetConfig()


def save_fleet(db: Session, user: Any, data: dict[str, Any]) -> FleetConfig:
    fleet = validate_fleet(data)
    _write(db, user, FLEET_KEY, asdict(fleet))
    return load_fleet(db)


__all__ = [
    "FLEET_KEY", "FleetConfig", "PAY_KEY", "RiderPay", "default_pay", "load_fleet", "load_pay",
    "save_fleet", "save_pay", "validate_fleet", "validate_pay",
]
