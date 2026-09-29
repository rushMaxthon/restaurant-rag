from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order_delivery import OrderDelivery
from app.api.deps import AppScopeDep, ensure_restaurant_readable, ensure_restaurant_writable
from app.config.database import get_db
from app.models.enums import OrderStatus, UserRole
from app.models.user import User
from app.schemas.order import (
    DeliveryQuoteRequest,
    DeliveryQuoteResponse,
    OrderCreateRequest,
    OrderDeliveryResponse,
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
    get_current_user,
    get_owner_restaurant_id,
    require_customer,
    require_owner,
    resolve_owner_restaurant_id,
)
from app.models.restaurant_location import RestaurantLocation
from app.services.delivery import geocoding
from app.services.delivery.quoting import fee_from, quote_for, usable_in
from app.services.orders import (
    create_order,
    normalize_stored_currency,
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


@router.post("/delivery-quote", response_model=DeliveryQuoteResponse)
def quote_delivery(
    payload: DeliveryQuoteRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> DeliveryQuoteResponse:
    """What delivery will cost, asked before the order exists.

    Always answers with a fee. A courier that is switched off, unconfigured,
    slow or unwilling to serve the address falls back to the branch's own flat
    rate — the figure every order has been charged until now — and says so in
    `source`. A checkout that could be left with no number to print would just
    invent one, which is the thing this whole path exists to avoid.

    Placing the order recomputes all of this server-side. This endpoint is for
    showing a customer a figure while they type, never the authority on what
    they are charged.
    """

    location = db.get(RestaurantLocation, payload.restaurant_location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    ensure_restaurant_writable(app_scope, location.restaurant_id)

    branch_fee = location.delivery_fee or 0
    # The same source an order is stamped from, so the figure shown here
    # and the figure charged cannot be in different currencies.
    currency = normalize_stored_currency(location.restaurant.currency)
    quote = quote_for(location, payload.delivery_address)
    if quote is None:
        return DeliveryQuoteResponse(
            delivery_fee=branch_fee, currency=currency, source="branch"
        )

    if not usable_in(quote, currency):
        # A courier pricing in a currency this order is not charged in has not
        # answered the question. The branch fee stands, and `source` says so
        # rather than a rupee figure appearing beside a dollar subtotal.
        return DeliveryQuoteResponse(
            delivery_fee=branch_fee, currency=currency, source="branch"
        )

    fee = fee_from(quote)
    if fee is None:
        # Unserviceable, or priced at nothing. The branch's fee stands and the
        # flag travels, so the page can warn without the fee disappearing.
        return DeliveryQuoteResponse(
            delivery_fee=branch_fee,
            currency=currency,
            source="branch",
            serviceable=quote.serviceable,
            exact_location=False,
        )

    pickup = geocoding.for_branch(location)
    drop = geocoding.for_address(payload.delivery_address)
    return DeliveryQuoteResponse(
        delivery_fee=fee,
        currency=currency,
        source="courier",
        serviceable=True,
        distance_metres=quote.distance_metres,
        assign_seconds=quote.assign_seconds,
        exact_location=pickup.exact and drop.exact,
    )


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
    owner_restaurant_id = (
        resolve_owner_restaurant_id(db, current_user)
        if current_user.role == UserRole.OWNER
        else None
    )
    order = get_order_for_user(db, current_user, order_id, owner_restaurant_id=owner_restaurant_id)
    ensure_restaurant_readable(app_scope, order.restaurant_id)
    return order


@router.get("/{order_id}/delivery", response_model=OrderDeliveryResponse | None)
def get_order_delivery(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
) -> OrderDeliveryResponse | None:
    """What the courier is doing with this order, or null if nobody was asked.

    Behind the same reader as the order itself rather than a looser check: a
    delivery carries a rider's phone number and the customer's distance, and
    whoever may not read the order may not read those either.
    """

    owner_restaurant_id = (
        resolve_owner_restaurant_id(db, current_user)
        if current_user.role == UserRole.OWNER
        else None
    )
    order = get_order_for_user(db, current_user, order_id, owner_restaurant_id=owner_restaurant_id)
    ensure_restaurant_readable(app_scope, order.restaurant_id)
    delivery = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))
    return OrderDeliveryResponse.model_validate(delivery) if delivery is not None else None


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
