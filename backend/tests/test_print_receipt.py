"""What actually comes out of the printer.

The renderer is a pure function of rows, so these are assertions about the
words on the paper rather than about SQLAlchemy — which is the point of
rendering server-side at all.

The one that matters most is half-and-half. `CLAUDE.md`: those rules "live in
three places that must agree, because a disagreement means the customer sees
one price and is charged another". A ticket is a fourth reader of the same
snapshot, and its failure mode is worse than a price: the snapshot is a flat
list in whatever order the customer tapped, so printing it verbatim hands a
cook four toppings with the sides interleaved and no way to tell which half
each belongs on. They make the wrong pizza, and nothing in the system is
wrong.

No database: `_prepare_order_draft` and friends are not involved, and a
stand-in order with real snapshot dictionaries exercises everything the
renderer reads.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.enums import (  # noqa: E402
    MenuItemPortion,
    OrderFulfillmentType,
    OrderScheduleType,
    PaymentMethod,
    PaymentStatus,
)
from app.services.print.document import PAPER_WIDTHS  # noqa: E402
from app.services.print.layout import lay_out  # noqa: E402
from app.services.print.render import (  # noqa: E402
    modifier_lines,
    order_code,
    render_customer_bill,
    render_kitchen_docket,
    render_test_page,
    render_void_slip,
)

TZ = ZoneInfo("Asia/Kolkata")


def option(
    name: str,
    *,
    portion: MenuItemPortion = MenuItemPortion.WHOLE,
    quantity: int = 1,
    countable: bool = False,
    group: str = "Toppings",
) -> dict[str, object]:
    """One entry of `selected_options_snapshot`, in the shape orders store."""

    return {
        "group_id": str(uuid.uuid4()),
        "group_title": group,
        "selection_type": "MULTI_SELECT",
        "option_id": str(uuid.uuid4()),
        "option_name": name,
        "extra_price": "20.00",
        "quantity": quantity,
        "is_countable": countable,
        "portion": portion.value,
    }


def line(
    name: str,
    *,
    quantity: int = 1,
    size: str | None = None,
    options: list[dict[str, object]] | None = None,
):
    return SimpleNamespace(
        item_name_snapshot=name,
        size_name_snapshot=size,
        quantity=quantity,
        selected_options_snapshot=options or [],
    )


def make_order(**overrides):
    now = datetime(2026, 10, 3, 19, 30, tzinfo=timezone.utc)
    fields = {
        "id": uuid.UUID("6373b312-6d34-4c3f-8742-0b27b6336061"),
        "created_at": now,
        "scheduled_at": now,
        "schedule_type": OrderScheduleType.ASAP,
        "fulfillment_type": OrderFulfillmentType.DELIVERY,
        "status": "PLACED",
        "payment_method": PaymentMethod.CARD,
        "payment_status": PaymentStatus.PAID,
        "currency": "INR",
        "subtotal": Decimal("450.00"),
        "discount_amount": Decimal("0.00"),
        "tax_amount": Decimal("22.50"),
        "delivery_fee": Decimal("40.00"),
        "total_amount": Decimal("512.50"),
        "special_instructions": None,
        "delivery_address": "A-31 Rangdarshan Society, Katargam, Surat, Gujarat, 395004",
        "contact_name": "Asha Patel",
        "contact_phone": "9825322860",
        "items": [line("Margherita Pizza", quantity=1)],
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def flat(document) -> str:
    """Every word in the document, for "does this appear at all" checks."""

    parts: list[str] = []
    for item_line in document.lines:
        for value in (item_line.k, item_line.v):
            if value:
                parts.append(str(value))
        parts.extend(item_line.mods)
    return "\n".join(parts)


class HalfAndHalfReachesTheCookGrouped(unittest.TestCase):
    """The failure this whole function exists to prevent."""

    def test_sides_are_grouped_not_interleaved(self) -> None:
        # Tapped in the order a customer taps: left, right, left, right.
        order_line = line(
            "Build Your Own Pizza",
            options=[
                option("Olives", portion=MenuItemPortion.LEFT),
                option("Paneer", portion=MenuItemPortion.RIGHT),
                option("Jalapeno", portion=MenuItemPortion.LEFT),
                option("Mushroom", portion=MenuItemPortion.RIGHT),
            ],
        )
        self.assertEqual(
            modifier_lines(order_line),
            ["Left: Olives, Jalapeno", "Right: Paneer, Mushroom"],
        )

    def test_whole_item_options_come_first_and_ungrouped(self) -> None:
        # They apply to the lot, and a cook reading top to bottom should see
        # them before the split rather than after it.
        order_line = line(
            "Build Your Own Pizza",
            options=[
                option("Olives", portion=MenuItemPortion.LEFT),
                option("Thin crust", group="Base"),
                option("Paneer", portion=MenuItemPortion.RIGHT),
            ],
        )
        self.assertEqual(
            modifier_lines(order_line),
            ["Thin crust", "Left: Olives", "Right: Paneer"],
        )

    def test_left_always_prints_before_right(self) -> None:
        # Stable order regardless of how it was tapped, so two identical
        # orders produce two identical dockets. A cook comparing a remake
        # against the original should not have to read both carefully.
        tapped_right_first = line(
            "Pizza",
            options=[
                option("Paneer", portion=MenuItemPortion.RIGHT),
                option("Olives", portion=MenuItemPortion.LEFT),
            ],
        )
        self.assertEqual(
            modifier_lines(tapped_right_first),
            ["Left: Olives", "Right: Paneer"],
        )

    def test_a_count_shows_only_where_it_means_something(self) -> None:
        order_line = line(
            "Pizza",
            options=[
                option("Extra cheese", quantity=2, countable=True),
                # Countable but one of: "x1" on every single choice would bury
                # the ones that matter.
                option("Olives", quantity=1, countable=True),
                # Not countable, so a quantity is meaningless here.
                option("Thin crust", quantity=3, countable=False, group="Base"),
            ],
        )
        self.assertEqual(
            modifier_lines(order_line),
            ["Extra cheese x2", "Olives", "Thin crust"],
        )

    def test_a_portion_this_build_does_not_know_is_printed_not_dropped(self) -> None:
        # Forward compatibility, decided the safe way round. A cook who sees
        # an unplaced topping asks; a cook who sees nothing makes the wrong
        # food.
        order_line = line("Pizza", options=[{**option("Olives"), "portion": "MIDDLE"}])
        self.assertEqual(modifier_lines(order_line), ["Olives"])

    def test_a_nameless_option_is_skipped(self) -> None:
        order_line = line("Pizza", options=[option(""), option("Olives")])
        self.assertEqual(modifier_lines(order_line), ["Olives"])

    def test_a_snapshot_entry_that_is_not_a_dict_does_not_crash(self) -> None:
        # The column is JSONB and has been written by more than one version of
        # this app. A docket must not fail to print over a malformed row.
        order_line = line("Pizza", options=["olives", None, option("Paneer")])
        self.assertEqual(modifier_lines(order_line), ["Paneer"])


class TheOrderCodeMatchesEveryClient(unittest.TestCase):
    def test_it_is_the_same_formula_the_storefront_uses(self) -> None:
        # The identical uuid `frontend-customer/src/lib/bangkok-data.test.ts`
        # asserts against, so a change to either formula breaks a test on both
        # sides rather than printing a code nobody recognises.
        order = make_order(id=uuid.UUID("6373b312-6d34-4c3f-8742-0b27b6336061"))
        self.assertEqual(order_code(order), "#6373B312")


class TheKitchenDocketSaysWhatToCook(unittest.TestCase):
    def render(self, order, width: int = 48):
        return render_kitchen_docket(
            order,
            restaurant_name="Bhagwati Bakery",
            branch_name="Main Branch",
            width=width,
            tz=TZ,
        )

    def test_it_shows_no_money_at_all(self) -> None:
        # Deliberate. A cook does not price food, and a docket is often left
        # on a pass where a customer can see it.
        body = flat(self.render(make_order()))
        for forbidden in ("512.50", "450.00", "40.00", "22.50", "₹"):
            self.assertNotIn(forbidden, body, f"{forbidden} on a kitchen docket")

    def test_the_order_code_and_type_are_the_biggest_things_on_it(self) -> None:
        document = self.render(make_order())
        doubles = [line.v for line in document.lines if line.size == "double"]
        self.assertEqual(doubles, ["DELIVERY", "#6373B312"])

    def test_a_scheduled_order_shows_the_booked_time_not_when_it_arrived(self) -> None:
        # Printing "Placed" on a Friday order booked for Sunday is how a
        # kitchen cooks it on Friday.
        order = make_order(
            schedule_type=OrderScheduleType.SCHEDULED,
            scheduled_at=datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc),
        )
        labels = {line.k: line.v for line in self.render(order).lines if line.k}
        self.assertIn("Scheduled", labels)
        self.assertNotIn("Placed", labels)
        # 07:00 UTC is 12:30 in Asia/Kolkata. Rendered in the BRANCH's zone,
        # not the server's and not the printer PC's.
        self.assertEqual(labels["Scheduled"], "5 Oct, 12:30 PM")

    def test_the_time_is_the_branch_timezone(self) -> None:
        order = make_order(created_at=datetime(2026, 10, 3, 19, 30, tzinfo=timezone.utc))
        labels = {line.k: line.v for line in self.render(order).lines if line.k}
        # 19:30 UTC is 01:00 the next day in Kolkata. Asserted whole rather
        # than with `assertIn`, because "1:00 AM" is a substring of
        # "01:00 AM" — so a zero-padded hour passed a containment check while
        # the ticket read "4 Oct, 01:00 AM". It is now exact.
        self.assertEqual(labels["Placed"], "4 Oct, 1:00 AM")

    def test_a_note_is_last_and_bold(self) -> None:
        # The most expensive thing to miss on a docket: an allergy, a "no
        # onions". It gets its own block at the end rather than wherever the
        # form happened to put it.
        order = make_order(special_instructions="NO PEANUTS - allergy")
        document = self.render(order)
        bolded = [line.v for line in document.lines if line.bold]
        self.assertIn("NO PEANUTS - allergy", bolded)
        self.assertIn("NOTE", bolded)

    def test_a_collection_order_does_not_print_a_phone_number(self) -> None:
        # Handed over at the counter, so a customer's number on it is personal
        # data printed for no reason and left lying on a pass.
        order = make_order(
            fulfillment_type=OrderFulfillmentType.PICKUP, delivery_address="Main Branch"
        )
        body = flat(self.render(order))
        self.assertIn("COLLECTION", body)
        self.assertNotIn("9825322860", body)

    def test_a_delivery_order_prints_who_to_ring_and_where(self) -> None:
        body = flat(self.render(make_order()))
        self.assertIn("9825322860", body)
        self.assertIn("Asha Patel", body)
        self.assertIn("Rangdarshan", body)

    def test_the_halves_reach_the_docket(self) -> None:
        # The grouping above, end to end: what modifier_lines decides has to
        # survive into the document the agent prints.
        order = make_order(
            items=[
                line(
                    "Build Your Own Pizza",
                    size="Large",
                    options=[
                        option("Olives", portion=MenuItemPortion.LEFT),
                        option("Paneer", portion=MenuItemPortion.RIGHT),
                    ],
                )
            ]
        )
        items = [line for line in self.render(order).lines if line.t == "item"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].v, "Build Your Own Pizza (Large)")
        self.assertEqual(items[0].mods, ["Left: Olives", "Right: Paneer"])

    def test_it_ends_with_a_cut(self) -> None:
        # Without this the next ticket prints onto the same strip of paper and
        # a cook tears two orders apart by hand.
        self.assertEqual(self.render(make_order()).lines[-1].t, "cut")

    def test_the_width_is_carried_on_the_document(self) -> None:
        # The agent pads and truncates to it, so a document that does not
        # state it would be laid out for whatever the agent assumed.
        self.assertEqual(self.render(make_order(), width=32).width, 32)


class TheCustomerBillShowsTheMoney(unittest.TestCase):
    def render(self, order):
        return render_customer_bill(
            order,
            restaurant_name="Bhagwati Bakery",
            branch_name="Main Branch",
            width=48,
            tz=TZ,
        )

    def test_the_parts_add_up_to_the_total(self) -> None:
        # The arithmetic a customer does with their eyes. If these do not add
        # up the bill is worse than no bill: it looks like an overcharge.
        values = {line.k: line.v for line in self.render(make_order()).lines if line.k}
        # "Rs." rather than the rupee sign, decided here rather than in the
        # agent. CP437 has no rupee, and substituting it downstream - after
        # the layout had padded for one character - made a bill two columns
        # too wide. See `MoneyIsPrinterSafeBeforeAnythingCountsColumns`.
        self.assertEqual(values["Subtotal"], "Rs.450.00")
        self.assertEqual(values["Tax"], "Rs.22.50")
        self.assertEqual(values["Delivery"], "Rs.40.00")
        self.assertEqual(values["TOTAL"], "Rs.512.50")

    def test_a_zero_charge_is_left_off_rather_than_printed_as_zero(self) -> None:
        # "Delivery ₹0.00" on a collection order reads as a line somebody
        # forgot to remove.
        order = make_order(
            fulfillment_type=OrderFulfillmentType.PICKUP,
            delivery_fee=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("472.50"),
        )
        labels = {line.k for line in self.render(order).lines if line.k}
        self.assertNotIn("Delivery", labels)
        self.assertNotIn("Discount", labels)

    def test_a_discount_prints_as_a_subtraction(self) -> None:
        order = make_order(discount_amount=Decimal("50.00"), total_amount=Decimal("462.50"))
        values = {line.k: line.v for line in self.render(order).lines if line.k}
        self.assertEqual(values["Discount"], "-Rs.50.00")

    def test_an_unpaid_cash_order_says_so_unmistakably(self) -> None:
        # A bill handed over identical to a paid one is how a rider comes back
        # empty-handed.
        order = make_order(
            payment_method=PaymentMethod.COD, payment_status=PaymentStatus.PENDING
        )
        self.assertIn("TO PAY ON DELIVERY", flat(self.render(order)))

    def test_a_paid_cash_order_says_that_instead(self) -> None:
        order = make_order(payment_method=PaymentMethod.COD, payment_status=PaymentStatus.PAID)
        body = flat(self.render(order))
        self.assertIn("PAID - CASH", body)
        self.assertNotIn("TO PAY ON DELIVERY", body)

    def test_a_card_order_awaiting_a_webhook_is_not_called_paid(self) -> None:
        order = make_order(payment_status=PaymentStatus.PENDING)
        self.assertIn("PAYMENT PENDING", flat(self.render(order)))

    def test_a_non_rupee_tenant_gets_its_own_symbol(self) -> None:
        # One deployment serves every restaurant, so the symbol is per order.
        order = make_order(currency="USD")
        values = {line.k: line.v for line in self.render(order).lines if line.k}
        self.assertEqual(values["TOTAL"], "$512.50")


class TheVoidSlipContradictsADocket(unittest.TestCase):
    def render(self, **kwargs):
        return render_void_slip(
            make_order(),
            restaurant_name="Bhagwati Bakery",
            branch_name="Main Branch",
            width=48,
            tz=TZ,
            **kwargs,
        )

    def test_it_is_readable_across_a_room(self) -> None:
        document = self.render()
        doubles = [line.v for line in document.lines if line.size == "double"]
        self.assertIn("CANCELLED", doubles)
        self.assertIn(order_code(make_order()), doubles)

    def test_the_banner_cannot_wrap_on_any_paper(self) -> None:
        """The reason the word carries no asterisks.

        It used to read "*** CANCELLED ***" — 17 characters, where a
        double-width line on 58mm paper has 16. It wrapped mid-banner on the
        one ticket that has to be read correctly from across a room. The
        emphasis moved to full-width asterisk rules, which cannot wrap, and
        the word on its own fits everywhere.

        Asserted against the real layout at every supported width, rather than
        by counting characters here, so the day somebody lengthens it the test
        says so.
        """

        for width in PAPER_WIDTHS:
            document = render_void_slip(
                make_order(),
                restaurant_name="Bhagwati Bakery",
                branch_name="Main Branch",
                width=width,
                tz=TZ,
            )
            banner = next(
                line for line in document.lines if line.size == "double" and line.v == "CANCELLED"
            )
            self.assertLessEqual(
                len(banner.v or ""),
                width // 2,
                f"the banner wraps on {width}-column paper",
            )
        # And nothing in the laid-out slip overflows.
        for width in PAPER_WIDTHS:
            document = render_void_slip(
                make_order(),
                restaurant_name="Bhagwati Bakery",
                branch_name="Main Branch",
                width=width,
                tz=TZ,
            )
            for row in lay_out(document).splitlines():
                self.assertLessEqual(len(row), width)

    def test_it_does_not_repeat_the_items(self) -> None:
        # Printing them invites a glance that reads this as a new order — the
        # exact opposite of what it is for.
        self.assertEqual([line for line in self.render().lines if line.t == "item"], [])

    def test_it_says_what_to_do(self) -> None:
        self.assertIn("Do not make this order.", flat(self.render()))

    def test_a_reason_is_included_when_there_is_one(self) -> None:
        self.assertIn("Payment expired", flat(self.render(reason="Payment expired")))


class TheTestPageProvesThePrinterWorks(unittest.TestCase):
    def test_it_exercises_what_a_real_ticket_uses(self) -> None:
        # A test page of plain text proves the socket works and nothing about
        # whether a docket will be legible.
        document = render_test_page(
            restaurant_name="Bhagwati Bakery",
            printer_name="Kitchen",
            width=32,
            tz=TZ,
        )
        kinds = {line.t for line in document.lines}
        self.assertEqual(kinds, {"text", "kv", "rule", "blank", "cut"})
        self.assertTrue(any(line.size == "double" for line in document.lines))
        self.assertIn("32", flat(document))


class TheDocumentSerialisesCleanly(unittest.TestCase):
    def test_only_what_is_set_reaches_the_column(self) -> None:
        # The JSONB is read by a human when a ticket came out wrong, so a rule
        # should not arrive as eleven nulls.
        document = render_kitchen_docket(
            make_order(),
            restaurant_name="Bhagwati Bakery",
            branch_name="Main Branch",
            width=48,
            tz=TZ,
        )
        payload = document.to_dict()
        self.assertEqual(payload["width"], 48)
        self.assertEqual(payload["kind"], "KITCHEN_DOCKET")
        self.assertIn({"t": "rule"}, payload["lines"])
        self.assertIn({"t": "cut"}, payload["lines"])

    def test_it_is_json_serialisable(self) -> None:
        # It goes into JSONB. A Decimal or a datetime surviving into the
        # document would fail at the moment an order was placed.
        import json

        document = render_customer_bill(
            make_order(),
            restaurant_name="Bhagwati Bakery",
            branch_name="Main Branch",
            width=48,
            tz=TZ,
        )
        json.dumps(document.to_dict())


if __name__ == "__main__":
    unittest.main()
