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
class PaySlab:
    #: A trip up to this far (inclusive) pays `amount`.
    up_to_km: float
    amount: Decimal


@dataclass(frozen=True, slots=True)
class RiderPay:
    """The owner's rate card (2026-10-10), replacing `base + per_km x km`.

    A trip pays the slab its distance falls in, plus `incentive` for every
    delivery. Past the last slab there is no price: the trip waits for the
    admin to set one (the owner's "manual pricing above 8 km"), so a long
    ride is never paid a number nobody chose. `minimum` is what a ride to
    the restaurant pays when the order is cancelled after the rider got
    there - the incentive is for a delivery, so it is not added.
    """

    slabs: tuple[PaySlab, ...]
    incentive: Decimal
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
    #: A killed app (the owner's rule, 2026-10-10): sends no location, but a
    #: push still wakes it. A rider on shift whose phone has a push token stays
    #: reachable this long after it went quiet - asked after every rider whose
    #: phone IS reporting - and only then is taken off shift, with a push
    #: saying so. 0 = the old rule (`silent_minutes` for everyone).
    push_minutes: int = 15
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


#: The owner's table, 2026-10-10. Rs 25 up to 3 km, then Rs 5 more every km.
_RATE_CARD = (
    (3.0, "25"), (3.5, "25"), (4.0, "30"), (4.5, "30"), (5.0, "35"), (5.5, "35"),
    (6.0, "40"), (6.5, "40"), (7.0, "45"), (7.5, "45"), (8.0, "50"),
)


def default_pay() -> RiderPay:
    return RiderPay(
        slabs=tuple(PaySlab(km, Decimal(amount)) for km, amount in _RATE_CARD),
        incentive=Decimal("5"),
        minimum=Decimal("25"),
    )


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
    """Refused rather than repaired: a saved mistake is every rider's pay at once."""

    rows = data.get("slabs")
    if not isinstance(rows, list) or not rows:
        raise _refuse("Add at least one distance slab")
    if len(rows) > 40:
        raise _refuse("At most 40 distance slabs")
    slabs: list[PaySlab] = []
    for row in rows:
        if not isinstance(row, dict):
            raise _refuse("Each slab needs a distance and an amount")
        try:
            km = float(row.get("up_to_km"))
        except (TypeError, ValueError):
            raise _refuse("Each slab's distance must be a number") from None
        if not 0 < km <= 50:
            raise _refuse("A slab's distance must be between 0 and 50 km")
        amount = _money(row.get("amount"), "A slab's pay")
        if slabs and km <= slabs[-1].up_to_km:
            raise _refuse("Each slab must go further than the one before it")
        if slabs and amount < slabs[-1].amount:
            # A rider must never earn less for riding further.
            raise _refuse("A longer slab cannot pay less than a shorter one")
        slabs.append(PaySlab(round(km, 2), amount))
    pay = RiderPay(
        slabs=tuple(slabs),
        incentive=_money(data.get("incentive"), "Incentive per delivery"),
        minimum=_money(data.get("minimum"), "Pay for a cancelled ride"),
    )
    if all(s.amount == 0 for s in pay.slabs) and pay.incentive == 0:
        raise _refuse("A delivery must pay the rider something")
    return pay


def pay_value(pay: RiderPay) -> dict[str, Any]:
    """The stored and wire shape: amounts as strings, so nothing rounds on the way."""

    return {
        "slabs": [{"up_to_km": s.up_to_km, "amount": str(s.amount)} for s in pay.slabs],
        "incentive": str(pay.incentive),
        "minimum": str(pay.minimum),
    }


def load_pay(db: Session | None) -> RiderPay:
    raw = _read(db, PAY_KEY)
    if not raw:
        return default_pay()
    try:
        return validate_pay(raw)
    except HTTPException:
        # Also a row from before the rate card (base + per_km): not a rate
        # card, and the owner's table is what replaced it.
        logger.error("Saved rider pay is invalid; using defaults: %s", raw)
        return default_pay()


def save_pay(db: Session, user: Any, data: dict[str, Any]) -> RiderPay:
    pay = validate_pay(data)
    _write(db, user, PAY_KEY, pay_value(pay))
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
        push_minutes=_whole(data, "push_minutes", 0, 60, base.push_minutes),
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
    "FLEET_KEY", "FleetConfig", "PAY_KEY", "PaySlab", "RiderPay", "default_pay", "load_fleet", "load_pay",
    "pay_value", "save_fleet", "save_pay", "validate_fleet", "validate_pay",
]
