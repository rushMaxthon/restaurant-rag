"""The platform's commission, inside the menu price.

The owner types 100; at the default 10% the customer sees 110 and pays 110.
The rate is one number per branch, set by the platform's admin, and 0 means
the menu is exactly what was typed.

The way this goes wrong is always the same: two figures for one dish. So the
price is WRITTEN when the rate moves or an item is saved, and everything that
reads a price reads the result. What is pinned here is the writing.

**Marked up twice.** The editor loads a price, the owner changes the name, the
editor saves the price back. If what it loaded was 110, the item is now 121
and goes up again on every save. The typed figure is kept beside the price and
is what an editor is handed.

**No way back.** 110 / 1.10 is 100, but 54.95 / 1.10 is 49.9545. Changing the
rate starts again from the typed figure, where it was kept, not by division.

**A cart that does not add up.** Half of an extra, and three of a dish, are
worked out from the LISTED price by three clients. The listed price is
therefore rounded to the paisa once, here, before anything multiplies it.

**An owner lowering the platform's cut.** The rate is the platform's, on a
form the owner also uses. The server refuses an owner who changes it; hiding
the field is not the rule.
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.enums import UserRole  # noqa: E402
from app.services import menu_pricing  # noqa: E402
from app.services.menu_pricing import (  # noqa: E402
    commission_percent_of,
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
    def test_the_default_is_ten_percent(self) -> None:
        from app.models.restaurant_location import RestaurantLocation
        from app.schemas.restaurant import RestaurantLocationBase

        self.assertEqual(menu_pricing.DEFAULT_COMMISSION_PERCENT, D("10.00"))
        column = RestaurantLocation.__table__.columns["commission_percent"]
        self.assertEqual(column.default.arg, D("10.00"))
        self.assertEqual(D(column.server_default.arg), D("10.00"))
        self.assertEqual(
            RestaurantLocationBase.model_fields["commission_percent"].default, D("10.00")
        )

    def test_ten_percent_on_what_was_typed(self) -> None:
        self.assertEqual(listed_price(D("100"), commission_percent=D("10")), D("110.00"))
        self.assertEqual(listed_price(D("249"), commission_percent=D("10")), D("273.90"))

    def test_the_rate_is_whatever_the_branch_is_set_to(self) -> None:
        self.assertEqual(listed_price(D("100"), commission_percent=D("12.5")), D("112.50"))
        self.assertEqual(listed_price(D("100"), commission_percent=D("25")), D("125.00"))

    def test_no_commission_is_the_typed_price(self) -> None:
        self.assertEqual(listed_price(D("100"), commission_percent=D("0")), D("100.00"))
        self.assertEqual(listed_price(D("100"), commission_percent=None), D("100.00"))

    def test_it_is_rounded_to_the_paisa_half_up(self) -> None:
        # 49.95 * 1.10 = 54.945. Banker's rounding gives 54.94, and a column
        # somebody adds up by eye then looks short.
        self.assertEqual(listed_price(D("49.95"), commission_percent=D("10")), D("54.95"))

    def test_a_free_extra_stays_free(self) -> None:
        self.assertEqual(listed_price(D("0"), commission_percent=D("10")), D("0.00"))
        self.assertEqual(listed_price(None, commission_percent=D("10")), D("0.00"))

    def test_a_stand_in_branch_has_no_commission(self) -> None:
        # Several suites build a Mock branch, whose every attribute is a Mock.
        self.assertEqual(commission_percent_of(mock.Mock()), D("0.00"))
        self.assertEqual(commission_percent_of(SimpleNamespace()), D("0.00"))
        self.assertEqual(
            commission_percent_of(SimpleNamespace(commission_percent=D("10.00"))), D("10.00")
        )


class SavingAnItemTests(unittest.TestCase):
    def test_everything_on_the_item_is_listed_and_the_typed_figure_is_kept(self) -> None:
        item = an_item(
            "200",
            sizes=[a_size("200"), a_size("350")],
            options=[an_option("30"), an_option("0")],
        )
        stamp_entered_prices(item, commission_percent=D("10"))

        self.assertEqual((item.base_price, item.price), (D("200.00"), D("220.00")))
        self.assertEqual([s.base_price for s in item.sizes], [D("200.00"), D("350.00")])
        self.assertEqual([s.price for s in item.sizes], [D("220.00"), D("385.00")])
        options = item.customization_groups[0].options
        self.assertEqual([o.base_extra_price for o in options], [D("30.00"), D("0.00")])
        self.assertEqual([o.extra_price for o in options], [D("33.00"), D("0.00")])

    def test_what_was_typed_wins_over_what_was_recorded(self) -> None:
        # The owner changed 100 to 120. The price column holds the 120 they
        # typed; the base still says 100 and must not be believed.
        item = an_item("120", base="100")
        stamp_entered_prices(item, commission_percent=D("10"))
        self.assertEqual((item.base_price, item.price), (D("120.00"), D("132.00")))

    def test_a_branch_at_zero_sells_at_the_typed_price(self) -> None:
        item = an_item("120", sizes=[a_size("120")], options=[an_option("15")])
        stamp_entered_prices(item, commission_percent=D("0"))
        self.assertEqual((item.base_price, item.price), (D("120.00"), D("120.00")))
        self.assertEqual(item.sizes[0].price, D("120.00"))
        self.assertEqual(item.customization_groups[0].options[0].extra_price, D("15.00"))

    def test_saving_what_the_editor_was_handed_changes_nothing(self) -> None:
        # The double mark-up, as it would happen: load, save, load, save.
        item = an_item("100")
        stamp_entered_prices(item, commission_percent=D("10"))
        for _ in range(3):
            item.price = item.base_price  # the editor sends back the BASE
            stamp_entered_prices(item, commission_percent=D("10"))
        self.assertEqual(item.price, D("110.00"))


class ChangingTheRateTests(unittest.TestCase):
    def test_a_menu_that_never_had_a_base_is_marked_up_once(self) -> None:
        item = an_item("99", sizes=[a_size("99")], options=[an_option("20")])
        relist_menu_item(item, commission_percent=D("10"))
        self.assertEqual((item.base_price, item.price), (D("99.00"), D("108.90")))
        self.assertEqual(item.sizes[0].price, D("108.90"))
        self.assertEqual(item.customization_groups[0].options[0].extra_price, D("22.00"))

    def test_the_same_rate_twice_is_the_rate_once(self) -> None:
        # A retried request, or two tabs. 10% of 110 must never be added.
        item = an_item("100")
        relist_menu_item(item, commission_percent=D("10"))
        relist_menu_item(item, commission_percent=D("10"))
        self.assertEqual(item.price, D("110.00"))

    def test_a_new_rate_starts_from_what_was_typed(self) -> None:
        item = an_item("100")
        relist_menu_item(item, commission_percent=D("10"))
        relist_menu_item(item, commission_percent=D("15"))
        # 15% of 100, not 15% of 110 and not 5% more than 110.
        self.assertEqual((item.base_price, item.price), (D("100.00"), D("115.00")))

    def test_zero_returns_exactly_what_was_typed(self) -> None:
        # 54.95 / 1.10 = 49.9545... — division misses by a paisa somewhere.
        for typed in ("99", "49.95", "0.05", "1234.56"):
            with self.subTest(typed=typed):
                item = an_item(typed)
                relist_menu_item(item, commission_percent=D("10"))
                relist_menu_item(item, commission_percent=D("0"))
                self.assertEqual(item.price, D(typed).quantize(D("0.01")))

    def test_the_cheapest_size_is_still_the_items_price(self) -> None:
        item = an_item("180", sizes=[a_size("180"), a_size("260")])
        relist_menu_item(item, commission_percent=D("10"))
        self.assertEqual(item.price, min(size.price for size in item.sizes))


class SavingTheBranchTests(unittest.TestCase):
    ADMIN = SimpleNamespace(role=UserRole.ADMIN)
    OWNER = SimpleNamespace(role=UserRole.OWNER)

    def apply(self, branch, changes, user=None):
        from app.api import restaurants

        with mock.patch.object(menu_pricing, "reprice_location", return_value=["item"]) as reprice:
            result = restaurants._apply_location_changes(
                mock.Mock(), branch, dict(changes), user or self.ADMIN
            )
        return result, reprice

    def test_changing_the_rate_reprices_the_menu(self) -> None:
        branch = SimpleNamespace(commission_percent=D("10.00"))
        result, reprice = self.apply(branch, {"commission_percent": D("12.00")})
        reprice.assert_called_once()
        self.assertEqual(result, ["item"])
        self.assertEqual(branch.commission_percent, D("12.00"))

    def test_a_save_that_leaves_it_alone_reprices_nothing(self) -> None:
        # Every save of the settings form sends the rate along with the rest,
        # and a form sends 10 where the column holds 10.00.
        branch = SimpleNamespace(commission_percent=D("10.00"), delivery_fee=D("0"))
        result, reprice = self.apply(
            branch, {"commission_percent": D("10"), "delivery_fee": D("40")}
        )
        reprice.assert_not_called()
        self.assertEqual(result, [])
        self.assertEqual(branch.delivery_fee, D("40"))

    def test_a_null_is_no_opinion(self) -> None:
        branch = SimpleNamespace(commission_percent=D("10.00"))
        _, reprice = self.apply(branch, {"commission_percent": None})
        reprice.assert_not_called()
        self.assertEqual(branch.commission_percent, D("10.00"))

    def test_the_gst_switch_still_reprices_nothing(self) -> None:
        branch = SimpleNamespace(commission_percent=D("10.00"), gst_in_menu_prices=False)
        result, reprice = self.apply(branch, {"gst_in_menu_prices": True})
        reprice.assert_not_called()
        self.assertEqual(result, [])
        self.assertTrue(branch.gst_in_menu_prices)

    def test_only_the_platform_admin_is_told_the_rate(self) -> None:
        # The owner's branch page had a tile reading "10% commission". The
        # rate is the platform's term with the restaurant, not a figure for
        # the owner's dashboard.
        from app.services.menu_pricing import sees_commission_rate

        self.assertTrue(sees_commission_rate(SimpleNamespace(role=UserRole.ADMIN)))
        for role in (UserRole.OWNER, UserRole.KITCHEN, UserRole.CUSTOMER):
            with self.subTest(role=role):
                self.assertFalse(sees_commission_rate(SimpleNamespace(role=role)))

    def test_an_owner_is_still_handed_the_price_they_typed(self) -> None:
        # Hiding the rate must not hide this: the editor loads the typed
        # price, and loading the listed one marks the dish up on every save.
        from app.services.menu_pricing import sees_typed_prices

        self.assertTrue(sees_typed_prices(SimpleNamespace(role=UserRole.OWNER)))

    def test_an_owner_may_not_change_the_platforms_rate(self) -> None:
        branch = SimpleNamespace(commission_percent=D("10.00"), delivery_fee=D("0"))
        with self.assertRaises(HTTPException) as refused:
            self.apply(
                branch, {"commission_percent": D("0"), "delivery_fee": D("40")}, self.OWNER
            )
        self.assertEqual(refused.exception.status_code, 403)
        # Refused whole: the fee beside it is not half-saved.
        self.assertEqual(branch.commission_percent, D("10.00"))
        self.assertEqual(branch.delivery_fee, D("0"))

    def test_an_owner_saving_the_form_unchanged_is_not_refused(self) -> None:
        # The owner's form carries the rate it was shown.
        branch = SimpleNamespace(commission_percent=D("10.00"), delivery_fee=D("0"))
        _, reprice = self.apply(
            branch, {"commission_percent": D("10"), "delivery_fee": D("40")}, self.OWNER
        )
        reprice.assert_not_called()
        self.assertEqual(branch.delivery_fee, D("40"))


class WhatACustomerIsSentTests(unittest.TestCase):
    """The rate, and the typed price that gives it away, go to staff only.

    The branch and menu routes answer the storefront as well as the dashboard.
    A customer is sent the price they pay; `commission_percent` and
    `base_price` beside it would let anybody read the platform's cut off the
    network tab.
    """

    def test_only_the_roles_that_manage_a_menu_see_them(self) -> None:
        from app.services.menu_pricing import sees_typed_prices

        for role in (UserRole.ADMIN, UserRole.OWNER):
            with self.subTest(role=role):
                self.assertTrue(sees_typed_prices(SimpleNamespace(role=role)))
        for role in (UserRole.CUSTOMER, UserRole.KITCHEN):
            with self.subTest(role=role):
                self.assertFalse(sees_typed_prices(SimpleNamespace(role=role)))

    def test_nobody_is_a_customer(self) -> None:
        # An anonymous storefront request, and a serializer called without a
        # viewer by code written later: both must hide, not publish.
        from app.services.menu_pricing import sees_commission_rate, sees_typed_prices

        self.assertFalse(sees_commission_rate(None))
        self.assertFalse(sees_commission_rate(mock.Mock()))
        self.assertFalse(sees_typed_prices(None))
        self.assertFalse(sees_typed_prices(mock.Mock()))

    def test_the_serializers_hide_unless_told_who_is_asking(self) -> None:
        import inspect

        from app.services.favorites import serialize_menu_item, serialize_menu_items
        from app.services.restaurant_locations import build_location_response

        for fn in (serialize_menu_item, serialize_menu_items, build_location_response):
            with self.subTest(fn=fn.__name__):
                self.assertIsNone(inspect.signature(fn).parameters["viewer"].default)

    def test_a_dish_is_serialised_without_the_typed_price_for_a_customer(self) -> None:
        from app.services.favorites import _serialize_menu_item_customization_option as option
        from app.services.favorites import _serialize_menu_item_size as size_of

        row = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001", name="Large", price=D("110.00"),
            base_price=D("100.00"), is_active=True, sort_order=0, customization_groups=[],
            stock_quantity=None, stock_daily_quantity=None,
        )
        self.assertIsNone(size_of(row).base_price)
        self.assertEqual(size_of(row, typed=True).base_price, D("100.00"))
        self.assertEqual(size_of(row).price, D("110.00"))

        extra = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000002", name="Cheese", extra_price=D("22.00"),
            base_extra_price=D("20.00"), is_active=True, is_countable=False, sort_order=0,
        )
        self.assertIsNone(option(extra).base_extra_price)
        self.assertEqual(option(extra, typed=True).base_extra_price, D("20.00"))

    def test_the_branch_response_can_carry_no_rate(self) -> None:
        from app.schemas.restaurant import RestaurantLocationResponse

        field = RestaurantLocationResponse.model_fields["commission_percent"]
        self.assertIsNone(field.default)


if __name__ == "__main__":
    unittest.main()
