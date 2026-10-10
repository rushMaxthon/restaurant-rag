"""Riders bring in riders (the owner's rule, 2026-10-10).

A rider shares their code; a new rider signs up with it. Once the new rider
is approved, the clock runs: N successful deliveries within X days and both
are paid - the referrer A, the new rider B - as bonus rows that the next
payout includes (`payouts.py`). The terms are copied onto the referral when
the code is accepted, so the admin changing them later never breaks a
promise. Expiry is applied when a referral is read; no beat task.

Settings live in `platform_settings` ("rider_referral"), the same shape as
`fleet/config.py`: defaults in code, an admin row overrides, refused rather
than repaired.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.services.fleet.config import _read, _write

logger = logging.getLogger(__name__)

REFERRAL_KEY = "rider_referral"


@dataclass(frozen=True, slots=True)
class ReferralConfig:
    enabled: bool = True
    referrer_amount: Decimal = Decimal("500")
    joiner_amount: Decimal = Decimal("200")
    deliveries_required: int = 20
    days_allowed: int = 30


def _refuse(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


def _amount(value: Any, name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise _refuse(f"{name} must be a number") from None
    if not amount.is_finite() or amount < 0 or amount > 10000:
        raise _refuse(f"{name} must be between 0 and 10000")
    return amount.quantize(Decimal("0.01"))


def _whole(value: Any, name: str, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise _refuse(f"{name} must be a whole number") from None
    if not low <= number <= high:
        raise _refuse(f"{name} must be between {low} and {high}")
    return number


def validate_config(data: dict[str, Any]) -> ReferralConfig:
    base = ReferralConfig()
    return ReferralConfig(
        enabled=bool(data.get("enabled", base.enabled)),
        referrer_amount=_amount(data.get("referrer_amount", base.referrer_amount), "Referrer bonus"),
        joiner_amount=_amount(data.get("joiner_amount", base.joiner_amount), "New rider bonus"),
        deliveries_required=_whole(data.get("deliveries_required", base.deliveries_required),
                                   "Deliveries needed", 1, 500),
        days_allowed=_whole(data.get("days_allowed", base.days_allowed), "Days allowed", 1, 365),
    )


def config_value(cfg: ReferralConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "referrer_amount": str(cfg.referrer_amount),
        "joiner_amount": str(cfg.joiner_amount),
        "deliveries_required": cfg.deliveries_required,
        "days_allowed": cfg.days_allowed,
    }


def load_config(db: Session | None) -> ReferralConfig:
    raw = _read(db, REFERRAL_KEY)
    if not raw:
        return ReferralConfig()
    try:
        return validate_config(raw)
    except HTTPException:
        logger.error("Saved referral settings are invalid; using defaults: %s", raw)
        return ReferralConfig()


def save_config(db: Session, user: Any, data: dict[str, Any]) -> ReferralConfig:
    cfg = validate_config(data)
    _write(db, user, REFERRAL_KEY, config_value(cfg))
    return load_config(db)
