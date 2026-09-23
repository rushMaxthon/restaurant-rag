"""Asking for something to be taken off takes it off.

With one Vagharela Khaman in the cart:

    > remove the khaman
      Your cart:
      - 1 x Vagharela Khaman (Per Plate) - ₹35
      Subtotal: ₹35. Ready to check out?

    > take it off
      (the same — the khaman still there)

Read back at, not removed. `remove them` happened to work, which made this
look like a phrasing problem. It is not: every one of these reads the same
way. Measured —

    remove the khaman     cancel_order=True
    take it off           cancel_order=True
    remove them           cancel_order=True
    delete the dhokla     cancel_order=True

— because the reading has no way to say "take one line out of the cart"; it
collapses all of them into "cancel the order". The branch that handles
`cancel_order` then looks for a placed order to cancel, finds none, and falls
through. Whether anything was removed came down to whether the model's tool
loop happened to call `remove_from_cart` on its own, which is why one
phrasing worked and the others did not.

The codebase already knew, in the comment beside that branch:

    Dropping an order is never assumed. A message naming a dish is a cart
    edit however it is read — live, "remove the corn fritters" came back as
    a cancellation.

So a cancellation with a cart and no placed order is read as a cart edit, and
which line is decided here from the cart's own rows rather than from the
reading.

Removing is destructive, so it follows the rule the rest of the cart tools
follow: act when there is one obvious answer, ask when there is not.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.loop import cart_lines_named_in

KHAMAN = {"menu_item_id": "m1", "name": "Vagharela Khaman", "quantity": 1}
SOUP = {"menu_item_id": "m2", "name": "Manchow Soup", "quantity": 1}
PIZZA = {"menu_item_id": "m3", "name": "Build Your Own Pizza", "quantity": 1}


class NamingALineTests(unittest.TestCase):
    """Which line a message is about, from the cart's own rows."""

    def test_a_dish_named_in_full(self) -> None:
        self.assertEqual(
            cart_lines_named_in("remove Vagharela Khaman", [KHAMAN, SOUP]), [KHAMAN]
        )

    def test_a_dish_named_in_part(self) -> None:
        # Nobody types the whole name. "khaman" is how somebody refers to a
        # Vagharela Khaman, and it is unambiguous in this cart.
        self.assertEqual(cart_lines_named_in("remove the khaman", [KHAMAN, SOUP]), [KHAMAN])

    def test_case_does_not_matter(self) -> None:
        self.assertEqual(cart_lines_named_in("REMOVE THE SOUP", [KHAMAN, SOUP]), [SOUP])

    def test_two_lines_named_are_both_returned(self) -> None:
        # The caller decides what to do about that; this only reports.
        self.assertEqual(
            cart_lines_named_in("take off the khaman and the soup", [KHAMAN, SOUP]),
            [KHAMAN, SOUP],
        )

    def test_the_order_in_the_cart_is_the_order_returned(self) -> None:
        self.assertEqual(
            cart_lines_named_in("soup and khaman", [KHAMAN, SOUP]), [KHAMAN, SOUP]
        )

    def test_a_word_inside_a_longer_word_is_not_a_line(self) -> None:
        # Or "remove the soupçon" would empty somebody's order.
        self.assertEqual(cart_lines_named_in("soupy noodles", [SOUP]), [])

    def test_naming_nothing_names_nothing(self) -> None:
        for message in ("take it off", "remove them", "remove it", "cancel that", ""):
            with self.subTest(message=message):
                self.assertEqual(cart_lines_named_in(message, [KHAMAN, SOUP]), [])

    def test_an_empty_cart_has_no_lines_to_name(self) -> None:
        self.assertEqual(cart_lines_named_in("remove the khaman", []), [])
        self.assertEqual(cart_lines_named_in("remove the khaman", None), [])

    def test_a_line_with_no_name_is_skipped_not_matched(self) -> None:
        self.assertEqual(cart_lines_named_in("anything", [{"menu_item_id": "m9"}]), [])


class WhichLineToTakeOffTests(unittest.TestCase):
    """Removing is destructive: act on one obvious answer, ask otherwise."""

    def decide(self, message, lines):
        from app.services.ordering_agent.loop import line_to_remove

        return line_to_remove(message, lines)

    def test_the_line_they_named(self) -> None:
        self.assertEqual(self.decide("remove the khaman", [KHAMAN, SOUP]), KHAMAN)

    def test_a_cart_of_one_needs_no_name(self) -> None:
        # "take it off" with one thing in the cart has exactly one meaning.
        self.assertEqual(self.decide("take it off", [KHAMAN]), KHAMAN)
        self.assertEqual(self.decide("remove them", [KHAMAN]), KHAMAN)

    def test_several_lines_and_no_name_is_a_question(self) -> None:
        # Guessing here throws away something somebody chose.
        self.assertIsNone(self.decide("take it off", [KHAMAN, SOUP]))

    def test_several_lines_named_is_a_question_too(self) -> None:
        self.assertIsNone(self.decide("the khaman and the soup", [KHAMAN, SOUP]))

    def test_a_named_line_wins_over_the_count(self) -> None:
        self.assertEqual(self.decide("the pizza", [KHAMAN, SOUP, PIZZA]), PIZZA)

    def test_an_empty_cart_removes_nothing(self) -> None:
        self.assertIsNone(self.decide("remove the khaman", []))


if __name__ == "__main__":
    unittest.main()
