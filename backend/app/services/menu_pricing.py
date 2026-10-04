"""GST inside the menu price, per branch.

A branch can be switched to sell at prices that already contain 18% GST: the
owner types 100, the customer sees and pays 118, and no separate tax on food
is added at checkout. `restaurant_locations.gst_in_menu_prices` is the switch.

**The price is written, not worked out on the way past.** The obvious way to
build this is to multiply by 1.18 wherever a price is shown. A price is read in
about ninety places here — the menu, the cart, the order, favourites,
recommendations, combos, offers, the chat prompt, the WhatsApp agent, the
embedding text — and in three clients that each add up a cart themselves. Miss
one and a customer is shown one figure and charged another, which is the exact
failure the half-and-half rules exist to prevent.

So `price` stays what it has always been: what the customer pays. The figure
the owner typed is kept beside it in `base_price` (`base_extra_price` on an
option), and `price` is rewritten from it in the only two places that can
change the answer — an item being saved, and the switch being flipped. Nothing
that reads a price needs to know this module exists.

**Rounded once, at the listed price.** 18% of 99 is 17.82; of 49.50 it is
8.91. Each listed price is rounded to the paisa here and every later sum —
quantity, half of an extra, a discount — runs on that rounded figure, in the
same order the clients do it. Rounding at the end instead would let a cart of
three differ from three times the price on the menu.

**`base_price` NULL means "what is in `price` is what was typed".** Every row
written before this existed is in that state, and so is anything a seed script
inserts. It is why the columns are nullable rather than backfilled: a row with
no base is never marked up twice, because the first relist records its base.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

#: The rate, as a percent. One figure for every branch: the switch is "GST is
#: inside the menu price", and 18% is what that GST is. A branch that needs a
#: different rate on the bill has `tax_percent` for that, with the switch off.
GST_PERCENT = Decimal("18.00")

TWO_PLACES = Decimal("0.01")


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def listed_price(entered: Any, *, gst_in_menu_prices: bool) -> Decimal:
    """What a customer pays for something the owner priced at `entered`."""

    entered = _money(entered or 0)
    if not gst_in_menu_prices:
        return entered
    return _money(entered * (Decimal("100") + GST_PERCENT) / Decimal("100"))


def _relist(row: Any, price_attr: str, base_attr: str, *, gst: bool, typed: bool) -> None:
    """Rewrite one row's customer price from what the owner typed.

    `typed` says where that figure is right now. Straight after an editor save
    it is in the price column, whatever the base says — the owner just typed
    it. When the switch is flipped nobody typed anything, so the base is the
    record, and only a row that has never had one falls back to its price.
    """

    base = getattr(row, base_attr, None)
    entered = getattr(row, price_attr) if typed or base is None else base
    entered = _money(entered or 0)
    setattr(row, base_attr, entered)
    setattr(row, price_attr, listed_price(entered, gst_in_menu_prices=gst))


def _walk(menu_item: Any, *, gst: bool, typed: bool) -> None:
    _relist(menu_item, "price", "base_price", gst=gst, typed=typed)
    for size in menu_item.sizes:
        _relist(size, "price", "base_price", gst=gst, typed=typed)
    # Groups scoped to a size hang off the item as well, so this one list is
    # every option the item has.
    for group in menu_item.customization_groups:
        for option in group.options:
            _relist(option, "extra_price", "base_extra_price", gst=gst, typed=typed)


def stamp_entered_prices(menu_item: Any, *, gst_in_menu_prices: bool) -> None:
    """After an editor save: every price on the item is what the owner typed.

    Call it once the payload has been applied and before the commit. The item's
    own price needs no special case for sizes — it is the cheapest active size,
    and the cheapest stays the cheapest after every size is raised by the same
    percentage.
    """

    _walk(menu_item, gst=gst_in_menu_prices, typed=True)


def relist_menu_item(menu_item: Any, *, gst_in_menu_prices: bool) -> None:
    """After the switch moved: rewrite the item from its recorded base prices.

    Safe to run twice. The second run reads the same base and writes the same
    price, which is what stops a retried request marking a menu up by 18% of
    118.
    """

    _walk(menu_item, gst=gst_in_menu_prices, typed=False)


def reprice_location(db: Session, location: Any) -> list[Any]:
    """Rewrite every price a branch sells at, to match its switch.

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
    gst = bool(location.gst_in_menu_prices)
    for item in items:
        relist_menu_item(item, gst_in_menu_prices=gst)
    return items


__all__ = [
    "GST_PERCENT",
    "listed_price",
    "relist_menu_item",
    "reprice_location",
    "stamp_entered_prices",
]
