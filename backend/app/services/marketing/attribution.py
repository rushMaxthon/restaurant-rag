"""Did the campaign cause an order?

Answered against the recipient rows, never against the segment. Segment
membership is recomputed continuously — by the time a report is read, "lapsed
regulars" no longer contains the people who were messaged precisely because the
campaign worked and they came back. Attributing to the segment would therefore
credit a campaign for orders from customers it never reached, and lose the
customers it did.

The rule, and its limits, stated plainly because the number is one an owner may
spend money on:

**An order counts when a customer who received this campaign ordered from this
restaurant within the window, after their own send instant.** Per recipient,
not per campaign: a send spanning minutes must not shorten the last customer's
window by the first customer's clock.

**This is correlation with a cutoff, not proof.** A customer who was going to
order anyway still counts. `baseline_orders` is what makes that visible — the
same customers' order rate in the equal-length window immediately before the
send — so the owner can see the lift rather than the raw total. It is a
comparison, not a control group, and this module does not pretend otherwise.

Only statuses in `insights_counted_order_statuses` count, which is the same
rule the rest of the product's revenue figures use: a cancelled order is not
revenue, and a campaign must not be credited with one.

**A public post is attributed differently, and worse.** An Instagram or
Facebook campaign writes no recipient rows, because it was not sent to
anybody this product can name — so the rule above has no subject. Its only
handle is the promo code the customer typed at checkout, which credits the
campaign that published the code within the same window. That is a weaker
claim in two ways worth saying out loud: it misses everyone who saw the post
and ordered without the code, and it has no honest baseline, because "the
same customers before the send" names a set that does not exist. The social
report therefore reports no baseline at all rather than a zero, and the UI
says what the number is measuring.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import CampaignRecipientState, PushNotificationCampaignStatus
from app.models.order import Order
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.push_notification_campaign_recipient import (
    PushNotificationCampaignRecipient,
)

settings = get_settings()

TWO_PLACES = Decimal("0.01")


@dataclass(slots=True)
class DailyPoint:
    label: str
    revenue: float
    orders: int


@dataclass(slots=True)
class AttributionReport:
    window_days: int
    #: True while the window is still collecting — the figures below are not
    #: final and the report says so rather than reading as a result.
    window_open: bool
    orders: int
    revenue: float
    discount_given: float
    net_revenue: float
    average_order_value: float
    #: The same recipients' order count in the equal window before the send.
    baseline_orders: int
    returning_customers: int
    new_customers: int
    daily: list[DailyPoint] = field(default_factory=list)


def _counted_statuses() -> list[str]:
    return settings.insights_counted_order_statuses_list


def _money(value: Decimal | float | None) -> float:
    if value is None:
        return 0.0
    return float(Decimal(str(value)).quantize(TWO_PLACES))


def _attributed_orders_query(
    campaign: PushNotificationCampaign,
) -> Select:
    """Orders credited to this campaign.

    The join carries the per-recipient send instant, so the window is applied
    per customer in SQL rather than by fetching every recipient and looping.
    """

    window = timedelta(days=campaign.attribution_window_days or 7)
    return (
        select(Order, PushNotificationCampaignRecipient.user_id)
        .join(
            PushNotificationCampaignRecipient,
            and_(
                PushNotificationCampaignRecipient.user_id == Order.customer_id,
                PushNotificationCampaignRecipient.campaign_id == campaign.id,
                PushNotificationCampaignRecipient.state == CampaignRecipientState.SENT,
                PushNotificationCampaignRecipient.sent_at.is_not(None),
                Order.created_at >= PushNotificationCampaignRecipient.sent_at,
                Order.created_at
                <= PushNotificationCampaignRecipient.sent_at + window,
            ),
        )
        .where(
            Order.restaurant_id == campaign.restaurant_id,
            Order.status.in_(_counted_statuses()),
        )
    )


def _baseline_order_count(db: Session, campaign: PushNotificationCampaign) -> int:
    """The same customers' orders in the equal window *before* the send.

    The honest denominator for "did this work". Without it a campaign to
    regulars reports a large number that says nothing: those customers were
    always going to order.
    """

    window = timedelta(days=campaign.attribution_window_days or 7)
    return (
        db.scalar(
            select(func.count())
            .select_from(Order)
            .join(
                PushNotificationCampaignRecipient,
                and_(
                    PushNotificationCampaignRecipient.user_id == Order.customer_id,
                    PushNotificationCampaignRecipient.campaign_id == campaign.id,
                    PushNotificationCampaignRecipient.state
                    == CampaignRecipientState.SENT,
                    PushNotificationCampaignRecipient.sent_at.is_not(None),
                    Order.created_at
                    >= PushNotificationCampaignRecipient.sent_at - window,
                    Order.created_at < PushNotificationCampaignRecipient.sent_at,
                ),
            )
            .where(
                Order.restaurant_id == campaign.restaurant_id,
                Order.status.in_(_counted_statuses()),
            )
        )
        or 0
    )


def build_attribution(
    db: Session,
    campaign: PushNotificationCampaign,
    *,
    now: datetime | None = None,
) -> AttributionReport | None:
    """The campaign's report, or None when there is nothing to report on."""

    if campaign.status is not PushNotificationCampaignStatus.SENT:
        return None
    if campaign.dispatched_at is None or campaign.restaurant_id is None:
        return None

    now = now or datetime.now(UTC)
    window_days = campaign.attribution_window_days or 7
    sent_at = campaign.dispatched_at
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    window_open = now < sent_at + timedelta(days=window_days)

    rows = db.execute(_attributed_orders_query(campaign)).all()

    orders = len(rows)
    revenue = sum(Decimal(str(order.total_amount or 0)) for order, _ in rows)
    discount = sum(Decimal(str(order.discount_amount or 0)) for order, _ in rows)

    # "Returning" means this customer had ordered from this restaurant before
    # the campaign, not before this order — a customer who orders twice in the
    # window is one returning customer, not one of each.
    customer_ids = {user_id for _, user_id in rows}
    returning = _returning_customer_ids(db, campaign, customer_ids, sent_at)

    daily = _daily_series(rows, sent_at, window_days, now)

    return AttributionReport(
        window_days=window_days,
        window_open=window_open,
        orders=orders,
        revenue=_money(revenue),
        discount_given=_money(discount),
        net_revenue=_money(revenue - discount),
        average_order_value=_money(revenue / orders) if orders else 0.0,
        baseline_orders=_baseline_order_count(db, campaign),
        returning_customers=len(returning),
        new_customers=len(customer_ids - returning),
        daily=daily,
    )


