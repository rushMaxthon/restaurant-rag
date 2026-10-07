"""What the platform admin should be looking at right now.

The admin panel could show every restaurant, every order and every user, and
still not answer the question an operator opens it with: is anything wrong?
Each problem below was found the slow way first - by a customer, an owner, or
an afternoon of debugging - because nothing on any screen said it:

* the scheduler was not running, so unpaid orders were never cleaned up and
  the morning stock refill never happened;
* the database pool was full and pages failed at random;
* paid orders sat in New with nobody accepting them;
* a branch was "open" with no dish a customer could order, or no way to pay.

So this module asks all of those questions at once, and answers each with a
sentence and a place to go and fix it. It READS only. Nothing here changes an
order, a restaurant or a setting.

Three parts, because they are three different kinds of looking:

* **Checks** - is the machinery up? Database, Redis, the background worker,
  the scheduler, the queues, the AI model, the courier, live updates.
* **Issues** - what needs a person, across every restaurant, worst first.
* **Restaurants** - today, one line each, so a quiet restaurant and a broken
  one can be told apart.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models.app_client import AppClient
from app.models.enums import AppClientStatus, OrderScheduleType, OrderStatus, PaymentStatus
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_delivery import OrderDelivery
from app.models.payment import PaymentTransaction
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation

logger = logging.getLogger(__name__)

OK, WARN, DOWN = "ok", "warn", "down"
HIGH, MEDIUM, LOW = "high", "medium", "low"
_SEVERITY_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}

#: Written by `tasks.platform.heartbeat_task`, which beat sends every minute
#: and a worker runs. Fresh means both are alive.
HEARTBEAT_KEY = "platform:heartbeat:last_seen"
HEARTBEAT_STALE_AFTER = timedelta(minutes=3)

#: A paid order nobody has accepted after this long is a customer waiting.
ACCEPT_WITHIN = timedelta(minutes=10)
#: Accepted or cooking for longer than this is worth a phone call.
KITCHEN_WITHIN = timedelta(minutes=60)
#: Out for delivery for longer than this has probably gone wrong.
ROAD_WITHIN = timedelta(minutes=90)
#: A queue deeper than this is a worker that has fallen behind or stopped.
QUEUE_BACKLOG = 50
QUEUES = ("default", "notifications", "embeddings", "analytics")

_NOT_A_SALE = (OrderStatus.PAYMENT_PENDING, OrderStatus.CANCELLED)
_SETTLED = (PaymentStatus.PAID, PaymentStatus.COD)


@dataclass(slots=True)
class Check:
    key: str
    label: str
    status: str
    detail: str
    #: What to do about it, when it is not OK.
    hint: str = ""


@dataclass(slots=True)
class Issue:
    key: str
    severity: str
    title: str
    detail: str
    count: int = 1
    restaurant_id: uuid.UUID | None = None
    restaurant_name: str | None = None
    location_id: uuid.UUID | None = None
    #: Where in the panel this is fixed.
    link: str | None = None


@dataclass(slots=True)
class RestaurantToday:
    restaurant_id: uuid.UUID
    name: str
    city: str
    approved: bool
    storefront: str | None
    branches: int
    branches_open: int
    orders_today: int
    sales_today: Decimal
    awaiting_accept: int
    out_of_stock: int
    issues: int = 0


@dataclass(slots=True)
class PlatformWatch:
    generated_at: datetime
    checks: list[Check] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    restaurants: list[RestaurantToday] = field(default_factory=list)


# --- checks -----------------------------------------------------------------


def _timed(fn) -> tuple[object, float]:
    started = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - started) * 1000


def _check_database(db: Session) -> Check:
    try:
        _, ms = _timed(lambda: db.execute(select(1)).scalar())
    except Exception as error:  # noqa: BLE001 - the answer IS the failure
        return Check("database", "Database", DOWN, f"Not answering: {str(error)[:120]}",
                     "Every page and order depends on this. Check the database server and its connection limit.")
    pool = db.get_bind().pool
    in_use = getattr(pool, "checkedout", lambda: 0)()
    size = getattr(pool, "size", lambda: 0)() + max(0, getattr(pool, "_max_overflow", 0))
    detail = f"Answering in {ms:.0f} ms. {in_use} of {size} connections in use here."
    if ms > 800 or (size and in_use >= size):
        return Check("database", "Database", WARN, detail,
                     "Slow or out of connections: pages will queue and may time out. "
                     "Check the connection pool limit on the database host.")
    return Check("database", "Database", OK, detail)


def _redis():
    from app.services.cache import get_redis_client

    return get_redis_client()


def _check_redis() -> Check:
    try:
        _, ms = _timed(lambda: _redis().ping())
    except Exception as error:  # noqa: BLE001
        return Check("redis", "Cache and queue (Redis)", DOWN, f"Not answering: {str(error)[:120]}",
                     "Chat memory, caching and every background job need it. Start Redis.")
    return Check("redis", "Cache and queue (Redis)", OK, f"Answering in {ms:.0f} ms.")


def _check_worker() -> Check:
    try:
        from app.config.celery import celery_app

        # Its own short-lived connection, to 127.0.0.1 where the URL says
        # localhost. On Windows "localhost" is tried as IPv6 first and a Redis
        # bound to IPv4 only answers after a timeout; the first ping in a
        # process measured nine seconds for that reason alone.
        url = get_settings().celery_broker_url.replace("://localhost", "://127.0.0.1")
        with celery_app.connection_for_write(url) as connection:
            replies = celery_app.control.ping(timeout=1.0, connection=connection) or []
    except Exception as error:  # noqa: BLE001
        return Check("worker", "Background worker", DOWN, f"Could not ask: {str(error)[:120]}",
                     "Start a Celery worker. Notifications, deliveries and AI jobs wait until one runs.")
    if not replies:
        return Check("worker", "Background worker", DOWN, "No worker answered.",
                     "Start a Celery worker. Order notifications, rider booking and menu indexing "
                     "are queued and will not run until one does.")
    return Check("worker", "Background worker", OK, f"{len(replies)} worker(s) answering.")


def _check_scheduler(now: datetime) -> Check:
    label = "Scheduler (Celery beat)"
    try:
        raw = _redis().get(HEARTBEAT_KEY)
    except Exception:  # noqa: BLE001 - Redis being down is its own check
        return Check("scheduler", label, WARN, "Cannot tell: Redis is not answering.")
    if not raw:
        return Check("scheduler", label, DOWN, "No heartbeat has ever been recorded.",
                     "Start Celery beat. Without it unpaid orders are never cleaned up, deliveries "
                     "are not refreshed and the morning stock refill does not happen.")
    try:
        seen = datetime.fromisoformat(raw.decode() if isinstance(raw, bytes) else str(raw))
    except ValueError:
        return Check("scheduler", label, WARN, "The last heartbeat could not be read.")
    age = now - seen
    minutes = int(age.total_seconds() // 60)
    if age > HEARTBEAT_STALE_AFTER:
        return Check("scheduler", label, DOWN, f"Last heartbeat {minutes} min ago.",
                     "Beat or the worker has stopped. Scheduled jobs - unpaid-order cleanup, "
                     "delivery refresh, the daily stock refill - are not running.")
    return Check("scheduler", label, OK, "Heartbeat in the last minute or two.")


def _check_queues() -> Check:
    label = "Job queues"
    try:
        settings = get_settings()
        if settings.celery_broker_url == settings.redis_url:
            # The same server as the cache: reuse its connection rather than
            # open a fresh one per page load.
            broker = _redis()
        else:
            from redis import Redis

            broker = Redis.from_url(settings.celery_broker_url, socket_timeout=2)
        depth = {queue: int(broker.llen(queue)) for queue in QUEUES}
    except Exception:  # noqa: BLE001
        return Check("queues", label, WARN, "Cannot read the queues.")
    waiting = sum(depth.values())
    busiest = max(depth, key=depth.get)
    detail = f"{waiting} job(s) waiting" + (f", most in {busiest} ({depth[busiest]})." if waiting else ".")
    if depth[busiest] > QUEUE_BACKLOG:
        return Check("queues", label, WARN, detail,
                     "A queue is backing up: the worker is down, too slow, or not listening on it.")
    return Check("queues", label, OK, detail)


def _ai_in_use() -> bool:
    settings = get_settings()
    return any(
        getattr(settings, flag, False)
        for flag in (
            "enable_ordering_agent",
            "enable_ai_manager_chat",
            "enable_ai_manager_insights",
            "enable_ai_offer_generation",
        )
    )


def _check_ai() -> Check:
    label = "AI model (Ollama)"
    if not _ai_in_use():
        return Check("ai", label, OK, "No AI feature is switched on, so it is not needed.")
    try:
        import httpx

        url = get_settings().ollama_base_url.rstrip("/") + "/api/tags"
        _, ms = _timed(lambda: httpx.get(url, timeout=2.0).raise_for_status())
    except Exception:  # noqa: BLE001
        return Check("ai", label, WARN, "Not answering.",
                     "The chat and AI Manager fall back to plain templates until it is back.")
    return Check("ai", label, OK, f"Answering in {ms:.0f} ms.")


def _check_delivery() -> Check:
    settings = get_settings()
    label = "Delivery partner"
    if not (settings.enable_delivery_dispatch or settings.enable_delivery_quotes):
        return Check("delivery", label, WARN, "Off. Delivery is charged at each branch's flat fee and no rider is booked.",
                     "Fine if restaurants deliver themselves.")
    from app.services.delivery.registry import delivery_provider

    provider = delivery_provider()
    if provider is None:
        return Check("delivery", label, DOWN, "Switched on, but no courier account is configured.",
                     "Add the courier's credentials, or switch delivery quotes and dispatch off.")
    parts = []
    parts.append("quotes on" if settings.enable_delivery_quotes else "quotes off")
    parts.append("rider booking on" if settings.enable_delivery_dispatch else "rider booking off")
    return Check("delivery", label, OK, f"{type(provider).__name__.replace('Provider', '')}: {', '.join(parts)}.")


def _google_configured() -> bool:
    return bool(get_settings().google_maps_api_key)


#: How long after Google refuses us the check stays red with no newer word.
MAPS_REFUSAL_WINDOW = timedelta(hours=1)


def _check_maps(now: datetime) -> Check:
    """Whether Google is answering address lookups and suggestions.

    Added 2026-10-07, when Google refused every call (billing switched off on
    the Cloud project) and the only sign was a customer told their address
    was not on the map. Addresses fall back to OpenStreetMap meanwhile, but
    suggestions-as-you-type stop entirely.
    """

    from app.services.geocoding import health

    label = "Maps and address search (Google)"
    if not _google_configured():
        return Check("maps", label, WARN, "No Google key: addresses use OpenStreetMap and there are no suggestions as you type.",
                     "Set GOOGLE_MAPS_API_KEY for building-level accuracy and the address dropdown.")
    refusal = health.last_refusal()
    if refusal and now - refusal["at"] <= MAPS_REFUSAL_WINDOW:
        minutes = max(0, int((now - refusal["at"]).total_seconds() // 60))
        return Check("maps", label, DOWN, f"Google refused us {minutes} min ago: {refusal['message'][:140]}",
                     "Turn billing back on for the key's Google Cloud project (or check the key's API "
                     "restrictions). Until then addresses are found through OpenStreetMap, less precisely, "
                     "and checkout has no address suggestions.")
    return Check("maps", label, OK, "Answering.")


def _check_realtime() -> Check:
    if get_settings().enable_realtime:
        return Check("realtime", "Live updates", OK, "On. Boards update the moment an order moves.")
    return Check("realtime", "Live updates", WARN, "Off. Boards refresh every 30 seconds instead.",
                 "Switch on ENABLE_REALTIME for instant updates on the kitchen and live boards.")


#: The whole set of checks gets this long. One down service must not hold the
#: page hostage - a worker that never answers is exactly the case to report.
CHECKS_BUDGET_SECONDS = 6.0

_LABELS = {
    "redis": "Cache and queue (Redis)",
    "worker": "Background worker",
    "scheduler": "Scheduler (Celery beat)",
    "queues": "Job queues",
    "ai": "AI model (Ollama)",
    "delivery": "Delivery partner",
    "realtime": "Live updates",
    "maps": "Maps and address search (Google)",
}


def _start_checks(now: datetime):
    from concurrent.futures import ThreadPoolExecutor

    others = {
        "redis": _check_redis,
        "worker": _check_worker,
        "scheduler": lambda: _check_scheduler(now),
        "queues": _check_queues,
        "ai": _check_ai,
        "delivery": _check_delivery,
        "realtime": _check_realtime,
        "maps": lambda: _check_maps(now),
    }
    pool = ThreadPoolExecutor(max_workers=len(others), thread_name_prefix="platform-watch")
    return pool, {key: pool.submit(fn) for key, fn in others.items()}


def _collect_checks(pool, futures, *, deadline: float) -> list[Check]:
    from concurrent.futures import wait

    wait(futures.values(), timeout=max(0.0, deadline - time.monotonic()))
    results = []
    for key, future in futures.items():
        if future.done() and future.exception() is None:
            results.append(future.result())
        elif future.done():
            results.append(Check(key, _LABELS[key], WARN, f"The check itself failed: {str(future.exception())[:120]}"))
        else:
            results.append(Check(key, _LABELS[key], WARN, f"Did not answer within {CHECKS_BUDGET_SECONDS:.0f} seconds.",
                                 "Slow or unreachable. Check it directly if this persists."))
    # Do not wait for stragglers: they finish in the background and are dropped.
    pool.shutdown(wait=False, cancel_futures=True)
    return results


def system_checks(db: Session, *, now: datetime) -> list[Check]:
    """Every check at once, in parallel, within one time budget.

    Run one after another they took fourteen seconds on a cold start: the
    worker ping alone is a second, the AI model two. In parallel the page
    waits for the slowest, and anything still silent at the deadline is
    reported as not answering rather than waited for.

    The database check runs here, in the request's own thread: a session is
    not to be shared across threads.
    """

    deadline = time.monotonic() + CHECKS_BUDGET_SECONDS
    pool, futures = _start_checks(now)
    return [_check_database(db), *_collect_checks(pool, futures, deadline=deadline)]


# --- issues -----------------------------------------------------------------


def _orders_by_restaurant(db: Session, *conditions) -> dict[uuid.UUID, tuple[int, datetime | None]]:
    rows = db.execute(
        select(Order.restaurant_id, func.count(Order.id), func.min(Order.placed_at))
        .where(*conditions)
        .group_by(Order.restaurant_id)
    ).all()
    return {row[0]: (int(row[1]), row[2]) for row in rows}


def _minutes(since: datetime | None, now: datetime) -> int:
    if since is None:
        return 0
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return max(0, int((now - since).total_seconds() // 60))


def find_issues(db: Session, *, now: datetime) -> list[Issue]:
    from app.services.payments.registry import available_payment_methods

    settings = get_settings()
    restaurants = {
        r.id: r
        for r in db.scalars(
            select(Restaurant).options(selectinload(Restaurant.locations))
        )
    }
    # Demo kitchens are not watched: what is wrong with seeded data is not
    # something anybody has to act on.
    demo = {rid for rid, r in restaurants.items() if r.is_demo}
    restaurants = {rid: r for rid, r in restaurants.items() if rid not in demo}
    name = lambda rid: restaurants[rid].name if rid in restaurants else None  # noqa: E731
    issues: list[Issue] = []

    # Paid, and nobody has said yes. Scheduled orders only once their slot is
    # near - an order for tomorrow is not late tonight.
    waiting = _orders_by_restaurant(
        db,
        Order.status == OrderStatus.PLACED,
        Order.payment_status.in_(_SETTLED),
        Order.placed_at < now - ACCEPT_WITHIN,
        or_(Order.schedule_type == OrderScheduleType.ASAP, Order.scheduled_at <= now + timedelta(minutes=30)),
    )
    for rid, (count, oldest) in waiting.items():
        issues.append(Issue(
            "orders_not_accepted", HIGH, f"{count} paid order(s) not accepted",
            f"The oldest has waited {_minutes(oldest, now)} min. The customer has paid and is waiting.",
            count, rid, name(rid), link="/live-orders",
        ))

    for statuses, limit, key, title in (
        ((OrderStatus.ACCEPTED, OrderStatus.PREPARING), KITCHEN_WITHIN, "orders_stuck_kitchen", "in the kitchen for over an hour"),
        ((OrderStatus.OUT_FOR_DELIVERY,), ROAD_WITHIN, "orders_stuck_road", "out for delivery for over 90 minutes"),
    ):
        stuck = _orders_by_restaurant(db, Order.status.in_(statuses), Order.updated_at < now - limit)
        for rid, (count, _) in stuck.items():
            issues.append(Issue(
                key, MEDIUM, f"{count} order(s) {title}",
                "Probably finished and never marked, or genuinely stuck. Worth a call to the restaurant.",
                count, rid, name(rid), link="/live-orders",
            ))

    failed_rides = db.execute(
        select(Order.restaurant_id, func.count(OrderDelivery.id))
        .join(Order, Order.id == OrderDelivery.order_id)
        .where(OrderDelivery.state == "FAILED", OrderDelivery.updated_at > now - timedelta(hours=24))
        .group_by(Order.restaurant_id)
    ).all()
    for rid, count in failed_rides:
        issues.append(Issue(
            "deliveries_failed", HIGH, f"{count} delivery(ies) failed in the last 24 hours",
            "The rider could not hand the food over. Somebody has to decide about a refund or a resend.",
            int(count), rid, name(rid), link="/orders",
        ))

    # A rider network that charges far more than the customer paid for the
    # trip. Pidge auto-allocates, so it is Pidge's choice and nothing else
    # would ever say so - two Rs 57 trips went at Rs 285.61 on 2026-10-06.
    from app.services.delivery.service import courier_overpriced, paid_for_delivery

    priced = db.execute(
        select(Order, OrderDelivery)
        .join(OrderDelivery, OrderDelivery.order_id == Order.id)
        .where(OrderDelivery.courier_charge.is_not(None), OrderDelivery.created_at > now - timedelta(hours=24))
    ).all()
    over: dict[uuid.UUID, list[tuple[Decimal, Decimal]]] = {}
    for order, delivery in priced:
        if order.restaurant_id in demo or not courier_overpriced(order, delivery):
            continue
        over.setdefault(order.restaurant_id, []).append((Decimal(delivery.courier_charge), paid_for_delivery(order)))
    for rid, trips in over.items():
        charge, paid = max(trips)
        issues.append(Issue(
            "courier_overpriced", MEDIUM, f"{len(trips)} rider(s) charged far more than the customer paid",
            f"Worst: Rs {charge:.2f} charged for a trip the customer paid Rs {paid:.2f} for. "
            "Pidge chose the rider network; ask them to prefer a cheaper one.",
            len(trips), rid, name(rid), link="/orders",
        ))

    failed_payments = db.execute(
        select(Order.restaurant_id, func.count(PaymentTransaction.id))
        .join(Order, Order.id == PaymentTransaction.order_id)
        .where(PaymentTransaction.status == PaymentStatus.FAILED, PaymentTransaction.created_at > now - timedelta(hours=24))
        .group_by(Order.restaurant_id)
    ).all()
    for rid, count in failed_payments:
        issues.append(Issue(
            "payments_failed", MEDIUM, f"{count} payment(s) failed in the last 24 hours",
            "A few are normal - a declined card. Many in a row usually means the gateway account needs attention.",
            int(count), rid, name(rid), link=f"/admin/restaurants/{rid}/payments",
        ))

    for restaurant in restaurants.values():
        if not restaurant.is_approved and restaurant.is_active:
            issues.append(Issue(
                "restaurant_pending", MEDIUM, "Waiting for approval",
                "Not visible to customers until approved.",
                1, restaurant.id, restaurant.name, link="/restaurants",
            ))

    suspended = db.execute(
        select(AppClient.restaurant_id).where(AppClient.status == AppClientStatus.SUSPENDED, AppClient.restaurant_id.is_not(None))
    ).scalars().all()
    for rid in suspended:
        issues.append(Issue(
            "storefront_suspended", LOW, "Storefront suspended",
            "Its app and site are not taking orders. Expected only if it was suspended on purpose.",
            1, rid, name(rid), link="/tenants",
        ))

    on_sale = dict(
        db.execute(
            select(MenuItem.restaurant_location_id, func.count(MenuItem.id))
            .where(MenuItem.is_on_sale)
            .group_by(MenuItem.restaurant_location_id)
        ).all()
    )
    for restaurant in restaurants.values():
        if not (restaurant.is_approved and restaurant.is_active):
            continue
        for location in restaurant.locations:
            if not location.is_active:
                continue
            where = f"/admin/restaurants/{restaurant.id}/locations/{location.id}"
            branch = location.branch_name
            if not on_sale.get(location.id):
                issues.append(Issue(
                    "branch_empty_menu", HIGH, f"{branch}: nothing customers can order",
                    "Every dish is hidden or out of stock, so the menu reads as empty.",
                    1, restaurant.id, restaurant.name, location.id, link=where,
                ))
            try:
                methods = available_payment_methods(db, restaurant_id=restaurant.id, location=location)
            except Exception:  # noqa: BLE001 - one branch must not sink the page
                logger.exception("Could not read payment methods for location %s", location.id)
                methods = None
            if methods == []:
                issues.append(Issue(
                    "branch_no_payment", HIGH, f"{branch}: no way to pay",
                    "No payment method is both switched on and backed by a working gateway, so checkout cannot finish.",
                    1, restaurant.id, restaurant.name, location.id, link=f"/admin/restaurants/{restaurant.id}/payments",
                ))
            if location.delivery_enabled and (location.latitude is None or location.longitude is None):
                issues.append(Issue(
                    "branch_not_on_map", MEDIUM, f"{branch}: not pinned on the map",
                    "Delivery cannot be priced by distance and falls back to the flat fee.",
                    1, restaurant.id, restaurant.name, location.id, link=where,
                ))
            if location.delivery_enabled and Decimal(str(location.delivery_fee or 0)) <= 0:
                issues.append(Issue(
                    "branch_no_delivery_fee", MEDIUM if settings.enable_delivery_quotes else HIGH,
                    f"{branch}: no flat delivery fee",
                    "Delivery orders are refused whenever the courier cannot price the trip."
                    if settings.enable_delivery_quotes
                    else "Courier quotes are off, so every delivery order is refused.",
                    1, restaurant.id, restaurant.name, location.id, link=where,
                ))
            if Decimal(str(location.commission_percent or 0)) <= 0:
                issues.append(Issue(
                    "branch_no_commission", LOW, f"{branch}: 0% commission",
                    "The platform earns nothing on this branch's orders. Fine if agreed.",
                    1, restaurant.id, restaurant.name, location.id, link=where,
                ))

    out = db.execute(
        select(MenuItem.restaurant_id, func.count(MenuItem.id))
        .where(MenuItem.is_available.is_(True), or_(MenuItem.out_of_stock.is_(True), MenuItem.stock_quantity == 0))
        .group_by(MenuItem.restaurant_id)
    ).all()
    for rid, count in out:
        issues.append(Issue(
            "dishes_out_of_stock", LOW, f"{count} dish(es) out of stock",
            "Shown to customers as out of stock. Restock or mark them back in.",
            int(count), rid, name(rid), link="/menu-items",
        ))

    issues = [issue for issue in issues if issue.restaurant_id not in demo]
    issues.sort(key=lambda issue: (_SEVERITY_ORDER[issue.severity], -issue.count, issue.restaurant_name or ""))
    return issues


# --- today, per restaurant ----------------------------------------------------


def restaurants_today(db: Session, *, now: datetime, issues: list[Issue]) -> list[RestaurantToday]:
    zone = get_settings().business_timezone_info
    midnight = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)

    sales = {
        rid: (int(count), Decimal(str(total or 0)))
        for rid, count, total in db.execute(
            select(Order.restaurant_id, func.count(Order.id), func.sum(Order.total_amount))
            .where(Order.placed_at >= midnight, Order.status.not_in(_NOT_A_SALE))
            .group_by(Order.restaurant_id)
        ).all()
    }
    awaiting = dict(
        db.execute(
            select(Order.restaurant_id, func.count(Order.id))
            .where(Order.status == OrderStatus.PLACED, Order.payment_status.in_(_SETTLED))
            .group_by(Order.restaurant_id)
        ).all()
    )
    out_of_stock = dict(
        db.execute(
            select(MenuItem.restaurant_id, func.count(MenuItem.id))
            .where(MenuItem.is_available.is_(True), or_(MenuItem.out_of_stock.is_(True), MenuItem.stock_quantity == 0))
            .group_by(MenuItem.restaurant_id)
        ).all()
    )
    storefronts = dict(
        db.execute(select(AppClient.restaurant_id, AppClient.status).where(AppClient.restaurant_id.is_not(None))).all()
    )
    issue_count: dict[uuid.UUID, int] = {}
    for issue in issues:
        if issue.restaurant_id is not None and issue.severity != LOW:
            issue_count[issue.restaurant_id] = issue_count.get(issue.restaurant_id, 0) + 1

    rows = []
    for restaurant in db.scalars(
        select(Restaurant).where(Restaurant.is_demo.is_(False)).options(selectinload(Restaurant.locations))
    ):
        active = [location for location in restaurant.locations if location.is_active]
        count, total = sales.get(restaurant.id, (0, Decimal("0")))
        status = storefronts.get(restaurant.id)
        rows.append(RestaurantToday(
            restaurant_id=restaurant.id,
            name=restaurant.name,
            city=restaurant.city or "",
            approved=bool(restaurant.is_approved),
            storefront=str(status) if status is not None else None,
            branches=len(active),
            branches_open=sum(1 for location in active if location.is_open),
            orders_today=count,
            sales_today=total.quantize(Decimal("0.01")),
            awaiting_accept=int(awaiting.get(restaurant.id, 0)),
            out_of_stock=int(out_of_stock.get(restaurant.id, 0)),
            issues=issue_count.get(restaurant.id, 0),
        ))
    # Something wrong first, then the busiest.
    rows.sort(key=lambda row: (-row.issues, -row.awaiting_accept, -row.orders_today, row.name.lower()))
    return rows


def build(db: Session) -> PlatformWatch:
    now = datetime.now(UTC)
    # The machinery is asked first and answers in the background while the
    # database questions are asked here, so the page waits for the slower of
    # the two rather than for both one after the other.
    deadline = time.monotonic() + CHECKS_BUDGET_SECONDS
    pool, futures = _start_checks(now)
    database = _check_database(db)
    issues = find_issues(db, now=now)
    restaurants = restaurants_today(db, now=now, issues=issues)
    return PlatformWatch(
        generated_at=now,
        checks=[database, *_collect_checks(pool, futures, deadline=deadline)],
        issues=issues,
        restaurants=restaurants,
    )


__all__ = [
    "Check", "HEARTBEAT_KEY", "Issue", "PlatformWatch", "RestaurantToday",
    "build", "find_issues", "restaurants_today", "system_checks",
]
