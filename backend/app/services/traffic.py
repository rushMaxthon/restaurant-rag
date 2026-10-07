"""Who is on each restaurant's website, and how many came today.

The storefront sends `POST /traffic/beat` with an anonymous id it keeps in the
browser: once when a page opens on screen, then every 60 seconds while it
stays on screen. Everything here is counted from those beats, and every count
is of PEOPLE, not of requests:

- **A visitor is one row per restaurant per business day**
  (`StorefrontVisitorDay`). Reloads, extra tabs (they share the id) and the
  heartbeat itself update that row; they never add one.
- **Online now** is visitors whose last beat was in the last
  `ONLINE_WINDOW`. A closed tab stops beating and drops off within it.
- **The restaurant comes from the address the page was opened on**
  (`AppScope`, resolved by the server), never from the browser's say-so.
- **Robots, link previews and local development are not visitors**
  (`is_bot`, `is_local_host`). `localhost` is mapped to a real restaurant and
  local development uses the live database, so a developer's own testing
  would otherwise be a customer.
- **One address cannot invent visitors.** A script, or somebody reloading in
  a private window, makes a new id each time; past `NEW_VISITORS_PER_ADDRESS`
  new ids from one address in a day, further new ones are ignored.
- **"Ordered" is a visitor whose storefront account placed an order that day
  at that restaurant** - signing in is what connects the two, and a checkout
  whose payment never finished is not an order.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from redis.exceptions import RedisError
from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import OrderCancellationReason, OrderStatus
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.storefront_visit import StorefrontVisitorDay
from app.services.cache import get_redis_client

logger = logging.getLogger(__name__)

#: A page beats every 60 seconds, so two minutes allows one missed beat.
ONLINE_WINDOW = timedelta(minutes=2)
#: Generous for an office or a family on one Wi-Fi, small enough that a
#: script cannot make a restaurant look busy.
NEW_VISITORS_PER_ADDRESS = 30
DAYS_SHOWN = 30
HOURS_OVER_DAYS = 7

_BOT = re.compile(
    r"bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|facebookexternalhit|"
    r"whatsapp|telegram|discord|slack|curl|wget|python-requests|httpx|axios|node-fetch|"
    r"go-http-client|java/|okhttp|postman|insomnia|monitor|uptime|pingdom|phantomjs|selenium|puppeteer|playwright",
    re.IGNORECASE,
)
_PAYMENT_CANCELLATIONS = (
    OrderCancellationReason.PAYMENT_NOT_COMPLETED,
    OrderCancellationReason.PAYMENT_ABANDONED,
    OrderCancellationReason.PAYMENT_FAILED,
)


# --- reading a request ------------------------------------------------------


def is_bot(user_agent: str | None) -> bool:
    """Robots, link previews, scripts and test browsers. No agent at all is one too."""

    agent = (user_agent or "").strip()
    return not agent or bool(_BOT.search(agent))


def device_of(user_agent: str | None) -> str:
    agent = (user_agent or "").lower()
    if "ipad" in agent or "tablet" in agent or ("android" in agent and "mobile" not in agent):
        return "tablet"
    if "iphone" in agent or "ipod" in agent or "mobile" in agent:
        return "phone"
    return "desktop"


def is_local_host(host: str | None) -> bool:
    """A development address: localhost, *.localhost, or a private network IP."""

    name = (host or "").split(",")[0].strip().lower()
    if name.startswith("["):  # [::1]:5173
        name = name[1:].split("]")[0]
    elif name.count(":") == 1:
        name = name.split(":")[0]
    if not name:
        return False
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


def _business_tz():
    return get_settings().business_timezone_info


def business_day(now: datetime) -> date:
    return now.astimezone(_business_tz()).date()


def business_hour(now: datetime) -> int:
    return now.astimezone(_business_tz()).hour


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=_business_tz())
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def allow_new_visitor(client_address: str | None, restaurant_id: uuid.UUID, now: datetime) -> bool:
    """Whether one more NEW visitor id from this address may be counted today.

    The address is hashed before it is used as a key and never stored. If
    Redis is down the visitor is counted: losing real customers to protect
    against a script is the worse trade.
    """

    digest = hashlib.sha256((client_address or "-").encode()).hexdigest()[:16]
    key = f"traffic:new:{restaurant_id}:{business_day(now)}:{digest}"
    try:
        client = get_redis_client()
        count = client.incr(key)
        if count == 1:
            client.expire(key, 2 * 24 * 3600)
        return int(count) <= NEW_VISITORS_PER_ADDRESS
    except RedisError:
        return True


# --- writing ----------------------------------------------------------------


def known_today(db: Session, restaurant_id: uuid.UUID, visitor_id: uuid.UUID, now: datetime) -> bool:
    return (
        db.get(StorefrontVisitorDay, (restaurant_id, business_day(now), visitor_id)) is not None
    )


def record_beat(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    visitor_id: uuid.UUID,
    user_id: uuid.UUID | None,
    user_agent: str | None,
    now: datetime,
) -> None:
    """Count this visitor for today, or update the row they already have.

    One statement (`INSERT ... ON CONFLICT DO UPDATE`), so two beats arriving
    together from two tabs still make one row.
    """

    day = business_day(now)
    bit = 1 << business_hour(now)
    seen_before = db.scalar(
        select(literal(True))
        .where(
            StorefrontVisitorDay.restaurant_id == restaurant_id,
            StorefrontVisitorDay.visitor_id == visitor_id,
            StorefrontVisitorDay.visit_date < day,
        )
        .limit(1)
    )
    table = StorefrontVisitorDay.__table__
    statement = insert(table).values(
        restaurant_id=restaurant_id,
        visit_date=day,
        visitor_id=visitor_id,
        device=device_of(user_agent),
        is_new=not seen_before,
        user_id=user_id,
        first_seen_at=now,
        last_seen_at=now,
        hours_mask=bit,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.restaurant_id, table.c.visit_date, table.c.visitor_id],
        set_={
            "last_seen_at": func.greatest(table.c.last_seen_at, statement.excluded.last_seen_at),
            "hours_mask": table.c.hours_mask.op("|")(statement.excluded.hours_mask),
            # Signing in attaches the account; signing out does not detach it.
            "user_id": func.coalesce(statement.excluded.user_id, table.c.user_id),
        },
    )
    db.execute(statement)
    db.commit()


# --- reading ----------------------------------------------------------------


@dataclass
class TodayTraffic:
    visitors: int = 0
    new: int = 0
    returning: int = 0
    devices: dict[str, int] = field(default_factory=lambda: {"phone": 0, "tablet": 0, "desktop": 0})
    #: Visitors whose account placed an order today at this restaurant.
    ordered: int = 0
    conversion_percent: float | None = None
    #: Every order placed today at this restaurant, however it was placed.
    orders: int = 0


@dataclass
class DayCount:
    day: date
    visitors: int
    ordered: int


@dataclass
class TrafficSummary:
    restaurant_id: uuid.UUID
    online_now: int
    today: TodayTraffic
    daily: list[DayCount]
    #: Unique visitors seen in each hour of the day, over the last 7 days.
    hours: list[int]
    generated_at: datetime


@dataclass
class OverviewRow:
    restaurant_id: uuid.UUID
    restaurant_name: str
    online_now: int
    visitors_today: int
    visitors_yesterday: int
    ordered_today: int
    conversion_percent: float | None


def _real_orders(restaurant_id, start: datetime, end: datetime):
    return and_(
        Order.restaurant_id == restaurant_id,
        Order.placed_at >= start,
        Order.placed_at < end,
        Order.status != OrderStatus.PAYMENT_PENDING,
        or_(Order.cancellation_reason.is_(None), Order.cancellation_reason.notin_(_PAYMENT_CANCELLATIONS)),
    )


def _ordered_on(db: Session, restaurant_id: uuid.UUID, day: date) -> int:
    start, end = _day_bounds(day)
    buyers = select(Order.customer_id).where(_real_orders(restaurant_id, start, end))
    return db.scalar(
        select(func.count())
        .select_from(StorefrontVisitorDay)
        .where(
            StorefrontVisitorDay.restaurant_id == restaurant_id,
            StorefrontVisitorDay.visit_date == day,
            StorefrontVisitorDay.user_id.in_(buyers),
        )
    ) or 0


def _percent(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def online_now(db: Session, restaurant_id: uuid.UUID, now: datetime) -> int:
    # Across days on purpose: someone browsing over midnight is still online
    # though their row belongs to yesterday. Distinct, because their row for
    # today and yesterday could both be inside the window.
    return db.scalar(
        select(func.count(func.distinct(StorefrontVisitorDay.visitor_id))).where(
            StorefrontVisitorDay.restaurant_id == restaurant_id,
            StorefrontVisitorDay.last_seen_at >= now - ONLINE_WINDOW,
        )
    ) or 0


def summary(db: Session, restaurant_id: uuid.UUID, *, now: datetime | None = None) -> TrafficSummary:
    now = now or datetime.now(timezone.utc)
    today = business_day(now)
    rows = StorefrontVisitorDay

    counts = db.execute(
        select(
            func.count(),
            func.count().filter(rows.is_new.is_(True)),
            func.count().filter(rows.device == "phone"),
            func.count().filter(rows.device == "tablet"),
            func.count().filter(rows.device == "desktop"),
        ).where(rows.restaurant_id == restaurant_id, rows.visit_date == today)
    ).one()
    visitors, new, phone, tablet, desktop = (int(value or 0) for value in counts)
    ordered = _ordered_on(db, restaurant_id, today)
    start, end = _day_bounds(today)
    orders = db.scalar(select(func.count()).select_from(Order).where(_real_orders(restaurant_id, start, end))) or 0
    today_traffic = TodayTraffic(
        visitors=visitors,
        new=new,
        returning=visitors - new,
        devices={"phone": phone, "tablet": tablet, "desktop": desktop},
        ordered=ordered,
        conversion_percent=_percent(ordered, visitors),
        orders=orders,
    )

    first_day = today - timedelta(days=DAYS_SHOWN - 1)
    per_day = dict(
        db.execute(
            select(rows.visit_date, func.count())
            .where(rows.restaurant_id == restaurant_id, rows.visit_date >= first_day)
            .group_by(rows.visit_date)
        ).all()
    )
    daily = []
    for offset in range(DAYS_SHOWN):
        day = first_day + timedelta(days=offset)
        count = int(per_day.get(day, 0))
        daily.append(DayCount(day=day, visitors=count, ordered=_ordered_on(db, restaurant_id, day) if count else 0))

    masks = db.scalars(
        select(rows.hours_mask).where(
            rows.restaurant_id == restaurant_id,
            rows.visit_date > today - timedelta(days=HOURS_OVER_DAYS),
        )
    ).all()
    hours = [sum(1 for mask in masks if mask & (1 << hour)) for hour in range(24)]

    return TrafficSummary(
        restaurant_id=restaurant_id,
        online_now=online_now(db, restaurant_id, now),
        today=today_traffic,
        daily=daily,
        hours=hours,
        generated_at=now,
    )


def overview(db: Session, *, now: datetime | None = None) -> list[OverviewRow]:
    """Every real restaurant, busiest first. Demo restaurants are left out."""

    now = now or datetime.now(timezone.utc)
    today = business_day(now)
    yesterday = today - timedelta(days=1)
    rows = StorefrontVisitorDay

    restaurants = db.execute(
        select(Restaurant.id, Restaurant.name).where(Restaurant.is_demo.is_(False)).order_by(Restaurant.name)
    ).all()
    per_restaurant = {
        restaurant_id: (int(today_count or 0), int(yesterday_count or 0), int(online or 0))
        for restaurant_id, today_count, yesterday_count, online in db.execute(
            select(
                rows.restaurant_id,
                func.count().filter(rows.visit_date == today),
                func.count().filter(rows.visit_date == yesterday),
                func.count(func.distinct(rows.visitor_id)).filter(rows.last_seen_at >= now - ONLINE_WINDOW),
            )
            .where(rows.visit_date >= yesterday)
            .group_by(rows.restaurant_id)
        ).all()
    }
    result = []
    for restaurant_id, name in restaurants:
        today_count, yesterday_count, online = per_restaurant.get(restaurant_id, (0, 0, 0))
        ordered = _ordered_on(db, restaurant_id, today) if today_count else 0
        result.append(
            OverviewRow(
                restaurant_id=restaurant_id,
                restaurant_name=name,
                online_now=online,
                visitors_today=today_count,
                visitors_yesterday=yesterday_count,
                ordered_today=ordered,
                conversion_percent=_percent(ordered, today_count),
            )
        )
    result.sort(key=lambda row: (-row.online_now, -row.visitors_today, row.restaurant_name))
    return result


__all__ = [
    "NEW_VISITORS_PER_ADDRESS",
    "ONLINE_WINDOW",
    "allow_new_visitor",
    "business_day",
    "business_hour",
    "device_of",
    "is_bot",
    "is_local_host",
    "known_today",
    "online_now",
    "overview",
    "record_beat",
    "summary",
]
