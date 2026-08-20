from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
import sqlalchemy as sa
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.config.celery import celery_app
from app.models.enums import (
    OrderEventActor,
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.personalized_offer import GeneratedOffer, PersonalizedOffer
from app.services.order_events import actor_for_user, record_order_status_event
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.order import (
    OrderCreateRequest,
    OrderCustomerSummary,
    OrderItemResponse,
    OrderValidationResponse,
    OrderRestaurantLocationSummary,
    OrderResponse,
    OrderRestaurantSummary,
)
from app.services.menu_item_customizations import (
    SelectedCustomizationOptionInput,
    fetch_menu_items_for_customized_order,
    resolve_menu_item_selection,
)
from app.services.bestsellers import invalidate_bestseller_cache_for_locations
from app.services.personalized_offers import (
    invalidate_user_personalized_offers_cache,
    rebuild_generated_offers,
    record_offer_conversion,
    sync_global_welcome_offer_for_user,
    validate_generated_offer_for_order,
    validate_offer_for_order,
)
from app.services.payments.registry import (
    available_payment_methods,
    is_method_supported,
    provider_name_for,
)
from app.services.recommendations import invalidate_user_recommendation_cache
from app.services.restaurant_locations import (
    get_enabled_payment_methods,
    get_location_fulfillment_status,
    resolve_location_for_restaurant,
    schedule_slot_is_available,
)
from app.services.notifications import send_order_placed_notification
from app.config import get_settings

settings = get_settings()
BUSINESS_TIMEZONE: ZoneInfo = settings.business_timezone_info
logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")
# Money has actually been committed. PAYMENT_PENDING orders are excluded, which
# is what keeps an unpaid card order out of the restaurant's queue.
SETTLED_PAYMENT_STATUSES = frozenset({PaymentStatus.PAID, PaymentStatus.COD})
# PAYMENT_PENDING and CANCELLED are absent by design: neither can be advanced.
ORDER_STATUS_FLOW: dict[OrderStatus, OrderStatus] = {
    OrderStatus.PLACED: OrderStatus.ACCEPTED,
    OrderStatus.ACCEPTED: OrderStatus.PREPARING,
    OrderStatus.PREPARING: OrderStatus.OUT_FOR_DELIVERY,
    OrderStatus.OUT_FOR_DELIVERY: OrderStatus.DELIVERED,
}


@dataclass(slots=True)
class PreparedOrderDraft:
    restaurant: Restaurant
    restaurant_location: RestaurantLocation
    scheduled_at: datetime
    subtotal: Decimal
    delivery_fee: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    order_items: list[OrderItem]
    applied_offer: object | None


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _safe_decimal(value: Decimal | int | float | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return _quantize(value)
    return _quantize(Decimal(str(value)))


def _refresh_generated_combos_after_order_event(*, lookback_days: int) -> None:
    # Keep combo generation reliable even when Celery is not running in local/dev setups.
    try:
        from app.config.database import SessionLocal
        from app.services.generated_combos import rebuild_generated_combos

        db = SessionLocal()
        try:
            rebuild_generated_combos(db, lookback_days=lookback_days)
        finally:
            db.close()
    except Exception:
        # Order placement/status flow should not fail if combo refresh has a problem.
        logger.exception(
            "Generated combo refresh failed after order event lookback_days=%s",
            lookback_days,
        )


def _order_base_query() -> Select[tuple[Order]]:
    return (
        select(Order)
        .options(
            selectinload(Order.items),
            selectinload(Order.restaurant),
            selectinload(Order.restaurant_location),
            selectinload(Order.customer),
        )
        .order_by(Order.placed_at.desc(), Order.created_at.desc())
    )


def _serialize_order(order: Order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        customer_id=order.customer_id,
        restaurant_id=order.restaurant_id,
        restaurant=OrderRestaurantSummary(
            id=order.restaurant.id,
            name=order.restaurant.name,
            slug=order.restaurant.slug,
            cuisine_type=order.restaurant.cuisine_type,
            city=order.restaurant.city,
            address_line_1=order.restaurant.address_line_1,
        ),
        restaurant_location_id=order.restaurant_location_id,
        restaurant_location=OrderRestaurantLocationSummary(
            id=order.restaurant_location.id,
            branch_name=order.restaurant_location.branch_name,
            city=order.restaurant_location.city,
            address_line_1=order.restaurant_location.address_line_1,
            delivery_fee=order.restaurant_location.delivery_fee,
            minimum_order_amount=order.restaurant_location.minimum_order_amount,
            estimated_delivery_time=order.restaurant_location.estimated_delivery_time,
            estimated_pickup_time=order.restaurant_location.estimated_pickup_time,
            delivery_enabled=order.restaurant_location.delivery_enabled,
            pickup_enabled=order.restaurant_location.pickup_enabled,
            enabled_payment_methods=get_enabled_payment_methods(order.restaurant_location),
            is_open=order.restaurant_location.is_open,
            is_active=order.restaurant_location.is_active,
        ),
        customer=OrderCustomerSummary(
            id=order.customer.id,
            full_name=order.customer.full_name,
            email=order.customer.email,
            phone_number=order.customer.phone_number,
        ),
        status=order.status,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        payment_provider=order.payment_provider,
        payment_reference=order.payment_reference,
        fulfillment_type=order.fulfillment_type,
        schedule_type=order.schedule_type,
        scheduled_at=order.scheduled_at,
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        tax_amount=order.tax_amount,
        discount_amount=order.discount_amount,
        total_amount=order.total_amount,
        currency=order.currency,
        special_instructions=order.special_instructions,
        delivery_address=order.delivery_address,
        placed_at=order.placed_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[
            OrderItemResponse(
                id=item.id,
                menu_item_id=item.menu_item_id,
                menu_item_size_id=item.menu_item_size_id,
                item_name_snapshot=item.item_name_snapshot,
                size_name_snapshot=item.size_name_snapshot,
                quantity=item.quantity,
                base_unit_price=item.base_unit_price,
                customization_total_price=item.customization_total_price,
                unit_price=item.unit_price,
                total_price=item.total_price,
                selected_options_snapshot=item.selected_options_snapshot,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in order.items
        ],
    )


def _load_restaurant_for_order(db: Session, restaurant_id: uuid.UUID) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None or not restaurant.is_active or not restaurant.is_approved:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    if not restaurant.is_open:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restaurant is currently closed")
    return restaurant


def _load_location_for_order(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID | None,
    fulfillment_type: OrderFulfillmentType,
    schedule_type: OrderScheduleType,
    scheduled_at: datetime,
) -> RestaurantLocation:
    location = resolve_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=restaurant_location_id,
        include_inactive=False,
    )
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant location not found")
    if not location.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restaurant location is inactive")
    if not location.is_open:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restaurant location is currently closed")
    if schedule_type == OrderScheduleType.SCHEDULED:
        is_available, unavailable_reason = schedule_slot_is_available(
            location,
            fulfillment_type=fulfillment_type,
            scheduled_at=scheduled_at,
        )
    else:
        is_available, unavailable_reason = get_location_fulfillment_status(
            location,
            fulfillment_type=fulfillment_type,
        )
    if not is_available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=unavailable_reason or "This branch is unavailable for the selected fulfillment type right now",
        )
    return location


def _resolve_scheduled_at(payload: OrderCreateRequest) -> datetime:
    if payload.schedule_type == OrderScheduleType.SCHEDULED:
        if payload.scheduled_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please choose a valid scheduled time.",
            )
        if payload.scheduled_at.tzinfo is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Scheduled time must include timezone information.",
            )
        return payload.scheduled_at.astimezone(BUSINESS_TIMEZONE)
    return datetime.now(BUSINESS_TIMEZONE)


