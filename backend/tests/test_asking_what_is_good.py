"""Asking what is good, or what is cheapest, is not a dish search.

From the persona run, at a branch with 136 dishes:

    > what do you recommend
      I could not find what do you recommend on the menu. This is what we do
      have: [eight dishes, none of them chosen for any reason]

    > what's your cheapest item
      I could not find cheapest item on the menu. ...

Both were searched for as though the words named a dish, and both echoed the
customer's own question back as the thing that does not exist. They are two of
the commonest things anybody types.

Both are answerable from this branch's own columns. `is_bestseller` and
`popularity_score` are what "what's good" means here, and `price` is what
"cheapest" means — no taste is being invented, and nothing comes from another
branch's menu: every query is scoped to `restaurant_location_id`, the same way
`dishes_to_suggest` already is.

What is NOT added is anything the menu cannot answer. There is no jain flag and
no spice level on `menu_items`, so "anything jain" and "nothing too spicy" are
left alone rather than answered from a guess.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.planner import quick_read


class AskingWhatIsGoodTests(unittest.TestCase):
    """The recommendation family."""

    def test_the_reported_message(self) -> None:
        self.assertEqual(quick_read("what do you recommend"), "suggest")

    def test_the_ways_people_ask_for_a_recommendation(self) -> None:
        for message in (
            "recommend", "recommendations", "any recommendations",
            "suggest something", "suggestions",
            "what's good", "whats good", "what's popular", "popular",
            "best", "what is the best dish", "bestseller", "bestsellers",
            "most popular", "must try", "what do you suggest",
        ):
            with self.subTest(message=message):
                self.assertEqual(quick_read(message), "suggest")


class AskingWhatIsCheapestTests(unittest.TestCase):
    """The price family."""

    def test_the_reported_message(self) -> None:
        self.assertEqual(quick_read("what's your cheapest item"), "cheapest")

    def test_the_ways_people_ask_for_the_cheapest(self) -> None:
        for message in (
            "cheapest", "cheapest item", "cheapest dish", "what is cheapest",
            "anything cheap", "something cheap", "cheap", "lowest price",
        ):
            with self.subTest(message=message):
                self.assertEqual(quick_read(message), "cheapest")


class WhatIsLeftAloneTests(unittest.TestCase):
    """The menu has no column for these, so nothing is claimed about them."""

    def test_a_diet_the_menu_does_not_record(self) -> None:
        # `menu_items` has `is_veg` and nothing for jain or for heat. Mapping
        # these to a canned answer would be inventing a filter.
        for message in ("anything jain", "nothing too spicy please", "is it halal"):
            with self.subTest(message=message):
                self.assertNotIn(quick_read(message), {"suggest", "cheapest"})

    def test_a_dish_is_still_a_dish(self) -> None:
        # "Radhe Special Pulao" and "Special Thali" are real dishes; naming one
        # must not be read as "surprise me".
        for message in ("Radhe Special Pulao", "khaman dhokla", "Manchow Soup"):
            with self.subTest(message=message):
                self.assertIsNone(quick_read(message))

    def test_the_signals_that_already_existed_are_untouched(self) -> None:
        self.assertEqual(quick_read("menu"), "menu")
        self.assertEqual(quick_read("cart"), "cart")
        self.assertEqual(quick_read("checkout"), "checkout")
        self.assertEqual(quick_read("categories"), "menu")

    def test_turning_something_down_is_not_a_request(self) -> None:
        for message in ("no recommendations", "nothing cheap", "dont suggest"):
            with self.subTest(message=message):
                self.assertIsNone(quick_read(message))


if __name__ == "__main__":
    unittest.main()
