"""Half-and-half toppings: pepperoni on one side, mushroom on the other.

A pizza is the obvious case, but nothing here is pizza-specific: a group the
owner marks as splittable lets each chosen option apply to the WHOLE item, its
LEFT half or its RIGHT half.

Two decisions worth stating, because both are product choices rather than
consequences of the schema:

* A half portion costs HALF the option's extra price, rounded the same way
  every other amount in this module is. Charging full price for half coverage
  is defensible and some chains do it, but it is the choice a customer is most
  likely to call wrong, and "I only got it on half, so I pay half" needs no
  explaining.
* The same topping chosen for BOTH halves is the same thing as choosing it for
  the whole item, so it is normalised to WHOLE. It prices identically either
  way; the point is that the kitchen ticket reads "Pepperoni" rather than
  "Pepperoni (left half), Pepperoni (right half)".

Groups that are not marked splittable reject LEFT and RIGHT outright, so a
client cannot half-price a topping on an item the kitchen cannot split.
"""

from __future__ import annotations

import unittest
import uuid
from decimal import Decimal

from fastapi import HTTPException

from app.main import app  # noqa: F401 - imported first to settle import order
from app.models.enums import (
    MenuItemCustomizationSelectionType,
    MenuItemPortion,
)
from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.services.menu_item_customizations import (
    SelectedCustomizationOptionInput,
    resolve_menu_item_selection,
)


def option(name: str, extra_price: str, **over) -> MenuItemCustomizationOption:
    return MenuItemCustomizationOption(
        id=over.get("id", uuid.uuid4()),
        group_id=over.get("group_id", uuid.uuid4()),
        name=name,
        extra_price=Decimal(extra_price),
        is_active=over.get("is_active", True),
        is_countable=over.get("is_countable", False),
        sort_order=0,
    )


def build_pizza(*, supports_halves: bool = True, max_selection: int = 4) -> MenuItem:
    """A pizza with one splittable toppings group."""

    item = MenuItem(
        id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        restaurant_location_id=uuid.uuid4(),
        name="Margherita",
        category="Pizza",
        price=Decimal("12.00"),
        is_veg=True,
        is_available=True,
        has_sizes=False,
        has_customizations=True,
    )
    group = MenuItemCustomizationGroup(
        id=uuid.uuid4(),
        menu_item_id=item.id,
        menu_item_size_id=None,
        title="Toppings",
        selection_type=MenuItemCustomizationSelectionType.MULTI,
        is_required=False,
        min_selection=0,
        max_selection=max_selection,
        is_active=True,
        sort_order=0,
        supports_halves=supports_halves,
    )
    group.options = [
        option("Pepperoni", "3.00", group_id=group.id, id=PEPPERONI_ID),
        option("Mushroom", "2.50", group_id=group.id, id=MUSHROOM_ID),
        option("Olives", "1.25", group_id=group.id, id=OLIVES_ID),
    ]
    item.sizes = []
    item.customization_groups = [group]
    return item


PEPPERONI_ID = uuid.uuid4()
MUSHROOM_ID = uuid.uuid4()
OLIVES_ID = uuid.uuid4()


def choose(option_id: uuid.UUID, portion: MenuItemPortion = MenuItemPortion.WHOLE, quantity: int = 1):
    return SelectedCustomizationOptionInput(
        option_id=option_id, quantity=quantity, portion=portion
    )


class HalfPricingTests(unittest.TestCase):
    def test_a_whole_topping_costs_its_full_extra_price(self) -> None:
        resolved = resolve_menu_item_selection(
            build_pizza(),
            menu_item_size_id=None,
            selected_options=[choose(PEPPERONI_ID)],
        )
        self.assertEqual(resolved.customization_total_price, Decimal("3.00"))
        self.assertEqual(resolved.unit_price, Decimal("15.00"))

    def test_a_half_topping_costs_half(self) -> None:
        resolved = resolve_menu_item_selection(
            build_pizza(),
            menu_item_size_id=None,
            selected_options=[choose(PEPPERONI_ID, MenuItemPortion.LEFT)],
        )
        self.assertEqual(resolved.customization_total_price, Decimal("1.50"))
        self.assertEqual(resolved.unit_price, Decimal("13.50"))

    def test_two_different_halves_are_priced_independently(self) -> None:
        # The headline case: pepperoni one side, mushroom the other.
        resolved = resolve_menu_item_selection(
            build_pizza(),
            menu_item_size_id=None,
            selected_options=[
                choose(PEPPERONI_ID, MenuItemPortion.LEFT),
                choose(MUSHROOM_ID, MenuItemPortion.RIGHT),
            ],
        )
        # 3.00/2 + 2.50/2
        self.assertEqual(resolved.customization_total_price, Decimal("2.75"))

    def test_an_odd_half_price_rounds_the_way_every_other_amount_does(self) -> None:
        # Olives are 1.25, so a half is 0.625 and must land on 0.63, not 0.62.
        resolved = resolve_menu_item_selection(
            build_pizza(),
            menu_item_size_id=None,
            selected_options=[choose(OLIVES_ID, MenuItemPortion.RIGHT)],
        )
        self.assertEqual(resolved.customization_total_price, Decimal("0.63"))