def _prepare_order_draft(
    db: Session,
    customer: User,
    payload: OrderCreateRequest,
    *,
    require_payment_validation: bool,
) -> PreparedOrderDraft:
    if customer.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can place orders",
        )

    logger.info(
        "Order draft request customer_id=%s restaurant_id=%s location_id=%s items=%s require_payment_validation=%s",
        customer.id,
        payload.restaurant_id,
        payload.restaurant_location_id,
        [
            {
                "menu_item_id": str(item.menu_item_id),
                "menu_item_size_id": str(item.menu_item_size_id) if item.menu_item_size_id else None,
                "selected_options": [
                    {
                        "option_id": str(option.option_id),
                        "quantity": option.quantity,
                    }
                    for option in item.selected_options
                ],
                "quantity": item.quantity,
            }
            for item in payload.items
        ],
        require_payment_validation,
    )

    restaurant = _load_restaurant_for_order(db, payload.restaurant_id)
    scheduled_at = _resolve_scheduled_at(payload)
    restaurant_location = _load_location_for_order(
        db,
        restaurant_id=restaurant.id,
        restaurant_location_id=payload.restaurant_location_id,
        fulfillment_type=payload.fulfillment_type,
        schedule_type=payload.schedule_type,
        scheduled_at=scheduled_at,
    )
    enabled_payment_methods = get_enabled_payment_methods(restaurant_location)
    if not enabled_payment_methods:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This branch does not have any payment methods enabled right now.",
        )
    if (
        require_payment_validation
        and payload.payment_method not in enabled_payment_methods
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This payment method is not enabled for the selected branch.",
        )
    # The branch may advertise a method this deployment cannot actually settle
    # (GOOGLE_PAY/RAZORPAY are still valid enum values from the mocked era).
    if require_payment_validation and not is_method_supported(payload.payment_method):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This payment method is not supported.",
        )
    if (
        require_payment_validation
        and payload.payment_method == PaymentMethod.CARD
        and PaymentMethod.CARD not in available_payment_methods()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Card payments are not available right now.",
        )
    menu_items = fetch_menu_items_for_customized_order(
        db,
        restaurant_id=restaurant.id,
        restaurant_location_id=restaurant_location.id,
        menu_item_ids=[item.menu_item_id for item in payload.items],
    )

    subtotal = Decimal("0.00")
    order_items: list[OrderItem] = []
    for cart_item in payload.items:
        menu_item = menu_items[cart_item.menu_item_id]
        logger.info(
            "Resolving order cart item menu_item_id=%s menu_item_name=%s size_id=%s selected_options=%s quantity=%s",
            menu_item.id,
            menu_item.name,
            cart_item.menu_item_size_id,
            [
                {
                    "option_id": str(selected_option.option_id),
                    "quantity": selected_option.quantity,
                }
                for selected_option in cart_item.selected_options
            ],
            cart_item.quantity,
        )
        resolved_selection = resolve_menu_item_selection(
            menu_item,
            menu_item_size_id=cart_item.menu_item_size_id,
            selected_options=[
                SelectedCustomizationOptionInput(
                    option_id=selected_option.option_id,
                    quantity=selected_option.quantity,
                )
                for selected_option in cart_item.selected_options
            ],
        )
        unit_price = resolved_selection.unit_price
        total_price = _quantize(unit_price * cart_item.quantity)
        subtotal += total_price

        order_items.append(
            OrderItem(
                menu_item_id=menu_item.id,
                item_name_snapshot=menu_item.name,
                menu_item_size_id=resolved_selection.size_id,
                size_name_snapshot=resolved_selection.size_name,
                quantity=cart_item.quantity,
                base_unit_price=resolved_selection.base_unit_price,
                customization_total_price=resolved_selection.customization_total_price,
                unit_price=unit_price,
                total_price=total_price,
                selected_options_snapshot=resolved_selection.selected_options_snapshot(),
            )
        )

    subtotal = _quantize(subtotal)
    minimum_order_amount = _safe_decimal(restaurant_location.minimum_order_amount)
    if subtotal < minimum_order_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Minimum order amount for this restaurant is {minimum_order_amount:.2f}",
        )

    delivery_fee = (
        _safe_decimal(restaurant_location.delivery_fee)
        if payload.fulfillment_type == OrderFulfillmentType.DELIVERY
        else Decimal("0.00")
    )
    tax_amount = _quantize(subtotal * Decimal("0.05"))
    discount_amount = Decimal("0.00")
    applied_offer = None
    if payload.generated_offer_id is not None:
        applied_offer, discount_amount = validate_generated_offer_for_order(
            db,
            user=customer,
            generated_offer_id=payload.generated_offer_id,
            generated_offer_user_match_id=payload.generated_offer_user_match_id,
            restaurant_id=restaurant.id,
            restaurant_location_id=restaurant_location.id,
            menu_items=menu_items.values(),
            subtotal=subtotal,
            delivery_fee=delivery_fee,
        )
    elif payload.personalized_offer_id is not None:
        applied_offer, discount_amount = validate_offer_for_order(
            db,
            user=customer,
            offer_id=payload.personalized_offer_id,
            restaurant_id=restaurant.id,
            restaurant_location_id=restaurant_location.id,
            menu_items=menu_items.values(),
            subtotal=subtotal,
            delivery_fee=delivery_fee,
        )
    total_amount = _quantize(subtotal + delivery_fee + tax_amount - discount_amount)

    return PreparedOrderDraft(
        restaurant=restaurant,
        restaurant_location=restaurant_location,
        scheduled_at=scheduled_at,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        tax_amount=tax_amount,
        discount_amount=discount_amount,
        total_amount=total_amount,
        order_items=order_items,
        applied_offer=applied_offer,
    )


