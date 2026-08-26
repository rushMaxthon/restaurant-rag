from __future__ import annotations

import itertools
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models.enums import GeneratedComboLifecycleStatus, OrderStatus, PaymentStatus
from app.models.generated_combo import GeneratedCombo, GeneratedComboItem
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.schemas.generated_combo import (
    ComboUpsellSuggestionResponse,
    GeneratedComboItemSummary,
    GeneratedComboRebuildResponse,
    GeneratedComboResponse,
)
from app.services.cache import cache_delete_pattern
from app.services.favorites import apply_generated_combo_item_favorite_flags
from app.services.recommendations import invalidate_all_recommendation_caches

settings = get_settings()
logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")
EXTRA_DISCOUNT_CONFIDENCE_THRESHOLD = Decimal("8.00")
DEFAULT_COUNTED_ORDER_STATUSES = (OrderStatus.DELIVERED,)
DEFAULT_COUNTED_PAYMENT_STATUSES = (PaymentStatus.PAID, PaymentStatus.COD)
LIVE_STATUS_VALUES = (
    GeneratedComboLifecycleStatus.LIVE.value,
    "PUBLISHED",
)


@dataclass
class ComboPattern:
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    item_ids: tuple[uuid.UUID, ...]
    order_count: int = 0
    unique_user_ids: set[uuid.UUID] | None = None
    last_seen_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.unique_user_ids is None:
            self.unique_user_ids = set()


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _safe_decimal(value: Decimal | float | int | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return _quantize(value)
    return _quantize(Decimal(str(value)))


def _combo_signature(
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID,
    item_ids: tuple[uuid.UUID, ...],
) -> str:
    normalized_item_ids = tuple(sorted(item_ids, key=str))
    joined = ":".join(str(item_id) for item_id in normalized_item_ids)
    return f"{restaurant_id}:{restaurant_location_id}:{joined}"


def _build_combo_name(menu_items: list[MenuItem]) -> str:
    parts = [item.name for item in menu_items[:3]]
    if not parts:
        return "Generated Combo"
    if len(parts) == 1:
        return f"{parts[0]} Combo"
    if len(parts) == 2:
        return f"{parts[0]} + {parts[1]} Combo"
    return f"{parts[0]} + {parts[1]} + {parts[2]} Combo"


def _build_combo_description(menu_items: list[MenuItem]) -> str:
    names = [item.name for item in menu_items]
    if not names:
        return "Frequently ordered together."
    if len(names) == 1:
        return f"Customers often pair this with other dishes from the same restaurant."
    if len(names) == 2:
        return f"Frequently ordered together: {names[0]} and {names[1]}."
    return f"Frequently ordered together: {', '.join(names[:-1])}, and {names[-1]}."


def _counted_order_statuses() -> tuple[OrderStatus, ...]:
    resolved_statuses: list[OrderStatus] = []
    invalid_statuses: list[str] = []
    for status_name in settings.generated_combo_counted_statuses_list:
        try:
            status = OrderStatus(status_name)
        except ValueError:
            invalid_statuses.append(status_name)
            continue
        if status not in resolved_statuses:
            resolved_statuses.append(status)
    if invalid_statuses:
        logger.warning(
            "Generated combo counted statuses ignored unknown values=%s",
            invalid_statuses,
        )
    if not resolved_statuses:
        return DEFAULT_COUNTED_ORDER_STATUSES
    return tuple(resolved_statuses)


def _counted_payment_statuses() -> tuple[PaymentStatus, ...]:
    resolved_statuses: list[PaymentStatus] = []
    invalid_statuses: list[str] = []
    for status_name in settings.generated_combo_counted_payment_statuses_list:
        try:
            status = PaymentStatus(status_name)
        except ValueError:
            invalid_statuses.append(status_name)
            continue
        if status not in resolved_statuses:
            resolved_statuses.append(status)
    if invalid_statuses:
        logger.warning(
            "Generated combo counted payment statuses ignored unknown values=%s",
            invalid_statuses,
        )
    if not resolved_statuses:
        return DEFAULT_COUNTED_PAYMENT_STATUSES
    return tuple(resolved_statuses)


def _calculate_confidence_score(
    order_count: int,
    unique_user_count: int,
    last_seen_at: datetime,
    *,
    now: datetime | None = None,
) -> Decimal:
    recency_bonus = Decimal("0.0")
    reference_time = now or datetime.now(timezone.utc)
    age_days = max((reference_time - last_seen_at).days, 0)
    if age_days <= 7:
        recency_bonus = Decimal("2.00")
    elif age_days <= 21:
        recency_bonus = Decimal("1.00")
    return _quantize(
        Decimal(order_count)
        + (Decimal(unique_user_count) * Decimal("2.00"))
        + recency_bonus
    )


def _should_apply_discount_boost(confidence_score: Decimal, unique_user_count: int) -> bool:
    return (
        confidence_score >= EXTRA_DISCOUNT_CONFIDENCE_THRESHOLD
        and unique_user_count >= settings.generated_combo_min_visible_unique_users
    )


def _suggested_price(original_total: Decimal, confidence_score: Decimal, unique_user_count: int) -> Decimal:
    discount_rate = Decimal(str(settings.generated_combo_discount_rate))
    if _should_apply_discount_boost(confidence_score, unique_user_count):
        discount_rate += Decimal("0.02")
    return _quantize(original_total * (Decimal("1.00") - discount_rate))


def _is_combo_stale(
    last_seen_at: datetime,
    *,
    now: datetime | None = None,
    expiry_days: int | None = None,
) -> bool:
    reference_time = now or datetime.now(timezone.utc)
    max_age_days = expiry_days or settings.generated_combo_expiry_days
    return last_seen_at < (reference_time - timedelta(days=max_age_days))


def _is_draft_combo_expired(
    created_at: datetime,
    *,
    now: datetime | None = None,
    expiry_days: int | None = None,
) -> bool:
    reference_time = now or datetime.now(timezone.utc)
    max_age_days = expiry_days or settings.generated_combo_draft_expiry_days
    return created_at < (reference_time - timedelta(days=max_age_days))


def remaining_unique_users_to_publish(unique_user_count: int) -> int:
    """How many more distinct customers a combo needs before it is published.

    Public because the owner chat shows it on a combo card: activating a combo
    that is still below the threshold changes its status without making it
    visible, and an owner who is not told that reads it as a broken button.
    """

    return max(settings.generated_combo_min_visible_unique_users - unique_user_count, 0)


# Retained so the existing private call sites in this module keep working.
_remaining_unique_users_to_publish = remaining_unique_users_to_publish


def _normalize_combo_status_value(status_value: str | None) -> str | None:
    if status_value == "PUBLISHED":
        return GeneratedComboLifecycleStatus.LIVE.value
    return status_value


def _manual_status_override(combo: GeneratedCombo) -> GeneratedComboLifecycleStatus | None:
    raw_value = _normalize_combo_status_value(combo.manual_status_override)
    if raw_value is None:
        return None
    try:
        return GeneratedComboLifecycleStatus(raw_value)
    except ValueError:
        return None


def _derive_combo_status(
    *,
    unique_user_count: int,
    created_at: datetime,
    last_seen_at: datetime,
    now: datetime | None = None,
) -> GeneratedComboLifecycleStatus:
    reference_time = now or datetime.now(timezone.utc)
    if unique_user_count >= settings.generated_combo_min_visible_unique_users:
        if _is_combo_stale(last_seen_at, now=reference_time):
            return GeneratedComboLifecycleStatus.ARCHIVED
        return GeneratedComboLifecycleStatus.LIVE
    if _is_draft_combo_expired(created_at, now=reference_time):
        return GeneratedComboLifecycleStatus.ARCHIVED
    return GeneratedComboLifecycleStatus.DRAFT


def _is_combo_customer_visible(combo: GeneratedCombo) -> bool:
    return (
        _normalize_combo_status_value(combo.status) == GeneratedComboLifecycleStatus.LIVE.value
        and combo.is_customer_visible
        and combo.is_active
    )


def _apply_combo_lifecycle(
    combo: GeneratedCombo,
    *,
    unique_user_count: int,
    created_at: datetime,
    last_seen_at: datetime,
    now: datetime | None = None,
) -> GeneratedComboLifecycleStatus:
    lifecycle_status = _derive_combo_status(
        unique_user_count=unique_user_count,
        created_at=created_at,
        last_seen_at=last_seen_at,
        now=now,
    )
    override_status = _manual_status_override(combo)
    effective_status = override_status or lifecycle_status
    combo.status = effective_status.value
    combo.is_customer_visible = effective_status == GeneratedComboLifecycleStatus.LIVE
    combo.is_active = effective_status != GeneratedComboLifecycleStatus.ARCHIVED
    return effective_status


def _combo_base_query() -> Select[tuple[GeneratedCombo]]:
    return (
        select(GeneratedCombo)
        .join(Restaurant, GeneratedCombo.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, GeneratedCombo.restaurant_location_id == RestaurantLocation.id)
        .where(
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            RestaurantLocation.is_active.is_(True),
        )
        .options(
            selectinload(GeneratedCombo.restaurant),
            selectinload(GeneratedCombo.restaurant_location),
            selectinload(GeneratedCombo.combo_items).selectinload(GeneratedComboItem.menu_item),
        )
        .order_by(
            GeneratedCombo.confidence_score.desc(),
            GeneratedCombo.order_count.desc(),
            GeneratedCombo.last_seen_at.desc(),
            GeneratedCombo.created_at.desc(),
        )
    )


def _serialize_combo(
    combo: GeneratedCombo,
    *,
    favorite_ids: set[uuid.UUID] | None = None,
) -> GeneratedComboResponse:
    combo_items = sorted(combo.combo_items, key=lambda entry: (entry.sort_order, entry.menu_item.name))
    items = [
        GeneratedComboItemSummary(
            menu_item_id=entry.menu_item_id,
            restaurant_location_id=entry.menu_item.restaurant_location_id,
            restaurant_location_name=entry.menu_item.restaurant_location.branch_name
            if entry.menu_item.restaurant_location is not None
            else None,
            name=entry.menu_item.name,
            category=entry.menu_item.category,
            price=entry.menu_item.price,
            quantity=entry.quantity,
            image_url=entry.menu_item.image_url,
            is_veg=entry.menu_item.is_veg,
            is_available=entry.menu_item.is_available,
        )
        for entry in combo_items
    ]
    if favorite_ids:
        items = apply_generated_combo_item_favorite_flags(items, favorite_ids)
    image_url = next((entry.menu_item.image_url for entry in combo_items if entry.menu_item.image_url), None)
    original_total = _safe_decimal(combo.original_total_price)
    combo_price = _safe_decimal(combo.suggested_combo_price)
    remaining_to_publish = (
        _remaining_unique_users_to_publish(combo.unique_user_count)
        if combo.status == GeneratedComboLifecycleStatus.DRAFT.value
        else 0
    )
    return GeneratedComboResponse(
        id=combo.id,
        restaurant_id=combo.restaurant_id,
        restaurant_location_id=combo.restaurant_location_id,
        restaurant_name=combo.restaurant.name,
        restaurant_location_name=combo.restaurant_location.branch_name,
        combo_name=combo.combo_name,
        description=combo.description,
        items=items,
        order_count=combo.order_count,
        unique_user_count=combo.unique_user_count,
        confidence_score=_safe_decimal(combo.confidence_score),
        status=_normalize_combo_status_value(combo.status) or combo.status,
        manual_status_override=_normalize_combo_status_value(combo.manual_status_override),
        is_customer_visible=combo.is_customer_visible,
        remaining_unique_users_to_publish=remaining_to_publish,
        original_total_price=original_total,
        suggested_combo_price=combo_price,
        savings_amount=_quantize(max(original_total - combo_price, Decimal("0.00"))),
        image_url=image_url,
        is_active=combo.is_active,
        generated_from_orders=combo.generated_from_orders,
        last_seen_at=combo.last_seen_at,
        created_at=combo.created_at,
        updated_at=combo.updated_at,
    )


def _invalidate_combo_related_caches() -> None:
    invalidate_all_recommendation_caches()
    cache_delete_pattern("rag:response:*")


def _is_missing_generated_combo_schema(error: Exception) -> bool:
    if not isinstance(error, ProgrammingError):
        return False
    message = str(getattr(error, "orig", error)).lower()
    return "generated_combos" in message or "generated_combo_items" in message


def _combo_schema_not_ready_http_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Generated combo tables are not ready yet. Run `alembic upgrade head` and rebuild generated combos.",
    )


