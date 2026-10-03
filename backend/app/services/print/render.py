"""Turning an order into a ticket.

Three documents, because they have three audiences and three jobs:

* a **kitchen docket** shouts what to cook and deliberately shows no money —
  a cook comparing prices is a cook not cooking, and a docket left on a
  counter should not be a bill;
* a **customer bill** shows the money and nothing about the kitchen;
* a **void slip** exists to contradict a docket somebody is already holding,
  so it has to be unmistakable from across a room.

Everything here is a pure function of rows already loaded. No database, no
clock of its own, nothing that can fail — so the tests are about the words on
the paper rather than about SQLAlchemy, and a renderer change cannot break an
order.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.models.enums import (
    MenuItemPortion,
    OrderFulfillmentType,
    OrderScheduleType,
    PaymentMethod,
    PaymentStatus,
)
from app.models.order import Order
from app.models.order_item import OrderItem
from app.services.currency import currency_for
from app.services.print.document import (
    Document,
    Line,
    blank,
    cut,
    item,
    kv,
    money_str,
    rule,
    text,
)

#: How a portion reads on paper.
#:
#: "Left" and "Right" rather than the enum's own names because a cook reads
#: this at arm's length under time pressure; `LEFT` in capitals next to a
#: topping looks like part of the topping's name.
_PORTION_LABEL = {
    MenuItemPortion.LEFT: "Left",
    MenuItemPortion.RIGHT: "Right",
}


def order_code(order: Order) -> str:
    """The order's number as the CUSTOMER sees it.

    There is no `order_number` column: the code is derived from the id, and
    every client derives it the same way — `orderCode` in
    `frontend-customer/src/lib/bangkok-data.ts` is
    `#${order.id.slice(0, 8).toUpperCase()}`.

    It has to match, and not approximately. This string is what a customer
    quotes on the phone, what the kitchen calls out, and what an owner types
    into the admin to find the order. A ticket carrying a different code from
    the confirmation screen makes every one of those conversations fail.

    `test_print_receipt.py` pins it against the same uuid
    `bangkok-data.test.ts` uses, so a change to either formula breaks a test
    on both sides rather than silently printing a code nobody recognises.
    """

    return f"#{str(order.id)[:8].upper()}"


def _clock(moment: datetime, tz: ZoneInfo) -> str:
    """"4 Oct, 1:00 AM" — in the BRANCH's timezone.

    Built field by field rather than with one `strftime`, because the obvious
    `strftime("%d %b, %I:%M %p").lstrip("0")` strips the leading zero off the
    DAY and leaves it on the hour: "4 Oct, 01:00 AM". `%-I` is not portable to
    Windows, where this backend also runs.

    Zero-padded hours are not a cosmetic worry on a ticket read at arm's
    length — "01:00" scans as a duration, "1:00 AM" as a time.
    """

    local = moment.astimezone(tz)
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local.day} {local.strftime('%b')}, {hour}:{local.strftime('%M %p')}"


def _option_text(option: dict[str, object]) -> str:
    """One chosen option, with its count if it is countable.

    `quantity` is only meaningful for a countable group — "extra cheese x2" —
    and printing "x1" against every single-select choice would bury the ones
    that matter in noise.
    """

    name = str(option.get("option_name") or "").strip()
    if not name:
        return ""
    quantity = option.get("quantity")
    countable = bool(option.get("is_countable"))
    if countable and isinstance(quantity, int) and quantity > 1:
        return f"{name} x{quantity}"
    return name


def modifier_lines(line: OrderItem) -> list[str]:
    """What was chosen on this line, grouped so a cook can act on it.

    **Halves are grouped by side, and that is the whole reason this function
    exists.** The snapshot is a flat list in whatever order the customer
    tapped, so rendering it verbatim gives a cook "Olives, Paneer, Jalapeno,
    Mushroom" with the sides interleaved — four toppings and no way to tell
    which half each belongs on. Grouped, it reads:

        Left: Olives, Jalapeno
        Right: Paneer x2, Mushroom

    Whole-item options stay ungrouped and come first, because they apply to
    the lot and a cook reading top to bottom should see them before the split.
    """

    snapshot = line.selected_options_snapshot or []

    whole: list[str] = []
    halves: dict[MenuItemPortion, list[str]] = {
        MenuItemPortion.LEFT: [],
        MenuItemPortion.RIGHT: [],
    }

    for option in snapshot:
        if not isinstance(option, dict):
            continue
        label = _option_text(option)
        if not label:
            continue
        raw_portion = str(option.get("portion") or MenuItemPortion.WHOLE.value)
        try:
            portion = MenuItemPortion(raw_portion)
        except ValueError:
            # A portion this build does not know about. Printed as a whole-item
            # option rather than dropped: a cook seeing an unplaced topping
            # will ask, and a cook seeing nothing will make the wrong food.
            portion = MenuItemPortion.WHOLE
        if portion in halves:
            halves[portion].append(label)
        else:
            whole.append(label)

    out = list(whole)
    for portion in (MenuItemPortion.LEFT, MenuItemPortion.RIGHT):
        chosen = halves[portion]
        if chosen:
            out.append(f"{_PORTION_LABEL[portion]}: {', '.join(chosen)}")
    return out


def _item_lines(order: Order) -> list[Line]:
    lines: list[Line] = []
    for order_item in order.items:
        name = order_item.item_name_snapshot
        if order_item.size_name_snapshot:
            name = f"{name} ({order_item.size_name_snapshot})"
        lines.append(
            item(order_item.quantity, name, mods=modifier_lines(order_item))
        )
    return lines


def _fulfillment_banner(order: Order) -> str:
    return (
        "DELIVERY" if order.fulfillment_type == OrderFulfillmentType.DELIVERY else "COLLECTION"
    )


def _when(order: Order, tz: ZoneInfo) -> tuple[str, str]:
    """The label and value for the time that matters on this ticket.

    A scheduled order's booked slot is the operative time and an ASAP order's
    is when it arrived. Printing "Placed" on a Friday order booked for Sunday
    is how a kitchen cooks it on Friday.
    """

    if order.schedule_type == OrderScheduleType.SCHEDULED:
        return "Scheduled", _clock(order.scheduled_at, tz)
    return "Placed", _clock(order.created_at, tz)


def render_kitchen_docket(
    order: Order,
    *,
    restaurant_name: str,
    branch_name: str | None,
    width: int,
    tz: ZoneInfo,
) -> Document:
    """What to cook, and nothing else.

    No prices anywhere, on purpose. A cook does not price food, a docket is
    often left on a pass where a customer can see it, and money on it invites
    exactly one conversation nobody in a kitchen has time for.
    """

    when_label, when_value = _when(order, tz)
    lines: list[Line] = [
        text(_fulfillment_banner(order), align="center", bold=True, size="double"),
        text(order_code(order), align="center", bold=True, size="double"),
        rule(),
        kv(when_label, when_value, bold=order.schedule_type == OrderScheduleType.SCHEDULED),
    ]

    if branch_name:
        lines.append(kv("Branch", branch_name))

    lines.extend([rule(), *_item_lines(order)])

    if order.special_instructions:
        # Last, boxed by rules, and bold. A note is the single most expensive
        # thing to miss on a docket — an allergy, a "no onions" — and it used
        # to arrive wherever the form happened to put it.
        lines.extend(
            [
                rule(),
                text("NOTE", bold=True),
                text(order.special_instructions.strip(), bold=True),
            ]
        )

    # Who to ring, on a DELIVERY docket only. A collection order is handed over
    # at the counter, so a phone number on it is a customer's number printed
    # for no reason and left lying on a pass.
    if order.fulfillment_type == OrderFulfillmentType.DELIVERY:
        lines.append(rule())
        if order.contact_name:
            lines.append(kv("For", order.contact_name))
        if order.contact_phone:
            lines.append(kv("Phone", order.contact_phone))
        if order.delivery_address:
            lines.extend([blank(), text(order.delivery_address.strip())])

    lines.extend([blank(), cut()])
    return Document(width=width, lines=lines, kind="KITCHEN_DOCKET")


def render_customer_bill(
    order: Order,
    *,
    restaurant_name: str,
    branch_name: str | None,
    width: int,
    tz: ZoneInfo,
) -> Document:
    """What was charged, for the customer's hand.

    The charge lines come from `order.charges` when the order carries them,
    because that is the breakdown the customer was shown at checkout and was
    actually billed. Falling back to subtotal plus total would print a bill
    whose middle is missing and whose arithmetic the customer cannot follow.
    """

    currency = currency_for(order.currency if hasattr(order, "currency") else None)
    symbol = currency.symbol
    when_label, when_value = _when(order, tz)

    lines: list[Line] = [
        text(restaurant_name, align="center", bold=True, size="double"),
    ]
    if branch_name:
        lines.append(text(branch_name, align="center"))
    lines.extend(
        [
            rule(),
            kv("Order", order_code(order), bold=True),
            kv(when_label, when_value),
            kv("Type", _fulfillment_banner(order).title()),
            rule(),
            *_item_lines(order),
            rule(),
        ]
    )

    lines.append(kv("Subtotal", money_str(order.subtotal, symbol)))

    discount = Decimal(str(order.discount_amount or 0))
    if discount > 0:
        lines.append(kv("Discount", f"-{money_str(discount, symbol)}"))

    tax = Decimal(str(getattr(order, "tax_amount", 0) or 0))
    if tax > 0:
        lines.append(kv("Tax", money_str(tax, symbol)))

    fee = Decimal(str(getattr(order, "delivery_fee", 0) or 0))
    if fee > 0:
        lines.append(kv("Delivery", money_str(fee, symbol)))

    lines.extend(
        [
            rule(),
            kv("TOTAL", money_str(order.total_amount, symbol), bold=True),
            blank(),
        ]
    )

    # Whether money has actually arrived. A bill handed over with a cash order
    # still owing, printed identically to a paid one, is how a rider comes
    # back empty-handed.
    if order.payment_method == PaymentMethod.COD:
        lines.append(
            text(
                "TO PAY ON DELIVERY"
                if order.payment_status != PaymentStatus.PAID
                else "PAID - CASH",
                align="center",
                bold=True,
            )
        )
    elif order.payment_status == PaymentStatus.PAID:
        lines.append(text("PAID", align="center", bold=True))
    else:
        lines.append(text("PAYMENT PENDING", align="center", bold=True))

    lines.extend([blank(), text("Thank you", align="center"), blank(), cut()])
    return Document(width=width, lines=lines, kind="CUSTOMER_BILL")


def render_void_slip(
    order: Order,
    *,
    restaurant_name: str,
    branch_name: str | None,
    width: int,
    tz: ZoneInfo,
    reason: str | None = None,
) -> Document:
    """A ticket whose only job is to contradict one already in the kitchen.

    Short, loud, and it names the order number in double height twice over —
    because it has to be read correctly from across a room by someone who is
    already holding the docket it cancels. Everything a docket says about how
    to cook the food is deliberately absent; repeating the items here invites
    a glance that reads it as a new order.
    """

    lines: list[Line] = [
        # Asterisk rules rather than asterisks in the word. "*** CANCELLED ***"
        # needs 17 of the 16 columns a double-width line gets on 58mm paper, so
        # it wrapped mid-banner on the one ticket that must be read correctly
        # from across a room. Drawn to the paper's width it cannot wrap, and
        # "CANCELLED" alone fits at double size on every size of paper.
        rule("*"),
        text("CANCELLED", align="center", bold=True, size="double"),
        rule("*"),
        blank(),
        text(order_code(order), align="center", bold=True, size="double"),
        blank(),
        rule(),
        kv("Cancelled", _clock(datetime.now(tz), tz)),
    ]
    if branch_name:
        lines.append(kv("Branch", branch_name))
    if reason:
        lines.extend([rule(), text("Reason", bold=True), text(reason)])
    lines.extend(
        [
            rule(),
            text("Do not make this order.", align="center", bold=True),
            blank(),
            cut(),
        ]
    )
    return Document(width=width, lines=lines, kind="VOID_SLIP")


def render_test_page(
    *,
    restaurant_name: str,
    printer_name: str,
    width: int,
    tz: ZoneInfo,
) -> Document:
    """Proof that this printer works, printed from the admin screen.

    Exercises every capability a real ticket uses — double height, bold,
    a right-aligned value, a rule, and the cut — because a test page that only
    prints plain text proves the socket works and nothing about whether a
    docket will be legible.
    """

    now = datetime.now(tz)
    return Document(
        width=width,
        kind="TEST",
        lines=[
            text("TEST PRINT", align="center", bold=True, size="double"),
            rule(),
            kv("Restaurant", restaurant_name),
            kv("Printer", printer_name),
            kv("Columns", str(width)),
            kv("Time", _clock(now, tz)),
            rule(),
            text("If you can read this, orders will print here.", align="center"),
            blank(),
            cut(),
        ],
    )