def validate_order_draft(
    db: Session,
    customer: User,
    payload: OrderCreateRequest,
) -> OrderValidationResponse:
    draft = _prepare_order_draft(
        db,
        customer,
        payload,
        require_payment_validation=False,
    )
    return OrderValidationResponse(
        valid=True,
        restaurant_id=draft.restaurant.id,
        restaurant_location_id=draft.restaurant_location.id,
        fulfillment_type=payload.fulfillment_type,
        schedule_type=payload.schedule_type,
        scheduled_at=draft.scheduled_at,
        subtotal=draft.subtotal,
        delivery_fee=draft.delivery_fee,
        tax_amount=draft.tax_amount,
        discount_amount=draft.discount_amount,
        total_amount=draft.total_amount,
        currency="INR",
        item_count=sum(item.quantity for item in draft.order_items),
    )


def _offer_attribution(
    draft: PreparedOrderDraft,
    payload: OrderCreateRequest,
) -> dict[str, uuid.UUID | None]:
    """The offer links to stamp on a new order.

    Returns empty links when no offer was applied, so an ordinary order is
    unaffected. A manual template offer and a generated offer are recorded in
    separate columns because they are separate tables, not two flavours of one.
    """

    if draft.applied_offer is None:
        return {
            "applied_offer_id": None,
            "applied_generated_offer_id": None,
            "applied_offer_user_match_id": None,
        }

    applied = draft.applied_offer
    manual_offer_id = applied.id if isinstance(applied, PersonalizedOffer) else None
    generated_offer_id = (
        applied.id if isinstance(applied, GeneratedOffer) else payload.generated_offer_id
    )

    return {
        "applied_offer_id": manual_offer_id,
        "applied_generated_offer_id": generated_offer_id,
        "applied_offer_user_match_id": payload.generated_offer_user_match_id,
    }


