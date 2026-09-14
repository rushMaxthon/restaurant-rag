"""A stripped filter word must still apply its filter.

Reported: "some spicy thing" returned Build Your Own Pizza, and "also some sweet
thing too" returned the same item again.

Neither was an embedding problem — every one of the 516 dishes is embedded. The
query never mentioned spice at all:

    "some spicy thing"  ->  dish='thing'  effective='thing'  spicy=None

"spicy" is stripped from the topic as a filter word, but nothing set
`intent.spicy`, so the requirement vanished. "thing" then survived as the dish
name — `something` and `anything` are stopwords, `thing` was not — and keyword
search matched it against "Choose the size, the crust and everything on top of
it".

So the assistant searched for the word "thing" and found "everything".
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.rag import (
    SessionConversationState,
    _canonicalize_topic,
    _fallback_extract_intent,
)


def intent_for(message: str):
    return _fallback_extract_intent(message, SessionConversationState())


class SpiceIsAppliedNotJustStrippedTests(unittest.TestCase):
    def test_asking_for_spicy_sets_the_spice_filter(self) -> None:
        for phrase in ("some spicy thing", "i want something spicy", "spicy food please"):
            with self.subTest(phrase=phrase):
                self.assertIs(intent_for(phrase).spicy, True)

    def test_saying_not_spicy_sets_it_the_other_way(self) -> None:
        """A substring test reads "nothing too spicy" as a request FOR heat.

        Storing that would tell the kitchen the opposite of what was asked.
        """

        for phrase in ("nothing too spicy", "not spicy please", "mild not spicy"):
            with self.subTest(phrase=phrase):
                self.assertIs(intent_for(phrase).spicy, False)

    def test_a_message_about_neither_leaves_it_unset(self) -> None:
        self.assertIsNone(intent_for("i want pad thai").spicy)


class DietIsAppliedNotJustStrippedTests(unittest.TestCase):
    def test_veg_sets_the_diet(self) -> None:
        self.assertEqual(intent_for("some veg thing").diet, "veg")

    def test_non_veg_is_not_read_as_veg(self) -> None:
        """"non veg" contains "veg"; testing veg first reads a request as its
        own opposite."""

        self.assertEqual(intent_for("non veg please").diet, "non_veg")


class ThingIsNotADishTests(unittest.TestCase):
    def test_thing_never_becomes_a_topic(self) -> None:
        """`something` and `anything` were stopwords and `thing` was not, so it
        survived alone and matched "everything" in a pizza description."""

        for phrase in ("some spicy thing", "give me a thing", "some sweet things"):
            with self.subTest(phrase=phrase):
                topic = _canonicalize_topic(phrase) or ""
                self.assertNotIn("thing", topic)

    def test_a_real_dish_is_untouched(self) -> None:
        self.assertEqual(_canonicalize_topic("i want pad thai"), "pad thai")


if __name__ == "__main__":
    unittest.main()
