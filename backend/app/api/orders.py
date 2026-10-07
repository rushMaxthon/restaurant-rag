from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order
from app.api.deps import AppScope, AppScopeDep, ensure_restaurant_readable, ensure_restaurant_writable
from app.config.database import get_db
from app.models.enums import OrderStatus, UserRole
from app.models.order_delivery import OrderDelivery
from app.models.user import User
from app.schemas.order import (
    LiveOrdersResponse,
    DeliveryQuoteRequest,
    DeliveryQuoteResponse,
    OrderCreateRequest,
    DeliverySimulateRequest,
    OrderDeliveryResponse,
    OrderResponse,
    OrderStatusUpdateRequest,
    OrderCancelRequest,
    OrderValidationResponse,
)
from app.schemas.payment import PaymentIntentResponse, PaymentLinkResponse, PaymentStatusResponse
from app.services.rate_limit import per_ip
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
from app.models.restaurant_location import RestaurantLocation
from app.models.user_saved_address import UserSavedAddress
from app.services.delivery.quoting import attempt_quote, before_delivery_tax, fee_from, points_for, usable_in
from app.services.delivery.slabs import price_trip, slab_pricing_on
from app.services.geocoding.base import AddressQuery, GeocodeConfidence
from app.services import order_charges
from app.services.live_orders import build_live_board
from app.services.orders import (
    charges_response,
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


def _priced(location, payload: DeliveryQuoteRequest, delivery_fee) -> dict:
    """The rest of the bill, when the client sent a subtotal.

    The SAME function that charges the customer works this out, which is the
    whole point: a client adding up its own tax from rates on the branch would
    eventually disagree with what is charged, and the customer would be right to
    believe the screen.

    Empty when no subtotal was sent, so a caller that only wants a delivery fee
    still gets one.
    """

    if payload.subtotal is None:
        return {}
    charges = order_charges.for_location(
        location,
        subtotal=payload.subtotal,
        delivery_fee=delivery_fee,
        discount_amount=payload.discount_amount,
    )
    return {"charges": charges_response(charges), "total_amount": charges.total_amount}


def _why_no_quote(attempt, unusable: str, drop) -> str:
    """Which of the several reasons the branch fee is standing.

    Worth getting right because the page acts on it: one reason tells the
    customer to check their address, another tells them there is nothing they
    can do. Reporting "no courier" for a lookup that landed in the wrong city
    sends them to wait for a problem that is theirs to fix.

    This used to GUESS, because `quote_for` returned a bare `None` for every
    kind of failure: no quote plus an inexact drop was read as the address
    being at fault. It is now told. The guess was wrong in the case that
    matters most — Pidge's sandbox answering 503 while a perfectly real Surat
    society geocoded to a `sublocality` — and it put the blame on the one
    person who could do nothing about it.

    A refused quote with an INEXACT drop is still read as the address: that is
    how the 1,605 km quote arrived, the courier priced the journey honestly and
    the distance backstop threw it out, which is a statement about the address.
    """

    if unusable:
        return unusable
    if attempt.quote is not None:
        return "currency_mismatch"
    reason = attempt.reason
    if reason in {"quotes_disabled", "no_courier", "cannot_quote"}:
        return "no_courier"
    if reason == "courier_unavailable":
        return "courier_unavailable"
    # `out_of_range` falls through: the courier answered, and the answer says
    # the address is somewhere nobody is driving to.
    return "address_unknown" if not drop.exact else "unserviceable"


@router.post("/delivery-quote", response_model=DeliveryQuoteResponse)
def quote_delivery(
    # Counted before anything else runs (`services/rate_limit.py`).
    _rate_limited: Annotated[None, Depends(per_ip("delivery-quote", limit=30, window_seconds=60))],
    payload: DeliveryQuoteRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> DeliveryQuoteResponse:
    """What delivery will cost, asked before the order exists.

    Always answers with a fee. A courier that is switched off, unconfigured,
    slow or unwilling to serve the address falls back to the branch's own flat
    rate — the figure every order has been charged until now — and says so in
    `source`. A checkout left with no number to print would invent one, which
    is the thing this whole path exists to avoid.

    Placing the order recomputes all of this server-side from the same rule.
    This endpoint shows a customer a figure while they type; it is never the
    authority on what they are charged.
    """

    location = db.get(RestaurantLocation, payload.restaurant_location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    ensure_restaurant_writable(app_scope, location.restaurant_id)

    branch_fee = location.delivery_fee or 0
    # The same source an order is stamped from, so the figure shown here and
    # the figure charged cannot be in different currencies.
    currency = normalize_stored_currency(location.restaurant.currency)

    # A saved address the customer picked from the autocomplete already carries
    # the map provider's own coordinates for that building. Re-geocoding it
    # would be a paid call that returns a worse answer than the stored one.
    known_drop: tuple[float, float, str] | None = None
    if payload.latitude is not None and payload.longitude is not None:
        # A place the customer picked. ROOFTOP because they chose a building
        # from a list rather than typed a string somebody has to interpret —
        # which is the one case where the coordinate is better than anything
        # this server could work out for itself.
        known_drop = (payload.latitude, payload.longitude, GeocodeConfidence.ROOFTOP.value)
    elif payload.saved_address_id is not None:
        saved = db.get(UserSavedAddress, payload.saved_address_id)
        # Scoped to the caller: an address id is a guessable handle, and
        # quoting against somebody else's would leak where they live by way of
        # a delivery distance.
        if saved is not None and saved.user_id == current_user.id:
            if saved.latitude is not None and saved.longitude is not None:
                known_drop = (saved.latitude, saved.longitude, saved.geocode_confidence)

    query = AddressQuery(
        line1=payload.delivery_address,
        city=payload.city,
        state=payload.state,
        postal_code=payload.postal_code,
        country=payload.country,
        # When the form sent no parts, the line is all there is and it is a
        # whole address rather than a street — so it is geocoded as freeform.
        freeform="" if payload.city else payload.delivery_address,
    )

    # Located once and passed down. Geocoding both ends twice would double
    # every paid lookup, which caching hides in development and a bill exposes
    # in production.
    pickup, drop = points_for(location, query, db=db, known_drop=known_drop)
    located = {
        "exact_location": pickup.exact and drop.exact,
        "located_by": drop.source,
        "matched_address": drop.matched,
    }
    # A branch located for the first time has its coordinates written onto its
    # row by `for_branch`. Committing here is what makes every later order free.
    if db.is_modified(location):
        db.commit()

    # Which end failed, when one did. A checkout that only knows "the flat fee
    # applies" cannot tell a customer whether to fix their address or whether
    # there is nothing they can do — and the difference is the whole of whether
    # the page is useful. Reported before the courier is asked, because a
    # coordinate problem is not the courier's fault.
    unusable = (
        "branch_unknown"
        if not pickup.usable
        else "address_unknown"
        if not drop.usable
        else ""
    )

    if slab_pricing_on() and not unusable:
        # The platform's price for the distance - the same function, with the
        # same points, as the order that will charge it.
        trip = price_trip(location, query, db=db, points=(pickup, drop))
        if trip.reason == "out_of_range":
            no_fee = Decimal("0.00")
            return DeliveryQuoteResponse(
                delivery_fee=no_fee,
                currency=currency,
                source="distance",
                serviceable=False,
                fallback_reason="out_of_range",
                distance_metres=trip.distance_metres,
                max_distance_km=trip.limit_km,
                **_priced(location, payload, no_fee),
                **located,
            )
        if trip.fee is not None:
            return DeliveryQuoteResponse(
                delivery_fee=trip.fee,
                currency=currency,
                source="distance",
                serviceable=trip.serviceable,
                distance_metres=trip.distance_metres,
                max_distance_km=trip.limit_km,
                assign_seconds=trip.quote.assign_seconds if trip.quote else None,
                travel_seconds=trip.quote.travel_seconds if trip.quote else None,
                **_priced(location, payload, trip.fee),
                **located,
            )

    attempt = attempt_quote(location, query, db=db, points=(pickup, drop))
    quote = attempt.quote
    if quote is None or not usable_in(quote, currency):
        # No courier, a coordinate we could not trust, or one pricing in a
        # currency this order is not charged in — which has not answered the
        # question. Either way the branch fee stands, and the reason travels so
        # the page does not announce free delivery over a failed lookup.
        return DeliveryQuoteResponse(
            delivery_fee=branch_fee,
            currency=currency,
            source="branch",
            fallback_reason=_why_no_quote(attempt, unusable, drop),
            **_priced(location, payload, branch_fee),
            **located,
        )

    fee = fee_from(quote)
    if fee is not None:
        # The same step the order path takes, or the checkout would quote one
        # delivery fee and the order would charge another.
        fee = before_delivery_tax(fee, location)
    if fee is None:
        # Unserviceable, or priced at nothing. The branch's fee stands and the
        # flag travels, so the page can warn without the fee disappearing.
        return DeliveryQuoteResponse(
            delivery_fee=branch_fee,
            currency=currency,
            source="branch",
            serviceable=quote.serviceable,
            fallback_reason="unserviceable",
            **_priced(location, payload, branch_fee),
            **located,
        )

    return DeliveryQuoteResponse(
        delivery_fee=fee,
        currency=currency,
        source="courier",
        serviceable=True,
        distance_metres=quote.distance_metres,
        assign_seconds=quote.assign_seconds,
        travel_seconds=quote.travel_seconds,
        **_priced(location, payload, fee),
        **located,
    )


@router.get("/live", response_model=LiveOrdersResponse)
def get_live_orders(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
    restaurant_id: uuid.UUID | None = Query(default=None),
    restaurant_location_id: uuid.UUID | None = Query(default=None),
    # "Today" is the operator's own midnight, which only their browser knows.
    # Unset, the board falls back to the last 24 hours rather than guessing a
    # timezone.
    completed_from: datetime | None = Query(default=None),
) -> LiveOrdersResponse:
    """Every open order in scope, and the ones delivered today.

    Declared before `/{order_id}` on purpose: registered after it, "live"
    would be read as an order id. Staff only — a customer has their own order
    history and no business with a board.

    The scope is `resolve_order_board_scope`, the same resolver `GET /orders`
    uses, so an admin may name a restaurant or see all of them, an owner sees
    their own, and a pinned kitchen account its own branch.
    """

    if current_user.role not in ORDER_BOARD_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view the live orders board",
        )
    scope = resolve_order_board_scope(
        db,
        current_user,
        requested_restaurant_id=restaurant_id,
        requested_restaurant_location_id=restaurant_location_id,
    )
    owner_restaurant_id = (
        scope.restaurant_id if current_user.role in (UserRole.OWNER, UserRole.KITCHEN) else None
    )
    return build_live_board(
        db,
        current_user,
        owner_restaurant_id=owner_restaurant_id,
        restaurant_id=restaurant_id,
        restaurant_location_id=scope.restaurant_location_id,
        app_scope_restaurant_id=app_scope.restaurant_filter_id,
        completed_from=completed_from or datetime.now(timezone.utc) - timedelta(hours=24),
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
    # The live-queue window, measured on when the kitchen must COOK an order
    # rather than when it was ordered. A scheduled order is placed days before
    # its slot — one in this database 21 days before — so a `placed_at` window
    # would hide tonight's work because it was ordered last week. Optional and
    # unset by every existing caller, so the owner and admin lists are
    # untouched: they want history, which is a different question.
    due_from: datetime | None = Query(default=None),
    # The kitchen's history: orders DELIVERED at or after this instant, from
    # the status-event log. See `list_orders` for why it is not `due_from`.
    completed_from: datetime | None = Query(default=None),
    sort: str | None = Query(default=None, max_length=40),
    # 200 when unset, never unlimited (2026-10-07 security review): an
    # admin's GET /orders with no limit returned every order on the platform,
    # each with a customer's name, phone and address, in one response. 200
    # is the most any screen asks for; a customer's own history fits in it.
    limit: int | None = Query(default=200, ge=1, le=200),
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
        completed_from=completed_from,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    # A kitchen tablet gets no customer account details (`for_viewer`).
    return [order.for_viewer(current_user) for order in orders]


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


def _read_order(
    db: Session,
    current_user: User,
    order_id: uuid.UUID,
    app_scope: AppScope,
) -> OrderResponse:
    # One reader for the order and everything hung off it. The delivery route
    # was written against the owner-only scope and would otherwise have been a
    # second copy of this rule to fall out of step — a pinned cook must not
    # read a rider's phone number for a branch whose order they cannot open.
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


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
) -> OrderResponse:
    return _read_order(db, current_user, order_id, app_scope).for_viewer(current_user)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: uuid.UUID,
    payload: OrderCancelRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_order_board)],
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> OrderResponse:
    """Cancel an order the rider has not collected, and refund it if prepaid.

    The platform admin or the restaurant's owner only; a cook is refused in
    `order_cancellation`, which also holds every other rule. Scoped by
    `resolve_order_board_scope` like every board route, so an order outside
    the caller's restaurant is a 404.
    """

    from app.services import order_cancellation
    from app.services.orders import serialize_order_by_id

    scope = resolve_order_board_scope(db, current_user, requested_restaurant_id=restaurant_id)
    order = order_cancellation.cancel_by_staff(
        db,
        current_user,
        order_id=order_id,
        scope_restaurant_id=scope.restaurant_id,
        reason=payload.reason,
        note=payload.note,
    )
    return serialize_order_by_id(db, order.id)


