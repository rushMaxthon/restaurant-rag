from __future__ import annotations

import uuid
from datetime import datetime
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
from app.schemas.payment import PaymentIntentResponse, PaymentLinkResponse, PaymentStatusResponse
from app.services.payments import (
    cancel_payment,
    create_payment_intent,
    create_payment_link,
    get_payment_status,
)
from app.services.auth import (
    ORDER_BOARD_ROLES,
    get_current_user,
    require_customer,
    require_order_board,
    resolve_order_board_scope,
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
    # The live-queue window, measured on when the kitchen must COOK an order
    # rather than when it was ordered. A scheduled order is placed days before
    # its slot — one in this database 21 days before — so a `placed_at` window
    # would hide tonight's work because it was ordered last week. Optional and
    # unset by every existing caller, so the owner and admin lists are
    # untouched: they want history, which is a different question.
    due_from: datetime | None = Query(default=None),
    sort: str | None = Query(default=None, max_length=40),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[OrderResponse]:
    # One resolver for every staff role, so the board a cook is shown and the
    # orders they can advance are decided by the same rule. A CUSTOMER never
    # reaches it: `list_orders` narrows them to their own orders by id, which
    # is a different question entirely.
    owner_restaurant_id: uuid.UUID | None = None
    scoped_location_id = restaurant_location_id
    if current_user.role in ORDER_BOARD_ROLES:
        scope = resolve_order_board_scope(
            db,
            current_user,
            requested_restaurant_id=restaurant_id,
            requested_restaurant_location_id=restaurant_location_id,
        )
        scoped_location_id = scope.restaurant_location_id
        # An ADMIN keeps reaching `list_orders` through `restaurant_id` below,
        # which is the unnarrowed platform-staff path it has always used.
        if current_user.role in (UserRole.OWNER, UserRole.KITCHEN):
            owner_restaurant_id = scope.restaurant_id
    orders, total = list_orders(
        db,
        current_user,
        owner_restaurant_id=owner_restaurant_id,
        restaurant_id=restaurant_id,
        app_scope_restaurant_id=app_scope.restaurant_filter_id,
        restaurant_location_id=scoped_location_id,
        search=search,
        status_filter=order_status,
        due_from=due_from,
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


@router.post("/{order_id}/payment-link", response_model=PaymentLinkResponse)
def create_order_payment_link(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> PaymentLinkResponse:
    """A hosted page to pay this order on, as a URL.

    The same guards as the payment sheet, and the same amount — read off the
    stored order, never off the request. What differs is where the card is
    typed: on Stripe's page, which is what makes this usable in a chat.
    """

    return create_payment_link(
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
    owner_restaurant_id: uuid.UUID | None = None
    owner_restaurant_location_id: uuid.UUID | None = None
    if current_user.role in (UserRole.OWNER, UserRole.KITCHEN):
        scope = resolve_order_board_scope(db, current_user)
        owner_restaurant_id = scope.restaurant_id
        owner_restaurant_location_id = scope.restaurant_location_id
    order = get_order_for_user(
        db,
        current_user,
        order_id,
        owner_restaurant_id=owner_restaurant_id,
        owner_restaurant_location_id=owner_restaurant_location_id,
    )
    ensure_restaurant_readable(app_scope, order.restaurant_id)
    return order


@router.patch("/{order_id}/status", response_model=OrderResponse)
def patch_order_status(
    order_id: uuid.UUID,
    payload: OrderStatusUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_order_board)],
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> OrderResponse:
    """Advance one order by one step.

    Was `require_owner`, which meant the only way to put a screen in a kitchen
    was to leave the owner signed in on it. It now admits the three roles that
    have a reason to touch an order board — and `resolve_order_board_scope`,
    not this route, decides what each of them may reach: an ADMIN names a
    restaurant or gets all of them, an OWNER gets their own, and a KITCHEN
    account gets the restaurant and branch stored on its row.

    `restaurant_id` is for an ADMIN, who has no restaurant of their own. An
    OWNER or KITCHEN account passing one is checked against their real scope
    and refused if it disagrees, never trusted.
    """

    scope = resolve_order_board_scope(
        db,
        current_user,
        requested_restaurant_id=restaurant_id,
    )
    return update_order_status(
        db,
        current_user,
        order_id=order_id,
        new_status=payload.status,
        owner_restaurant_id=scope.restaurant_id,
        owner_restaurant_location_id=scope.restaurant_location_id,
    )
