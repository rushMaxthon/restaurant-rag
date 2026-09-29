"""Every list we show is numbered, and a number answers it as well as a name.

"Menu" used to be answered with one comma-joined line:

    Here is what we serve: Salads, Curry, Rice, Beverages, Combo, Main Course,
    Appetizer, Pizza, Dessert, Soup, Noodles. Which of those would you like to
    see?

That is a paragraph to read and nothing to answer — it asks somebody to pick a
name out of prose and type it back. Numbered, one per line, the shortest valid
answer is one character.

The dish lists and the size/topping lists were already answerable by position
(`_remember_dish_choice` records the names in the order they are printed and
`ordinal_asked_for` counts along them) — the numbers were simply never shown,
so only a customer who guessed found out. Now all three print them.

The half that matters is that a printed number means something. `sections_offered`
returns exactly the sections `offer_of_sections` listed, the turn records THAT
list, and picking off it sets `category` — the same field typing "Pizza"
produces — because picking a dish adds it and picking a section shows it.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent import loop as loop_module
from app.services.ordering_agent import order_draft
from app.services.ordering_agent.loop import (
    _dish_line,
    lays_its_options_out,
    listed_in_order,
    ordinal_asked_for,
)

SOURCE = inspect.getsource(loop_module.run_turn)
from app.services.ordering_agent.tools import offer_of_sections, sections_offered

SECTIONS = ["Salads", "Curry", "Rice", "Beverages", "Pizza", "Dessert"]


class TheSectionListTests(unittest.TestCase):
    def test_it_is_numbered_one_per_line(self) -> None:
        offer = offer_of_sections(SECTIONS)
        self.assertIn("\n1. Salads", offer)
        self.assertIn("\n2. Curry", offer)
        self.assertIn("\n6. Dessert", offer)

    def test_it_says_both_answers_are_accepted(self) -> None:
        self.assertIn("number or the name", offer_of_sections(SECTIONS))

    def test_what_was_printed_is_what_is_offered(self) -> None:
        # The two must not drift: the caller records `sections_offered`, and a
        # list that disagreed with the printed one would make "2" the wrong
        # section.
        self.assertEqual(sections_offered(SECTIONS), SECTIONS)

    def test_duplicates_and_blanks_are_dropped_from_both(self) -> None:
        messy = ["Soup", None, "Soup", "   ", "Khaman"]
        self.assertEqual(sections_offered(messy), ["Soup", "Khaman"])
        self.assertIn("\n2. Khaman", offer_of_sections(messy))

    def test_a_long_menu_is_capped_and_says_so(self) -> None:
        many = [f"Section {n}" for n in range(60)]
        offer = offer_of_sections(many)
        self.assertEqual(len(sections_offered(many)), 18)
        self.assertIn("\n18. Section 17", offer)
        self.assertIn("more", offer)
        # And the numbering never runs past what was shown.
        self.assertNotIn("19.", offer)

    def test_nothing_to_offer_is_none(self) -> None:
        self.assertIsNone(offer_of_sections([]))
        self.assertEqual(sections_offered([None, "", "  "]), [])


class TheDishListTests(unittest.TestCase):
    def test_a_dish_line_is_numbered(self) -> None:
        line = _dish_line({"name": "Margherita Pizza", "price": "11.99"}, 3)
        self.assertEqual(line, "3. Margherita Pizza - $11.99")

    def test_a_sized_dish_is_still_quoted_from_its_base(self) -> None:
        # The numbering must not lose the guard that stops a Large being
        # quoted at the Small's price.
        line = _dish_line({"name": "Build Your Own Pizza", "price": "14.99", "has_sizes": True}, 1)
        self.assertEqual(line, "1. Build Your Own Pizza - from $14.99")


class CountingAlongANumberedListTests(unittest.TestCase):
    """`listed_in_order` reads the question's own lines, in either style."""

    OPTIONS = [
        {"name": "Small", "size_id": "s1"},
        {"name": "Medium", "size_id": "s2"},
        {"name": "Large", "size_id": "s3"},
    ]

    def test_a_numbered_question(self) -> None:
        asked = {
            "question": "Which size for Pizza?\n1. Small — $14.99\n2. Medium — $19.49\n3. Large — $24.49",
            "options": self.OPTIONS,
        }
        self.assertEqual([o["name"] for o in listed_in_order(asked)], ["Small", "Medium", "Large"])
        self.assertEqual(ordinal_asked_for("2", count=3), 2)

    def test_a_question_written_by_the_previous_build(self) -> None:
        # A bulleted question can still be standing in Redis when this build
        # starts answering it, so both styles are read.
        asked = {
            "question": "Which size for Pizza?\n- Small — $14.99\n- Medium — $19.49",
            "options": self.OPTIONS,
        }
        self.assertEqual([o["name"] for o in listed_in_order(asked)], ["Small", "Medium"])

    def test_a_part_answered_group_counts_only_what_is_left(self) -> None:
        toppings = [
            {"name": "Mozzarella", "option_id": "t1"},
            {"name": "Mushroom", "option_id": "t2"},
            {"name": "Thai basil", "option_id": "t3"},
        ]
        asked = {
            "question": (
                "Which toppings for Pizza? You have Mozzarella — pick 1 more."
                "\n1. Mushroom (+$1.50)\n2. Thai basil (+$0.75)"
            ),
            "options": toppings,
        }
        self.assertEqual([o["name"] for o in listed_in_order(asked)], ["Mushroom", "Thai basil"])


