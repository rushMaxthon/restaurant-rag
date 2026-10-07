"""What a customer is charged, and the ways a bill goes quietly wrong.

Every case here is a way the arithmetic could be defensible and still cost
somebody money. A bill has no error state: it just comes out a bit different,
and nobody notices until a customer adds it up or an accountant does.

The one that matters most is the first: the defaults must reproduce exactly what
was charged before this existed. A pricing change that ships by accident is the
worst outcome available, so it has a test of its own.
"""

from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings  # noqa: E402
from app.services import order_charges  # noqa: E402


def bill(**over) -> order_charges.OrderCharges:
    base = {
        "subtotal": Decimal("1000"),
        "delivery_fee": Decimal("50"),
        "discount_amount": Decimal("0"),
        "packaging_fee": Decimal("0"),
        "platform_fee": Decimal("0"),
        "tax_percent": Decimal("5"),
        "delivery_tax_percent": Decimal("0"),
    }
    base.update(over)
    return order_charges.compute(**base)


class TheDefaultsChangeNobodysPrices(unittest.TestCase):
    """The most important test here, and the least interesting to read.

    Before this module, `orders.py` charged `subtotal * 0.05` and added it to
    the subtotal and the delivery fee. Every default below reproduces that
    exactly, so switching the code in re-prices nothing and an operator has to
    deliberately edit a branch before any customer pays a different amount.
    """

    def test_a_default_branch_bills_what_it_always_did(self) -> None:
        charges = bill()
        # 1000 + 50 + 5% of 1000
        self.assertEqual(charges.food_tax, Decimal("50.00"))
        self.assertEqual(charges.tax_amount, Decimal("50.00"))
        self.assertEqual(charges.total_amount, Decimal("1100.00"))

    def test_a_branch_row_missing_the_columns_still_prices(self) -> None:
        # A row written before the columns existed, or a test double. Falling
        # over in a checkout because a column is absent is not an option.
        #
        # Under courier pricing, where the branch's own delivery-tax column is
        # the one read. Slab pricing (the default since 2026-10-07) puts the
        # platform's GST on delivery whatever the row says - deliberately, and
        # `test_delivery_slabs.GstOnTop` holds that rule.
        with mock.patch.dict(os.environ, {"DELIVERY_PRICING": "courier"}):
            get_settings.cache_clear()
            self.addCleanup(get_settings.cache_clear)
            charges = order_charges.for_location(
                SimpleNamespace(),
                subtotal=Decimal("1000"),
                delivery_fee=Decimal("50"),
                discount_amount=Decimal("0"),
            )
        self.assertEqual(charges.food_tax, Decimal("50.00"))
        self.assertEqual(charges.total_amount, Decimal("1100.00"))

    def test_a_branch_that_sets_zero_tax_is_believed(self) -> None:
        # Zero is a real choice, not a missing value, and must not fall back to
        # the 5% default. `for_location` distinguishes them with `is not None`.
        charges = order_charges.for_location(
            SimpleNamespace(tax_percent=Decimal("0")),
            subtotal=Decimal("1000"),
            delivery_fee=Decimal("0"),
            discount_amount=Decimal("0"),
        )
        self.assertEqual(charges.food_tax, Decimal("0.00"))


class WhatIsTaxedAndWhatIsNot(unittest.TestCase):
    """The distinctions that cost money when they are wrong."""

    def test_food_tax_follows_the_discount(self) -> None:
        # A customer who paid less is taxed on less. Taxing the pre-discount
        # subtotal overcharges every customer who ever uses an offer.
        self.assertEqual(bill(discount_amount=Decimal("400")).food_tax, Decimal("30.00"))

    def test_delivery_is_taxed_at_its_own_rate(self) -> None:
        # 18% on the service where food is 5%. Folding them into one rate
        # produces a figure that matches no invoice.
        charges = bill(delivery_tax_percent=Decimal("18"))
        self.assertEqual(charges.delivery_tax, Decimal("9.00"))
        self.assertEqual(charges.food_tax, Decimal("50.00"))

    def test_the_platform_fee_is_never_taxed(self) -> None:
        # It is described to the customer as inclusive of tax. Taxing it again
        # charges them twice for the same thing.
        with_fee = bill(platform_fee=Decimal("20"))
        without = bill()
        self.assertEqual(with_fee.food_tax, without.food_tax)
        self.assertEqual(with_fee.total_amount - without.total_amount, Decimal("20.00"))

    def test_packaging_is_taxed_at_the_food_rate(self) -> None:
        # It is part of the restaurant's charge for the meal, not a separate
        # service, so it carries the food rate.
        self.assertEqual(bill(packaging_fee=Decimal("100")).food_tax, Decimal("55.00"))

    def test_a_discount_larger_than_the_food_never_taxes_below_zero(self) -> None:
        charges = bill(subtotal=Decimal("100"), discount_amount=Decimal("500"))
        self.assertEqual(charges.food_tax, Decimal("0.00"))


