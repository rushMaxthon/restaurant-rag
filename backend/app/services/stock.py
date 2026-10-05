"""How many of a dish are left to sell, and whether it can be sold at all.

A dish had one switch, available or not, and it meant "on the menu". Nothing
said "on the menu, but none left" - so the customer after the last loaf
ordered one, paid, and was rung by the shop.

There are now three things an owner can say, and they are different facts:

* **Hidden** (`is_available` false). Not on the menu. Nobody sees it.
* **Out of stock, by hand** (`out_of_stock` true). On the menu, marked out of
  stock, cannot be added. The oven broke; nobody is counting anything.
* **Counted** (`stock_quantity` a number). On the menu with that many left; at
  zero it is out of stock by itself. NULL means nobody is counting, which is
  every dish that existed before the column did.

**A size can have a count of its own.** A "Pack of 4" and a "Pack of 8" may
come off different trays. Where a size carries a number, a line for that size
draws on the size's count and leaves the dish's alone. Where it does not, the
line draws on the dish's count, one per unit whatever the size - which is what
every sized dish did before sizes could be counted, so nothing changes until
an owner types a number against a size.

**Stock is taken when the order is created, not when it is paid.** A card
order sits in PAYMENT_PENDING while the customer is at the gateway. Taking
stock only at payment would let two people pay for the last loaf, and the fix
for that is a refund and an apology. The price of that choice is that an
abandoned checkout holds stock until the unpaid-order reaper cancels it - a
few minutes - and `release` is what gives it back.

**The check is not what protects the last one. The write is.** Two checkouts
can both read "1 left" and both pass `ensure_in_stock`. `reserve` is one
UPDATE per counter that succeeds only while enough remains, so the database
decides who was first. `ensure_in_stock` exists so a cart can be told early
and in words.

**What an order took is written on the order.** `order_items.stock_reserved`
says the line subtracted from a count, and `stock_reserved_size` says it was
the size's count rather than the dish's. Without the first, a cancellation
would hand back loaves an older order never took; without the second, it
could put them on the wrong shelf after an owner starts or stops counting a
size.

**A daily amount is a refill, not a ceiling.** `stock_daily_quantity` is what
the shop bakes each morning. `restock_daily` sets the count back to it once a
day. It never touches a count with no daily amount, and it never clears a
manual "out of stock" - a person said that, and a person takes it back.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.menu_item import MenuItem
from app.models.menu_item_size import MenuItemSize

#: ("size", id) or ("dish", id): which count a cart line draws on.
Counter = tuple[str, uuid.UUID]


def wanted_by_dish(lines: Iterable[Any]) -> dict[uuid.UUID, int]:
    """Quantities added up per dish, across every line of one cart."""

    wanted: dict[uuid.UUID, int] = {}
    for line in lines:
        wanted[line.menu_item_id] = wanted.get(line.menu_item_id, 0) + int(line.quantity)
    return wanted


def _refusal(name: str, left: int) -> str:
    # "Only 0 left" is arithmetic. "Out of stock" is what a person says.
    if left <= 0:
        return f"{name} is out of stock."
    return f"Only {left} {name} left."


def _refuse(problems: list[str]) -> HTTPException:
    return HTTPException(
        # 409, not 400: nothing is wrong with the request. It was right a
        # minute ago, and somebody else got there first.
        status_code=status.HTTP_409_CONFLICT,
        detail=" ".join(dict.fromkeys(problems)) + " Please update your cart.",
    )


def _size_of(dish: Any, size_id: uuid.UUID | None) -> Any | None:
    if size_id is None:
        return None
    for size in getattr(dish, "sizes", None) or ():
        if size.id == size_id:
            return size
    return None


def ensure_in_stock(menu_items: Mapping[uuid.UUID, Any], lines: Iterable[Any]) -> None:
    """Refuse a cart that asks for more than is left, naming every short dish.

    Every one, not the first: a customer told about the bread fixes the bread,
    tries again and is told about the pav.

    Lines are added up per COUNT, not per line: two lines of one dish draw on
    one number, and checked a line at a time three and three both fit into
    five.
    """

    wanted: dict[Counter, int] = {}
    counts: dict[Counter, tuple[str, int]] = {}
    problems: list[str] = []
    for line in lines:
        dish = menu_items.get(line.menu_item_id)
        if dish is None:
            continue
        if getattr(dish, "out_of_stock", False) is True:
            problems.append(_refusal(dish.name, 0))
            continue
        size = _size_of(dish, getattr(line, "menu_item_size_id", None))
        size_left = getattr(size, "stock_quantity", None) if size is not None else None
        dish_left = getattr(dish, "stock_quantity", None)
        if size_left is not None:
            key: Counter = ("size", size.id)
            counts[key] = (f"{dish.name} ({size.name})", size_left)
        elif dish_left is not None:
            key = ("dish", dish.id)
            counts[key] = (dish.name, dish_left)
        else:
            continue
        wanted[key] = wanted.get(key, 0) + int(line.quantity)

    for key, quantity in wanted.items():
        name, left = counts[key]
        if quantity > left:
            problems.append(_refusal(name, left))
    if problems:
        raise _refuse(problems)


def reserve(db: Session, lines: Iterable[Any]) -> None:
    """Take this order's stock, or refuse the order.

    Raises before anything is committed, so the caller's transaction - the
    order row included - goes with it. A cart of three dishes where the third
    is short leaves the first two exactly as they were.
    """

    lines = list(lines)
    if not lines:
        return
    dish_ids = {line.menu_item_id for line in lines}
    size_ids = {
        line.menu_item_size_id for line in lines if getattr(line, "menu_item_size_id", None)
    }

    # Read first, to learn which count each line draws on. This read decides
    # nothing about who gets the last one - the guarded UPDATEs below do.
    dishes = {
        row.id: row
        for row in db.execute(
            select(
                MenuItem.id, MenuItem.name, MenuItem.stock_quantity, MenuItem.out_of_stock
            ).where(MenuItem.id.in_(dish_ids))
        )
    }
    sizes = (
        {
            row.id: row
            for row in db.execute(
                select(MenuItemSize.id, MenuItemSize.name, MenuItemSize.stock_quantity).where(
                    MenuItemSize.id.in_(size_ids)
                )
            )
        }
        if size_ids
        else {}
    )

    problems: list[str] = []
    wanted: dict[Counter, int] = {}
    draws_on: list[Counter | None] = []
    for line in lines:
        dish = dishes.get(line.menu_item_id)
        size = sizes.get(getattr(line, "menu_item_size_id", None))
        key: Counter | None = None
        if dish is not None and dish.out_of_stock:
            problems.append(_refusal(dish.name, 0))
        elif size is not None and size.stock_quantity is not None:
            key = ("size", size.id)
        elif dish is not None and dish.stock_quantity is not None:
            key = ("dish", dish.id)
        draws_on.append(key)
        if key is not None:
            wanted[key] = wanted.get(key, 0) + int(line.quantity)

    for (kind, counter_id), quantity in wanted.items():
        model = MenuItemSize if kind == "size" else MenuItem
        taken = db.execute(
            update(model)
            .where(
                model.id == counter_id,
                model.stock_quantity.is_not(None),
                model.stock_quantity >= quantity,
            )
            .values(stock_quantity=model.stock_quantity - quantity)
            # The session may hold this row from the draft it built a moment
            # ago; without this it would go on reading the old count.
            .execution_options(synchronize_session=False)
        ).rowcount
        if taken:
            continue
        # No row changed: not enough left, or the owner stopped counting this
        # in the instant since the read. Only a fresh read can say which.
        left = db.scalar(select(model.stock_quantity).where(model.id == counter_id))
        if left is None:
            draws_on[:] = [None if key == (kind, counter_id) else key for key in draws_on]
            continue
        if kind == "size":
            size = sizes[counter_id]
            dish_name = next(
                (
                    dishes[line.menu_item_id].name
                    for line in lines
                    if getattr(line, "menu_item_size_id", None) == counter_id
                    and line.menu_item_id in dishes
                ),
                "",
            )
            problems.append(_refusal(f"{dish_name} ({size.name})".strip(), left))
        else:
            problems.append(_refusal(dishes[counter_id].name, left))

    if problems:
        raise _refuse(problems)
    for line, key in zip(lines, draws_on):
        line.stock_reserved = key is not None
        line.stock_reserved_size = key is not None and key[0] == "size"


def release(db: Session, lines: Iterable[Any]) -> None:
    """Give back what a cancelled order took. Safe to call twice.

    Only lines marked as having taken stock, each back to the count it came
    from, and each unmarked as it is returned - a cancellation delivered
    twice gives four loaves back and not eight. Nothing goes back to a count
    the owner has since stopped keeping: there is no number to add to.
    """

    lines = [line for line in lines if getattr(line, "stock_reserved", False)]
    back: dict[Counter, int] = {}
    for line in lines:
        from_size = getattr(line, "stock_reserved_size", False) and getattr(
            line, "menu_item_size_id", None
        )
        key: Counter = ("size", line.menu_item_size_id) if from_size else ("dish", line.menu_item_id)
        back[key] = back.get(key, 0) + int(line.quantity)

    for (kind, counter_id), quantity in back.items():
        model = MenuItemSize if kind == "size" else MenuItem
        db.execute(
            update(model)
            .where(model.id == counter_id, model.stock_quantity.is_not(None))
            .values(stock_quantity=model.stock_quantity + quantity)
            .execution_options(synchronize_session=False)
        )
    for line in lines:
        line.stock_reserved = False
        line.stock_reserved_size = False


def restock_daily(db: Session) -> int:
    """Set every count that has a daily amount back to it. Returns how many.

    The morning's bake. A dish with no daily amount is left exactly as it is -
    the owner restocks that one by hand - and a manual "out of stock" is not
    cleared: a person said it, and a person takes it back.

    Set TO the daily amount, never added to what is left. Yesterday's unsold
    loaves are not on today's shelf.
    """

    changed = 0
    for model in (MenuItem, MenuItemSize):
        changed += db.execute(
            update(model)
            .where(model.stock_daily_quantity.is_not(None))
            .values(stock_quantity=model.stock_daily_quantity)
            .execution_options(synchronize_session=False)
        ).rowcount
    return changed


__all__ = ["ensure_in_stock", "release", "reserve", "restock_daily", "wanted_by_dish"]