def _menu_item_names_by_id(
    menu_item_by_id: dict[uuid.UUID, MenuItem],
    item_ids: tuple[uuid.UUID, ...],
) -> list[str]:
    return [menu_item_by_id[item_id].name for item_id in item_ids if item_id in menu_item_by_id]


def list_generated_combos(
    db: Session,
    *,
    restaurant_id: uuid.UUID | None = None,
    restaurant_location_id: uuid.UUID | None = None,
    limit: int = 12,
    active_only: bool = True,
    customer_visible_only: bool = True,
    fail_open: bool = True,
    favorite_ids: set[uuid.UUID] | None = None,
) -> list[GeneratedComboResponse]:
    query = _combo_base_query()
    if active_only:
        query = query.where(GeneratedCombo.is_active.is_(True))
    if customer_visible_only:
        query = query.where(
            GeneratedCombo.status.in_(LIVE_STATUS_VALUES),
            GeneratedCombo.is_customer_visible.is_(True),
        )
    if restaurant_id is not None:
        query = query.where(GeneratedCombo.restaurant_id == restaurant_id)
    if restaurant_location_id is not None:
        query = query.where(GeneratedCombo.restaurant_location_id == restaurant_location_id)
    try:
        combos = db.scalars(query.limit(limit)).all()
    except ProgrammingError as exc:
        if not _is_missing_generated_combo_schema(exc):
            raise
        logger.warning(
            "Generated combo list skipped because schema is not ready restaurant_id=%s active_only=%s",
            restaurant_id,
            active_only,
        )
        if fail_open:
            return []
        raise _combo_schema_not_ready_http_error() from exc
    if customer_visible_only:
        combos = [combo for combo in combos if _is_combo_customer_visible(combo)]
    serialized = [_serialize_combo(combo, favorite_ids=favorite_ids) for combo in combos]
    logger.info(
        "Generated combo list returned restaurant_id=%s restaurant_location_id=%s active_only=%s customer_visible_only=%s count=%d",
        restaurant_id,
        restaurant_location_id,
        active_only,
        customer_visible_only,
        len(serialized),
    )
    return serialized


