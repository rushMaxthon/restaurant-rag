"""Which Socket.IO room a socket sits in, and which rooms an order event reaches.

The rooms ARE the scope. A socket joins exactly one staff room, chosen from the
`OrderBoardScope` that `resolve_order_board_scope` returned for it, and an order
event is emitted to every room that could legitimately contain a viewer of that
order. Nothing filters per message after that — so the question "may this socket
hear about this order" is answered once, by the same function that answers it
for `GET /orders`, and never re-derived here.

Pure on purpose: every rule in this file is testable without a server, a
database or a Redis.
"""

from __future__ import annotations

import uuid

from app.models.enums import UserRole
from app.services.auth import OrderBoardScope

# Platform staff watching the unnarrowed board. Every order event reaches it,
# which is what an ADMIN's `GET /orders` without a restaurant returns too.
ADMIN_ALL_ROOM = "admin:all"


def restaurant_room(restaurant_id: uuid.UUID) -> str:
    return f"restaurant:{restaurant_id}"


def location_room(restaurant_location_id: uuid.UUID) -> str:
    return f"location:{restaurant_location_id}"


def user_room(user_id: uuid.UUID) -> str:
    """One account's private room.

    Every socket joins it, staff included, because it is also where
    `session:revoked` is announced. Only a CUSTOMER receives order events
    through it — as the customer of that order.
    """

    return f"user:{user_id}"


def staff_room(scope: OrderBoardScope) -> str:
    """The single room a staff socket watches, from its resolved scope.

    Narrowest first. A branch-pinned scope must NOT also sit in the restaurant
    room, or a cook pinned to one branch would hear every branch's orders —
    exactly what the pin exists to prevent.
    """

    if scope.restaurant_location_id is not None:
        return location_room(scope.restaurant_location_id)
    if scope.restaurant_id is not None:
        return restaurant_room(scope.restaurant_id)
    # Reachable only by an ADMIN who named no restaurant; see `OrderBoardScope`.
    return ADMIN_ALL_ROOM


def is_staff_role(role: UserRole) -> bool:
    return role in (UserRole.ADMIN, UserRole.OWNER, UserRole.KITCHEN)


def order_event_rooms(
    *,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID,
    customer_id: uuid.UUID | None,
) -> list[str]:
    """Every room with a legitimate viewer of this order.

    A socket is in one staff room at most, and the manager de-duplicates across
    a list of rooms anyway, so nobody hears the same event twice.
    """

    rooms = [
        location_room(restaurant_location_id),
        restaurant_room(restaurant_id),
        ADMIN_ALL_ROOM,
    ]
    if customer_id is not None:
        rooms.append(user_room(customer_id))
    return rooms
