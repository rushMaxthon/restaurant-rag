"""Payouts: what each restaurant is owed and where it is, and its linked
account.

One screen for both roles, like the rest of the panel. An OWNER is pinned to
their restaurant and may not name another (403). An ADMIN may list across
restaurants, leaving out demo kitchens unless one is named, and must name one
for anything about a single account (400). Only an admin changes anything.
An owner never sees `platform_keeps`, which with their share and the order
total would give the commission away.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config.database import get_db
from app.models.enums import PayoutStatus, UserRole
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.restaurant_payout import RestaurantPayout
from app.models.user import User
from app.schemas.payout import (
    PayoutAccountInput, PayoutAccountResponse, PayoutBucket, PayoutListResponse, PayoutRow, PayoutSummary,
)
from app.services.auth import get_current_user, resolve_owner_restaurant_id
from app.services.payments.base import PaymentProviderError
from app.services.payouts import accounts, service

router = APIRouter(prefix="/payouts", tags=["payouts"])

_BUCKETS = {
    "held": {PayoutStatus.HELD.value},
    "released": {PayoutStatus.RELEASED.value},
    "settled": {PayoutStatus.SETTLED.value},
    "waiting": {PayoutStatus.WAITING_ACCOUNT.value},
    "problems": {PayoutStatus.FAILED.value, PayoutStatus.BLOCKED.value},
    "not_applicable": {PayoutStatus.NOT_APPLICABLE.value, PayoutStatus.REVERSED.value},
}


def _staff(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    return user


def _admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the platform admin can do this.")
    return user


def _scope(db: Session, user: User, restaurant_id: uuid.UUID | None, *, required: bool) -> uuid.UUID | None:
    if user.role == UserRole.OWNER:
        own = resolve_owner_restaurant_id(db, user)
        if restaurant_id is not None and restaurant_id != own:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="That is not your restaurant.")
        return own
    if required and restaurant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="restaurant_id is required.")
    return restaurant_id


def _client():
    client = service.default_client()
    if client is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="The platform's Razorpay keys are not configured.")
    return client


@router.get("", response_model=PayoutListResponse)
def list_payouts(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(_staff)],
    restaurant_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> PayoutListResponse:
    scoped = _scope(db, user, restaurant_id, required=False)
    query = (
        select(RestaurantPayout, Order.placed_at, Restaurant.name)
        .join(Order, Order.id == RestaurantPayout.order_id)
        .join(Restaurant, Restaurant.id == RestaurantPayout.restaurant_id)
    )
    if scoped is not None:
        query = query.where(RestaurantPayout.restaurant_id == scoped)
    else:
        query = query.where(Restaurant.is_demo.is_(False))
    if date_from is not None:
        query = query.where(Order.placed_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        query = query.where(Order.placed_at < datetime.combine(date_to + timedelta(days=1), time.min))
    if status_filter:
        query = query.where(RestaurantPayout.status == status_filter)
    found = db.execute(query.order_by(Order.placed_at.desc()).limit(1000)).all()

    owner = user.role == UserRole.OWNER
    rows = [
        PayoutRow(
            id=p.id, order_id=p.order_id, order_placed_at=placed_at, restaurant_id=p.restaurant_id,
            restaurant_name=name, restaurant_share=p.restaurant_share,
            platform_keeps=None if owner else p.platform_keeps, currency=p.currency, status=p.status,
            transfer_id=p.transfer_id, last_error=p.last_error, released_at=p.released_at,
            settled_at=p.settled_at,
        )
        for p, placed_at, name in found
    ]
    summary = {
        key: PayoutBucket(
            count=sum(1 for r in rows if r.status in statuses),
            amount=sum((r.restaurant_share for r in rows if r.status in statuses), Decimal("0.00")),
        )
        for key, statuses in _BUCKETS.items()
    }
    return PayoutListResponse(
        currency=rows[0].currency if rows else "INR",
        payouts_enabled=get_settings().enable_restaurant_payouts,
        summary=PayoutSummary(**summary),
        rows=rows,
    )


@router.post("/{payout_id}/retry", response_model=dict)
def retry_payout(payout_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                 _user: Annotated[User, Depends(_admin)]) -> dict:
    try:
        row = service.retry(db, payout_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payout not found") from error
    return {"status": row.status, "last_error": row.last_error}


@router.get("/account", response_model=PayoutAccountResponse | None)
def get_payout_account(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(_staff)],
                       restaurant_id: uuid.UUID | None = None):
    account = accounts.get_account(db, _scope(db, user, restaurant_id, required=True))
    return accounts.describe(account) if account is not None else None


@router.put("/account", response_model=PayoutAccountResponse)
def save_payout_account(payload: PayoutAccountInput, db: Annotated[Session, Depends(get_db)],
                        user: Annotated[User, Depends(_admin)], restaurant_id: uuid.UUID | None = None):
    scoped = _scope(db, user, restaurant_id, required=True)
    try:
        return accounts.describe(accounts.save_draft(db, scoped, payload, user.id))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/account/submit", response_model=PayoutAccountResponse)
def submit_payout_account(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(_admin)],
                          restaurant_id: uuid.UUID | None = None):
    scoped = _scope(db, user, restaurant_id, required=True)
    try:
        return accounts.describe(accounts.submit(db, scoped, _client()))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PaymentProviderError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


@router.post("/account/refresh", response_model=PayoutAccountResponse)
def refresh_payout_account(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(_admin)],
                           restaurant_id: uuid.UUID | None = None):
    scoped = _scope(db, user, restaurant_id, required=True)
    try:
        return accounts.describe(accounts.refresh_status(db, scoped, _client()))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PaymentProviderError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
