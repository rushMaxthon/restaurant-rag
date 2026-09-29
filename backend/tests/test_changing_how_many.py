"""Changing how many is a change of quantity, not a new order.

With a size question standing on a khaman:

    > add 2 khaman dhokla
      Which size for Vagharela Khaman?
    > actually make it 3
      Please specify what you'd like to make 3 of.

And after an add, "make it 3" reached the suggestion path instead. Measured,
the reading is the same either way and loses the number entirely:

    actually make it 3    wants_to_add=True
    make it 3             wants_to_add=True
    3 please              wants_to_add=True
    change to 2           wants_to_add=True
    make that two         wants_to_add=True

No dish, no quantity, nothing but "they want more of something" — the same
shape as the removal problem: the reading has no way to say "change the count",
so it says the nearest thing it does have.

The number is read off the message here instead. Deliberately ONLY a number:
whether the message names a dish, an option or a cart line is the caller's
question, and this refuses to answer when it cannot be sure which number it is
looking at — "500 ml" is a size, and a message with two numbers in it is not a
quantity change anybody should act on.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.loop import quantity_asked_for


class TheNumberTheyMeantTests(unittest.TestCase):
    """The messages from the run."""

    def test_the_reported_message(self) -> None:
        self.assertEqual(quantity_asked_for("actually make it 3"), 3)

    def test_the_ways_people_say_it(self) -> None:
        for message, wanted in (
            ("make it 3", 3),
            ("3 please", 3),
            ("change to 2", 2),
            ("make that 4", 4),
            ("i want 5", 5),
            ("2", 2),
        ):
            with self.subTest(message=message):
                self.assertEqual(quantity_asked_for(message), wanted)

    def test_a_number_written_as_a_word(self) -> None:
        for message, wanted in (
            ("make that two", 2),
            ("actually make it three", 3),
            ("ten please", 10),
        ):
            with self.subTest(message=message):
                self.assertEqual(quantity_asked_for(message), wanted)


class WhenItRefusesToGuessTests(unittest.TestCase):
    """A wrong number here changes what somebody pays."""

    def test_no_number_at_all(self) -> None:
        for message in ("make it bigger", "anything else", "", "yes"):
            with self.subTest(message=message):
                self.assertIsNone(quantity_asked_for(message))

    def test_two_numbers_are_not_a_quantity(self) -> None:
        # "2 khaman and 3 dhokla" is an order, not a change of count.
        self.assertIsNone(quantity_asked_for("2 khaman and 3 dhokla"))

    def test_a_number_that_is_not_a_count(self) -> None:
        # "500 ml" is a size and "1 Kg" is a size. A cart line of 500 is not
        # something anybody meant.
        for message in ("500 ml", "1000 ml", "make it 500"):
            with self.subTest(message=message):
                self.assertNotEqual(quantity_asked_for(message), 500)

    def test_zero_and_below_are_not_quantities(self) -> None:
        # "make it 0" is a removal, and removal has its own path that asks
        # before it throws anything away.
        self.assertIsNone(quantity_asked_for("make it 0"))
        self.assertIsNone(quantity_asked_for("0"))

    def test_an_absurd_count_is_refused(self) -> None:
        self.assertIsNone(quantity_asked_for("make it 900"))

    def test_a_phone_number_is_not_a_quantity(self) -> None:
        # Details arrive in the same conversation.
        self.assertIsNone(quantity_asked_for("9876543210"))

    def test_a_price_is_not_a_quantity(self) -> None:
        self.assertIsNone(quantity_asked_for("anything under 100"))


if __name__ == "__main__":
    unittest.main()
