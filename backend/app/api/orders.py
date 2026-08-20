from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import AppScopeDep, ensure_restaurant_readable, ensure_restaurant_writable
from app.config.database import get_db
from app.models.enums import OrderStatus, UserRole
from app.models.user import User
from app.schemas.order import (
    OrderCreateRequest,
    OrderResponse,
    OrderStatusUpdateRequest,
    OrderValidationResponse,
)
from app.schemas.payment import PaymentIntentResponse, PaymentStatusResponse
from app.services.payments import (
    cancel_payment,
    create_payment_intent,
    get_payment_status,
)
from app.services.auth import (
    get_current_user,
    get_owner_restaurant_id,
    require_customer,
    require_owner,
    resolve_owner_restaurant_id,
)
from app.services.orders import (
    create_order,
    get_order_for_user,
    list_orders,
    update_order_status,
    validate_order_draft,
)

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("", response_model=OrderResponse)
def place_order(
    payload: OrderCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> OrderResponse:
    ensure_restaurant_writable(app_scope, payload.restaurant_id)
    return create_order(db, current_user, payload)


@router.post("/validate", response_model=OrderValidationResponse)
def validate_order(
    payload: OrderCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> OrderValidationResponse:
    ensure_restaurant_writable(app_scope, payload.restaurant_id)
    return validate_order_draft(db, current_user, payload)


@router.get("", response_model=list[OrderResponse])
def get_orders(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
    restaurant_id: uuid.UUID | None = Query(default=None),
    restaurant_location_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
    order_status: OrderStatus | None = Query(default=None),
    sort: str | None = Query(default=None, max_length=40),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[OrderResponse]:
    owner_restaurant_id = (
        resolve_owner_restaurant_id(db, current_user)
        if current_user.role == UserRole.OWNER
        else None
    )
    if (
        current_user.role == UserRole.OWNER
        and restaurant_id is not None
        and restaurant_id != owner_restaurant_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Owners can only access orders for their own restaurant",
        )
    orders, total = list_orders(
        db,
        current_user,
        owner_restaurant_id=owner_restaurant_id,
        restaurant_id=restaurant_id,
        app_scope_restaurant_id=app_scope.restaurant_filter_id,
        restaurant_location_id=restaurant_location_id,
        search=search,
        status_filter=order_status,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    return orders


@router.post("/{order_id}/payment-intent", response_model=PaymentIntentResponse)
def create_order_payment_intent(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> PaymentIntentResponse:
    """Start (or resume) payment for a card order.

    The amount is taken from the stored order, never from the request body.
    """

    return create_payment_intent(
        db,
        current_user,
        order_id,
        app_scope_restaurant_id=app_scope.restaurant_filter_id,
    )


@router.post("/{order_id}/payment-cancel", response_model=PaymentStatusResponse)
def cancel_order_payment(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> PaymentStatusResponse:
    """Customer dismissed the payment sheet; the order stays retryable."""

    return cancel_payment(
        db,
        current_user,
        order_id,
        app_scope_restaurant_id=app_scope.restaurant_filter_id,
    )


@router.get("/{order_id}/payment-status", response_model=PaymentStatusResponse)
def read_order_payment_status(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> PaymentStatusResponse:
    """Short-poll fallback for the window before the webhook lands."""

    return get_payment_status(
        db,
        current_user,
        order_id,
        app_scope_restaurant_id=app_scope.restaurant_filter_id,
    )


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
) -> OrderResponse:
    owner_restaurant_id = (
        resolve_owner_restaurant_id(db, current_user)
        if current_user.role == UserRole.OWNER
        else None
    )
    order = get_order_for_user(db, current_user, order_id, owner_restaurant_id=owner_restaurant_id)
    ensure_restaurant_readable(app_scope, order.restaurant_id)
    return order


@router.patch("/{order_id}/status", response_model=OrderResponse)
def patch_order_status(
    order_id: uuid.UUID,
    payload: OrderStatusUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    owner_restaurant_id: Annotated[uuid.UUID, Depends(get_owner_restaurant_id)],
    current_user: Annotated[User, Depends(require_owner)],
) -> OrderResponse:
    return update_order_status(
        db,
        current_user,
        order_id=order_id,
        new_status=payload.status,
        owner_restaurant_id=owner_restaurant_id,
    )
