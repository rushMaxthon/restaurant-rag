"""A branch whose menu prices already contain GST.

One switch per branch, and it says something about the prices the owner
typed — it never changes them.

- ON: the menu is GST-inclusive. The customer pays the price on the menu and
  no tax on food is added at checkout.
- OFF: the menu is before tax. The branch's `tax_percent` is added on the
  bill, as it always was.

**This first shipped the other way round, and that was wrong.** ON used to
ADD 18% to every price the owner had typed: 100 became 118 on the menu. The
owner had been asked the wrong question — they were telling us their prices
already had GST in them, and we charged their customers 18% more for saying
so. What is pinned here is that a price is exactly what was typed, whichever
way the switch points, and that the only thing the switch moves is the tax
line on the bill.
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

from app.services import order_charges  # noqa: E402

D = Decimal


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

    def bill(self, branch, subtotal="100.00", discount="0"):
        return order_charges.for_location(
            branch, subtotal=D(subtotal), delivery_fee=D("0"), discount_amount=D(discount)
        )

    def test_gst_in_the_price_is_not_charged_again(self) -> None:
        charges = self.bill(self.branch(gst_in_menu_prices=True))
        self.assertEqual(charges.food_tax, D("0.00"))
        self.assertEqual(charges.total_amount, D("100.00"))
        self.assertNotIn("food_tax", [line.key for line in charges.lines])

    def test_prices_before_tax_are_taxed_at_checkout(self) -> None:
        charges = self.bill(self.branch())
        self.assertEqual(charges.food_tax, D("5.00"))
        self.assertEqual(charges.total_amount, D("105.00"))

    def test_the_rate_at_checkout_is_the_branchs_own(self) -> None:
        charges = self.bill(self.branch(tax_percent=D("18.00")))
        self.assertEqual(charges.food_tax, D("18.00"))
        self.assertEqual(charges.total_amount, D("118.00"))

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
        self.assertEqual(self.bill(old).food_tax, D("5.00"))

    def test_a_stand_in_branch_is_not_read_as_switched_on(self) -> None:
        # Several suites price against a Mock branch, whose every attribute is
        # truthy. Read loosely, that would silently drop their tax.
        stand_in = mock.Mock(
            packaging_fee=D("0"), platform_fee=D("0"), tax_percent=D("5.00"),
            delivery_tax_percent=D("0"),
        )
        self.assertEqual(self.bill(stand_in).food_tax, D("5.00"))


class ThePricesAreLeftAloneTests(unittest.TestCase):
    """Nothing rewrites a price because of the switch."""

    def test_there_is_no_markup_module(self) -> None:
        # `services/menu_pricing.py` was the thing that added 18%. If it comes
        # back, so does a menu that costs more than the owner typed.
        self.assertFalse((BACKEND_ROOT / "app" / "services" / "menu_pricing.py").exists())

    def test_nothing_keeps_a_second_price_beside_the_first(self) -> None:
        from app.models.menu_item import MenuItem
        from app.models.menu_item_customization_option import MenuItemCustomizationOption
        from app.models.menu_item_size import MenuItemSize

        for model, column in (
            (MenuItem, "base_price"),
            (MenuItemSize, "base_price"),
            (MenuItemCustomizationOption, "base_extra_price"),
        ):
            with self.subTest(model=model.__name__):
                self.assertNotIn(column, model.__table__.columns)

    def test_moving_the_switch_touches_only_the_branch(self) -> None:
        from app.api import restaurants

        branch = SimpleNamespace(gst_in_menu_prices=False, delivery_fee=D("0"))
        restaurants._apply_location_changes(
            branch, {"gst_in_menu_prices": True, "delivery_fee": D("40")}
        )
        self.assertIs(branch.gst_in_menu_prices, True)
        self.assertEqual(branch.delivery_fee, D("40"))

    def test_a_null_is_no_opinion(self) -> None:
        # The column is NOT NULL, and a form that sends null for a checkbox it
        # never rendered must not 500 or switch the branch off.
        from app.api import restaurants

        branch = SimpleNamespace(gst_in_menu_prices=True)
        restaurants._apply_location_changes(branch, {"gst_in_menu_prices": None})
        self.assertIs(branch.gst_in_menu_prices, True)


if __name__ == "__main__":
    unittest.main()
