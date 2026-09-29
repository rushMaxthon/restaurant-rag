"""Two versions of one dish are two lines, and the order can still be placed.

Live, on WhatsApp, with this cart:

    - 1 x Chiang Mai Noodle Box - $16.29
    - 1 x Build Your Own Pizza (Large (14")) - $24.49
    - 1 x Build Your Own Pizza (Large (14")) - $25.49
    - 1 x Coconut Turmeric Rice - $4.99

    > PROCEED CHECKOUT
      I could not place that: Duplicate menu items are not allowed in the cart.

Two pizzas, same dish, different sauce — $24.49 and $25.49 — and the whole
order refused for it. The customer had built both through four questions each.

`fetch_menu_items_for_customized_order` rejected any repeated `menu_item_id`
before running its query. Neither caller needed that: both walk the cart's
lines and look each one's dish up in the dict it returns, so a repeated id
simply finds the same dish twice, which is correct. The cart itself already
merges IDENTICAL lines — same dish, same size, same options — into one line
with a bigger count, so the only carts that ever reached this check with a
repeat were exactly the legitimate ones: the same dish, differently made.

The ids are deduplicated for the query instead. Nothing else about the
function changes: a dish from another restaurant, a dish that does not exist
and a dish that has gone unavailable are refused exactly as before.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.services import menu_item_customizations as customizations

RESTAURANT = uuid.uuid4()
BRANCH = uuid.uuid4()
PIZZA = uuid.uuid4()
RICE = uuid.uuid4()


def a_dish(menu_item_id, name="Build Your Own Pizza", available=True):
    return SimpleNamespace(id=menu_item_id, name=name, is_available=available)


def fetching(rows):
    """Run the fetch against a session whose query answers with `rows`."""

    db = mock.MagicMock()
    db.scalars.return_value.all.return_value = rows
    return db


class TheSameDishTwiceTests(unittest.TestCase):
    """The order from the thread."""

    def test_a_repeated_dish_is_not_refused(self) -> None:
        db = fetching([a_dish(PIZZA), a_dish(RICE, "Coconut Turmeric Rice")])
        found = customizations.fetch_menu_items_for_customized_order(
            db,
            restaurant_id=RESTAURANT,
            restaurant_location_id=BRANCH,
            menu_item_ids=[PIZZA, PIZZA, RICE],
        )
        self.assertEqual(set(found), {PIZZA, RICE})

    def test_each_line_can_still_find_its_dish(self) -> None:
        # Both callers do `found[line.menu_item_id]` per line; two pizza
        # lines both resolve to the pizza.
        db = fetching([a_dish(PIZZA)])
        found = customizations.fetch_menu_items_for_customized_order(
            db,
            restaurant_id=RESTAURANT,
            restaurant_location_id=BRANCH,
            menu_item_ids=[PIZZA, PIZZA],
        )
        self.assertIs(found[PIZZA], found[PIZZA])
        self.assertEqual(found[PIZZA].name, "Build Your Own Pizza")


class WhatIsStillRefusedTests(unittest.TestCase):
    """The checks that were worth keeping, unchanged."""

    def test_a_dish_that_does_not_exist_here(self) -> None:
        db = fetching([a_dish(PIZZA)])
        with self.assertRaises(HTTPException) as caught:
            customizations.fetch_menu_items_for_customized_order(
                db,
                restaurant_id=RESTAURANT,
                restaurant_location_id=BRANCH,
                menu_item_ids=[PIZZA, RICE],
            )
        self.assertIn("not found", caught.exception.detail)

    def test_a_dish_that_has_gone_unavailable(self) -> None:
        db = fetching([a_dish(PIZZA, available=False)])
        with self.assertRaises(HTTPException) as caught:
            customizations.fetch_menu_items_for_customized_order(
                db,
                restaurant_id=RESTAURANT,
                restaurant_location_id=BRANCH,
                menu_item_ids=[PIZZA],
            )
        self.assertIn("Unavailable", caught.exception.detail)

    def test_a_missing_dish_is_counted_against_the_unique_ids(self) -> None:
        # With [PIZZA, PIZZA, RICE] asked for and only the pizza returned,
        # the rice is missing. Counting the repeat as a second missing dish
        # was the old behaviour's other way of going wrong.
        db = fetching([a_dish(PIZZA)])
        with self.assertRaises(HTTPException):
            customizations.fetch_menu_items_for_customized_order(
                db,
                restaurant_id=RESTAURANT,
                restaurant_location_id=BRANCH,
                menu_item_ids=[PIZZA, PIZZA, RICE],
            )


if __name__ == "__main__":
    unittest.main()
