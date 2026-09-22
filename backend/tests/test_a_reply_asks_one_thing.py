"""A reply must not end on two questions, because "yes" can only answer one.

From a live WhatsApp thread with Bangkok Bowl:

    > Menu
      ... Want something lighter, or are you ready to order? 🍕🔥
    > Yes
      There is nothing in your order yet.

"Yes" to that is unanswerable, and it is unanswerable no matter how good the
reading is: the customer agreed to one of two different things and there is
nothing in the message saying which.

The rule already exists here for the agent's own sentences. `describe_applied`
used to end "Anything else, or shall we get it on its way?" and was cut back to
"Anything else?", with the reason recorded in its test:

    # "Anything else, or shall we get it on its way?" asked two things at
    # once, and the answer to both of them is yes.

That rule never bound the reply pipeline, where the model writes its own prose
and asks whatever it likes. This applies the same rule to that prose.

**Only a comma before "or".** "Would you like rice or naan?" is one question
offering two answers, and a customer answers it fine; cutting it to "Would you
like rice?" would invent a question nobody asked. Both real failures — the one
above and the one the agent's rule came from — put a comma before the "or", and
that comma is what separates a list of options from a second question.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.rag import ask_one_thing


class TwoQuestionsBecomeOneTests(unittest.TestCase):
    """The shape that made "yes" meaningless."""

    def test_the_reported_reply(self) -> None:
        self.assertEqual(
            ask_one_thing("Want something lighter, or are you ready to order?"),
            "Want something lighter?",
        )

    def test_the_agents_old_version_of_the_same_mistake(self) -> None:
        self.assertEqual(
            ask_one_thing("Added 2 x Corn Fritters. Anything else, or shall we get it on its way?"),
            "Added 2 x Corn Fritters. Anything else?",
        )

    def test_what_came_before_the_question_is_kept(self) -> None:
        said = ask_one_thing(
            "The Tom Yum Prawn Pizza is $19.49. Want to try it, or are you looking for something else?"
        )
        self.assertTrue(said.startswith("The Tom Yum Prawn Pizza is $19.49."), said)
        self.assertEqual(said.count("?"), 1)

    def test_anything_after_the_question_is_kept(self) -> None:
        # Emoji live out there, and dropping them would be a visible change to
        # replies that were not broken.
        self.assertEqual(
            ask_one_thing("Want something lighter, or are you ready to order? 🍕🔥"),
            "Want something lighter? 🍕🔥",
        )


class OneQuestionIsLeftAloneTests(unittest.TestCase):
    """The larger half: almost every reply must come through untouched."""

    def test_a_choice_between_two_things_is_one_question(self) -> None:
        # No comma. This is a question with two answers, not two questions,
        # and it is how half the useful questions on a menu are phrased.
        for said in (
            "Would you like rice or naan?",
            "Shall I make that Per Plate or 1 Kg?",
            "Red or green curry?",
        ):
            with self.subTest(said=said):
                self.assertEqual(ask_one_thing(said), said)

    def test_a_plain_question(self) -> None:
        self.assertEqual(ask_one_thing("Anything else?"), "Anything else?")

    def test_a_reply_with_no_question_at_all(self) -> None:
        said = "Added 1 x Vagharela Khaman to your order."
        self.assertEqual(ask_one_thing(said), said)

    def test_a_comma_and_or_that_is_not_in_the_question(self) -> None:
        # The rule reads the LAST question only. An "or" earlier in the reply
        # is prose, not a second question.
        said = "We have Khaman, or Idada if you prefer. Anything else?"
        self.assertEqual(ask_one_thing(said), said)

    def test_a_list_of_dishes_is_untouched(self) -> None:
        said = "Here is our Soup:\n- Manchow Soup - ₹95\n- Mushroom Soup - ₹110\n\nWhich one would you like?"
        self.assertEqual(ask_one_thing(said), said)

    def test_nothing_at_all(self) -> None:
        self.assertEqual(ask_one_thing(""), "")
        self.assertIsNone(ask_one_thing(None))


class BothRoutesApplyItTests(unittest.TestCase):
    """The web concierge streams; WhatsApp does not. A fix on one is half one.

    This repo has already been caught by exactly that: grounding enforcement
    "was wired into the non-streaming handler first, and the concierge streams
    — so for real users it was never running."
    """

    def source(self) -> str:
        return (BACKEND_ROOT / "app" / "services" / "rag.py").read_text(encoding="utf-8")

    def test_it_is_applied_twice(self) -> None:
        self.assertGreaterEqual(
            self.source().count("ask_one_thing("),
            3,  # the definition, plus one call per route
            "one of the two routes can still end a reply on two questions",
        )


if __name__ == "__main__":
    unittest.main()