def create_order(db: Session, customer: User, payload: OrderCreateRequest) -> OrderResponse:
    draft = _prepare_order_draft(
        db,
        customer,
        payload,
        require_payment_validation=True,
    )

    order_id = uuid.uuid4()
    is_cod = payload.payment_method == PaymentMethod.COD
    # Card orders are born unpaid and stay out of the kitchen queue until a
    # verified provider webhook says the money moved. `payment_provider` is
    # derived here rather than read from the request: a client must never be
    # able to describe its own payment.
    order_status = OrderStatus.PLACED if is_cod else OrderStatus.PAYMENT_PENDING
    payment_status = PaymentStatus.COD if is_cod else PaymentStatus.PENDING
    order = Order(
        id=order_id,
        customer_id=customer.id,
        restaurant_id=draft.restaurant.id,
        restaurant_location_id=draft.restaurant_location.id,
        status=order_status,
        payment_status=payment_status,
        payment_method=payload.payment_method,
        payment_provider=provider_name_for(payload.payment_method),
        fulfillment_type=payload.fulfillment_type,
        schedule_type=payload.schedule_type,
        scheduled_at=draft.scheduled_at,
        subtotal=draft.subtotal,
        delivery_fee=draft.delivery_fee,
        tax_amount=draft.tax_amount,
        discount_amount=draft.discount_amount,
        total_amount=draft.total_amount,
        # Stamped from config so the order and the charge can never disagree
        # about what currency the amount is in.
        currency=settings.payment_currency.upper(),
        special_instructions=payload.special_instructions,
        delivery_address=payload.delivery_address,
        items=draft.order_items,
        # Credit the offer that produced this order. The draft has already
        # validated it, so this only records what was applied — pricing and
        # eligibility are unchanged.
        **_offer_attribution(draft, payload),
    )
    # Set by the payment service once a provider intent exists; a client-supplied
    # reference is ignored entirely.
    order.payment_reference = None

    db.add(order)
    # The opening event, with no `from_status`: it records the state the order
    # was created in, so the history starts at creation rather than at the
    # first transition.
    record_order_status_event(
        db,
        order=order,
        from_status=None,
        to_status=order_status,
        actor=OrderEventActor.CUSTOMER,
        actor_user_id=customer.id,
        note="order created",
    )

    if draft.applied_offer is not None:
        record_offer_conversion(
            db,
            user_id=customer.id,
            offer=draft.applied_offer,
            order_id=order_id,
            generated_offer_id=payload.generated_offer_id,
            generated_offer_user_match_id=payload.generated_offer_user_match_id,
            target_type="ORDER",
            target_id=str(order.restaurant_id),
        )

    db.commit()

    created_order = db.scalar(_order_base_query().where(Order.id == order.id))
    if created_order is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create order")

    # A card order is not really placed yet — no notification, no combo/offer
    # rebuild — until the payment webhook confirms it. The payment service
    # calls the same routine at that point.
    if created_order.status == OrderStatus.PLACED:
        run_order_placed_side_effects(db, customer=customer, order_id=created_order.id)
        created_order = db.scalar(_order_base_query().where(Order.id == order.id)) or created_order

    return _serialize_order(created_order)


