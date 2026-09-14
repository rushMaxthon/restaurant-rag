"""What an owner may save for a customization group.

Three reports, all of them states the schema allowed and the customer then met:

* a group marked "not required" with `min_selection = 1` behaved as required,
  because the minimum is what gets enforced. The flag said optional and the
  order was refused;
* `min_selection` could exceed the number of options, which makes the item
  impossible to order at all - the customer is told to choose three from a list
  of one and can never finish;
* a new MULTI group took `max_selection = 1` from the field default, so a
  toppings group silently allowed exactly one topping.

The validator is the right place for all three: the admin UI, the seed script
and any future import all go through it, and a rule enforced in one screen is
a rule that holds until someone writes a second screen.
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.main import app  # noqa: F401 - imported first to settle import order
from app.models.enums import MenuItemCustomizationSelectionType
from app.schemas.menu_item import MenuItemCustomizationGroupPayload


def option(name: str = "Extra peanuts", extra_price: str = "1.50") -> dict:
    return {"name": name, "extra_price": extra_price, "is_active": True, "sort_order": 0}


def group(**over) -> dict:
    payload = {
        "title": "Toppings",
        "selection_type": MenuItemCustomizationSelectionType.MULTI,
        "is_required": False,
        "min_selection": 0,
        "is_active": True,
        "sort_order": 0,
        "options": [option()],
    }
    payload.update(over)
    return payload


class MinimumImpliesRequiredTests(unittest.TestCase):
    def test_a_minimum_of_one_makes_the_group_required(self) -> None:
        # Not an error: the owner's intent is clear, and the minimum is what the
        # order endpoint enforces. Normalising keeps the stored row honest so
        # the customer app can label it correctly from the flag alone.
        parsed = MenuItemCustomizationGroupPayload(
            **group(is_required=False, min_selection=1, options=[option(), option("Chilli")])
        )
        self.assertTrue(parsed.is_required)

    def test_a_minimum_of_zero_leaves_the_group_optional(self) -> None:
        parsed = MenuItemCustomizationGroupPayload(**group(is_required=False, min_selection=0))
        self.assertFalse(parsed.is_required)

    def test_required_with_no_minimum_still_gets_one(self) -> None:
        parsed = MenuItemCustomizationGroupPayload(**group(is_required=True, min_selection=1))
        self.assertTrue(parsed.is_required)
        self.assertGreaterEqual(parsed.min_selection, 1)


class MinimumMustBeSatisfiableTests(unittest.TestCase):
    def test_a_minimum_above_the_option_count_is_refused(self) -> None:
        # Otherwise the item cannot be ordered by anyone, and nothing in the
        # ordering flow can explain why.
        with self.assertRaises(ValidationError) as caught:
            MenuItemCustomizationGroupPayload(
                **group(min_selection=3, max_selection=3, options=[option(), option("Chilli")])
            )
        self.assertIn("options", str(caught.exception).lower())

    def test_a_minimum_equal_to_the_option_count_is_allowed(self) -> None:
        MenuItemCustomizationGroupPayload(
            **group(min_selection=2, max_selection=2, options=[option(), option("Chilli")])
        )


class MultiSelectDefaultsTests(unittest.TestCase):
    def test_a_multi_group_defaults_to_allowing_every_option(self) -> None:
        # The reported default of 1 turned a toppings group into a single
        # choice without anyone asking for that.
        parsed = MenuItemCustomizationGroupPayload(
            **group(options=[option(), option("Chilli"), option("Basil")])
        )
        self.assertEqual(parsed.max_selection, 3)

    def test_an_explicit_maximum_on_a_multi_group_is_respected(self) -> None:
        # Only the DEFAULT changes. An owner who deliberately says "at most 2"
        # still gets 2, and one who says 1 still gets 1.
        parsed = MenuItemCustomizationGroupPayload(
            **group(max_selection=2, options=[option(), option("Chilli"), option("Basil")])
        )
        self.assertEqual(parsed.max_selection, 2)

        one = MenuItemCustomizationGroupPayload(
            **group(max_selection=1, options=[option(), option("Chilli")])
        )
        self.assertEqual(one.max_selection, 1)

    def test_single_select_groups_are_untouched(self) -> None:
        parsed = MenuItemCustomizationGroupPayload(
            **group(
                selection_type=MenuItemCustomizationSelectionType.SINGLE,
                max_selection=1,
                options=[option(), option("Chilli")],
            )
        )
        self.assertEqual(parsed.max_selection, 1)

    def test_single_select_still_refuses_a_maximum_above_one(self) -> None:
        with self.assertRaises(ValidationError):
            MenuItemCustomizationGroupPayload(
                **group(
                    selection_type=MenuItemCustomizationSelectionType.SINGLE,
                    max_selection=2,
                    options=[option(), option("Chilli")],
                )
            )


if __name__ == "__main__":
    unittest.main()