@router.post("/{order_id}/refund/retry", response_model=OrderResponse)
def retry_order_refund(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_order_board)],
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> OrderResponse:
    """Try a refund the gateway refused again, once its cause is fixed."""

    from app.services import order_cancellation
    from app.services.orders import serialize_order_by_id

    scope = resolve_order_board_scope(db, current_user, requested_restaurant_id=restaurant_id)
    order = order_cancellation.retry_refund(
        db, current_user, order_id=order_id, scope_restaurant_id=scope.restaurant_id
    )
    return serialize_order_by_id(db, order.id)


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

    order = _read_order(db, current_user, order_id, app_scope)
    delivery = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))
    return _delivery_response(db, delivery, current_user)


def _delivery_response(db: Session, delivery: OrderDelivery | None, viewer: User) -> OrderDeliveryResponse | None:
    if delivery is None:
        return None
    from app.services.delivery import service as delivery_service

    order = db.get(Order, delivery.order_id)
    response = OrderDeliveryResponse.model_validate(delivery)
    response.can_rebook = (
        order is not None
        and str(viewer.role) in {"ADMIN", "OWNER"}
        and delivery_service.can_rebook(order, delivery)
    )
    response.can_cancel = (
        order is not None
        and str(viewer.role) in {"ADMIN", "OWNER"}
        and delivery_service.can_cancel(order, delivery)
    )
    response.can_allocate = (
        order is not None
        and str(viewer.role) in {"ADMIN", "OWNER"}
        and delivery_service.can_allocate(order, delivery)
    )
    response.can_simulate = str(viewer.role) == "ADMIN" and delivery_service.simulate_allowed()
    if order is not None:
        response.paid_for_delivery = delivery_service.paid_for_delivery(order)
        response.courier_overpriced = delivery_service.courier_overpriced(order, delivery)
    return response.for_viewer(viewer)


