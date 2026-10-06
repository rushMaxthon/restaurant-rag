"""The live orders board: everything in flight, and what went out today.

One request for the screen an operator keeps open — the platform's admin
across every restaurant, an owner across their own. It answers four questions
at a glance: what is waiting to be accepted, what is in the kitchen, what is
on the road, and what is already done.

**This is `list_orders`, asked once per stage.** Not a query of its own. Who
may see which restaurant and which branch is decided in exactly one place for
the Orders page, the kitchen board and an order's own page; a board with its
own WHERE clause would be a fourth copy of that rule, and the first one to
fall out of step would be showing somebody a restaurant that is not theirs.
Five small queries cost less than that risk.

**PAYMENT_PENDING and CANCELLED are not stages.** An unpaid checkout is not an
order yet — most of them are abandoned — and a cancelled one is nothing left
to do. Neither is work, and the board is a list of work.

**Open orders have no date window; done orders do.** An order placed at 23:50
and still in the kitchen at 00:10 is still open, so the four open stages are
"whatever is in this status". Delivered is "since the instant the caller
names": the operator's own midnight, which the server cannot know.

**Open stages are sent NEWEST first, and the old ones are counted apart.**
The first version sent the oldest hundred, on the reasoning that the order
that has waited longest is the one to look at. Then it met a real database:
213 orders sitting at PLACED, 208 of them weeks old and never going to be
accepted. Oldest-first with a cap of a hundred meant tonight's new order was
not on the board at all — it was behind a hundred that nobody will ever cook.
So the cap now keeps the newest, the screen puts them oldest-first among
themselves, and anything that has been waiting longer than `STALE_AFTER` is
counted separately (`stale_total`) so the headline number is tonight's work
and the backlog is a number beside it rather than the whole column.

**The courier is read once for the whole board**, by order id, and attached
to its card here. The alternative is a card per order calling
`/orders/{id}/delivery`, which on a board that refetches whenever any order
moves is the difference between one request and forty.

**Who has what is counted by the database.** The cards are capped at
`STAGE_LIMIT` a stage; a per-restaurant figure added up from them is wrong
the moment a stage is cut short, and it is the admin with the most orders
who would be shown the wrong number.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import OrderStatus
from app.models.order_delivery import OrderDelivery
from app.models.user import User
from app.schemas.order import (
    LiveOrderResponse,
    LiveOrdersResponse,
    LiveOrdersStage,
    LiveRestaurantLoad,
    OrderDeliveryResponse,
    OrderResponse,
)
from app.services.orders import count_live_orders_by_restaurant, list_orders

#: The stages, in the order food moves through them.
OPEN_STATUSES: tuple[OrderStatus, ...] = (
    OrderStatus.PLACED,
    OrderStatus.ACCEPTED,
    OrderStatus.PREPARING,
    OrderStatus.OUT_FOR_DELIVERY,
)

#: How many cards one stage carries. A stage's `total` is its real count, so a
#: column that is cut short says so rather than looking complete. 100 is more
#: than a person reads in a column and well inside `list_orders`' own cap.
STAGE_LIMIT = 100

#: How long an open order may wait before it stops being tonight's work and
#: becomes backlog. A day: nothing a kitchen is going to cook has been waiting
#: since yesterday. The screen is told this figure rather than keeping its own
#: copy, so the count here and the cards there cannot split on different lines.
STALE_AFTER = timedelta(hours=24)


def _as_card(order: OrderResponse, delivery: OrderDelivery | None, viewer: User) -> LiveOrderResponse:
    return LiveOrderResponse(
        **order.model_dump(),
        delivery=(
            OrderDeliveryResponse.model_validate(delivery).for_viewer(viewer)
            if delivery is not None
            else None
        ),
    )


def build_live_board(
    db: Session,
    current_user: User,
    *,
    owner_restaurant_id: uuid.UUID | None,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None,
    app_scope_restaurant_id: uuid.UUID | None,
    completed_from: datetime,
) -> LiveOrdersResponse:
    """Every open order in scope, and the ones delivered since `completed_from`.

    The scope arguments are passed straight through to `list_orders`; the
    caller resolves them with `resolve_order_board_scope`, as `GET /orders`
    does.
    """

    now = datetime.now(timezone.utc)

    def stage(status: OrderStatus, *, sort: str, since: datetime | None) -> tuple[list, int]:
        return list_orders(
            db,
            current_user,
            owner_restaurant_id=owner_restaurant_id,
            restaurant_id=restaurant_id,
            restaurant_location_id=restaurant_location_id,
            app_scope_restaurant_id=app_scope_restaurant_id,
            status_filter=status,
            completed_from=since,
            sort=sort,
            limit=STAGE_LIMIT,
            offset=0,
        )

    fetched: list[tuple[OrderStatus, list, int]] = []
    for status in OPEN_STATUSES:
        rows, total = stage(status, sort="placed_at:desc", since=None)
        fetched.append((status, rows, total))
    rows, total = stage(OrderStatus.DELIVERED, sort="completed_at:desc", since=completed_from)
    fetched.append((OrderStatus.DELIVERED, rows, total))

    order_ids = [order.id for _status, rows, _total in fetched for order in rows]
    deliveries: dict[uuid.UUID, OrderDelivery] = {}
    if order_ids:
        deliveries = {
            delivery.order_id: delivery
            for delivery in db.scalars(
                select(OrderDelivery).where(OrderDelivery.order_id.in_(order_ids))
            ).all()
        }

    loads: dict[uuid.UUID, LiveRestaurantLoad] = {}
    stale_by_status: dict[OrderStatus, int] = {}
    # Deliberately NOT narrowed to the restaurant an admin picked. This strip
    # is how they pick one, so it has to keep listing the ones they did not —
    # narrowed, choosing a restaurant would empty the list it was chosen from.
    # An owner or a kitchen account is still held to its own restaurant by
    # `owner_restaurant_id`, which is not a request parameter.
    for rest_id, name, city, status, count, stale in count_live_orders_by_restaurant(
        db,
        current_user,
        owner_restaurant_id=owner_restaurant_id,
        restaurant_id=None,
        restaurant_location_id=restaurant_location_id,
        app_scope_restaurant_id=app_scope_restaurant_id,
        open_statuses=OPEN_STATUSES,
        completed_from=completed_from,
        stale_before=now - STALE_AFTER,
    ):
        # A delivered order is finished, however long it took.
        stale = 0 if status == OrderStatus.DELIVERED else stale
        load = loads.get(rest_id)
        if load is None:
            load = loads[rest_id] = LiveRestaurantLoad(
                restaurant_id=rest_id, name=name, city=city, counts={}, stale={}
            )
        load.counts[status] = count
        if stale:
            load.stale[status] = stale
        # The columns ARE narrowed to the picked restaurant, so their backlog
        # figure is that restaurant's alone.
        if restaurant_id is None or rest_id == restaurant_id:
            stale_by_status[status] = stale_by_status.get(status, 0) + stale

    return LiveOrdersResponse(
        generated_at=now,
        completed_from=completed_from,
        stage_limit=STAGE_LIMIT,
        stale_after_minutes=int(STALE_AFTER.total_seconds() // 60),
        restaurants=list(loads.values()),
        stages=[
            LiveOrdersStage(
                status=status,
                total=total,
                stale_total=min(stale_by_status.get(status, 0), total),
                orders=[_as_card(order, deliveries.get(order.id), current_user) for order in rows],
            )
            for status, rows, total in fetched
        ],
    )


__all__ = ["OPEN_STATUSES", "STAGE_LIMIT", "STALE_AFTER", "build_live_board"]