def run_order_placed_side_effects(db: Session, *, customer: User, order_id: uuid.UUID) -> None:
    """Everything that should happen exactly once, when an order truly lands.

    COD orders reach this at creation; card orders reach it from the verified
    payment webhook, which is why it lives in its own function.
    """

    order = db.scalar(_order_base_query().where(Order.id == order_id))
    if order is None:
        return

    _refresh_generated_combos_after_order_event(
        lookback_days=settings.generated_combo_lookback_days,
    )
    if order.payment_status == PaymentStatus.PAID:
        sync_global_welcome_offer_for_user(db, user=customer)
    rebuild_generated_offers(db, restaurant_id=order.restaurant_id)
    db.commit()
    invalidate_bestseller_cache_for_locations([order.restaurant_location_id])
    invalidate_user_recommendation_cache(customer.id)
    invalidate_user_personalized_offers_cache(customer.id)
    from app.services.rag import invalidate_user_chat_caches
    from app.services.ai_recommendations import queue_ai_recommendation_refresh

    invalidate_user_chat_caches(customer.id)
    queue_ai_recommendation_refresh(
        user_id=customer.id,
        reason=(
            "order_paid" if order.payment_status == PaymentStatus.PAID else "order_created"
        ),
        force_refresh=order.payment_status == PaymentStatus.PAID,
    )
    try:
        send_order_placed_notification(
            db,
            customer=customer,
            order=order,
        )
    except Exception:
        # Push delivery should never block a successful order placement.
        pass


ORDER_SORT_COLUMNS = {
    "placed_at": Order.placed_at,
    "total_amount": Order.total_amount,
    "status": Order.status,
}


def list_orders(
    db: Session,
    current_user: User,
    *,
    owner_restaurant_id: uuid.UUID | None = None,
    restaurant_id: uuid.UUID | None = None,
    restaurant_location_id: uuid.UUID | None = None,
    app_scope_restaurant_id: uuid.UUID | None = None,
    search: str | None = None,
    status_filter: OrderStatus | None = None,
    sort: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[OrderResponse], int]:
    query = _order_base_query()
    if current_user.role == UserRole.CUSTOMER:
        query = query.where(Order.customer_id == current_user.id)
    elif current_user.role == UserRole.OWNER:
        if owner_restaurant_id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Owner restaurant scope is required",
            )
        query = query.where(Order.restaurant_id == owner_restaurant_id)
    elif restaurant_id is not None:
        query = query.where(Order.restaurant_id == restaurant_id)

    # Applied on top of the role filter rather than as part of it: a
    # single-restaurant app must narrow a customer's own order history too,
    # which the role branches above never do.
    if app_scope_restaurant_id is not None:
        query = query.where(Order.restaurant_id == app_scope_restaurant_id)

    if restaurant_location_id is not None:
        query = query.where(Order.restaurant_location_id == restaurant_location_id)

    if status_filter is not None:
        query = query.where(Order.status == status_filter)

    if search:
        normalized = f"%{search.strip()}%"
        query = query.join(Order.customer).join(Order.restaurant).where(
            sa.or_(
                User.full_name.ilike(normalized),
                User.email.ilike(normalized),
                Restaurant.name.ilike(normalized),
                sa.cast(Order.id, sa.String).ilike(normalized),
            )
        )

    if sort:
        field, _, direction = sort.partition(":")
        column = ORDER_SORT_COLUMNS.get(field)
        if column is not None:
            query = query.order_by(None).order_by(
                column.desc() if direction == "desc" else column.asc()
            )

    total = db.scalar(
        select(sa.func.count()).select_from(query.order_by(None).subquery())
    ) or 0

    if limit is not None:
        query = query.limit(limit).offset(max(offset, 0))

    orders = db.scalars(query).all()
    return [_serialize_order(order) for order in orders], total