def find_generated_combos_for_query(
    db: Session,
    *,
    topic: str | None,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None,
    budget_limit: Decimal | None,
    limit: int = 4,
) -> list[GeneratedComboResponse]:
    combos = list_generated_combos(
        db,
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
        limit=max(limit * 4, 16),
        active_only=True,
    )
    normalized_topic = (topic or "").strip().lower()
    if budget_limit is not None and budget_limit > 0:
        combos = [
            combo
            for combo in combos
            if _safe_decimal(combo.suggested_combo_price) <= budget_limit
        ]
    if normalized_topic:
        topic_tokens = [token for token in normalized_topic.split() if token]

        def matches(combo: GeneratedComboResponse) -> bool:
            haystack = " ".join(
                [
                    combo.combo_name,
                    combo.description or "",
                    *[item.name for item in combo.items],
                    *[item.category for item in combo.items],
                ]
            ).lower()
            return all(token in haystack for token in topic_tokens)

        matching = [combo for combo in combos if matches(combo)]
        if matching:
            combos = matching
    return combos[:limit]


def get_generated_combo(
    db: Session,
    combo_id: uuid.UUID,
    *,
    favorite_ids: set[uuid.UUID] | None = None,
    include_hidden: bool = False,
) -> GeneratedComboResponse:
    try:
        combo = db.scalar(_combo_base_query().where(GeneratedCombo.id == combo_id))
    except ProgrammingError as exc:
        if not _is_missing_generated_combo_schema(exc):
            raise
        raise _combo_schema_not_ready_http_error() from exc
    if combo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated combo not found")
    if not include_hidden and not _is_combo_customer_visible(combo):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated combo not found")
    return _serialize_combo(combo, favorite_ids=favorite_ids)