def _returning_customer_ids(
    db: Session,
    campaign: PushNotificationCampaign,
    customer_ids: set[uuid.UUID],
    sent_at: datetime,
) -> set[uuid.UUID]:
    if not customer_ids:
        return set()
    return set(
        db.scalars(
            select(Order.customer_id)
            .where(
                Order.restaurant_id == campaign.restaurant_id,
                Order.customer_id.in_(customer_ids),
                Order.created_at < sent_at,
                Order.status.in_(_counted_statuses()),
            )
            .distinct()
        ).all()
    )


def _daily_series(
    rows: list,
    sent_at: datetime,
    window_days: int,
    now: datetime,
) -> list[DailyPoint]:
    """One point per day of the window, including the days with nothing.

    Zero-filled deliberately: a chart that omits empty days draws a line
    implying steady trade across a gap, which is the opposite of what happened.
    """

    buckets: dict[date, tuple[Decimal, int]] = {}
    for order, _ in rows:
        created = order.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        day = created.date()
        revenue, count = buckets.get(day, (Decimal("0"), 0))
        buckets[day] = (revenue + Decimal(str(order.total_amount or 0)), count + 1)

    points: list[DailyPoint] = []
    for offset in range(window_days):
        day = (sent_at + timedelta(days=offset)).date()
        if day > now.date():
            # The future is not a data point. A window still open should show
            # the days that have happened, not a run of zeroes implying failure.
            break
        revenue, count = buckets.get(day, (Decimal("0"), 0))
        points.append(
            DailyPoint(label=day.isoformat(), revenue=_money(revenue), orders=count)
        )
    return points


def promo_code_for(campaign: PushNotificationCampaign) -> str | None:
    """The code this campaign told people to type, normalised.

    Upper-cased and stripped, matching how the order service stores what the
    customer typed, so "insta20" at checkout credits "INSTA20" in the post.
    """

    extra = (campaign.data_payload or {}).get("content_extra") or {}
    code = str(extra.get("promo_code") or "").strip().upper()
    return code or None


def _published_at(campaign: PushNotificationCampaign) -> datetime | None:
    post = (campaign.data_payload or {}).get("social_post") or {}
    raw = post.get("published_at")
    if raw:
        try:
            parsed = datetime.fromisoformat(str(raw))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    sent_at = campaign.dispatched_at
    if sent_at is None:
        return None
    return sent_at if sent_at.tzinfo else sent_at.replace(tzinfo=UTC)