class TheCollapsedLineAndItsParts(unittest.TestCase):
    """One row on the bill, and what opens behind it."""

    def test_the_line_is_the_sum_of_the_parts(self) -> None:
        # If these ever disagree, a customer adding up the modal gets a
        # different answer from the row that opened it.
        charges = bill(
            packaging_fee=Decimal("30"),
            platform_fee=Decimal("17.98"),
            delivery_tax_percent=Decimal("18"),
        )
        self.assertEqual(charges.tax_amount, sum(line.amount for line in charges.lines))

    def test_the_total_is_the_sum_of_everything_shown(self) -> None:
        charges = bill(
            discount_amount=Decimal("200"),
            packaging_fee=Decimal("30"),
            platform_fee=Decimal("17.98"),
            delivery_tax_percent=Decimal("18"),
        )
        self.assertEqual(
            charges.total_amount,
            charges.subtotal - charges.discount_amount + charges.delivery_fee + charges.tax_amount,
        )

    def test_a_charge_of_zero_gets_no_row(self) -> None:
        # A modal listing "Platform fee ₹0" invites the question of why it is
        # there at all.
        keys = {line.key for line in bill().lines}
        self.assertEqual(keys, {"food_tax"})

    def test_every_fee_row_explains_itself(self) -> None:
        # A fee with no sentence under it is assumed to be a tax, or assumed to
        # be the restaurant keeping it.
        charges = bill(packaging_fee=Decimal("30"), platform_fee=Decimal("18"))
        for line in charges.lines:
            with self.subTest(line=line.key):
                self.assertTrue(line.note, f"{line.key} has nothing explaining it")

    def test_nothing_charged_means_nothing_to_open(self) -> None:
        charges = bill(tax_percent=Decimal("0"))
        self.assertEqual(charges.lines, [])
        self.assertEqual(charges.tax_amount, Decimal("0.00"))


class Rounding(unittest.TestCase):
    def test_money_lands_on_two_places(self) -> None:
        charges = bill(subtotal=Decimal("333.33"), tax_percent=Decimal("5"))
        self.assertEqual(charges.food_tax.as_tuple().exponent, -2)
        self.assertEqual(charges.total_amount.as_tuple().exponent, -2)

    def test_half_rounds_up_not_to_even(self) -> None:
        # These figures sit in a column somebody adds up by eye. Banker's
        # rounding is correct and looks like a mistake.
        charges = bill(subtotal=Decimal("0"), delivery_fee=Decimal("1.50"),
                       delivery_tax_percent=Decimal("50"))
        self.assertEqual(charges.delivery_tax, Decimal("0.75"))


class TheSettingsFormCanActuallySaveThese(unittest.TestCase):
    """The branch settings endpoint must accept every rate the form sends.

    Reported as "I change the value, it says saved, and the old one comes
    back". The form had learned to send the four charge rates; the schema
    behind `PATCH .../general-settings` had not, and Pydantic's default is to
    DROP a field it does not recognise. So the endpoint answered 200, saved
    nothing, and the page re-rendered the stale values it had just been given
    back — with nothing in any log.

    Two guards. The first asserts each field is accepted. The second is the one
    that matters: the schema now forbids extras, so the next time a form learns
    a field before the schema does, it is a 422 somebody fixes in a minute
    rather than a silence reported as "it does not save".
    """

    def test_every_charge_rate_is_accepted(self) -> None:
        from app.schemas.restaurant import RestaurantLocationGeneralSettingsUpdate

        payload = RestaurantLocationGeneralSettingsUpdate(
            packaging_fee=Decimal("30"),
            platform_fee=Decimal("17.98"),
            tax_percent=Decimal("5"),
            delivery_tax_percent=Decimal("18"),
        )
        # `exclude_unset` is what the endpoint writes with, so a field missing
        # here never reaches the row.
        written = payload.model_dump(exclude_unset=True)
        self.assertEqual(
            set(written),
            {"packaging_fee", "platform_fee", "tax_percent", "delivery_tax_percent"},
        )

    def test_an_unknown_field_is_refused_rather_than_dropped(self) -> None:
        import pydantic

        from app.schemas.restaurant import RestaurantLocationGeneralSettingsUpdate

        with self.assertRaises(pydantic.ValidationError):
            RestaurantLocationGeneralSettingsUpdate(some_field_nobody_added=1)

    def test_a_rate_above_a_hundred_percent_is_refused(self) -> None:
        # A typo here charges every customer of this branch.
        import pydantic

        from app.schemas.restaurant import RestaurantLocationGeneralSettingsUpdate

        with self.assertRaises(pydantic.ValidationError):
            RestaurantLocationGeneralSettingsUpdate(tax_percent=Decimal("500"))


if __name__ == "__main__":
    unittest.main()
