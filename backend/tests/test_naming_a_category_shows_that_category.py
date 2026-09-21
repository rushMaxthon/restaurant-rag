"""Naming a section of the menu shows that section — all of it, and only it.

Asked for each of Radhe Dhokla's 21 categories by name, the assistant answered
with the wrong number of dishes almost every time:

    category                 has   shown
    Paneer Taste              17       8    truncated
    Vegetable Taste           13       8    truncated
    Tandoori Roti & Paratha   12       8    truncated
    Corn Dhokla                9       4    truncated
    Kofta Taste                2       6    padded from other categories
    Roti & Chapati             2       6    padded
    Biryani                    2       4    padded
    Kaju Taste                 5       -    answered with one dish's sizes

Two different faults with one cause: a category name was never recognised AS a
category. It went through dish-name matching, which caps at eight and matches
across the whole menu, so a big section came back cut off and a small one came
back with strangers in it. "Here are a few" over 8 of 17 is at least honest;
listing six dishes for a two-dish section is not.

`dishes_to_show` did have a category tier, and it sat BELOW name matching and
only ran when name matching found nothing at all. "Corn Dhokla" matched four
dish names — a strict subset of the nine-dish section of the same name — so it
never ran, and the customer never saw the other five.

The order now: a section named exactly beats a partial match on dish names, and
a section is read out complete. Naming a dish still wins over the section it
belongs to — "Manchow Soup" is one soup, not all three.

WHICH section is not decided here. The reading is already handed this branch's
own list of sections and picks from it, which is how "some drink" reaches
Beverages — string matching never gets there. All this rule decides is whether
the customer's words name that whole section or something narrower inside it.
`category_named_exactly` therefore takes the candidates it is given; the tests
below pass the full list because the interesting cases are the ambiguous ones.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.tools import category_named_exactly

#: Radhe Dhokla's real sections, with the sizes that made the fault visible.
CATEGORIES = [
    "Paneer Taste",
    "Vegetable Taste",
    "Tandoori Roti & Paratha",
    "Starters",
    "Rice & Dal",
    "Chinese Rice",
    "Corn Dhokla",
    "Farsan",
    "Khaman",
    "Tandoori Starter",
    "Idada",
    "Kaju Taste",
    "Noodles",
    "Pavbhaji",
    "Soup",
    "Roti & Chapati",
    "Biryani",
    "Thali",
    "Kofta Taste",
    "Pulao",
]


class NamingASectionTests(unittest.TestCase):
    """Which phrases name a section, and which only sound like they do."""

    def named(self, phrase: str) -> str | None:
        return category_named_exactly(phrase, CATEGORIES)

    def test_the_section_that_was_being_cut_off(self) -> None:
        # Four dish names matched, out of a nine-dish section.
        self.assertEqual(self.named("Corn Dhokla"), "Corn Dhokla")

    def test_a_one_word_section(self) -> None:
        for phrase, category in (
            ("soup", "Soup"),
            ("khaman", "Khaman"),
            ("biryani", "Biryani"),
            ("thali", "Thali"),
            ("noodles", "Noodles"),
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.named(phrase), category)

    def test_case_and_punctuation_do_not_matter(self) -> None:
        self.assertEqual(self.named("PANEER TASTE"), "Paneer Taste")
        self.assertEqual(self.named("roti & chapati"), "Roti & Chapati")
        self.assertEqual(self.named("roti and chapati"), "Roti & Chapati")

    def test_word_order_does_not_matter(self) -> None:
        self.assertEqual(self.named("taste paneer"), "Paneer Taste")

    def test_asking_around_it_still_names_it(self) -> None:
        # Nobody types a bare category. The words that carry meaning are the
        # ones compared, so the politeness around them is not a mismatch.
        for phrase in ("do you have soup", "show me the soup", "any soup"):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.named(phrase), "Soup")

    def test_naming_a_dish_beats_the_section_it_is_in(self) -> None:
        # The whole reason this is a word-SET rule and not a substring one.
        # "Manchow Soup" is one soup; answering with all three would throw away
        # the word that said which.
        self.assertIsNone(self.named("manchow soup"))
        self.assertIsNone(self.named("butter corn dhokla"))

    def test_a_bare_word_inside_a_section_name_is_not_the_section(self) -> None:
        # "dhokla" appears in dishes across several sections, so reading it as
        # "Corn Dhokla" would hide the rest of the dhoklas this branch sells.
        self.assertIsNone(self.named("dhokla"))

    def test_a_word_shared_by_four_sections_names_none_of_them(self) -> None:
        # Paneer Taste, Vegetable Taste, Kaju Taste, Kofta Taste. Picking one
        # would be a guess, and this rule never guesses.
        self.assertIsNone(self.named("taste"))

    def test_nothing_is_not_a_section(self) -> None:
        for phrase in ("", "   ", "pizza", "something nice"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(self.named(phrase))

    def test_a_menu_with_no_sections_names_nothing(self) -> None:
        self.assertIsNone(category_named_exactly("soup", []))


if __name__ == "__main__":
    unittest.main()
