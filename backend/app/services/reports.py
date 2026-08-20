from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, selectinload

from app.models.chat_history import ChatHistory
from app.models.enums import ChatMessageRole, OrderStatus, UserRole
from app.models.favorite import Favorite
from app.models.generated_combo import GeneratedCombo, GeneratedComboItem
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.report import (
    ReportChatUsage,
    ReportComboPerformance,
    ReportDimensionMetric,
    ReportFiltersApplied,
    ReportItemPerformance,
    ReportPeakHour,
    ReportRestaurantPerformance,
    ReportRestaurantScope,
    ReportsResponse,
    ReportStatusSummary,
    ReportSummary,
    ReportTrendPoint,
)
from app.services.auth import resolve_owner_restaurant_id


@dataclass
class ReportsFilters:
    date_from: date | None = None
    date_to: date | None = None
    restaurant_id: uuid.UUID | None = None
    cuisine_type: str | None = None
    category: str | None = None
    order_status: OrderStatus | None = None


def _safe_float(value: Decimal | int | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _day_end_exclusive(value: date) -> datetime:
    return datetime.combine(value + timedelta(days=1), time.min, tzinfo=UTC)


def _normalize_filters(filters: ReportsFilters) -> ReportsFilters:
    if filters.date_from is not None and filters.date_to is not None and filters.date_from > filters.date_to:
        filters.date_from, filters.date_to = filters.date_to, filters.date_from
    filters.cuisine_type = _normalized_text(filters.cuisine_type)
    filters.category = _normalized_text(filters.category)
    return filters


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _is_missing_table(error: Exception, *table_names: str) -> bool:
    if not isinstance(error, ProgrammingError):
        return False
    message = str(getattr(error, "orig", error)).lower()
    return any(table_name.lower() in message and "does not exist" in message for table_name in table_names)


def _format_hour_label(hour: int) -> str:
    start = datetime(2000, 1, 1, hour, 0)
    end = start + timedelta(hours=1)
    return f"{start.strftime('%I %p').lstrip('0')} - {end.strftime('%I %p').lstrip('0')}"


def _build_revenue_trend(
    orders: list[Order],
    *,
    date_from: date | None,
    date_to: date | None,
) -> list[ReportTrendPoint]:
    today = datetime.now(UTC).date()
    start_date = date_from or (date_to - timedelta(days=6) if date_to else today - timedelta(days=6))
    end_date = date_to or today
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    day_count = (end_date - start_date).days + 1
    buckets: list[tuple[date, date, str]] = []
    if day_count <= 10:
        cursor = start_date
        while cursor <= end_date:
            buckets.append((cursor, cursor, cursor.strftime("%d %b")))
            cursor += timedelta(days=1)
    else:
        cursor = start_date
        while cursor <= end_date:
            bucket_end = min(cursor + timedelta(days=6), end_date)
            label = (
                cursor.strftime("%d %b")
                if cursor == bucket_end
                else f"{cursor.strftime('%d %b')} - {bucket_end.strftime('%d %b')}"
            )
            buckets.append((cursor, bucket_end, label))
            cursor = bucket_end + timedelta(days=1)

    points: list[ReportTrendPoint] = []
    for bucket_start, bucket_end, label in buckets:
        bucket_orders = [
            order
            for order in orders
            if bucket_start <= order.placed_at.astimezone(UTC).date() <= bucket_end
        ]
        revenue = sum(_safe_float(order.total_amount) for order in bucket_orders)
        points.append(
            ReportTrendPoint(
                label=label,
                value=round(revenue),
                revenue=revenue,
                orders=len(bucket_orders),
            )
        )
    return points


def _menu_item_scope_condition(
    filters: ReportsFilters,
    *,
    scoped_restaurant_id: uuid.UUID | None,
) -> list:
    conditions: list = []
    if scoped_restaurant_id is not None:
        conditions.append(MenuItem.restaurant_id == scoped_restaurant_id)
    elif filters.restaurant_id is not None:
        conditions.append(MenuItem.restaurant_id == filters.restaurant_id)

    cuisine_type = _normalized_text(filters.cuisine_type)
    if cuisine_type is not None:
        lowered = cuisine_type.lower()
        conditions.append(
            or_(
                func.lower(func.coalesce(MenuItem.cuisine_type, "")) == lowered,
                and_(
                    MenuItem.cuisine_type.is_(None),
                    func.lower(Restaurant.cuisine_type) == lowered,
                ),
            )
        )

    category = _normalized_text(filters.category)
    if category is not None:
        conditions.append(func.lower(MenuItem.category) == category.lower())

    return conditions


def _restaurant_scope_query(
    db: Session,
    *,
    current_user: User,
    scoped_restaurant_id: uuid.UUID | None,
    filters: ReportsFilters,
) -> list[Restaurant]:
    query = select(Restaurant)
    if current_user.role == UserRole.OWNER:
        owner_restaurant_id = scoped_restaurant_id or resolve_owner_restaurant_id(db, current_user)
        query = query.where(Restaurant.id == owner_restaurant_id)
    elif scoped_restaurant_id is not None:
        query = query.where(Restaurant.id == scoped_restaurant_id)
    elif filters.restaurant_id is not None:
        query = query.where(Restaurant.id == filters.restaurant_id)

    cuisine_type = _normalized_text(filters.cuisine_type)
    if cuisine_type is not None:
        query = query.where(func.lower(Restaurant.cuisine_type) == cuisine_type.lower())

    category = _normalized_text(filters.category)
    if category is not None:
        query = (
            query.join(MenuItem, MenuItem.restaurant_id == Restaurant.id)
            .where(func.lower(MenuItem.category) == category.lower())
            .distinct()
        )

    return db.scalars(query.order_by(Restaurant.name.asc())).all()


def _load_filtered_orders(
    db: Session,
    *,
    filters: ReportsFilters,
    scoped_restaurant_id: uuid.UUID | None,
) -> list[Order]:
    query = (
        select(Order)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .options(
            selectinload(Order.items),
            selectinload(Order.customer),
            selectinload(Order.restaurant),
        )
    )

    if scoped_restaurant_id is not None:
        query = query.where(Order.restaurant_id == scoped_restaurant_id)
    elif filters.restaurant_id is not None:
        query = query.where(Order.restaurant_id == filters.restaurant_id)

    if filters.date_from is not None:
        query = query.where(Order.placed_at >= _day_start(filters.date_from))
    if filters.date_to is not None:
        query = query.where(Order.placed_at < _day_end_exclusive(filters.date_to))
    if filters.order_status is not None:
        query = query.where(Order.status == filters.order_status)

    join_order_items = _normalized_text(filters.category) is not None or _normalized_text(filters.cuisine_type) is not None
    if join_order_items:
        query = (
            query.join(OrderItem, OrderItem.order_id == Order.id)
            .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        )
        cuisine_type = _normalized_text(filters.cuisine_type)
        if cuisine_type is not None:
            lowered = cuisine_type.lower()
            query = query.where(
                or_(
                    func.lower(func.coalesce(MenuItem.cuisine_type, "")) == lowered,
                    and_(
                        MenuItem.cuisine_type.is_(None),
                        func.lower(Restaurant.cuisine_type) == lowered,
                    ),
                )
            )
        category = _normalized_text(filters.category)
        if category is not None:
            query = query.where(func.lower(MenuItem.category) == category.lower())
        query = query.distinct()

    return db.scalars(query.order_by(Order.placed_at.desc(), Order.created_at.desc())).unique().all()


def _load_favorite_counts(
    db: Session,
    *,
    filters: ReportsFilters,
    scoped_restaurant_id: uuid.UUID | None,
) -> dict[uuid.UUID, int]:
    conditions = _menu_item_scope_condition(filters, scoped_restaurant_id=scoped_restaurant_id)
    if filters.date_from is not None:
        conditions.append(Favorite.created_at >= _day_start(filters.date_from))
    if filters.date_to is not None:
        conditions.append(Favorite.created_at < _day_end_exclusive(filters.date_to))

    query = (
        select(Favorite.menu_item_id, func.count(Favorite.id))
        .join(MenuItem, MenuItem.id == Favorite.menu_item_id)
        .join(Restaurant, Restaurant.id == MenuItem.restaurant_id)
    )
    if conditions:
        query = query.where(*conditions)
    query = query.group_by(Favorite.menu_item_id)

    try:
        return {
            menu_item_id: int(count)
            for menu_item_id, count in db.execute(query).all()
        }
    except ProgrammingError as exc:
        if not _is_missing_table(exc, "favorites"):
            raise
        return {}


def _load_combo_rows(
    db: Session,
    *,
    filters: ReportsFilters,
    scoped_restaurant_id: uuid.UUID | None,
) -> list[GeneratedCombo]:
    query = (
        select(GeneratedCombo)
        .join(Restaurant, Restaurant.id == GeneratedCombo.restaurant_id)
        .options(
            selectinload(GeneratedCombo.restaurant),
            selectinload(GeneratedCombo.combo_items).selectinload(GeneratedComboItem.menu_item),
        )
    )
    if scoped_restaurant_id is not None:
        query = query.where(GeneratedCombo.restaurant_id == scoped_restaurant_id)
    elif filters.restaurant_id is not None:
        query = query.where(GeneratedCombo.restaurant_id == filters.restaurant_id)

    cuisine_type = _normalized_text(filters.cuisine_type)
    if cuisine_type is not None:
        query = query.where(func.lower(Restaurant.cuisine_type) == cuisine_type.lower())

    category = _normalized_text(filters.category)
    if category is not None:
        query = (
            query.join(GeneratedComboItem, GeneratedComboItem.combo_id == GeneratedCombo.id)
            .join(MenuItem, MenuItem.id == GeneratedComboItem.menu_item_id)
            .where(func.lower(MenuItem.category) == category.lower())
            .distinct()
        )

    if filters.date_from is not None:
        query = query.where(GeneratedCombo.last_seen_at >= _day_start(filters.date_from))
    if filters.date_to is not None:
        query = query.where(GeneratedCombo.last_seen_at < _day_end_exclusive(filters.date_to))

    try:
        return db.scalars(query.order_by(GeneratedCombo.order_count.desc(), GeneratedCombo.updated_at.desc())).unique().all()
    except ProgrammingError as exc:
        if not _is_missing_table(exc, "generated_combos", "generated_combo_items"):
            raise
        return []


def _load_chat_usage(
    db: Session,
    *,
    filters: ReportsFilters,
    scoped_restaurant_id: uuid.UUID | None,
) -> ReportChatUsage | None:
    if _normalized_text(filters.category) is not None:
        return None

    query = select(ChatHistory)
    if scoped_restaurant_id is not None:
        query = query.where(ChatHistory.restaurant_id == scoped_restaurant_id)
    elif filters.restaurant_id is not None:
        query = query.where(ChatHistory.restaurant_id == filters.restaurant_id)

    cuisine_type = _normalized_text(filters.cuisine_type)
    if cuisine_type is not None:
        query = (
            query.join(Restaurant, Restaurant.id == ChatHistory.restaurant_id)
            .where(func.lower(Restaurant.cuisine_type) == cuisine_type.lower())
        )

    if filters.date_from is not None:
        query = query.where(ChatHistory.created_at >= _day_start(filters.date_from))
    if filters.date_to is not None:
        query = query.where(ChatHistory.created_at < _day_end_exclusive(filters.date_to))

    messages = db.scalars(query.order_by(ChatHistory.created_at.desc())).all()
    if not messages:
        return ReportChatUsage(
            total_messages=0,
            total_sessions=0,
            user_messages=0,
            assistant_messages=0,
        )

    return ReportChatUsage(
        total_messages=len(messages),
        total_sessions=len({message.session_id for message in messages}),
        user_messages=sum(1 for message in messages if message.role == ChatMessageRole.USER),
        assistant_messages=sum(1 for message in messages if message.role == ChatMessageRole.ASSISTANT),
    )


def get_reports_snapshot(
    db: Session,
    *,
    current_user: User,
    filters: ReportsFilters,
) -> ReportsResponse:
    filters = _normalize_filters(filters)

    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access reports",
        )

    scoped_restaurant_id: uuid.UUID | None = None
    if current_user.role == UserRole.OWNER:
        scoped_restaurant_id = resolve_owner_restaurant_id(db, current_user)
        if filters.restaurant_id is not None and filters.restaurant_id != scoped_restaurant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Owners can only access reports for their own restaurant",
            )
        filters.restaurant_id = scoped_restaurant_id

    restaurants_in_scope = _restaurant_scope_query(
        db,
        current_user=current_user,
        scoped_restaurant_id=scoped_restaurant_id,
        filters=filters,
    )
    restaurant_scope = (
        ReportRestaurantScope(
            id=restaurants_in_scope[0].id,
            name=restaurants_in_scope[0].name,
            cuisine_type=restaurants_in_scope[0].cuisine_type,
            city=restaurants_in_scope[0].city,
        )
        if current_user.role == UserRole.OWNER and restaurants_in_scope
        else None
    )

    orders = _load_filtered_orders(db, filters=filters, scoped_restaurant_id=scoped_restaurant_id)

    order_item_totals: dict[uuid.UUID, dict[str, float | int]] = {}
    item_name_by_id: dict[uuid.UUID, str] = {}
    item_restaurant_by_id: dict[uuid.UUID, uuid.UUID] = {}
    restaurant_name_by_id: dict[uuid.UUID, str] = {}
    item_category_by_id: dict[uuid.UUID, str] = {}
    restaurant_cuisine_counter: dict[str, dict[str, float | int]] = {}
    category_counter: dict[str, dict[str, float | int]] = {}
    customer_order_counts: Counter[uuid.UUID] = Counter()
    restaurant_rollups: dict[uuid.UUID, dict[str, float | int | str]] = {}
    peak_hour_counts: Counter[int] = Counter()

    for order in orders:
        customer_order_counts[order.customer_id] += 1
        peak_hour_counts[order.placed_at.astimezone(UTC).hour] += 1

        restaurant_rollup = restaurant_rollups.setdefault(
            order.restaurant_id,
            {
                "restaurant_name": order.restaurant.name,
                "cuisine_type": order.restaurant.cuisine_type,
                "orders": 0,
                "revenue": 0.0,
            },
        )
        restaurant_rollup["orders"] = int(restaurant_rollup["orders"]) + 1
        restaurant_rollup["revenue"] = float(restaurant_rollup["revenue"]) + _safe_float(order.total_amount)
        restaurant_name_by_id[order.restaurant_id] = order.restaurant.name

        cuisine_rollup = restaurant_cuisine_counter.setdefault(
            order.restaurant.cuisine_type,
            {"orders": 0, "revenue": 0.0},
        )
        cuisine_rollup["orders"] = int(cuisine_rollup["orders"]) + 1
        cuisine_rollup["revenue"] = float(cuisine_rollup["revenue"]) + _safe_float(order.total_amount)

        for item in order.items:
            current = order_item_totals.setdefault(
                item.menu_item_id,
                {"quantity": 0, "revenue": 0.0},
            )
            current["quantity"] = int(current["quantity"]) + item.quantity
            current["revenue"] = float(current["revenue"]) + _safe_float(item.total_price)
            item_name_by_id[item.menu_item_id] = item.item_name_snapshot
            item_restaurant_by_id[item.menu_item_id] = order.restaurant_id

    menu_item_ids = list(order_item_totals.keys())
    if menu_item_ids:
        menu_rows = db.execute(
            select(MenuItem, Restaurant)
            .join(Restaurant, Restaurant.id == MenuItem.restaurant_id)
            .where(MenuItem.id.in_(menu_item_ids))
        ).all()
        for menu_item, restaurant in menu_rows:
            item_category_by_id[menu_item.id] = menu_item.category
            if menu_item.id not in item_name_by_id:
                item_name_by_id[menu_item.id] = menu_item.name
            if menu_item.id not in item_restaurant_by_id:
                item_restaurant_by_id[menu_item.id] = restaurant.id
            restaurant_name_by_id[restaurant.id] = restaurant.name

    favorite_counts = _load_favorite_counts(db, filters=filters, scoped_restaurant_id=scoped_restaurant_id)

    favorite_items: list[ReportItemPerformance] = []
    if favorite_counts:
        favorite_item_ids = list(favorite_counts.keys())
        favorite_rows = db.execute(
            select(MenuItem, Restaurant)
            .join(Restaurant, Restaurant.id == MenuItem.restaurant_id)
            .where(MenuItem.id.in_(favorite_item_ids))
        ).all()
        for menu_item, restaurant in favorite_rows:
            favorite_items.append(
                ReportItemPerformance(
                    menu_item_id=menu_item.id,
                    name=menu_item.name,
                    restaurant_id=restaurant.id,
                    restaurant_name=restaurant.name,
                    category=menu_item.category,
                    quantity=int(order_item_totals.get(menu_item.id, {}).get("quantity", 0)),
                    revenue=float(order_item_totals.get(menu_item.id, {}).get("revenue", 0.0)),
                    favorite_count=favorite_counts.get(menu_item.id, 0),
                )
            )
        favorite_items.sort(key=lambda item: (-item.favorite_count, -item.quantity, item.name.lower()))
        favorite_items = favorite_items[:6]

    top_selling_items: list[ReportItemPerformance] = []
    for item_id, metrics in order_item_totals.items():
        restaurant_id = item_restaurant_by_id.get(item_id)
        if restaurant_id is None:
            continue
        top_selling_items.append(
            ReportItemPerformance(
                menu_item_id=item_id,
                name=item_name_by_id.get(item_id, "Unknown item"),
                restaurant_id=restaurant_id,
                restaurant_name=restaurant_name_by_id.get(restaurant_id, "Unknown restaurant"),
                category=item_category_by_id.get(item_id, "Uncategorized"),
                quantity=int(metrics["quantity"]),
                revenue=float(metrics["revenue"]),
                favorite_count=favorite_counts.get(item_id, 0),
            )
        )
    top_selling_items.sort(key=lambda item: (-item.quantity, -item.revenue, item.name.lower()))
    top_selling_items = top_selling_items[:8]

    least_selling_items: list[ReportItemPerformance] = []
    if current_user.role == UserRole.OWNER and scoped_restaurant_id is not None:
        least_rows = db.execute(
            select(MenuItem, Restaurant)
            .join(Restaurant, Restaurant.id == MenuItem.restaurant_id)
            .where(MenuItem.restaurant_id == scoped_restaurant_id)
            .order_by(MenuItem.name.asc())
        ).all()
        for menu_item, restaurant in least_rows:
            metrics = order_item_totals.get(menu_item.id, {"quantity": 0, "revenue": 0.0})
            least_selling_items.append(
                ReportItemPerformance(
                    menu_item_id=menu_item.id,
                    name=menu_item.name,
                    restaurant_id=restaurant.id,
                    restaurant_name=restaurant.name,
                    category=menu_item.category,
                    quantity=int(metrics["quantity"]),
                    revenue=float(metrics["revenue"]),
                    favorite_count=favorite_counts.get(menu_item.id, 0),
                )
            )
        least_selling_items.sort(key=lambda item: (item.quantity, item.revenue, item.name.lower()))
        least_selling_items = least_selling_items[:8]
    else:
        least_selling_items = list(reversed(top_selling_items[-5:]))

    status_summary: list[ReportStatusSummary] = []
    for order_status in OrderStatus:
        status_orders = [order for order in orders if order.status == order_status]
        status_summary.append(
            ReportStatusSummary(
                status=order_status,
                count=len(status_orders),
                revenue=sum(_safe_float(order.total_amount) for order in status_orders),
            )
        )

    top_restaurants = [
        ReportRestaurantPerformance(
            restaurant_id=restaurant_id,
            restaurant_name=str(metrics["restaurant_name"]),
            cuisine_type=str(metrics["cuisine_type"]),
            orders=int(metrics["orders"]),
            revenue=float(metrics["revenue"]),
            average_order_value=(
                float(metrics["revenue"]) / int(metrics["orders"]) if int(metrics["orders"]) else 0.0
            ),
        )
        for restaurant_id, metrics in restaurant_rollups.items()
    ]
    top_restaurants.sort(key=lambda item: (-item.revenue, -item.orders, item.restaurant_name.lower()))
    top_restaurants = top_restaurants[:6]

    for item_id, metrics in order_item_totals.items():
        category = item_category_by_id.get(item_id, "Uncategorized")
        category_rollup = category_counter.setdefault(category, {"orders": 0, "revenue": 0.0})
        category_rollup["orders"] = int(category_rollup["orders"]) + int(metrics["quantity"])
        category_rollup["revenue"] = float(category_rollup["revenue"]) + float(metrics["revenue"])

    popular_cuisines = [
        ReportDimensionMetric(
            label=label,
            orders=int(metrics["orders"]),
            revenue=float(metrics["revenue"]),
        )
        for label, metrics in restaurant_cuisine_counter.items()
    ]
    popular_cuisines.sort(key=lambda item: (-item.orders, -item.revenue, item.label.lower()))
    popular_cuisines = popular_cuisines[:6]

    popular_categories = [
        ReportDimensionMetric(
            label=label,
            orders=int(metrics["orders"]),
            revenue=float(metrics["revenue"]),
        )
        for label, metrics in category_counter.items()
    ]
    popular_categories.sort(key=lambda item: (-item.orders, -item.revenue, item.label.lower()))
    popular_categories = popular_categories[:6]

    peak_order_times = [
        ReportPeakHour(
            hour=hour,
            label=_format_hour_label(hour),
            orders=count,
        )
        for hour, count in peak_hour_counts.most_common(6)
    ]
    peak_order_hour = peak_order_times[0].hour if peak_order_times else None
    peak_order_label = peak_order_times[0].label if peak_order_times else None

    combo_rows = _load_combo_rows(db, filters=filters, scoped_restaurant_id=scoped_restaurant_id)
    combo_performance = [
        ReportComboPerformance(
            combo_id=combo.id,
            combo_name=combo.combo_name,
            restaurant_id=combo.restaurant_id,
            restaurant_name=combo.restaurant.name,
            order_count=combo.order_count,
            unique_user_count=combo.unique_user_count,
            confidence_score=_safe_float(combo.confidence_score),
            suggested_combo_price=_safe_float(combo.suggested_combo_price),
            is_active=combo.is_active,
            last_seen_at=combo.last_seen_at,
        )
        for combo in combo_rows[:8]
    ]

    chat_usage = _load_chat_usage(db, filters=filters, scoped_restaurant_id=scoped_restaurant_id)
    revenue_total = sum(_safe_float(order.total_amount) for order in orders)
    restaurant_count = len(restaurants_in_scope)
    if restaurant_count == 0 and current_user.role == UserRole.OWNER and restaurant_scope is not None:
        restaurant_count = 1

    return ReportsResponse(
        role_scope=current_user.role,
        restaurant_scope=restaurant_scope,
        filters=ReportFiltersApplied(
            date_from=filters.date_from,
            date_to=filters.date_to,
            restaurant_id=filters.restaurant_id,
            cuisine_type=_normalized_text(filters.cuisine_type),
            category=_normalized_text(filters.category),
            order_status=filters.order_status,
        ),
        summary=ReportSummary(
            total_orders=len(orders),
            total_revenue=revenue_total,
            total_customers=len({order.customer_id for order in orders}),
            total_restaurants=restaurant_count,
            average_order_value=(revenue_total / len(orders)) if orders else 0.0,
            repeat_customer_count=sum(1 for count in customer_order_counts.values() if count >= 2),
            peak_order_hour=peak_order_hour,
            peak_order_label=peak_order_label,
            ai_chat_sessions=chat_usage.total_sessions if chat_usage is not None else 0,
            favorites_count=sum(favorite_counts.values()),
        ),
        revenue_trend=_build_revenue_trend(
            orders,
            date_from=filters.date_from,
            date_to=filters.date_to,
        ),
        order_status_summary=status_summary,
        top_restaurants=top_restaurants if current_user.role == UserRole.ADMIN else [],
        top_selling_items=top_selling_items,
        least_selling_items=least_selling_items,
        generated_combo_performance=combo_performance,
        popular_cuisines=popular_cuisines,
        popular_categories=popular_categories,
        peak_order_times=peak_order_times,
        chat_usage=chat_usage,
        favorite_items=favorite_items,
    )
