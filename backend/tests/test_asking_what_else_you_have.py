"""Asking what else there is, in the words people use for it.

From a live WhatsApp thread with Bangkok Bowl:

    > Show me categories
      I could not find categories on the menu. This is what we do have:
      - Appetizer Sampler - $18.99
      ... [seven more appetizers]

    > Show me other items
      I could not find other items on the menu. This is what we do have:
      ... [the same eight appetizers]

Both were searched for as though "categories" and "other items" were dishes,
and both were answered with eight appetizers out of a menu of hundreds. In the
same conversation "Show me menu" worked perfectly, because "menu" is in the
plain-phrase table and those two words are not.

Nothing about the machinery was missing. `quick_read` reduces a sentence to
the words that carry a request — "show me the categories" is already
"categories" by the time it is looked up — and the agent already answers the
`menu` signal with this branch's own sections. The table simply did not list
the other half of the ways somebody asks.

These are phrases, not meanings: every one of them is looked up, and what a
branch actually serves still comes from its own rows. What must not creep in
is a phrase that means something else — "one more", "2 more" and "add more"
are about quantity, and a customer saying them is not asking to browse.
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


class AskingToSeeTheMenuTests(unittest.TestCase):
    """The two from the thread, and the family they belong to."""

    def test_the_reported_messages(self) -> None:
        self.assertEqual(quick_read("Show me categories"), "menu")
        self.assertEqual(quick_read("Show me other items"), "menu")

    def test_asking_for_the_sections(self) -> None:
        for message in ("categories", "category", "sections", "section",
                        "show me the categories", "menu categories"):
            with self.subTest(message=message):
                self.assertEqual(quick_read(message), "menu")

    def test_asking_what_else_there_is(self) -> None:
        for message in ("other items", "more items", "other dishes", "more dishes",
                        "other options", "anything else", "something else",
                        "what else do you have"):
            with self.subTest(message=message):
                self.assertEqual(quick_read(message), "menu")

    def test_asking_for_all_of_it(self) -> None:
        for message in ("full menu", "whole menu", "all items", "list of items"):
            with self.subTest(message=message):
                self.assertEqual(quick_read(message), "menu")

    def test_what_already_worked_still_does(self) -> None:
        for message in ("menu", "Menu", "show me the menu", "menu please", "dishes"):
            with self.subTest(message=message):
                self.assertEqual(quick_read(message), "menu")


class AskingForMoreOfSomethingIsNotBrowsingTests(unittest.TestCase):
    """The words that must not join the table."""

    def test_a_quantity_is_not_a_request_to_browse(self) -> None:
        # "one more" after a dish means another of it. Answering that with the
        # menu would lose an order that was already halfway made.
        for message in ("one more", "2 more", "add more", "more spicy"):
            with self.subTest(message=message):
                self.assertNotEqual(quick_read(message), "menu")

    def test_turning_something_down_is_not_a_request_either(self) -> None:
        # `_NEGATIONS` already guards this; pinned because this change adds
        # phrases that a negation could otherwise ride in on.
        for message in ("no other items", "not the menu", "dont show me categories"):
            with self.subTest(message=message):
                self.assertIsNone(quick_read(message))

    def test_a_dish_is_still_a_dish(self) -> None:
        for message in ("Pad Thai Veg", "khaman dhokla", "Build Your Own Pizza"):
            with self.subTest(message=message):
                self.assertIsNone(quick_read(message))


if __name__ == "__main__":
    unittest.main()