def set_generated_combo_status(
    db: Session,
    *,
    combo_id: uuid.UUID,
    status_value: str,
) -> GeneratedComboResponse:
    try:
        combo = db.scalar(_combo_base_query().where(GeneratedCombo.id == combo_id))
    except ProgrammingError as exc:
        if not _is_missing_generated_combo_schema(exc):
            raise
        raise _combo_schema_not_ready_http_error() from exc
    if combo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated combo not found")
    normalized_status = _normalize_combo_status_value(status_value)
    try:
        next_status = GeneratedComboLifecycleStatus(normalized_status or "")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid generated combo status",
        ) from exc
    combo.manual_status_override = next_status.value
    combo.status = next_status.value
    combo.is_customer_visible = next_status == GeneratedComboLifecycleStatus.LIVE
    combo.is_active = next_status != GeneratedComboLifecycleStatus.ARCHIVED
    db.add(combo)
    db.commit()
    try:
        refreshed = db.scalar(_combo_base_query().where(GeneratedCombo.id == combo_id))
    except ProgrammingError as exc:
        if not _is_missing_generated_combo_schema(exc):
            raise
        raise _combo_schema_not_ready_http_error() from exc
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to refresh generated combo")
    _invalidate_combo_related_caches()
    return _serialize_combo(refreshed)