def _staff_order(db: Session, current_user: User, order_id: uuid.UUID, app_scope: AppScope) -> Order:
    """The order, for an action only the restaurant or the platform may take.

    The reader decides whether this person may see it at all - 404 if not -
    and then the role decides whether they may act. A kitchen login sees the
    order and may not spend money on riders.
    """

    if str(current_user.role) not in {"ADMIN", "OWNER"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the restaurant or the platform can do this.")
    _read_order(db, current_user, order_id, app_scope)
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


def _delivery_action(db: Session, current_user: User, order: Order, action) -> OrderDeliveryResponse | None:
    from app.services.delivery.base import DeliveryProviderError

    try:
        row = action()
    except DeliveryProviderError as error:
        db.commit()  # keep `last_error`, which says why
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    db.commit()
    return _delivery_response(db, row, current_user)


@router.post("/{order_id}/delivery/cancel", response_model=OrderDeliveryResponse | None)
def cancel_order_delivery(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
) -> OrderDeliveryResponse | None:
    """Call the rider off, while the order itself stands.

    For a rider who is not coming, or an order the restaurant will hand over
    itself. Pidge allows it only before the food is collected; after that it
    refuses, and the refusal is shown rather than hidden.
    """

    from app.services.delivery import service as delivery_service

    order = _staff_order(db, current_user, order_id, app_scope)
    row = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))
    if not delivery_service.can_cancel(order, row):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This rider can no longer be called off: the order is finished or the food is already collected.",
        )
    return _delivery_action(db, current_user, order, lambda: delivery_service.cancel(db, order))


