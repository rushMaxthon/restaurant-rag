"""The platform's commission inside the menu price, per branch.

The owner types what THEY want for a dish; the customer is shown that plus
the platform's commission. Typed 100 at 10% is 110 on the menu, in the cart
and on the order. `restaurant_locations.commission_percent` is the rate: 10 by
default, set per branch by the platform's admin, and 0 means the menu is
exactly what was typed.

This module existed once before, deleted in `0076`, as "add 18% GST to the
menu". That was the wrong reading of the GST switch and is still wrong — the
switch only moves the tax line on the bill (`test_gst_menu_prices`). The
mechanism was sound and is what is back here, with a rate somebody chose
instead of a tax nobody asked to be added.

**The price is written, not worked out on the way past.** The obvious way to
build this is to multiply wherever a price is shown. A price is read in about
ninety places here — the menu, the cart, the order, favourites,
recommendations, combos, offers, the chat prompt, the WhatsApp agent, the
embedding text — and in three clients that each add up a cart themselves. Miss
one and a customer is shown one figure and charged another, which is the exact
failure the half-and-half rules exist to prevent.

So `price` stays what it has always been: what the customer pays. The figure
the owner typed is kept beside it in `base_price` (`base_extra_price` on an
option), and `price` is rewritten from it in the only two places that can
change the answer — an item being saved, and the branch's rate being changed.
Nothing that reads a price needs to know this module exists.

**Rounded once, at the listed price.** 10% of 99 is 9.90; of 49.95 it is
4.995. Each listed price is rounded to the paisa here and every later sum —
quantity, half of an extra, a discount — runs on that rounded figure, in the
same order the clients do it. Rounding at the end instead would let a cart of
three differ from three times the price on the menu.

**The typed figure is kept, never divided back out.** 108.90 / 1.10 lands on
99.00; 54.95 / 1.10 does not land on 49.95. Changing the rate from 10 to 12
has to start from what was typed, so it is stored.

**`base_price` NULL means "what is in `price` is what was typed".** That is
the state of anything a seed script inserts. A row with no base is never
marked up twice, because the first relist records its base.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

#: What a branch is created at, and what a branch row from before the column
#: is read as. One figure, here, so the model default, the schema default and
#: the migration cannot drift apart.
DEFAULT_COMMISSION_PERCENT = Decimal("10.00")

TWO_PLACES = Decimal("0.01")


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def commission_percent_of(location: Any) -> Decimal:
    """A branch's rate, read strictly.

    Several suites price against a `Mock` branch, whose every attribute is
    another Mock. Anything that is not a number is "no commission configured",
    never a markup by whatever the stand-in happens to be.
    """

    value = getattr(location, "commission_percent", None)
    if isinstance(value, (Decimal, int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    return Decimal("0.00")


def sees_typed_prices(viewer: Any) -> bool:
    """Whether a response to `viewer` may carry the rate and the typed prices.

    Only the two roles that manage a menu. A customer is sent `price` and
    nothing else: the rate is the platform's own business, and a typed price
    beside a listed one gives it away by division. Nobody at all — an
    anonymous storefront, a serializer called without a viewer — is a
    customer, so forgetting to pass one hides the figures rather than
    publishing them.
    """

    # Compared by value: the models import nothing from services, and the role
    # is a StrEnum.
    return str(getattr(viewer, "role", "")) in {"ADMIN", "OWNER"}


def listed_price(entered: Any, *, commission_percent: Any) -> Decimal:
    """What a customer pays for something the owner priced at `entered`."""

    entered = _money(entered or 0)
    percent = Decimal(str(commission_percent or 0))
    if percent <= 0:
        return entered
    return _money(entered * (Decimal("100") + percent) / Decimal("100"))


def _relist(row: Any, price_attr: str, base_attr: str, *, percent: Decimal, typed: bool) -> None:
    """Rewrite one row's customer price from what the owner typed.

    `typed` says where that figure is right now. Straight after an editor save
    it is in the price column, whatever the base says — the owner just typed
    it. When the rate is changed nobody typed anything, so the base is the
    record, and only a row that has never had one falls back to its price.
    """

    base = getattr(row, base_attr, None)
    entered = getattr(row, price_attr) if typed or base is None else base
    entered = _money(entered or 0)
    setattr(row, base_attr, entered)
    setattr(row, price_attr, listed_price(entered, commission_percent=percent))


def _walk(menu_item: Any, *, percent: Decimal, typed: bool) -> None:
    _relist(menu_item, "price", "base_price", percent=percent, typed=typed)
    for size in menu_item.sizes:
        _relist(size, "price", "base_price", percent=percent, typed=typed)
    # Groups scoped to a size hang off the item as well, so this one list is
    # every option the item has.
    for group in menu_item.customization_groups:
        for option in group.options:
            _relist(option, "extra_price", "base_extra_price", percent=percent, typed=typed)


def stamp_entered_prices(menu_item: Any, *, commission_percent: Any) -> None:
    """After an editor save: every price on the item is what the owner typed.

    Call it once the payload has been applied and before the commit. The item's
    own price needs no special case for sizes — it is the cheapest active size,
    and the cheapest stays the cheapest after every size is raised by the same
    percentage.
    """

    _walk(menu_item, percent=Decimal(str(commission_percent or 0)), typed=True)


def relist_menu_item(menu_item: Any, *, commission_percent: Any) -> None:
    """After the rate moved: rewrite the item from its recorded base prices.

    Safe to run twice. The second run reads the same base and writes the same
    price, which is what stops a retried request taking 10% of 110.
    """

    _walk(menu_item, percent=Decimal(str(commission_percent or 0)), typed=False)


def reprice_location(db: Session, location: Any) -> list[Any]:
    """Rewrite every price a branch sells at, to match its rate.

    Returns the items touched, so the caller can do what an edited price always
    needs afterwards — drop the caches that hold the old figure and re-embed
    the text that quotes it. The caller commits.
    """

    # Imported here: the models import nothing from services, and this module
    # is imported by code the models' own package pulls in.
    from app.models.menu_item import MenuItem
    from app.models.menu_item_customization_group import MenuItemCustomizationGroup

    items = list(
        db.scalars(
            select(MenuItem)
            .options(
                selectinload(MenuItem.sizes),
                selectinload(MenuItem.customization_groups).selectinload(
                    MenuItemCustomizationGroup.options
                ),
            )
            .where(MenuItem.restaurant_location_id == location.id)
        ).all()
    )
    percent = commission_percent_of(location)
    for item in items:
        relist_menu_item(item, commission_percent=percent)
    return items


__all__ = [
    "DEFAULT_COMMISSION_PERCENT",
    "commission_percent_of",
    "listed_price",
    "relist_menu_item",
    "reprice_location",
    "sees_typed_prices",
    "stamp_entered_prices",
]