def rebuild_generated_combos(
    db: Session,
    *,
    lookback_days: int | None = None,
) -> GeneratedComboRebuildResponse:
    now = datetime.now(timezone.utc)
    window_days = lookback_days or settings.generated_combo_lookback_days
    window_start = now - timedelta(days=window_days)
    counted_statuses = _counted_order_statuses()
    counted_payment_statuses = _counted_payment_statuses()
    logger.info(
        "Generated combo rebuild started lookback_days=%s expiry_days=%s draft_expiry_days=%s min_order_count=%s min_unique_users=%s min_visible_unique_users=%s max_size=%s counted_statuses=%s counted_payment_statuses=%s",
        window_days,
        settings.generated_combo_expiry_days,
        settings.generated_combo_draft_expiry_days,
        settings.generated_combo_min_order_count,
        settings.generated_combo_min_unique_users,
        settings.generated_combo_min_visible_unique_users,
        settings.generated_combo_max_size,
        [status.value for status in counted_statuses],
        [status.value for status in counted_payment_statuses],
    )

    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.items))
        .where(
            Order.status.in_(counted_statuses),
            Order.payment_status.in_(counted_payment_statuses),
            Order.placed_at >= window_start,
        )
    ).all()

    pattern_map: dict[str, ComboPattern] = {}
    all_item_ids: set[uuid.UUID] = set()
    restaurant_ids: set[uuid.UUID] = set()
    scanned_order_count = 0
    logger.info("Generated combo rebuild analyzing orders count=%d", len(orders))

    for order in orders:
        distinct_item_ids = tuple(sorted({item.menu_item_id for item in order.items}))
        if len(distinct_item_ids) < 2:
            logger.info(
                "Generated combo rebuild skipping order order_id=%s restaurant_id=%s reason=not_enough_distinct_items item_count=%d",
                order.id,
                order.restaurant_id,
                len(distinct_item_ids),
            )
            continue
        scanned_order_count += 1
        restaurant_ids.add(order.restaurant_id)
        all_item_ids.update(distinct_item_ids)
        max_combo_size = min(settings.generated_combo_max_size, len(distinct_item_ids))
        for combo_size in range(2, max_combo_size + 1):
            for combo_item_ids in itertools.combinations(distinct_item_ids, combo_size):
                signature = _combo_signature(
                    order.restaurant_id,
                    order.restaurant_location_id,
                    combo_item_ids,
                )
                pattern = pattern_map.get(signature)
                if pattern is None:
                    pattern = ComboPattern(
                        restaurant_id=order.restaurant_id,
                        restaurant_location_id=order.restaurant_location_id,
                        item_ids=combo_item_ids,
                    )
                    pattern_map[signature] = pattern
                pattern.order_count += 1
                pattern.unique_user_ids.add(order.customer_id)
                if pattern.last_seen_at is None or order.placed_at > pattern.last_seen_at:
                    pattern.last_seen_at = order.placed_at

    if not pattern_map:
        try:
            existing = db.scalars(select(GeneratedCombo)).all()
        except ProgrammingError as exc:
            if not _is_missing_generated_combo_schema(exc):
                raise
            raise _combo_schema_not_ready_http_error() from exc
        deactivated_count = 0
        for combo in existing:
            if combo.is_active or combo.status != GeneratedComboLifecycleStatus.ARCHIVED.value:
                combo.status = GeneratedComboLifecycleStatus.ARCHIVED.value
                combo.is_active = False
                combo.is_customer_visible = False
                db.add(combo)
                deactivated_count += 1
        db.commit()
        if deactivated_count:
            _invalidate_combo_related_caches()
        return GeneratedComboRebuildResponse(
            created_count=0,
            updated_count=0,
            deactivated_count=deactivated_count,
            scanned_order_count=scanned_order_count,
            eligible_pattern_count=0,
        )

    menu_items = db.scalars(
        select(MenuItem)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .where(
            MenuItem.id.in_(all_item_ids),
            MenuItem.is_available.is_(True),
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            RestaurantLocation.is_active.is_(True),
        )
    ).all()
    menu_item_by_id = {item.id: item for item in menu_items}
    restaurant_by_id = {
        restaurant.id: restaurant
        for restaurant in db.scalars(
            select(Restaurant).where(
                Restaurant.id.in_(restaurant_ids),
                Restaurant.is_active.is_(True),
                Restaurant.is_approved.is_(True),
            )
        ).all()
    }
    try:
        existing_by_signature = {
            combo.signature: combo
            for combo in db.scalars(
                select(GeneratedCombo).options(selectinload(GeneratedCombo.combo_items))
            ).all()
        }
    except ProgrammingError as exc:
        if not _is_missing_generated_combo_schema(exc):
            raise
        raise _combo_schema_not_ready_http_error() from exc

    persisted_signatures: set[str] = set()
    created_count = 0
    updated_count = 0
    eligible_pattern_count = 0

    logger.info(
        "Generated combo rebuild detected raw_patterns=%d scanned_order_count=%d",
        len(pattern_map),
        scanned_order_count,
    )

    for signature, pattern in pattern_map.items():
        unique_user_count = len(pattern.unique_user_ids)
        item_names = _menu_item_names_by_id(menu_item_by_id, pattern.item_ids)
        if pattern.order_count < settings.generated_combo_min_order_count:
            logger.info(
                "Generated combo threshold fail signature=%s restaurant_id=%s items=%s order_count=%d unique_user_count=%d reason=min_order_count",
                signature,
                pattern.restaurant_id,
                item_names,
                pattern.order_count,
                unique_user_count,
            )
            continue
        if unique_user_count < settings.generated_combo_min_unique_users:
            logger.info(
                "Generated combo threshold fail signature=%s restaurant_id=%s items=%s order_count=%d unique_user_count=%d reason=min_unique_users",
                signature,
                pattern.restaurant_id,
                item_names,
                pattern.order_count,
                unique_user_count,
            )
            continue
        if pattern.restaurant_id not in restaurant_by_id or pattern.last_seen_at is None:
            logger.info(
                "Generated combo threshold fail signature=%s restaurant_id=%s items=%s order_count=%d unique_user_count=%d reason=restaurant_or_last_seen",
                signature,
                pattern.restaurant_id,
                item_names,
                pattern.order_count,
                unique_user_count,
            )
            continue
        ordered_items = [menu_item_by_id.get(item_id) for item_id in pattern.item_ids]
        if any(item is None for item in ordered_items):
            logger.info(
                "Generated combo threshold fail signature=%s restaurant_id=%s items=%s order_count=%d unique_user_count=%d reason=missing_or_unavailable_items",
                signature,
                pattern.restaurant_id,
                item_names,
                pattern.order_count,
                unique_user_count,
            )
            continue
        menu_item_rows = [item for item in ordered_items if item is not None]
        if any(item.restaurant_id != pattern.restaurant_id for item in menu_item_rows):
            logger.info(
                "Generated combo threshold fail signature=%s restaurant_id=%s items=%s order_count=%d unique_user_count=%d reason=cross_restaurant_mismatch",
                signature,
                pattern.restaurant_id,
                item_names,
                pattern.order_count,
                unique_user_count,
            )
            continue
        if any(item.restaurant_location_id != pattern.restaurant_location_id for item in menu_item_rows):
            logger.info(
                "Generated combo threshold fail signature=%s restaurant_id=%s items=%s order_count=%d unique_user_count=%d reason=cross_location_mismatch",
                signature,
                pattern.restaurant_id,
                item_names,
                pattern.order_count,
                unique_user_count,
            )
            continue

        confidence_score = _calculate_confidence_score(
            pattern.order_count,
            unique_user_count,
            pattern.last_seen_at,
            now=now,
        )
        original_total = _quantize(sum((_safe_decimal(item.price) for item in menu_item_rows), Decimal("0.00")))
        combo_price = _suggested_price(original_total, confidence_score, unique_user_count)
        combo = existing_by_signature.get(signature)
        created_at = combo.created_at if combo is not None and combo.created_at is not None else now
        lifecycle_status = _derive_combo_status(
            unique_user_count=unique_user_count,
            created_at=created_at,
            last_seen_at=pattern.last_seen_at,
            now=now,
        )
        persisted_signatures.add(signature)
        if lifecycle_status == GeneratedComboLifecycleStatus.LIVE:
            eligible_pattern_count += 1
        logger.info(
            "Generated combo lifecycle signature=%s restaurant_id=%s items=%s order_count=%d unique_user_count=%d status=%s remaining_unique_users=%d",
            signature,
            pattern.restaurant_id,
            item_names,
            pattern.order_count,
            unique_user_count,
            lifecycle_status.value,
            _remaining_unique_users_to_publish(unique_user_count),
        )
        if combo is None:
            combo = GeneratedCombo(
                restaurant_id=pattern.restaurant_id,
                restaurant_location_id=pattern.restaurant_location_id,
                signature=signature,
                generated_from_orders=True,
                status=GeneratedComboLifecycleStatus.DRAFT.value,
                manual_status_override=None,
                is_customer_visible=False,
            )
            created_count += 1
            action = "created"
        else:
            updated_count += 1
            action = "updated"

        combo.combo_name = _build_combo_name(menu_item_rows)
        combo.description = _build_combo_description(menu_item_rows)
        combo.order_count = pattern.order_count
        combo.unique_user_count = unique_user_count
        combo.confidence_score = confidence_score
        combo.original_total_price = original_total
        combo.suggested_combo_price = combo_price
        combo.last_seen_at = pattern.last_seen_at
        _apply_combo_lifecycle(
            combo,
            unique_user_count=unique_user_count,
            created_at=created_at,
            last_seen_at=pattern.last_seen_at,
            now=now,
        )
        if combo.combo_items:
            combo.combo_items.clear()
            db.flush()
        combo.combo_items = [
            GeneratedComboItem(
                menu_item_id=item.id,
                quantity=1,
                sort_order=index,
            )
            for index, item in enumerate(menu_item_rows)
        ]
        db.add(combo)
        logger.info(
            "Generated combo %s signature=%s combo_name=%s restaurant_id=%s item_names=%s",
            action,
            signature,
            combo.combo_name,
            pattern.restaurant_id,
            [item.name for item in menu_item_rows],
        )

    deactivated_count = 0
    for signature, combo in existing_by_signature.items():
        if signature in persisted_signatures:
            continue
        if combo.is_active or combo.status != GeneratedComboLifecycleStatus.ARCHIVED.value:
            combo.status = GeneratedComboLifecycleStatus.ARCHIVED.value
            combo.is_active = False
            combo.is_customer_visible = False
            db.add(combo)
            deactivated_count += 1

    db.commit()
    _invalidate_combo_related_caches()

    logger.info(
        "Generated combo rebuild finished created=%s updated=%s deactivated=%s scanned_orders=%s eligible_patterns=%s",
        created_count,
        updated_count,
        deactivated_count,
        scanned_order_count,
        eligible_pattern_count,
    )
    return GeneratedComboRebuildResponse(
        created_count=created_count,
        updated_count=updated_count,
        deactivated_count=deactivated_count,
        scanned_order_count=scanned_order_count,
        eligible_pattern_count=eligible_pattern_count,
    )


