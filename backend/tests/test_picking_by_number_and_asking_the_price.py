"""Two things a WhatsApp customer does constantly, answered from our own rows.

**Picking by number.** After a list is read out, "1" is how most people answer
it — the list is numbered in their head whether or not it is on screen. Live,
with eight dhoklas listed and "Which one would you like?" standing:

    > 1
      Sorry, I did not catch that. Which one would you like? Just reply with
      one of these: Butter Corn Dhokla, Cheese Butter Dhokla, ...

The list is ours, in the order we said it, so which dish "1" or "the second
one" means is not a question for the model. It is read here, against the list,
and the NAME at that position is handed to the same matcher a typed name goes
through — nothing new is added to a cart by a number alone.

**Asking the price.** "how much", "hw much", "kitne ka hai" — with a dish just
named or a list just shown — was searched for as a dish and answered "Sorry, I
did not catch that." The price is on the row we were already talking about.

Only a number, or only a price question: a message that also names a dish
("2 khaman") is an order, not a pick, and is left to the path that reads
orders.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.loop import (
    describe_prices,
    listed_in_order,
    ordinal_asked_for,
)
from app.services.ordering_agent.planner import quick_read


class PickingByNumberTests(unittest.TestCase):
    """Which position in a list of `count` a message points at (1-based)."""

    def test_a_bare_number(self) -> None:
        self.assertEqual(ordinal_asked_for("1", count=8), 1)
        self.assertEqual(ordinal_asked_for("3", count=8), 3)

    def test_the_words_people_use(self) -> None:
        for message, wanted in (
            ("first", 1), ("the first one", 1), ("first one", 1), ("1st", 1),
            ("second", 2), ("the second one", 2), ("2nd", 2),
            ("third", 3), ("3rd", 3), ("fourth", 4), ("4th", 4),
            ("last", 8), ("the last one", 8),
            ("number 2", 2), ("option 3", 3), ("no 2", 2),
        ):
            with self.subTest(message=message):
                self.assertEqual(ordinal_asked_for(message, count=8), wanted)

    def test_beyond_the_list_is_not_a_pick(self) -> None:
        # Nine of eight is not the ninth of something else.
        self.assertIsNone(ordinal_asked_for("9", count=8))
        self.assertIsNone(ordinal_asked_for("ninth", count=8))

    def test_zero_is_not_a_pick(self) -> None:
        self.assertIsNone(ordinal_asked_for("0", count=8))

    def test_a_number_with_a_dish_beside_it_is_an_order_not_a_pick(self) -> None:
        # "2 khaman" means two khamans. Reading it as the second item on a
        # list would put the wrong dish in the cart.
        self.assertIsNone(ordinal_asked_for("2 khaman", count=8))
        self.assertIsNone(ordinal_asked_for("2 x dhokla", count=8))

    def test_nothing_to_pick_from(self) -> None:
        self.assertIsNone(ordinal_asked_for("1", count=0))
        self.assertIsNone(ordinal_asked_for("", count=8))

    def test_two_numbers_are_not_a_pick(self) -> None:
        self.assertIsNone(ordinal_asked_for("1 and 2", count=8))


class CountingAlongTheQuestionTests(unittest.TestCase):
    """"2" counts along what the customer SAW, not along what is stored."""

    SIZES = [
        {"name": "Small", "size_id": "s1"},
        {"name": "Medium", "size_id": "s2"},
        {"name": "Large", "size_id": "s3"},
    ]

    def test_a_question_that_lists_nothing_uses_the_stored_order(self) -> None:
        asked = {"question": "Which one would you like?", "options": self.SIZES}
        self.assertEqual([o["name"] for o in listed_in_order(asked)], ["Small", "Medium", "Large"])

    def test_a_part_answered_group_counts_only_what_is_left(self) -> None:
        # The stored options hold the whole group; the question, after one
        # pick, lists only the remaining two. "1" means the first one SHOWN.
        toppings = [
            {"name": "Mozzarella", "option_id": "t1"},
            {"name": "Mushroom", "option_id": "t2"},
            {"name": "Thai basil", "option_id": "t3"},
        ]
        asked = {
            "question": (
                "Which toppings for Build Your Own Pizza? You have Mozzarella — pick 1 more."
                "\n- Mushroom (+$1.50)\n- Thai basil (+$0.75)"
            ),
            "options": toppings,
        }
        self.assertEqual([o["name"] for o in listed_in_order(asked)], ["Mushroom", "Thai basil"])

    def test_the_size_question_counts_its_sizes(self) -> None:
        asked = {
            "question": "Which size for Farmhouse Pizza?\n- Small — $17.49\n- Medium — $21.99\n- Large — $26.99",
            # Sizes first, then a required group's options, as `_remember_choice` stores them.
            "options": self.SIZES + [{"name": "Thin crust", "option_id": "c1"}],
        }
        self.assertEqual([o["name"] for o in listed_in_order(asked)], ["Small", "Medium", "Large"])

    def test_nothing_readable_is_nothing(self) -> None:
        self.assertEqual(listed_in_order(None), [])
        self.assertEqual(listed_in_order({}), [])


class SayingThePriceTests(unittest.TestCase):
    """Every figure is a row's own; a sized dish is never one number."""

    def test_one_flat_dish(self) -> None:
        self.assertEqual(
            describe_prices([{"name": "Khaman", "price": "60.00", "has_sizes": False, "sizes": []}]),
            "Khaman is $60.00.",
        )

    def test_one_sized_dish_gets_every_size(self) -> None:
        said = describe_prices([{
            "name": "Farmhouse Pizza", "price": "17.49", "has_sizes": True,
            "sizes": [{"name": "Small", "price": "17.49"}, {"name": "Medium", "price": "21.99"},
                      {"name": "Large", "price": "26.99"}],
        }])
        self.assertEqual(
            said, "Farmhouse Pizza is $17.49 for Small, $21.99 for Medium and $26.99 for Large."
        )
        self.assertNotIn("Farmhouse Pizza is $17.49.", said)

    def test_a_list_quotes_a_sized_dish_from_its_cheapest(self) -> None:
        said = describe_prices([
            {"name": "Margherita Pizza", "price": "11.99", "has_sizes": False, "sizes": []},
            {"name": "Build Your Own Pizza", "price": "14.99", "has_sizes": True,
             "sizes": [{"name": "Large", "price": "24.49"}, {"name": "Small", "price": "14.99"}]},
        ])
        self.assertEqual(
            said,
            "- Margherita Pizza - $11.99\n- Build Your Own Pizza - from $14.99",
        )

    def test_no_rows_is_no_answer(self) -> None:
        self.assertIsNone(describe_prices([]))


class AskingThePriceTests(unittest.TestCase):
    """The plain question, in the ways it arrives."""

    def test_the_ways_people_ask(self) -> None:
        for message in (
            "how much", "how much is it", "how much?", "hw much", "price", "price?",
            "what's the price", "whats the price", "how much does it cost", "cost",
            "kitne ka hai", "kitna hai", "kitne ka", "rate", "kya rate hai",
        ):
            with self.subTest(message=message):
                self.assertEqual(quick_read(message), "price")

    def test_a_price_question_about_a_named_dish_is_not_this(self) -> None:
        # "how much is the khaman" names a dish and the existing menu-question
        # path answers it. This signal is for the bare question about
        # whatever is already in front of them.
        self.assertIsNone(quick_read("how much is the khaman"))

    def test_turning_it_down_is_not_asking(self) -> None:
        self.assertIsNone(quick_read("no price"))

    def test_the_other_signals_are_untouched(self) -> None:
        self.assertEqual(quick_read("menu"), "menu")
        self.assertEqual(quick_read("cheapest"), "cheapest")
        self.assertEqual(quick_read("what do you recommend"), "suggest")


if __name__ == "__main__":
    unittest.main()
