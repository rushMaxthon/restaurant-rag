"""Response models for the AI Restaurant Manager diagnostics layer."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    ActionOutcomeVerdict,
    InsightNarrationSource,
    OwnerInsightSeverity,
    OwnerInsightStatus,
    OwnerInsightType,
)


class InsightsPeriod(BaseModel):
    start_date: date
    end_date: date
    day_count: int
    label: str


class InsightsScopeResponse(BaseModel):
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None
    timezone: str


class MetricDeltaResponse(BaseModel):
    metric: str
    current: float
    previous: float
    absolute_change: float
    percent_change: float | None
    direction: str
    sufficient_data: bool
    note: str | None = None


class ContributionResponse(BaseModel):
    key: str
    label: str
    current: float
    previous: float
    absolute_change: float
    percent_change: float | None
    contribution_share: float | None
    direction: str
    current_orders: int
    previous_orders: int
    current_quantity: int
    previous_quantity: int


class ContributionBreakdownResponse(BaseModel):
    dimension: str
    basis: str
    parent_change: float
    sufficient_data: bool
    note: str | None = None
    # Movement not represented in `contributions`, so the listed shares can be
    # reconciled against `parent_change`.
    excluded_change: float = 0.0
    excluded_children: int = 0
    contributions: list[ContributionResponse]


class AnomalyPointResponse(BaseModel):
    day: date
    metric: str
    value: float
    baseline_median: float
    robust_z: float
    direction: str
    severity: str


class AnomalyReportResponse(BaseModel):
    evaluated: bool
    baseline_days: int
    baseline_median_orders: float
    note: str | None = None
    points: list[AnomalyPointResponse]


class InsightsDataQuality(BaseModel):
    """Caveats a narrator must surface rather than quietly paper over."""

    sufficient_volume: bool
    weekday_aligned: bool
    includes_partial_day: bool
    counted_order_statuses: list[str]
    notes: list[str]
    # Defaulted so a cached snapshot written before these existed still
    # validates on read.
    trading_days: int = 0
    days_in_window: int = 0


class DiagnosticsSnapshotResponse(BaseModel):
    scope: InsightsScopeResponse
    current_period: InsightsPeriod
    previous_period: InsightsPeriod
    generated_at: str
    data_quality: InsightsDataQuality
    headline: list[MetricDeltaResponse]
    breakdowns: list[ContributionBreakdownResponse]
    anomalies: AnomalyReportResponse


class OwnerInsightResponse(BaseModel):
    id: uuid.UUID
    insight_type: OwnerInsightType
    severity: OwnerInsightSeverity
    status: OwnerInsightStatus
    title: str
    body: str
    dimension: str | None
    subject: str | None
    score: float
    # Why it happened, where the operational history supports an explanation.
    # Null is the common and honest case.
    root_cause: str | None = None
    period_start: date
    period_end: date
    facts: dict[str, Any]
    created_at: datetime
    acknowledged_at: datetime | None
    # Computed for the period on screen rather than read from a stored run. A
    # live finding has no row behind it yet, so it cannot be marked seen or
    # dismissed — the client hides those controls rather than offering an
    # action that would 404.
    is_live: bool = False

    model_config = ConfigDict(from_attributes=True)


class OwnerBriefingResponse(BaseModel):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None
    period_start: date
    period_end: date
    previous_period_start: date
    previous_period_end: date
    headline: str
    narrative: str
    narration_source: InsightNarrationSource
    insight_count: int
    generated_at: datetime
    insights: list[OwnerInsightResponse] = []
    # Computed live for the period the owner is looking at, rather than read
    # from the nightly run. A live briefing is never stale by definition.
    is_live: bool = False
    # True when the stored briefing does not cover the last complete day. The
    # card was the loudest thing on the screen and had no way to say it was
    # describing a window that ended days ago.
    is_stale: bool = False
    stale_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OfferPerformanceRow(BaseModel):
    offer_id: uuid.UUID
    offer_name: str
    offer_kind: str
    orders: int
    customers: int
    gross_revenue: float
    discount_cost: float
    net_revenue: float
    average_order_value: float
    # Gross revenue earned per unit of discount given away. None when nothing
    # was discounted.
    return_per_unit_discount: float | None
    views: int
    clicks: int
    conversions: int
    click_through_rate: float | None
    conversion_rate: float | None


class OfferPerformanceResponse(BaseModel):
    scope: InsightsScopeResponse
    period: InsightsPeriod
    # Net revenue is revenue after discount, not profit: food and delivery costs
    # are not recorded anywhere in the platform.
    total_gross_revenue: float
    total_discount_cost: float
    total_orders: int
    offers: list[OfferPerformanceRow]


class ActionOutcomeResponse(BaseModel):
    """What was observed after an approved action ran.

    Observation, not attribution: there is no holdout group, so these are orders
    that *used* the offer, not orders the offer can be shown to have caused.
    """

    id: uuid.UUID
    proposal_id: uuid.UUID
    offer_id: uuid.UUID | None
    verdict: ActionOutcomeVerdict
    window_start: date
    window_end: date
    window_days: int
    attributed_orders: int
    attributed_customers: int
    attributed_revenue: float
    discount_cost: float
    net_revenue: float
    estimated_impact: float | None
    summary: str
    measured_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OwnerInsightStatusUpdate(BaseModel):
    status: OwnerInsightStatus


class InsightGenerationTriggerResponse(BaseModel):
    task_id: str
    queued: bool
    detail: str


__all__ = [
    "ActionOutcomeResponse",
    "AnomalyPointResponse",
    "AnomalyReportResponse",
    "ContributionBreakdownResponse",
    "ContributionResponse",
    "DiagnosticsSnapshotResponse",
    "InsightGenerationTriggerResponse",
    "InsightsDataQuality",
    "InsightsPeriod",
    "InsightsScopeResponse",
    "MetricDeltaResponse",
    "OfferPerformanceResponse",
    "OfferPerformanceRow",
    "OwnerBriefingResponse",
    "OwnerInsightResponse",
    "OwnerInsightStatusUpdate",
]