def refresh_generated_combo_availability(
    db: Session,
    *,
    restaurant_id: uuid.UUID | None = None,
    restaurant_location_id: uuid.UUID | None = None,
    menu_item_id: uuid.UUID | None = None,
) -> int:
    query = _combo_base_query()
    if restaurant_id is not None:
        query = query.where(GeneratedCombo.restaurant_id == restaurant_id)
    if restaurant_location_id is not None:
        query = query.where(GeneratedCombo.restaurant_location_id == restaurant_location_id)
    try:
        combos = db.scalars(query).all()
    except ProgrammingError as exc:
        if not _is_missing_generated_combo_schema(exc):
            raise
        logger.warning(
            "Generated combo availability refresh skipped because schema is not ready restaurant_id=%s menu_item_id=%s",
            restaurant_id,
            menu_item_id,
        )
        return 0
    changed = 0
    for combo in combos:
        if menu_item_id is not None and not any(entry.menu_item_id == menu_item_id for entry in combo.combo_items):
            continue
        should_be_active = (
            combo.status != GeneratedComboLifecycleStatus.ARCHIVED.value
            and len(combo.combo_items) >= 2
            and all(
                entry.menu_item.is_available
                and entry.menu_item.restaurant_location.is_active
                and combo.restaurant.is_active
                and combo.restaurant.is_approved
                for entry in combo.combo_items
            )
        )
        if combo.is_active != should_be_active:
            combo.is_active = should_be_active
            db.add(combo)
            changed += 1
    if changed:
        db.commit()
        _invalidate_combo_related_caches()
    return changed


