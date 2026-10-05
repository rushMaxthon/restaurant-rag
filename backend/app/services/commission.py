"""What the platform earned on an order, written down when the order is made.

The commission is inside the menu price (`services/menu_pricing.py`): the
owner types 100, the customer pays 110, and ten of that is the platform's. Until
this existed nothing recorded the ten. It could be worked out afterwards from
the branch's rate - but the rate is a dial the admin turns, so "afterwards" is
a different rate, and an October order would be re-costed at November's terms.

So the order carries its own answer: the rate that applied when it was placed,
and the amount that rate put inside its subtotal. A later change of rate
changes later orders.

**Worked back out of the subtotal, not added up dish by dish.** The subtotal is
what was charged, to the paisa. Each listed price was rounded when it was
written, so the exact commission on three items is not three times one item's
- but the difference is fractions of a paisa per line, and deriving it from the
figure actually charged keeps "sales" and "commission" on one report adding up
to something a person can check with a calculator.

**NULL is "not recorded", and is not zero.** Every order placed before this
column existed has no figure. They are left out of the report rather than
counted as earning nothing, and the report says from when it counts.

**On the food, before any discount.** A discount is the restaurant's or the
platform's promotion; whose pocket it comes from is a commercial question this
does not settle. The commission recorded is what the prices carried.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.restaurant import Restaurant

_PAISA = Decimal("0.01")

#: An order that earned nothing: never paid for, or called off.
NOT_EARNED = (OrderStatus.CANCELLED, OrderStatus.PAYMENT_PENDING)


def commission_in(subtotal: Decimal | int | float | None, percent: Decimal | int | float | None) -> Decimal:
    """The part of a commission-inclusive subtotal that is the commission.

    110.00 at 10% is 10.00, not 11.00: the rate was applied to the typed
    price, so it is taken back out of the listed one, not charged on it again.
    """

    amount = Decimal(str(subtotal or 0))
    rate = Decimal(str(percent or 0))
    if amount <= 0 or rate <= 0:
        return Decimal("0.00")
    typed = amount * Decimal("100") / (Decimal("100") + rate)
    return (amount - typed).quantize(_PAISA, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class RestaurantCommission:
    restaurant_id: uuid.UUID
    restaurant_name: str
    orders: int
    sales: Decimal
    commission: Decimal


def summarise(db: Session, *, since: datetime) -> list[RestaurantCommission]:
    """Per restaurant, since a moment: orders, what they sold, what it earned.

    Only orders that carry a recorded commission and were neither cancelled
    nor left unpaid. Largest earner first.
    """

    earned = func.coalesce(func.sum(Order.commission_amount), 0)
    rows = db.execute(
        select(
            Restaurant.id,
            Restaurant.name,
            func.count(Order.id),
            func.coalesce(func.sum(Order.subtotal), 0),
            earned,
        )
        .join(Order, Order.restaurant_id == Restaurant.id)
        .where(
            Order.placed_at >= since,
            Order.commission_amount.is_not(None),
            Order.status.not_in(NOT_EARNED),
        )
        .group_by(Restaurant.id, Restaurant.name)
        .order_by(earned.desc(), Restaurant.name.asc())
    ).all()
    return [
        RestaurantCommission(
            restaurant_id=row[0],
            restaurant_name=row[1],
            orders=int(row[2]),
            sales=Decimal(str(row[3])).quantize(_PAISA),
            commission=Decimal(str(row[4])).quantize(_PAISA),
        )
        for row in rows
    ]


def first_recorded_at(db: Session) -> datetime | None:
    """When the earliest counted order was placed, so the report can say so."""

    return db.scalar(select(func.min(Order.placed_at)).where(Order.commission_amount.is_not(None)))


__all__ = ["NOT_EARNED", "RestaurantCommission", "commission_in", "first_recorded_at", "summarise"]
