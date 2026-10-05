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
    """Nothing rewrites a price because of the switch.

    `services/menu_pricing.py` and the `base_price` columns are back, and they
    are not this: they carry the platform's commission (`test_menu_commission`).
    What must never come back is the GST switch reaching them.
    """

    ADMIN = SimpleNamespace(role="ADMIN")

    def apply(self, branch, changes):
        from app.api import restaurants
        from app.services import menu_pricing

        with mock.patch.object(menu_pricing, "reprice_location") as reprice:
            result = restaurants._apply_location_changes(
                mock.Mock(), branch, dict(changes), self.ADMIN
            )
        return result, reprice

    def test_the_markup_module_knows_nothing_about_gst(self) -> None:
        source = (BACKEND_ROOT / "app" / "services" / "menu_pricing.py").read_text("utf-8")
        code = source.split('"""', 2)[2]
        self.assertNotIn("gst_in_menu_prices", code)

    def test_moving_the_switch_touches_only_the_branch(self) -> None:
        for before in (False, True):
            with self.subTest(before=before):
                branch = SimpleNamespace(gst_in_menu_prices=before, delivery_fee=D("0"))
                result, reprice = self.apply(
                    branch, {"gst_in_menu_prices": not before, "delivery_fee": D("40")}
                )
                reprice.assert_not_called()
                self.assertEqual(result, [])
                self.assertIs(branch.gst_in_menu_prices, not before)
                self.assertEqual(branch.delivery_fee, D("40"))

    def test_a_null_is_no_opinion(self) -> None:
        # The column is NOT NULL, and a form that sends null for a checkbox it
        # never rendered must not 500 or switch the branch off.
        branch = SimpleNamespace(gst_in_menu_prices=True)
        self.apply(branch, {"gst_in_menu_prices": None})
        self.assertIs(branch.gst_in_menu_prices, True)


if __name__ == "__main__":
    unittest.main()