def get_combo_upsell_suggestions(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID | None,
    item_id: uuid.UUID,
    cart_item_ids: list[uuid.UUID] | None = None,
    limit: int = 3,
    favorite_ids: set[uuid.UUID] | None = None,
) -> list[ComboUpsellSuggestionResponse]:
    current_item_ids = set(cart_item_ids or [])
    current_item_ids.add(item_id)

    try:
        query = _combo_base_query().where(
            GeneratedCombo.restaurant_id == restaurant_id,
            GeneratedCombo.is_active.is_(True),
            GeneratedCombo.status.in_(LIVE_STATUS_VALUES),
            GeneratedCombo.is_customer_visible.is_(True),
        )
        if restaurant_location_id is not None:
            query = query.where(GeneratedCombo.restaurant_location_id == restaurant_location_id)
        combos = db.scalars(query.limit(20)).all()
    except ProgrammingError as exc:
        if not _is_missing_generated_combo_schema(exc):
            raise
        logger.warning(
            "Generated combo upsell skipped because schema is not ready restaurant_id=%s item_id=%s",
            restaurant_id,
            item_id,
        )
        return []

    suggestions: list[ComboUpsellSuggestionResponse] = []
    for combo in combos:
        combo_item_ids = {entry.menu_item_id for entry in combo.combo_items}
        if item_id not in combo_item_ids:
            continue
        missing_items = [
            entry
            for entry in combo.combo_items
            if entry.menu_item_id not in current_item_ids and entry.menu_item.is_available
        ]
        if not missing_items:
            continue
        missing_summaries = [
            GeneratedComboItemSummary(
                menu_item_id=entry.menu_item_id,
                restaurant_location_id=entry.menu_item.restaurant_location_id,
                restaurant_location_name=entry.menu_item.restaurant_location.branch_name
                if entry.menu_item.restaurant_location is not None
                else None,
                name=entry.menu_item.name,
                category=entry.menu_item.category,
                price=entry.menu_item.price,
                quantity=entry.quantity,
                image_url=entry.menu_item.image_url,
                is_veg=entry.menu_item.is_veg,
                is_available=entry.menu_item.is_available,
            )
            for entry in missing_items
        ]
        if favorite_ids:
            missing_summaries = apply_generated_combo_item_favorite_flags(missing_summaries, favorite_ids)
        missing_names = [entry.name for entry in missing_summaries]
        if len(missing_names) == 1:
            message = f"Many users order {missing_names[0]} with this item. Add it?"
        else:
            message = f"Many users order {' and '.join(missing_names[:2])} with this item. Add them?"
        suggestions.append(
            ComboUpsellSuggestionResponse(
                combo_id=combo.id,
                combo_name=combo.combo_name,
                restaurant_id=combo.restaurant_id,
                restaurant_location_id=combo.restaurant_location_id,
                restaurant_name=combo.restaurant.name,
                restaurant_location_name=combo.restaurant_location.branch_name,
                confidence_score=_safe_decimal(combo.confidence_score),
                suggested_combo_price=_safe_decimal(combo.suggested_combo_price),
                missing_items=missing_summaries,
                message=message,
            )
        )
        if len(suggestions) >= limit:
            break
    return suggestions
