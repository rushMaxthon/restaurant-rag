"""A branch that sells at prices already containing 18% GST.

The owner types 100; the customer sees 118 and pays 118, and nothing is added
for tax on food at checkout. One switch per branch.

The way this goes wrong is always the same: two figures for one dish. So the
price is WRITTEN when the switch moves or an item is saved, and everything that
reads a price reads the result. What is pinned here is the writing.

**Marked up twice.** The editor loads a price, the owner changes the name, the
editor saves the price back. If what it loaded was 118, the item is now 139.24
and goes up again on every save. The typed figure is kept beside the price and
is what an editor is handed.

**No way back.** 118 / 1.18 is 100, but 116.82 / 1.18 is 98.9999. Switching
off restores the typed figure from where it was kept, not by division.

**Taxed twice.** With GST inside the price, the branch's own `tax_percent`
must not also be charged — and with the switch off it must be charged exactly
as before.

**A cart that does not add up.** Half of an extra, and three of a dish, are
worked out from the LISTED price by three clients. The listed price is
therefore rounded to the paisa once, here, before anything multiplies it.
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import menu_pricing, order_charges  # noqa: E402
from app.services.menu_pricing import (  # noqa: E402
    listed_price,
    relist_menu_item,
    stamp_entered_prices,
)

D = Decimal


def an_option(extra: str, base: str | None = None):
    return SimpleNamespace(extra_price=D(extra), base_extra_price=None if base is None else D(base))


def a_size(price: str, base: str | None = None):
    return SimpleNamespace(price=D(price), base_price=None if base is None else D(base))


def an_item(price: str, *, base: str | None = None, sizes=(), options=()):
    return SimpleNamespace(
        price=D(price),
        base_price=None if base is None else D(base),
        sizes=list(sizes),
        customization_groups=[SimpleNamespace(options=list(options))] if options else [],
    )


class TheListedPriceTests(unittest.TestCase):
    def test_off_is_the_typed_price(self) -> None:
        self.assertEqual(listed_price(D("100"), gst_in_menu_prices=False), D("100.00"))

    def test_on_adds_eighteen_percent(self) -> None:
        self.assertEqual(listed_price(D("100"), gst_in_menu_prices=True), D("118.00"))
        self.assertEqual(listed_price(D("249"), gst_in_menu_prices=True), D("293.82"))

    def test_it_is_rounded_to_the_paisa_half_up(self) -> None:
        # 49.75 * 1.18 = 58.705. Banker's rounding gives 58.70, and a column
        # somebody adds up by eye then looks short.
        self.assertEqual(listed_price(D("49.75"), gst_in_menu_prices=True), D("58.71"))

    def test_a_free_extra_stays_free(self) -> None:
        self.assertEqual(listed_price(D("0"), gst_in_menu_prices=True), D("0.00"))
        self.assertEqual(listed_price(None, gst_in_menu_prices=True), D("0.00"))


class SavingAnItemTests(unittest.TestCase):
    def test_everything_on_the_item_is_listed_and_the_typed_figure_is_kept(self) -> None:
        item = an_item(
            "200",
            sizes=[a_size("200"), a_size("350")],
            options=[an_option("30"), an_option("0")],
        )
        stamp_entered_prices(item, gst_in_menu_prices=True)

        self.assertEqual((item.base_price, item.price), (D("200.00"), D("236.00")))
        self.assertEqual([s.base_price for s in item.sizes], [D("200.00"), D("350.00")])
        self.assertEqual([s.price for s in item.sizes], [D("236.00"), D("413.00")])
        options = item.customization_groups[0].options
        self.assertEqual([o.base_extra_price for o in options], [D("30.00"), D("0.00")])
        self.assertEqual([o.extra_price for o in options], [D("35.40"), D("0.00")])

    def test_what_was_typed_wins_over_what_was_recorded(self) -> None:
        # The owner changed 100 to 120. The price column holds the 120 they
        # typed; the base still says 100 and must not be believed.
        item = an_item("120", base="100")
        stamp_entered_prices(item, gst_in_menu_prices=True)
        self.assertEqual((item.base_price, item.price), (D("120.00"), D("141.60")))

    def test_a_branch_with_the_switch_off_sells_at_the_typed_price(self) -> None:
        item = an_item("120", sizes=[a_size("120")], options=[an_option("15")])
        stamp_entered_prices(item, gst_in_menu_prices=False)
        self.assertEqual((item.base_price, item.price), (D("120.00"), D("120.00")))
        self.assertEqual(item.sizes[0].price, D("120.00"))
        self.assertEqual(item.customization_groups[0].options[0].extra_price, D("15.00"))

    def test_saving_what_the_editor_was_handed_changes_nothing(self) -> None:
        # The double mark-up, as it would have happened: load, save, load, save.
        item = an_item("100")
        stamp_entered_prices(item, gst_in_menu_prices=True)
        for _ in range(3):
            item.price = item.base_price  # the editor sends back the BASE
            stamp_entered_prices(item, gst_in_menu_prices=True)
        self.assertEqual(item.price, D("118.00"))


class FlippingTheSwitchTests(unittest.TestCase):
    def test_on_marks_up_a_menu_that_never_had_a_base(self) -> None:
        # Every row that exists before this feature: a price, and no base.
        item = an_item("99", sizes=[a_size("99")], options=[an_option("20")])
        relist_menu_item(item, gst_in_menu_prices=True)
        self.assertEqual((item.base_price, item.price), (D("99.00"), D("116.82")))
        self.assertEqual(item.sizes[0].price, D("116.82"))
        self.assertEqual(item.customization_groups[0].options[0].extra_price, D("23.60"))

    def test_on_twice_is_on_once(self) -> None:
        # A retried request, or two tabs. 18% of 118 must never be added.
        item = an_item("100")
        relist_menu_item(item, gst_in_menu_prices=True)
        relist_menu_item(item, gst_in_menu_prices=True)
        self.assertEqual(item.price, D("118.00"))

    def test_off_returns_exactly_what_was_typed(self) -> None:
        # 116.82 / 1.18 = 98.99915... — division would hand back 99.00 here by
        # luck and miss by a paisa elsewhere. The base is the record.
        for typed in ("99", "49.75", "0.05", "1234.56"):
            with self.subTest(typed=typed):
                item = an_item(typed)
                relist_menu_item(item, gst_in_menu_prices=True)
                relist_menu_item(item, gst_in_menu_prices=False)
                self.assertEqual(item.price, D(typed).quantize(D("0.01")))

    def test_the_cheapest_size_is_still_the_items_price(self) -> None:
        # An item with sizes carries the cheapest active size as its own
        # price. Raising everything by one percentage keeps that true.
        item = an_item("180", sizes=[a_size("180"), a_size("260")])
        relist_menu_item(item, gst_in_menu_prices=True)
        self.assertEqual(item.price, min(size.price for size in item.sizes))


class TheBillTests(unittest.TestCase):
    def branch(self, **over):
        fields = {
            "packaging_fee": D("0"),
            "platform_fee": D("0"),
            "tax_percent": D("5.00"),
            "delivery_tax_percent": D("0"),
            "gst_in_menu_prices": False,
        }
        fields.update(over)
        return SimpleNamespace(**fields)

    def bill(self, branch, subtotal="118.00", discount="0"):
        return order_charges.for_location(
            branch, subtotal=D(subtotal), delivery_fee=D("0"), discount_amount=D(discount)
        )

    def test_gst_in_the_price_is_not_charged_again(self) -> None:
        charges = self.bill(self.branch(gst_in_menu_prices=True))
        self.assertEqual(charges.food_tax, D("0.00"))
        self.assertEqual(charges.total_amount, D("118.00"))
        self.assertNotIn("food_tax", [line.key for line in charges.lines])

    def test_the_switch_off_charges_what_it_always_did(self) -> None:
        charges = self.bill(self.branch(), subtotal="100.00")
        self.assertEqual(charges.food_tax, D("5.00"))
        self.assertEqual(charges.total_amount, D("105.00"))

    def test_the_other_charges_are_untouched_by_the_switch(self) -> None:
        # The switch is about tax on FOOD. Delivery keeps its own rate and the
        # fees stay on the bill.
        branch = self.branch(
            gst_in_menu_prices=True,
            packaging_fee=D("10"),
            platform_fee=D("5"),
            delivery_tax_percent=D("18"),
        )
        charges = order_charges.for_location(
            branch, subtotal=D("118.00"), delivery_fee=D("50"), discount_amount=D("0")
        )
        self.assertEqual(charges.delivery_tax, D("9.00"))
        self.assertEqual(charges.total_amount, D("192.00"))

    def test_a_branch_row_from_before_the_column_prices_as_before(self) -> None:
        old = SimpleNamespace(tax_percent=D("5.00"))
        self.assertEqual(self.bill(old, subtotal="100.00").food_tax, D("5.00"))

    def test_a_stand_in_branch_is_not_read_as_switched_on(self) -> None:
        # Several suites price against a Mock branch, whose every attribute is
        # truthy. Read loosely, that would silently drop their tax.
        stand_in = mock.Mock(
            packaging_fee=D("0"), platform_fee=D("0"), tax_percent=D("5.00"),
            delivery_tax_percent=D("0"),
        )
        self.assertEqual(self.bill(stand_in, subtotal="100.00").food_tax, D("5.00"))


class SavingTheBranchTests(unittest.TestCase):
    def apply(self, branch, changes):
        from app.api import restaurants

        with mock.patch.object(menu_pricing, "reprice_location", return_value=["item"]) as reprice:
            result = restaurants._apply_location_changes(mock.Mock(), branch, dict(changes))
        return result, reprice

    def test_moving_the_switch_reprices_the_menu(self) -> None:
        branch = SimpleNamespace(gst_in_menu_prices=False)
        result, reprice = self.apply(branch, {"gst_in_menu_prices": True})
        reprice.assert_called_once()
        self.assertEqual(result, ["item"])
        self.assertTrue(branch.gst_in_menu_prices)

    def test_a_save_that_leaves_it_alone_reprices_nothing(self) -> None:
        # Every save of the settings form sends the switch along with the rest.
        for before in (True, False):
            with self.subTest(before=before):
                branch = SimpleNamespace(gst_in_menu_prices=before, delivery_fee=D("0"))
                result, reprice = self.apply(
                    branch, {"gst_in_menu_prices": before, "delivery_fee": D("40")}
                )
                reprice.assert_not_called()
                self.assertEqual(result, [])
                self.assertEqual(branch.delivery_fee, D("40"))

    def test_a_null_is_no_opinion(self) -> None:
        branch = SimpleNamespace(gst_in_menu_prices=True)
        _, reprice = self.apply(branch, {"gst_in_menu_prices": None})
        reprice.assert_not_called()
        self.assertIs(branch.gst_in_menu_prices, True)


if __name__ == "__main__":
    unittest.main()