def get_order_for_user(
    db: Session,
    current_user: User,
    order_id: uuid.UUID,
    *,
    owner_restaurant_id: uuid.UUID | None = None,
) -> OrderResponse:
    query = _order_base_query().where(Order.id == order_id)
    if current_user.role == UserRole.CUSTOMER:
        query = query.where(Order.customer_id == current_user.id)
    elif current_user.role == UserRole.OWNER:
        if owner_restaurant_id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Owner restaurant scope is required",
            )
        query = query.where(Order.restaurant_id == owner_restaurant_id)

    order = db.scalar(query)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return _serialize_order(order)


def update_order_status(
    db: Session,
    current_user: User,
    *,
    order_id: uuid.UUID,
    new_status: OrderStatus,
    owner_restaurant_id: uuid.UUID,
    owner_restaurant_location_id: uuid.UUID | None = None,
) -> OrderResponse:
    query = (
        _order_base_query()
        .where(
            Order.id == order_id,
            Order.restaurant_id == owner_restaurant_id,
        )
    )
    if owner_restaurant_location_id is not None:
        query = query.where(Order.restaurant_location_id == owner_restaurant_location_id)
    order = db.scalar(query)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    # An unpaid card order must never reach the kitchen, whatever the caller asks
    # for. This is the last line of defence behind PAYMENT_PENDING.
    if order.payment_status not in SETTLED_PAYMENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This order has not been paid yet.",
        )

    expected_next_status = ORDER_STATUS_FLOW.get(order.status)
    if expected_next_status is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order can no longer change status")
    if new_status != expected_next_status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status transition. Expected next status: {expected_next_status.value}",
        )

    previous_status = order.status
    order.status = new_status
    db.add(order)
    # Same transaction as the status change: if the commit below fails, the
    # event goes with it, so the log can never disagree with the order.
    record_order_status_event(
        db,
        order=order,
        from_status=previous_status,
        to_status=new_status,
        actor=actor_for_user(current_user),
        actor_user_id=current_user.id,
    )
    db.commit()

    updated_order = db.scalar(_order_base_query().where(Order.id == order.id))
    if updated_order is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to refresh order")

    celery_app.send_task(
        "app.tasks.notifications.send_order_status_notification",
        kwargs={
            "order_id": str(order.id),
            "customer_id": str(order.customer_id),
            "restaurant_id": str(order.restaurant_id),
            "new_status": new_status.value,
        },
    )
    if new_status == OrderStatus.DELIVERED:
        try:
            celery_app.send_task(
                "app.tasks.generated_combos.rebuild_generated_combos_task",
                kwargs={"lookback_days": settings.generated_combo_lookback_days},
            )
        except Exception:
            # The order status change should still succeed even if combo refresh queuing fails.
            pass
    _refresh_generated_combos_after_order_event(
        lookback_days=settings.generated_combo_lookback_days,
    )
    invalidate_bestseller_cache_for_locations([updated_order.restaurant_location_id])
    invalidate_user_recommendation_cache(updated_order.customer_id)
    invalidate_user_personalized_offers_cache(updated_order.customer_id)
    from app.services.rag import invalidate_user_chat_caches
    from app.services.ai_recommendations import queue_ai_recommendation_refresh

    invalidate_user_chat_caches(updated_order.customer_id)
    queue_ai_recommendation_refresh(
        user_id=updated_order.customer_id,
        reason=f"order_status_{new_status.value.lower()}",
        force_refresh=new_status == OrderStatus.DELIVERED,
    )
    rebuild_generated_offers(db, restaurant_id=updated_order.restaurant_id)
    db.commit()
    return _serialize_order(updated_order)
