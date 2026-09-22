"""The Hub home, computed from what was actually sent.

Every figure here is attributed rather than estimated. The screen previously
read from the frontend's mock even against a live backend, which meant an owner
could look at "$4,180 attributed revenue" for a workspace that had never sent a
campaign — the single most misleading thing in the product.

The 30-day window is fixed rather than configurable on purpose: the tiles
compare against the previous 30 days, and a window the owner can change is a
comparison they can accidentally make meaningless.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
    PushNotificationCampaignKind,
    PushNotificationCampaignStatus,
)
from app.models.push_notification_campaign import PushNotificationCampaign
from app.services.marketing.attribution import build_attribution

WINDOW_DAYS = 30


@dataclass(slots=True)
class BestCampaign:
    id: uuid.UUID
    name: str
    net_revenue: float
    orders: int
    sent_at: datetime | None


@dataclass(slots=True)
class AttentionFlag:
    id: str
    tone: str
    title: str
    detail: str
    campaign_id: uuid.UUID | None = None


@dataclass(slots=True)
class DashboardView:
    attributed_revenue_30d: float = 0.0
    attributed_revenue_previous_30d: float = 0.0
    campaigns_sent_30d: int = 0
    attributed_orders_30d: int = 0
    best_campaign: BestCampaign | None = None
    attention: list[AttentionFlag] = field(default_factory=list)
    revenue_trend: list[tuple[date, float]] = field(default_factory=list)


def _sent_campaigns(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    since: datetime,
    until: datetime,
) -> list[PushNotificationCampaign]:
    return list(
        db.scalars(
            select(PushNotificationCampaign)
            .where(
                PushNotificationCampaign.restaurant_id == restaurant_id,
                PushNotificationCampaign.kind == PushNotificationCampaignKind.MARKETING,
                PushNotificationCampaign.status == PushNotificationCampaignStatus.SENT,
                PushNotificationCampaign.dispatched_at.is_not(None),
                PushNotificationCampaign.dispatched_at >= since,
                PushNotificationCampaign.dispatched_at < until,
            )
            .order_by(PushNotificationCampaign.dispatched_at.desc())
        ).all()
    )


def build_dashboard(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    now: datetime | None = None,
) -> DashboardView:
    now = now or datetime.now(UTC)
    window_start = now - timedelta(days=WINDOW_DAYS)
    previous_start = now - timedelta(days=WINDOW_DAYS * 2)

    current = _sent_campaigns(db, restaurant_id=restaurant_id, since=window_start, until=now)
    previous = _sent_campaigns(
        db, restaurant_id=restaurant_id, since=previous_start, until=window_start
    )

    view = DashboardView(campaigns_sent_30d=len(current))

    # One trend line for the whole window, built by adding every campaign's
    # daily series into shared day buckets: the owner asked "how is marketing
    # doing", not "how is campaign 3 doing".
    trend: dict[date, Decimal] = {}
    best: BestCampaign | None = None
    revenue = Decimal("0")
    orders = 0

    for campaign in current:
        report = build_attribution(db, campaign, now=now)
        if report is None:
            continue
        revenue += Decimal(str(report.net_revenue))
        orders += report.orders
        for point in report.daily:
            day = date.fromisoformat(point.label)
            trend[day] = trend.get(day, Decimal("0")) + Decimal(str(point.revenue))
        if best is None or report.net_revenue > best.net_revenue:
            best = BestCampaign(
                id=campaign.id,
                name=campaign.name or "Untitled campaign",
                net_revenue=report.net_revenue,
                orders=report.orders,
                sent_at=campaign.dispatched_at,
            )

    previous_revenue = Decimal("0")
    for campaign in previous:
        report = build_attribution(db, campaign, now=now)
        if report is not None:
            previous_revenue += Decimal(str(report.net_revenue))

    view.attributed_revenue_30d = float(revenue)
    view.attributed_revenue_previous_30d = float(previous_revenue)
    view.attributed_orders_30d = orders
    view.best_campaign = best
    # Zero-filled across the whole window: a chart that skips empty days draws
    # a line implying steady trade across a gap.
    view.revenue_trend = [
        (
            (window_start + timedelta(days=offset)).date(),
            float(trend.get((window_start + timedelta(days=offset)).date(), Decimal("0"))),
        )
        for offset in range(WINDOW_DAYS)
    ]
    view.attention = _attention_flags(db, restaurant_id=restaurant_id, now=now)
    return view


def _attention_flags(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    now: datetime,
) -> list[AttentionFlag]:
    """Things worth the owner's attention, phrased as what to do about them.

    Deliberately few and specific. A dashboard that flags everything is one the
    owner learns to scroll past, so this only raises states that are actionable
    and unambiguous: a send that failed, and a campaign stuck mid-flight.
    """

    flags: list[AttentionFlag] = []

    failed = db.scalars(
        select(PushNotificationCampaign)
        .where(
            PushNotificationCampaign.restaurant_id == restaurant_id,
            PushNotificationCampaign.kind == PushNotificationCampaignKind.MARKETING,
            PushNotificationCampaign.status == PushNotificationCampaignStatus.FAILED,
        )
        .order_by(PushNotificationCampaign.updated_at.desc())
        .limit(3)
    ).all()
    for campaign in failed:
        flags.append(
            AttentionFlag(
                id=f"failed:{campaign.id}",
                tone="critical",
                title=f"“{campaign.name or 'Untitled campaign'}” did not go out",
                detail=campaign.last_error or "The send failed. Open it to try again.",
                campaign_id=campaign.id,
            )
        )

    # A campaign that has been SENDING for over an hour is not sending. The
    # worker died mid-dispatch, and nothing else will move it — SENDING only
    # leads to SENT or FAILED, both of which the dispatcher writes.
    stalled = db.scalars(
        select(PushNotificationCampaign).where(
            PushNotificationCampaign.restaurant_id == restaurant_id,
            PushNotificationCampaign.kind == PushNotificationCampaignKind.MARKETING,
            PushNotificationCampaign.status == PushNotificationCampaignStatus.SENDING,
            PushNotificationCampaign.updated_at < now - timedelta(hours=1),
        )
    ).all()
    for campaign in stalled:
        flags.append(
            AttentionFlag(
                id=f"stalled:{campaign.id}",
                tone="warning",
                title=f"“{campaign.name or 'Untitled campaign'}” is stuck mid-send",
                detail=(
                    "It has been sending for over an hour. Some customers may "
                    "already have it; open it to see how far it reached."
                ),
                campaign_id=campaign.id,
            )
        )

    return flags


def dashboard_view(view: DashboardView) -> dict:
    return {
        "attributed_revenue_30d": view.attributed_revenue_30d,
        "attributed_revenue_previous_30d": view.attributed_revenue_previous_30d,
        "campaigns_sent_30d": view.campaigns_sent_30d,
        "attributed_orders_30d": view.attributed_orders_30d,
        "best_campaign": (
            {
                "id": view.best_campaign.id,
                "name": view.best_campaign.name,
                "net_revenue": view.best_campaign.net_revenue,
                "orders": view.best_campaign.orders,
                "sent_at": view.best_campaign.sent_at,
            }
            if view.best_campaign
            else None
        ),
        "attention": [
            {
                "id": flag.id,
                "tone": flag.tone,
                "title": flag.title,
                "detail": flag.detail,
                "campaign_id": flag.campaign_id,
            }
            for flag in view.attention
        ],
        "revenue_trend": [
            {"date": day, "revenue": revenue} for day, revenue in view.revenue_trend
        ],
    }