def build_social_attribution(
    db: Session,
    campaign: PushNotificationCampaign,
    *,
    now: datetime | None = None,
) -> AttributionReport | None:
    """What a public post can honestly be credited with.

    Orders carrying this campaign's promo code, placed at this restaurant,
    inside the window that opened when the post went up. One window for the
    whole campaign rather than one per recipient — there are no recipients,
    and the post went up at a single instant, so the per-recipient subtlety
    the direct path needs does not arise here.

    `baseline_orders` is left at zero and the UI does not draw it. The direct
    report's baseline is "these same customers in the window before", and a
    post has no "these same customers" — inventing one would put a made-up
    denominator next to a real numerator.
    """

    if campaign.status is not PushNotificationCampaignStatus.SENT:
        return None
    code = promo_code_for(campaign)
    published = _published_at(campaign)
    if not code or published is None or campaign.restaurant_id is None:
        return None

    now = now or datetime.now(UTC)
    window_days = campaign.attribution_window_days or 7
    window_end = published + timedelta(days=window_days)

    rows = db.scalars(
        select(Order).where(
            Order.restaurant_id == campaign.restaurant_id,
            Order.marketing_promo_code == code,
            Order.created_at >= published,
            Order.created_at <= window_end,
            Order.status.in_(_counted_statuses()),
        )
    ).all()

    orders = len(rows)
    revenue = sum(Decimal(str(order.total_amount or 0)) for order in rows)
    discount = sum(Decimal(str(order.discount_amount or 0)) for order in rows)
    customer_ids = {order.customer_id for order in rows if order.customer_id}
    returning = _returning_customer_ids(db, campaign, customer_ids, published)

    return AttributionReport(
        window_days=window_days,
        window_open=now < window_end,
        orders=orders,
        revenue=_money(revenue),
        discount_given=_money(discount),
        net_revenue=_money(revenue - discount),
        average_order_value=_money(revenue / orders) if orders else 0.0,
        # Deliberately zero. See the docstring: there is no honest baseline
        # for a post, and a fabricated one is worse than none.
        baseline_orders=0,
        returning_customers=len(returning),
        new_customers=len(customer_ids - returning),
        daily=_daily_series([(order, order.customer_id) for order in rows], published, window_days, now),
    )


def social_post_view(campaign: PushNotificationCampaign) -> dict | None:
    """The post itself, for the report's header.

    Separate from attribution because it is a different kind of fact: where
    the post is and how it performed on the platform, versus what it sold.
    An owner wants both and they answer different questions.
    """

    post = (campaign.data_payload or {}).get("social_post")
    if not post:
        return None
    insights = (campaign.data_payload or {}).get("social_insights") or {}
    return {
        "state": post.get("state"),
        "post_id": post.get("post_id"),
        "permalink": post.get("permalink"),
        "published_at": post.get("published_at"),
        "dry_run": bool(post.get("dry_run")),
        "reason": post.get("reason"),
        "promo_code": promo_code_for(campaign),
        # Whatever the platform gave us, unchanged. A metric it stopped
        # serving disappears rather than reading as zero — an owner seeing
        # "0 impressions" on a post that clearly got seen would conclude the
        # product is broken, and they would be right.
        "insights": {key: value for key, value in insights.items() if key != "fetched_at"},
        "insights_updated_at": insights.get("fetched_at"),
    }


def attribution_view(report: AttributionReport | None) -> dict | None:
    if report is None:
        return None
    return {
        "window_days": report.window_days,
        "window_open": report.window_open,
        "orders": report.orders,
        "revenue": report.revenue,
        "discount_given": report.discount_given,
        "net_revenue": report.net_revenue,
        "average_order_value": report.average_order_value,
        "baseline_orders": report.baseline_orders,
        "returning_customers": report.returning_customers,
        "new_customers": report.new_customers,
        "daily": [
            {"label": point.label, "revenue": point.revenue, "orders": point.orders}
            for point in report.daily
        ],
    }


def failure_reason_view(db: Session, campaign: PushNotificationCampaign) -> list[dict]:
    """Why customers missed it, counted by reason.

    Read from recipient rows rather than the campaign's single `last_error`, so
    the report can say "812 delivered, 3 uninstalled" instead of one summary
    string that hides how many of each.
    """

    rows = db.execute(
        select(
            PushNotificationCampaignRecipient.failure_reason,
            func.count().label("count"),
        )
        .where(
            PushNotificationCampaignRecipient.campaign_id == campaign.id,
            PushNotificationCampaignRecipient.state.in_(
                [CampaignRecipientState.FAILED, CampaignRecipientState.SKIPPED]
            ),
            PushNotificationCampaignRecipient.failure_reason.is_not(None),
        )
        .group_by(PushNotificationCampaignRecipient.failure_reason)
        .order_by(func.count().desc())
        .limit(10)
    ).all()
    return [{"reason": reason, "count": count} for reason, count in rows]
