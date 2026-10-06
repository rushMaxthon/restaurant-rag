"""How one paid order divides between the restaurant and the platform.

The restaurant is owed its food at its own price (the menu price less the
commission folded into it), less the discounts it chose to run, plus packaging
and the GST on its food, which it files. The platform keeps the commission,
the delivery fee and its GST (it paid the rider), and the platform fee.
Razorpay's own fee is the platform's cost and is not in either figure.
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.payouts.split import split_order  # noqa: E402

D = Decimal


def order(**money):
    base = dict(
        subtotal=D("0"), commission_amount=D("0"), discount_amount=D("0"),
        packaging_fee=D("0"), food_tax_amount=D("0"), delivery_fee=D("0"),
        delivery_tax_amount=D("0"), platform_fee=D("0"), total_amount=D("0"),
    )
    base.update(money)
    return SimpleNamespace(**base)


class SplitTests(unittest.TestCase):
    def test_a_delivery_order_divides_and_reconciles(self) -> None:
        o = order(subtotal=D("500.00"), commission_amount=D("50.00"), packaging_fee=D("20.00"),
                  food_tax_amount=D("26.00"), delivery_fee=D("40.00"), delivery_tax_amount=D("7.20"),
                  platform_fee=D("5.00"), total_amount=D("598.20"))
        s = split_order(o)
        self.assertEqual(s.restaurant_share, D("496.00"))
        self.assertEqual(s.platform_keeps, D("102.20"))
        self.assertEqual(s.blocked_reason, "")

    def test_a_pickup_order_has_no_delivery_in_it(self) -> None:
        s = split_order(order(subtotal=D("200.00"), commission_amount=D("20.00"),
                              food_tax_amount=D("10.00"), total_amount=D("210.00")))
        self.assertEqual((s.restaurant_share, s.platform_keeps), (D("190.00"), D("20.00")))

    def test_a_discount_comes_out_of_the_restaurants_share(self) -> None:
        s = split_order(order(subtotal=D("300.00"), commission_amount=D("30.00"), discount_amount=D("60.00"),
                              food_tax_amount=D("12.00"), total_amount=D("252.00")))
        self.assertEqual(s.restaurant_share, D("222.00"))
        self.assertEqual(s.platform_keeps, D("30.00"))

    def test_no_recorded_commission_is_zero_commission(self) -> None:
        s = split_order(order(subtotal=D("100.00"), commission_amount=None, total_amount=D("100.00")))
        self.assertEqual((s.restaurant_share, s.platform_keeps, s.blocked_reason), (D("100.00"), D("0.00"), ""))

    def test_figures_that_do_not_add_up_are_blocked_not_guessed(self) -> None:
        # An order from before food and delivery GST were stored apart: only
        # the old combined tax column was filled, so nothing reconciles.
        s = split_order(order(subtotal=D("100.00"), total_amount=D("105.00")))
        self.assertIn("105.00", s.blocked_reason)
        self.assertIn("100.00", s.blocked_reason)

    def test_a_discount_bigger_than_the_food_is_blocked(self) -> None:
        s = split_order(order(subtotal=D("100.00"), commission_amount=D("10.00"), discount_amount=D("120.00"),
                              delivery_fee=D("40.00"), total_amount=D("20.00")))
        self.assertEqual(s.restaurant_share, D("-30.00"))
        self.assertTrue(s.blocked_reason)

    def test_paise_are_kept_exactly(self) -> None:
        s = split_order(order(subtotal=D("99.99"), commission_amount=D("9.99"), food_tax_amount=D("4.50"),
                              platform_fee=D("0.01"), total_amount=D("104.50")))
        self.assertEqual((s.restaurant_share, s.platform_keeps), (D("94.50"), D("10.00")))


if __name__ == "__main__":
    unittest.main()
