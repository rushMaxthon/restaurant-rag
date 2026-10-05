"""How many of a dish are left to sell.

A dish had one switch, available or not, and somebody had to flip it at the
moment the tray emptied. Nobody does, at seven on a Saturday, so the customer
after the last loaf ordered one, paid, and was rung by the shop.

`menu_items.stock_quantity` is the count. **NULL means nobody is counting**,
and nothing in this module applies: that is every dish that existed before the
column did, so the feature changes no menu until an owner types a number.

**Stock is taken when the order is created, not when it is paid.** A card
order sits in PAYMENT_PENDING while the customer is at the gateway. Taking
stock only at payment would let two people pay for the last loaf, and the fix
for that is a refund and an apology. Taken at creation, the second customer is
told before they reach for a card. The price of that choice is that an
abandoned checkout holds stock until the unpaid-order reaper cancels it — a
few minutes — and `release` is what gives it back.

**The check is not what protects the last one. The write is.** Two checkouts
can both read "1 left" and both pass `ensure_in_stock`. `reserve` is one
UPDATE that succeeds only while enough remains, so the database decides who
was first, and the loser's statement changes no row. `ensure_in_stock` exists
so a cart can be told early and in words; it is a courtesy, and deleting it
would cost a worse message, not an oversold loaf.

**One counter per dish.** A dish sold as "Pack of 4" and "Pack of 8" shares
one count, and each pack takes one from it whatever its size. Counting per
size is a real thing a bakery may want and is not done here; a dish whose
sizes genuinely draw down different trays is better listed as two dishes
until it is.

**What an order took is written on the order.** `order_items.stock_reserved`
says this line subtracted from the count. Without it a cancellation cannot
tell an order that took four loaves from one placed last week, before the
owner started counting — and would hand back four that were never taken.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.menu_item import MenuItem


def wanted_by_dish(lines: Iterable[Any]) -> dict[uuid.UUID, int]:
    """Quantities added up per dish, across every line of one cart.

    Two lines of one dish — two sizes, or the same dish with and without an
    extra — are one demand on one counter. Checked a line at a time, three and
    three both fit into five.
    """

    wanted: dict[uuid.UUID, int] = {}
    for line in lines:
        wanted[line.menu_item_id] = wanted.get(line.menu_item_id, 0) + int(line.quantity)
    return wanted


def _refusal(name: str, left: int) -> str:
    # "Only 0 left" is arithmetic. "Sold out" is what a person says.
    if left <= 0:
        return f"{name} is sold out."
    return f"Only {left} {name} left."


def _refuse(problems: list[str]) -> HTTPException:
    return HTTPException(
        # 409, not 400: nothing is wrong with the request. It was right a
        # minute ago, and somebody else got there first.
        status_code=status.HTTP_409_CONFLICT,
        detail=" ".join(problems) + " Please update your cart.",
    )


def ensure_in_stock(menu_items: Mapping[uuid.UUID, Any], lines: Iterable[Any]) -> None:
    """Refuse a cart that asks for more than is left, naming every short dish.

    Every one, not the first: a customer told about the bread fixes the bread,
    tries again and is told about the pav.
    """

    problems = []
    for dish_id, quantity in wanted_by_dish(lines).items():
        dish = menu_items.get(dish_id)
        left = getattr(dish, "stock_quantity", None)
        if dish is None or left is None:
            continue
        if quantity > left:
            problems.append(_refusal(dish.name, left))
    if problems:
        raise _refuse(problems)


def reserve(db: Session, lines: Iterable[Any]) -> None:
    """Take this order's stock, or refuse the order.

    Raises before anything is committed, so the caller's transaction — the
    order row included — goes with it. A cart of three dishes where the third
    is short leaves the first two exactly as they were.
    """

    lines = list(lines)
    taken: set[uuid.UUID] = set()
    problems: list[str] = []
    for dish_id, quantity in wanted_by_dish(lines).items():
        result = db.execute(
            update(MenuItem)
            .where(
                MenuItem.id == dish_id,
                MenuItem.stock_quantity.is_not(None),
                MenuItem.stock_quantity >= quantity,
            )
            .values(stock_quantity=MenuItem.stock_quantity - quantity)
            # The session may hold this row from the draft it built a moment
            # ago; without this it would go on reading the old count.
            .execution_options(synchronize_session=False)
        )
        if result.rowcount:
            taken.add(dish_id)
            continue
        # No row changed. Either nobody is counting this dish, which is fine,
        # or there was not enough — and only a fresh read can say which.
        name, left = db.execute(
            select(MenuItem.name, MenuItem.stock_quantity).where(MenuItem.id == dish_id)
        ).one_or_none() or (None, None)
        if left is not None:
            problems.append(_refusal(name, left))

    if problems:
        raise _refuse(problems)
    for line in lines:
        line.stock_reserved = line.menu_item_id in taken


def release(db: Session, lines: Iterable[Any]) -> None:
    """Give back what a cancelled order took. Safe to call twice.

    Only lines marked as having taken stock, and each is unmarked as it is
    returned — a cancellation delivered twice, by a retried webhook, gives
    four loaves back and not eight. Nothing goes back to a dish the owner has
    since stopped counting: there is no count to add to.
    """

    lines = [line for line in lines if getattr(line, "stock_reserved", False)]
    for dish_id, quantity in wanted_by_dish(lines).items():
        db.execute(
            update(MenuItem)
            .where(MenuItem.id == dish_id, MenuItem.stock_quantity.is_not(None))
            .values(stock_quantity=MenuItem.stock_quantity + quantity)
            .execution_options(synchronize_session=False)
        )
    for line in lines:
        line.stock_reserved = False


__all__ = ["ensure_in_stock", "release", "reserve", "wanted_by_dish"]
