"""Tests for the two ways the concierge used to answer the wrong question.

Both were reported from real use, and both come from the same root cause: every
input was funnelled into "search the menu for a dish", so anything that was not
a dish request came back as a dish request that failed.

* "Do you have any customize item in Menu?" was read as a search for a dish
  named "customize", missed, and answered "we don't have a customize option —
  try the Penne Arrabbiata". The customer asked whether they could adjust an
  order and was told about pasta.
* "rice" returned Pad Thai and a combo box, because the keyword SQL ORs the
  query across name, category AND description with equal weight and then ranks
  by popularity alone — so a dish whose description merely mentions rice
  outranks a dish that is rice.

No Ollama and no database: these are the deterministic parts, and they are
deterministic precisely so the answer to "can I customise this" cannot depend
on what a model felt like saying.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from datetime import time  # noqa: E402

from app.services.rag import (  # noqa: E402
    KEYWORD_MATCH_CATEGORY,
    KEYWORD_MATCH_NAME,
    KEYWORD_MATCH_WEAK,
    _customization_reply,
    _format_clock,
    _is_customization_query,
    _is_hours_query,
    _keyword_match_strength,
)


@dataclass
class _Item:
    name: str
    category: str = ""
    cuisine_type: str = ""


@dataclass
class _Candidate:
    menu_item: _Item


class CustomizationQuestionTests(unittest.TestCase):
    def test_the_reported_phrasing_is_recognised(self) -> None:
        self.assertTrue(_is_customization_query("Do you have any customize item in Menu?"))

    def test_the_ways_people_ask_to_change_an_order(self) -> None:
        for message in (
            "can i customize my order",
            "is this customisable",
            "any add-ons available",
            "do you have add ons",
            "what size options do you have",
            "can i choose a size",
        ):
            with self.subTest(message=message):
                self.assertTrue(_is_customization_query(message))

    def test_ordinary_dish_requests_are_left_alone(self) -> None:
        # This guard runs before dish retrieval, so a false positive here costs
        # a customer their actual search.
        for message in ("i want rice", "something spicy", "do you have pizza", "add some noodles"):
            with self.subTest(message=message):
                self.assertFalse(_is_customization_query(message))

    def test_no_customisable_dishes_says_so_rather_than_inventing_one(self) -> None:
        reply = _customization_reply([])
        self.assertIn("comes as it's listed", reply)
        # The failure being guarded against: answering a capability question by
        # naming dishes, which is what made the original reply nonsense.
        self.assertNotIn("bestseller", reply.lower())

    def test_customisable_dishes_are_named(self) -> None:
        reply = _customization_reply(
            [_Candidate(_Item("Margherita Pizza")), _Candidate(_Item("Pad Thai"))]  # type: ignore[arg-type]
        )
        self.assertIn("Margherita Pizza", reply)
        self.assertIn("Pad Thai", reply)
        self.assertTrue(reply.startswith("Yes"))


class KeywordRelevanceTests(unittest.TestCase):
    def test_a_dish_that_is_rice_beats_a_dish_that_mentions_rice(self) -> None:
        tokens = {"rice"}
        is_rice = _Candidate(_Item("Fried Rice", category="Rice"))  # type: ignore[arg-type]
        mentions_rice = _Candidate(_Item("Pad Thai Veg", category="Noodles"))  # type: ignore[arg-type]
        self.assertEqual(_keyword_match_strength(is_rice, tokens), KEYWORD_MATCH_NAME)
        self.assertEqual(_keyword_match_strength(mentions_rice, tokens), KEYWORD_MATCH_WEAK)

    def test_the_category_counts_when_the_name_does_not_carry_the_word(self) -> None:
        # "Vegetable Biryani" is a rice dish whose name never says rice. It must
        # not be demoted to the same tier as a noodle dish.
        candidate = _Candidate(_Item("Vegetable Biryani", category="Rice"))  # type: ignore[arg-type]
        self.assertEqual(_keyword_match_strength(candidate, {"rice"}), KEYWORD_MATCH_CATEGORY)

    def test_cuisine_counts_as_a_category_match(self) -> None:
        candidate = _Candidate(_Item("Penne Arrabbiata", cuisine_type="Italian"))  # type: ignore[arg-type]
        self.assertEqual(_keyword_match_strength(candidate, {"italian"}), KEYWORD_MATCH_CATEGORY)

    def test_matching_is_case_insensitive(self) -> None:
        candidate = _Candidate(_Item("Fried RICE"))  # type: ignore[arg-type]
        self.assertEqual(_keyword_match_strength(candidate, {"rice"}), KEYWORD_MATCH_NAME)

    def test_strength_ordering_is_name_then_category_then_weak(self) -> None:
        self.assertGreater(KEYWORD_MATCH_NAME, KEYWORD_MATCH_CATEGORY)
        self.assertGreater(KEYWORD_MATCH_CATEGORY, KEYWORD_MATCH_WEAK)


class OpeningHoursQuestionTests(unittest.TestCase):
    """"What are your timings?" was refused as off-topic.

    Doubly wrong: it is squarely a restaurant question, and the answer was
    already in the database — all 18 locations have rows in
    `location_fulfillment_slots`, and nothing in the chat pipeline had ever read
    them. The concierge said "that's outside my kitchen" about its own hours.
    """

    def test_the_ways_people_ask_about_hours(self) -> None:
        for message in (
            "what are your timings",
            "are you open right now",
            "when do you close",
            "how late are you open",
            "opening hours?",
            "still open?",
            "what time do you open",
        ):
            with self.subTest(message=message):
                self.assertTrue(_is_hours_query(message))

    def test_dish_requests_are_not_mistaken_for_hours(self) -> None:
        # This guard runs ahead of dish retrieval, so a false positive costs a
        # customer their actual search.
        for message in ("i want pizza", "show me rice", "something spicy", "open sandwich"):
            with self.subTest(message=message):
                self.assertFalse(_is_hours_query(message))

    def test_times_read_the_way_people_say_them(self) -> None:
        # "18:00:00" is what the column holds; nobody says a restaurant shuts at
        # eighteen hundred.
        self.assertEqual(_format_clock(time(9, 0)), "9 am")
        self.assertEqual(_format_clock(time(12, 0)), "12 pm")
        self.assertEqual(_format_clock(time(21, 30)), "9:30 pm")
        self.assertEqual(_format_clock(time(0, 0)), "12 am")


if __name__ == "__main__":
    unittest.main()