@router.post("/{order_id}/delivery/rebook", response_model=OrderDeliveryResponse | None)
def rebook_order_delivery(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
) -> OrderDeliveryResponse | None:
    """Book another rider after the last trip failed or was called off."""

    from app.services.delivery import service as delivery_service

    order = _staff_order(db, current_user, order_id, app_scope)
    return _delivery_action(db, current_user, order, lambda: delivery_service.rebook(db, order))


@router.post("/{order_id}/delivery/allocate", response_model=OrderDeliveryResponse | None)
def allocate_order_delivery(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
) -> OrderDeliveryResponse | None:
    """Ask the courier's networks again for a rider, for a booking nobody took.

    By hand only: the call it makes is charged by Pidge per request, so it is
    never retried on a timer.
    """

    from app.services.delivery import service as delivery_service

    order = _staff_order(db, current_user, order_id, app_scope)
    return _delivery_action(db, current_user, order, lambda: delivery_service.allocate(db, order))


@router.post("/{order_id}/delivery/simulate", response_model=OrderDeliveryResponse | None)
def simulate_order_delivery(
    order_id: uuid.UUID,
    payload: DeliverySimulateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
) -> OrderDeliveryResponse | None:
    """Sandbox only: make the courier report a stage, and record it as real.

    Platform admin only, and refused unless the courier is its sandbox, where
    no rider exists to be sent anywhere.
    """

    from app.services.delivery import service as delivery_service

    if str(current_user.role) != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the platform admin can simulate.")
    order = _staff_order(db, current_user, order_id, app_scope)
    return _delivery_action(
        db, current_user, order, lambda: delivery_service.simulate(db, order, payload.status)
    )


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
    ).for_viewer(current_user)