class BothHalvesMeanWholeTests(unittest.TestCase):
    def test_the_same_topping_on_both_halves_becomes_whole(self) -> None:
        resolved = resolve_menu_item_selection(
            build_pizza(),
            menu_item_size_id=None,
            selected_options=[
                choose(PEPPERONI_ID, MenuItemPortion.LEFT),
                choose(PEPPERONI_ID, MenuItemPortion.RIGHT),
            ],
        )
        self.assertEqual(len(resolved.selected_options), 1)
        self.assertEqual(resolved.selected_options[0].portion, MenuItemPortion.WHOLE)
        # And it costs exactly what a whole one costs, not two halves rounded up.
        self.assertEqual(resolved.customization_total_price, Decimal("3.00"))

    def test_the_snapshot_says_which_half(self) -> None:
        resolved = resolve_menu_item_selection(
            build_pizza(),
            menu_item_size_id=None,
            selected_options=[choose(MUSHROOM_ID, MenuItemPortion.LEFT)],
        )
        snapshot = resolved.selected_options_snapshot()
        self.assertEqual(snapshot[0]["portion"], "LEFT")
        # The kitchen needs the price it was charged at, not the list price.
        self.assertEqual(snapshot[0]["extra_price"], "1.25")


class SplittingMustBeAllowedTests(unittest.TestCase):
    def test_a_group_that_does_not_support_halves_refuses_a_half(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            resolve_menu_item_selection(
                build_pizza(supports_halves=False),
                menu_item_size_id=None,
                selected_options=[choose(PEPPERONI_ID, MenuItemPortion.LEFT)],
            )
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("half", str(caught.exception.detail).lower())

    def test_a_group_that_does_not_support_halves_still_takes_whole(self) -> None:
        resolved = resolve_menu_item_selection(
            build_pizza(supports_halves=False),
            menu_item_size_id=None,
            selected_options=[choose(PEPPERONI_ID)],
        )
        self.assertEqual(resolved.customization_total_price, Decimal("3.00"))

    def test_the_same_topping_twice_on_the_same_half_is_still_a_duplicate(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            resolve_menu_item_selection(
                build_pizza(),
                menu_item_size_id=None,
                selected_options=[
                    choose(PEPPERONI_ID, MenuItemPortion.LEFT),
                    choose(PEPPERONI_ID, MenuItemPortion.LEFT),
                ],
            )
        self.assertIn("duplicate", str(caught.exception.detail).lower())


class HalvesCountTowardsLimitsTests(unittest.TestCase):
    def test_each_half_counts_as_one_selection(self) -> None:
        # A max of 2 means two toppings, whichever side they are on.
        with self.assertRaises(HTTPException) as caught:
            resolve_menu_item_selection(
                build_pizza(max_selection=2),
                menu_item_size_id=None,
                selected_options=[
                    choose(PEPPERONI_ID, MenuItemPortion.LEFT),
                    choose(MUSHROOM_ID, MenuItemPortion.RIGHT),
                    choose(OLIVES_ID, MenuItemPortion.LEFT),
                ],
            )
        self.assertIn("at most", str(caught.exception.detail).lower())

    def test_a_topping_normalised_to_whole_counts_once(self) -> None:
        # Left + right of the same topping is ONE topping, so a max of 1 allows
        # it. Counting it as two would refuse an order that is really "whole".
        resolved = resolve_menu_item_selection(
            build_pizza(max_selection=1),
            menu_item_size_id=None,
            selected_options=[
                choose(PEPPERONI_ID, MenuItemPortion.LEFT),
                choose(PEPPERONI_ID, MenuItemPortion.RIGHT),
            ],
        )
        self.assertEqual(len(resolved.selected_options), 1)


if __name__ == "__main__":
    unittest.main()
