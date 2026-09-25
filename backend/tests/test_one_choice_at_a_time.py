"""A waiter asks for one thing at a time, and lays the options out.

From a live WhatsApp thread ordering a Build Your Own Pizza:

    Crust for Build Your Own Pizza: Thin crust, Classic hand tossed, Cheese
    burst (+$4.00), Stuffed garlic crust (+$4.50). Sauce for Build Your Own
    Pizza: Tomato, Green curry (+$1.00), Tom yum cream (+$1.50), Garlic
    butter. Which would you like?

Two questions, eleven options and four prices in one paragraph, ending on a
single "Which would you like?" that could mean either of them. Nobody orders
like this, and the customer's next message — "Thin crust, Tomato" — was
answered "Build Your Own Pizza is $14.99. Shall I add one?", quoting the base
price of a pizza they had already sized Large ($24.49).

`ask_for_choice` built one `parts` entry for the size and one per group, then
`" ".join(parts)`. It holds everything needed to ask well: the dish, its sizes,
its groups, every option and every price, all off the tool's own rows.

So it now asks for the first outstanding thing only, and sets the options out
one per line. A size is chosen before a crust because Crust is size-scoped on
this menu — three separate groups, one per size, with different options and
different prices — so asking for a crust before a size is asking a question
whose answer we cannot use.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.loop import ask_for_choice


def pizza(**over) -> dict:
    """A `needs_choice` shaped like Build Your Own Pizza's real one."""

    result = {
        "outcome": "needs_choice",
        "name": "Build Your Own Pizza",
        "needs_size": True,
        "available_sizes": [
            {"name": 'Small (8")', "size_id": "s1", "price": "14.99"},
            {"name": 'Medium (11")', "size_id": "s2", "price": "19.49"},
            {"name": 'Large (14")', "size_id": "s3", "price": "24.49"},
        ],
        "customization_groups": [
            {
                "title": "Crust",
                "needs_selection": True,
                "min_selection": 1,
                "max_selection": 1,
                "options": [
                    {"name": "Thin crust", "option_id": "c1", "extra_price": "0.00"},
                    {"name": "Cheese burst", "option_id": "c2", "extra_price": "4.00"},
                ],
            },
            {
                "title": "Sauce",
                "needs_selection": True,
                "min_selection": 1,
                "max_selection": 1,
                "options": [
                    {"name": "Tomato", "option_id": "o1", "extra_price": "0.00"},
                    {"name": "Green curry", "option_id": "o2", "extra_price": "1.00"},
                ],
            },
        ],
    }
    result.update(over)
    return result


class OneThingAtATimeTests(unittest.TestCase):
    """The whole complaint: eleven options and two questions in one breath."""

    def test_the_size_comes_first_and_alone(self) -> None:
        said = ask_for_choice(pizza())
        self.assertIn("Which size", said)
        self.assertNotIn("Crust", said)
        self.assertNotIn("Sauce", said)

    def test_the_next_group_is_asked_once_the_size_is_settled(self) -> None:
        # Case-insensitive on the title: "Which crust for..." reads like a
        # waiter and "Crust for...:" reads like a form, and which of those the
        # sentence uses is not what this test is about.
        said = ask_for_choice(pizza(needs_size=False)).lower()
        self.assertIn("crust", said)
        self.assertNotIn("sauce", said, "two groups were asked in one message")

    def test_the_last_group_is_asked_on_its_own(self) -> None:
        result = pizza(needs_size=False)
        result["customization_groups"][0]["needs_selection"] = False
        said = ask_for_choice(result).lower()
        self.assertIn("sauce", said)
        self.assertNotIn("crust", said)

    def test_it_ends_on_exactly_one_question(self) -> None:
        for result in (pizza(), pizza(needs_size=False)):
            with self.subTest(needs_size=result["needs_size"]):
                self.assertEqual(ask_for_choice(result).count("?"), 1)

    def test_nothing_outstanding_asks_nothing(self) -> None:
        result = pizza(needs_size=False)
        for group in result["customization_groups"]:
            group["needs_selection"] = False
        self.assertIsNone(ask_for_choice(result))

    def test_it_is_still_none_for_anything_that_is_not_a_choice(self) -> None:
        self.assertIsNone(ask_for_choice({"outcome": "action"}))
        self.assertIsNone(ask_for_choice(None))


class TheOptionsAreLaidOutTests(unittest.TestCase):
    """A price list is read, not parsed."""

    def test_each_option_is_on_its_own_line_and_numbered(self) -> None:
        # Numbered, because "2" already answers this question — the options
        # are recorded in the order they are printed and counted along them —
        # and a number nobody can see is an affordance nobody uses.
        said = ask_for_choice(pizza())
        for position, size in enumerate(('Small (8")', 'Medium (11")', 'Large (14")'), 1):
            with self.subTest(size=size):
                self.assertIn(f"\n{position}. {size}", said)

    def test_every_size_carries_its_own_price(self) -> None:
        # The money bug this sits next to: a Large was quoted at the base
        # price. Showing each price at the moment of choosing is the defence.
        said = ask_for_choice(pizza())
        self.assertIn("$14.99", said)
        self.assertIn("$19.49", said)
        self.assertIn("$24.49", said)

    def test_an_extra_is_shown_and_a_free_option_is_not_marked(self) -> None:
        said = ask_for_choice(pizza(needs_size=False))
        self.assertIn("Cheese burst", said)
        self.assertIn("$4.00", said)
        thin = next(line for line in said.splitlines() if "Thin crust" in line)
        self.assertNotIn("+", thin, "a free option was priced")


class ChoosingSeveralIsInvitedTests(unittest.TestCase):
    """Toppings on this menu is MULTI, max 7 — and was never mentioned."""

    def topping_question(self, **group_over) -> str:
        group = {
            "title": "Toppings",
            "needs_selection": True,
            "min_selection": 0,
            "max_selection": 7,
            "options": [
                {"name": "Mozzarella", "option_id": "t1", "extra_price": "1.75"},
                {"name": "Mushroom", "option_id": "t2", "extra_price": "1.50"},
                {"name": "Thai basil", "option_id": "t3", "extra_price": "0.75"},
            ],
        }
        group.update(group_over)
        return ask_for_choice(
            pizza(needs_size=False, customization_groups=[group])
        )

    def test_a_group_that_takes_several_says_so(self) -> None:
        # Without this nobody knows they may pick more than one, so nobody
        # does, and the kitchen sells one topping instead of three.
        said = self.topping_question()
        self.assertIn("more than one", said.lower())

    def test_a_group_that_takes_one_does_not(self) -> None:
        said = ask_for_choice(pizza(needs_size=False))
        self.assertNotIn("more than one", said.lower())

    def test_what_is_already_chosen_is_credited(self) -> None:
        # A group wanting three answered the first correct pick with the
        # identical question — the same list, no sign anybody had heard.
        said = self.topping_question(min_selection=3, selected_option_ids=["t1"])
        self.assertIn("Mozzarella", said)
        self.assertNotIn("\n- Mozzarella", said, "an option already chosen was offered again")


if __name__ == "__main__":
    unittest.main()
