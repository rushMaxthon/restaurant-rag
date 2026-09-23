""""Clear cart" clears the cart, after a yes — and "all" means all of it.

Live, in one thread over a four-line cart:

    > Clear cart
      Which one shall I take off? Chiang Mai Noodle Box, Build Your Own
      Pizza, Build Your Own Pizza, Coconut Turmeric Rice.
    > All
      Added 1 x Red Curry Tofu to your order. Added 1 x Pad Thai Veg ...

Two faults. The reading had no key for "the whole cart" — every removal
collapsed into `cancel_order` — so a request to clear it was handled as a
request to take one line off. Then the answer to OUR question was handed to
the reading with the greeting's four dishes as its options, and came back as
a choice of all four: added, not removed.

Neither is fixed with a list of phrases. The READING now carries `clear_cart`,
told what it means and left to read the words however they arrive; and when
"which one shall I take off?" is standing, the reading is handed the cart's
own lines as the options and told that "all of them" is every one. The code
then acts only on what was read, against the rows it holds: `lines_named_among`
maps the names the reading copied back onto cart lines, and naming every line
is clearing. Clearing is destructive, so a request becomes a question and only
a yes clears anything; an answer to "which one?" was asked for a turn ago and
needs no second confirmation.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.loop import lines_named_among
from app.services.ordering_agent.planner import read_order_intent

LINES = [
    {"name": "Chiang Mai Noodle Box", "menu_item_id": "m1"},
    {"name": "Build Your Own Pizza", "menu_item_id": "m2"},
    {"name": "Coconut Turmeric Rice", "menu_item_id": "m3"},
]


def a_model_saying(payload: dict) -> tuple[callable, dict]:
    """A scripted model, and the prompt it was shown."""

    seen: dict = {}

    def generate(prompt: str, timeout: float, max_tokens: int) -> str:
        seen["prompt"] = prompt
        return json.dumps(payload)

    return generate, seen


class TheReadingCarriesClearCartTests(unittest.TestCase):
    def test_the_key_is_read(self) -> None:
        generate, _ = a_model_saying({"clear_cart": True})
        self.assertTrue(read_order_intent("clear my cart", missing=(), generate=generate)["clear_cart"])

    def test_absent_is_false(self) -> None:
        generate, _ = a_model_saying({"add": []})
        self.assertFalse(read_order_intent("remove the pizza", missing=(), generate=generate)["clear_cart"])

    def test_a_string_is_not_true(self) -> None:
        # Only a JSON true. A model answering "yes" or "true" as text has not
        # said true, and this is the field that empties a cart.
        generate, _ = a_model_saying({"clear_cart": "true"})
        self.assertFalse(read_order_intent("x", missing=(), generate=generate)["clear_cart"])

    def test_the_model_is_told_what_it_means(self) -> None:
        generate, seen = a_model_saying({})
        read_order_intent("x", missing=(), generate=generate)
        self.assertIn('"clear_cart"', seen["prompt"])
        # And told what it is NOT: one dish out, or a placed order dropped.
        self.assertIn("Taking one dish out is not this", seen["prompt"])

    def test_an_empty_message_reads_as_nothing(self) -> None:
        self.assertFalse(read_order_intent("   ", missing=(), generate=lambda *a, **k: "{}")["clear_cart"])


class AnsweringWhichOneTests(unittest.TestCase):
    """The reading is handed OUR question and OUR options."""

    def test_all_of_them_is_explained_to_the_model(self) -> None:
        generate, seen = a_model_saying({})
        read_order_intent(
            "all", missing=(), generate=generate,
            choice_question="Which one shall I take off your order?",
            choice_options=[line["name"] for line in LINES],
        )
        self.assertIn("Which one shall I take off your order?", seen["prompt"])
        self.assertIn("Chiang Mai Noodle Box; Build Your Own Pizza; Coconut Turmeric Rice", seen["prompt"])
        self.assertIn("all of them", seen["prompt"])

    def test_every_option_comes_back_as_a_list(self) -> None:
        generate, _ = a_model_saying({"chose": [line["name"] for line in LINES]})
        got = read_order_intent("all", missing=(), generate=generate,
                                choice_question="Which one?", choice_options=["a"])
        self.assertEqual(got["chose"], [line["name"] for line in LINES])


class MappingNamesBackOntoLinesTests(unittest.TestCase):
    """What the reading copied back, matched exactly against what we hold."""

    def test_one_line(self) -> None:
        self.assertEqual(lines_named_among(["Build Your Own Pizza"], LINES), [LINES[1]])

    def test_every_line_in_cart_order(self) -> None:
        named = ["Coconut Turmeric Rice", "Chiang Mai Noodle Box", "Build Your Own Pizza"]
        self.assertEqual(lines_named_among(named, LINES), LINES)

    def test_case_does_not_matter_but_words_do(self) -> None:
        self.assertEqual(lines_named_among(["build your own pizza"], LINES), [LINES[1]])
        # "pizza" alone is not a line we hold; a near miss is not a removal.
        self.assertEqual(lines_named_among(["pizza"], LINES), [])

    def test_nothing_named_is_nothing(self) -> None:
        self.assertEqual(lines_named_among([], LINES), [])
        self.assertEqual(lines_named_among(["Chiang Mai Noodle Box"], []), [])


if __name__ == "__main__":
    unittest.main()
