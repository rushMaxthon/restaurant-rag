"""A cart line says what the customer actually chose.

Build a pizza — Large, green curry sauce, thin crust — and the cart said:

    - 1 x Build Your Own Pizza (Large (14")) - $25.49

The size, and nothing else. The $25.49 is right and unexplained: $24.49 for
the Large plus $1.00 for the green curry, with the extra pound nowhere in the
sentence. A customer checking their order before paying cannot tell whether
the kitchen has the crust they asked for, and the one line they are given to
check it against does not mention it.

`view_cart` has carried all of it the whole time. Each line holds `size_name`
and, per group, `selected_option_ids` alongside the options' names. The
read-back read the size and dropped the rest.

Groups are named, because "Green curry, Thin crust" is a list of words and
"Sauce: Green curry, Crust: Thin crust" is an order. And every chosen option
is shown, including one that came from a default — the customer is being asked
to pay for it, so they are told about it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.loop import bind_chat_currency, chosen_options_in, describe_cart


def group(title, options, chosen):
    return {
        "title": title,
        "selected_option_ids": list(chosen),
        "options": [{"option_id": oid, "name": name} for oid, name in options],
    }


def pizza_line(**over):
    line = {
        "name": "Build Your Own Pizza",
        "size_name": 'Large (14")',
        "quantity": 1,
        "unit_price": "25.49",
        "total_price": "25.49",
        "customization_groups": [
            group("Sauce", [("o1", "Tomato"), ("o2", "Green curry")], ["o2"]),
            group("Crust", [("c1", "Thin crust"), ("c2", "Cheese burst")], ["c1"]),
        ],
    }
    line.update(over)
    return line


class WhatWasChosenTests(unittest.TestCase):
    """Reading the picks back off a line."""

    def test_each_group_is_named_with_its_pick(self) -> None:
        self.assertEqual(
            chosen_options_in(pizza_line()),
            ["Sauce: Green curry", "Crust: Thin crust"],
        )

    def test_several_picks_in_one_group_are_listed_together(self) -> None:
        # Toppings on this menu takes seven.
        line = pizza_line(customization_groups=[
            group(
                "Toppings",
                [("t1", "Mozzarella"), ("t2", "Mushroom"), ("t3", "Thai basil")],
                ["t1", "t3"],
            )
        ])
        self.assertEqual(chosen_options_in(line), ["Toppings: Mozzarella, Thai basil"])

    def test_a_group_nobody_chose_from_is_not_mentioned(self) -> None:
        line = pizza_line(customization_groups=[
            group("Toppings", [("t1", "Mozzarella")], []),
        ])
        self.assertEqual(chosen_options_in(line), [])

    def test_a_line_with_no_groups_says_nothing(self) -> None:
        self.assertEqual(chosen_options_in({"name": "Roti Canai"}), [])
        self.assertEqual(chosen_options_in(pizza_line(customization_groups=[])), [])

    def test_an_id_with_no_matching_option_is_skipped_not_guessed(self) -> None:
        line = pizza_line(customization_groups=[
            group("Sauce", [("o1", "Tomato")], ["missing"]),
        ])
        self.assertEqual(chosen_options_in(line), [])

    def test_a_group_with_no_title_still_reads(self) -> None:
        line = pizza_line(customization_groups=[
            {"selected_option_ids": ["o1"], "options": [{"option_id": "o1", "name": "Tomato"}]},
        ])
        self.assertEqual(chosen_options_in(line), ["Tomato"])


class TheCartReadsItBackTests(unittest.TestCase):
    """What the customer sees before they pay."""

    def setUp(self) -> None:
        bind_chat_currency("USD")

    def said(self, *lines) -> str:
        return describe_cart({"lines": list(lines), "subtotal": "25.49"})

    def test_the_picks_are_on_the_line(self) -> None:
        said = self.said(pizza_line())
        self.assertIn("Sauce: Green curry", said)
        self.assertIn("Crust: Thin crust", said)

    def test_the_size_and_the_price_are_still_there(self) -> None:
        said = self.said(pizza_line())
        self.assertIn('Large (14")', said)
        self.assertIn("$25.49", said)

    def test_a_plain_dish_is_unchanged(self) -> None:
        # Most lines have no options at all and must not grow an empty tail.
        said = self.said({"name": "Roti Canai", "quantity": 2, "total_price": "12.98"})
        self.assertIn("2 x Roti Canai", said)
        self.assertNotIn(":", said.split("Subtotal")[0].split("Roti Canai")[1])

    def test_an_empty_cart_is_unchanged(self) -> None:
        self.assertEqual(
            describe_cart({"lines": [], "subtotal": "0.00"}),
            "Your cart is empty at the moment.",
        )


if __name__ == "__main__":
    unittest.main()
