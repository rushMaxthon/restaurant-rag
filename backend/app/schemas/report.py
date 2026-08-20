from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.enums import OrderStatus, UserRole


class ReportRestaurantScope(BaseModel):
    id: uuid.UUID
    name: str
    cuisine_type: str
    city: str


class ReportFiltersApplied(BaseModel):
    date_from: date | None
    date_to: date | None
    restaurant_id: uuid.UUID | None
    cuisine_type: str | None
    category: str | None
    order_status: OrderStatus | None


class ReportSummary(BaseModel):
    total_orders: int
    total_revenue: float
    total_customers: int
    total_restaurants: int
    average_order_value: float
    repeat_customer_count: int
    peak_order_hour: int | None
    peak_order_label: str | None
    ai_chat_sessions: int
    favorites_count: int


class ReportTrendPoint(BaseModel):
    label: str
    value: int
    revenue: float
    orders: int


class ReportStatusSummary(BaseModel):
    status: OrderStatus
    count: int
    revenue: float


class ReportDimensionMetric(BaseModel):
    label: str
    orders: int
    revenue: float


class ReportRestaurantPerformance(BaseModel):
    restaurant_id: uuid.UUID
    restaurant_name: str
    cuisine_type: str
    orders: int
    revenue: float
    average_order_value: float


class ReportItemPerformance(BaseModel):
    menu_item_id: uuid.UUID
    name: str
    restaurant_id: uuid.UUID
    restaurant_name: str
    category: str
    quantity: int
    revenue: float
    favorite_count: int


class ReportPeakHour(BaseModel):
    hour: int
    label: str
    orders: int


class ReportChatUsage(BaseModel):
    total_messages: int
    total_sessions: int
    user_messages: int
    assistant_messages: int


class ReportComboPerformance(BaseModel):
    combo_id: uuid.UUID
    combo_name: str
    restaurant_id: uuid.UUID
    restaurant_name: str
    order_count: int
    unique_user_count: int
    confidence_score: float
    suggested_combo_price: float
    is_active: bool
    last_seen_at: datetime


class ReportsResponse(BaseModel):
    role_scope: UserRole
    restaurant_scope: ReportRestaurantScope | None
    filters: ReportFiltersApplied
    summary: ReportSummary
    revenue_trend: list[ReportTrendPoint]
    order_status_summary: list[ReportStatusSummary]
    top_restaurants: list[ReportRestaurantPerformance]
    top_selling_items: list[ReportItemPerformance]
    least_selling_items: list[ReportItemPerformance]
    generated_combo_performance: list[ReportComboPerformance]
    popular_cuisines: list[ReportDimensionMetric]
    popular_categories: list[ReportDimensionMetric]
    peak_order_times: list[ReportPeakHour]
    chat_usage: ReportChatUsage | None
    favorite_items: list[ReportItemPerformance]