class ThePairingsAreTheListInFrontOfThemTests(unittest.TestCase):
    """"Added 1 x Cheese Burst. People often add: 1. ... 2. ... Anything else?"

    That message is what is on screen, so "1" is the first thing offered. It
    used to be the first dish of the section they had been browsing, off a
    list that had scrolled away.
    """

    def helper(self) -> str:
        start = SOURCE.index("def _applied_with_pairings(")
        return SOURCE[start : SOURCE.index("def _goes_with(", start)]

    def test_what_was_printed_is_recorded(self) -> None:
        # A printed number means nothing unless the list behind it is written
        # down, and only an ADD is offered pairings — so the recording is
        # keyed on the heading actually appearing.
        helper = self.helper()
        self.assertIn("_remember_pairings", helper)
        self.assertIn("_PEOPLE_OFTEN_ADD in said", helper)

    def test_it_is_computed_once(self) -> None:
        # `_hold_the_question` tells which sentence this is by identity, and
        # a second call returns an equal string that is not the same object.
        self.assertEqual(self.helper().count("describe_applied("), 1)

    def test_the_browsed_list_is_kept_beneath_the_pairings(self) -> None:
        # Somebody working down a numbered section and saying "6" after
        # adding the second means the sixth dish there — "6" cannot be one of
        # two pairings, so the number itself says which list is meant.
        #
        # The rule lives in `order_draft.remember_offered`, because the reply
        # pipeline records its own listed dishes the same way and two
        # implementations of "what is in front of them" would drift apart.
        rule = inspect.getsource(order_draft.remember_offered)
        self.assertIn('"beneath"', rule)
        # One level deep, and it holds what was BROWSED: a second offer in a
        # row must not push the section out in favour of the previous offer.
        self.assertIn('was.get("kind") in {"offered", "pairings"}', rule)

    def test_an_empty_offer_never_clears_what_is_shown(self) -> None:
        # Called with nothing, it must leave the list alone rather than
        # replacing it with an empty one nobody can pick from.
        rule = inspect.getsource(order_draft.remember_offered)
        self.assertIn("if not options:", rule)
        self.assertIn("return", rule)

    def test_a_number_too_big_for_the_pairings_falls_through_to_it(self) -> None:
        start = SOURCE.index("listed_now = asked_before or shown_before")
        body = SOURCE[start : SOURCE.index("wanted = (", start)]
        self.assertIn('listed_now.get("beneath")', body)

    def test_a_name_is_matched_against_both(self) -> None:
        # The numbering stays separate, but "Margherita Pizza" is unambiguous
        # whichever of the two lists it came off.
        start = SOURCE.index("They picked one of the dishes the reply pipeline showed")
        body = SOURCE[start : SOURCE.index("elif wanted.get(\"chose\") and asked_before", start)]
        self.assertIn('shown_before.get("beneath")', body)


class SpellingTheOptionsOutTwiceTests(unittest.TestCase):
    """A re-ask must not list what the question already lists."""

    def test_a_numbered_list_lays_its_options_out(self) -> None:
        self.assertTrue(lays_its_options_out("Which size?\n1. Small\n2. Large"))

    def test_a_bulleted_list_does_too(self) -> None:
        self.assertTrue(lays_its_options_out("Which size?\n- Small\n- Large"))

    def test_a_plain_question_does_not(self) -> None:
        self.assertFalse(lays_its_options_out("Which one would you like?"))
        self.assertFalse(lays_its_options_out(""))

    def test_a_number_in_the_question_itself_is_not_a_list(self) -> None:
        # The first line is the question; only the lines under it are options.
        self.assertFalse(lays_its_options_out("2. is not a list on its own"))


if __name__ == "__main__":
    unittest.main()
