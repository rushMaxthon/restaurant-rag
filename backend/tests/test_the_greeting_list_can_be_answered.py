"""The first list a customer ever sees is the one "1" did not answer.

    > Hi
      Good evening 👋 You're through to Bangkok Bowl. What are you in the mood
      for tonight? Here is what people are ordering:
      • Red Curry Tofu — $14.64
      • Pad Thai Veg — $13.84
      ...
    > 1
      I have not shown you a list to pick from yet. Here is what we serve: ...

Every other list this app prints is numbered and says "Reply with the number
or the name" — the sections, the dishes in a section, the sizes, the toppings,
the pairings after an add. The greeting's dishes come from the reply pipeline
rather than the ordering agent, so they were bulleted and nothing recorded
them. That makes the very first message the one that lies about what it takes.

Two halves, and they have to agree: `render_reply` prints the numbers, and
`dishes_listed_under` reports exactly the dishes it printed so the caller can
record them. A list that was never printed must never be what a number counts
along — which is why the agent owning the turn yields nothing here, having
already recorded whatever it showed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.tasks.whatsapp import dishes_listed_under
from app.services.whatsapp import render_reply

DISHES = [
    {"name": "Red Curry Tofu", "price": "14.64"},
    {"name": "Pad Thai Veg", "price": "13.84"},
    {"name": "Thai Basil Chicken", "price": "14.84"},
]


def an_answer(**over):
    base = {"reply": "Hi there.", "agent_reply": None, "agent_asks": False, "suggestions": []}
    base.update(over)
    return SimpleNamespace(**base)


class TheDishesArePrintedNumberedTests(unittest.TestCase):
    def test_each_one_carries_its_position(self) -> None:
        said = render_reply("What are you in the mood for?", DISHES, "USD")
        self.assertIn("\n1. Red Curry Tofu — $14.64", said)
        self.assertIn("\n2. Pad Thai Veg — $13.84", said)
        self.assertIn("\n3. Thai Basil Chicken — $14.84", said)
        self.assertNotIn("•", said)

    def test_it_says_both_answers_are_accepted(self) -> None:
        said = render_reply("What are you in the mood for?", DISHES, "USD")
        self.assertIn("Reply with the number or the name.", said)

    def test_a_reply_with_no_dishes_promises_nothing(self) -> None:
        # The invitation only belongs under a list that exists.
        said = render_reply("We are closed right now.", [], "USD")
        self.assertNotIn("Reply with the number", said)
        self.assertEqual(said, "We are closed right now.")

    def test_a_dish_with_no_price_is_still_numbered(self) -> None:
        said = render_reply("Here:", [{"name": "Soup of the day"}], "USD")
        self.assertIn("1. Soup of the day", said)

    def test_a_nameless_row_does_not_take_a_number(self) -> None:
        # Otherwise the printed numbers and the recorded list disagree, and
        # "2" buys the wrong dish.
        said = render_reply("Here:", [{"price": "9.99"}, {"name": "Money Bags"}], "USD")
        self.assertIn("1. Money Bags", said)
        self.assertNotIn("2.", said)


class TheSameDishesAreRecordedTests(unittest.TestCase):
    """What was printed, and nothing else."""

    def test_the_names_come_back_in_order(self) -> None:
        self.assertEqual(
            dishes_listed_under(an_answer(suggestions=DISHES)),
            ["Red Curry Tofu", "Pad Thai Veg", "Thai Basil Chicken"],
        )

    def test_a_nameless_row_is_skipped_exactly_as_it_is_in_print(self) -> None:
        listed = dishes_listed_under(an_answer(suggestions=[{"price": "9.99"}, {"name": "Money Bags"}]))
        self.assertEqual(listed, ["Money Bags"])

    def test_the_agent_owning_the_turn_records_nothing(self) -> None:
        # Its suggestions are not printed under its own sentence, and it has
        # already recorded whatever it did show. Overwriting that with a list
        # the customer never saw is how "1" buys the wrong dish.
        answer = an_answer(suggestions=DISHES, agent_reply="Added 1 x Money Bags.", agent_asks=True)
        self.assertEqual(dishes_listed_under(answer), [])

    def test_an_agent_reply_nobody_is_asked_to_answer_still_lists(self) -> None:
        # `agent_asks` false means the pipeline's answer is what is sent, so
        # the dishes under it are real.
        answer = an_answer(suggestions=DISHES, agent_reply="something", agent_asks=False)
        self.assertEqual(len(dishes_listed_under(answer)), 3)

    def test_nothing_suggested_is_nothing_recorded(self) -> None:
        self.assertEqual(dishes_listed_under(an_answer()), [])
        self.assertEqual(dishes_listed_under(an_answer(suggestions=None)), [])

    def test_objects_work_as_well_as_dicts(self) -> None:
        # The pipeline hands back models on one route and dicts on another.
        rows = [SimpleNamespace(name="Money Bags", price="9.49")]
        self.assertEqual(dishes_listed_under(an_answer(suggestions=rows)), ["Money Bags"])


if __name__ == "__main__":
    unittest.main()
