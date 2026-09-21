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
from pathlib import Path
from unittest import mock

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


class ASectionIsNotADishTests(unittest.TestCase):
    """Naming a section must never put one of its dishes in the cart.

    Live, before this — and this is the one that could actually cost somebody
    money, because it needed no confirmation from anybody:

        >>> Tandoori Starter
            Added 1 x Paneer Pahadi Tikka Dry to your order. Anything else?

    Nobody asked for Paneer Pahadi Tikka Dry. `get_dish` was asked to resolve
    "Tandoori Starter", the vector tier answered with the nearest dish, the
    guardrail measured it at better than 0.38 and said `named` — its highest
    confidence — and the model did the obvious thing with a confidently
    resolved dish.

    Nothing in the dish's own name is wrong. What is wrong is that the words
    asked for were the name of the SECTION the dish sits in, which the result
    itself says: `category: 'Tandoori Starter'`. So the check costs no query at
    all — it compares what was asked for with the category of what came back.
    """

    def test_the_section_name_and_the_matched_dishs_category_are_compared(self) -> None:
        # The comparison that decides it, in the form `_get_dish` uses: one
        # candidate category, not the branch's whole list.
        self.assertEqual(
            category_named_exactly("Tandoori Starter", ["Tandoori Starter"]),
            "Tandoori Starter",
        )

    def test_a_dish_whose_words_go_beyond_its_section_is_still_a_dish(self) -> None:
        # "khaman dhokla" resolves to Vagharela Khaman, in the "Khaman"
        # section. The words say more than the section does, so it is an
        # order, not a request to browse.
        self.assertIsNone(category_named_exactly("khaman dhokla", ["Khaman"]))
        self.assertIsNone(category_named_exactly("Paneer Pahadi Tikka Dry", ["Tandoori Starter"]))

    def test_a_dish_with_no_section_is_unaffected(self) -> None:
        self.assertIsNone(category_named_exactly("anything", [None]))


class TheToolRefusesASectionTests(unittest.TestCase):
    """`get_dish`'s own gate, at the seam where the wrong answer was formed.

    Driven with retrieval mocked rather than with a fake menu, because the
    fault is not in retrieval: the vector tier did its job and returned the
    nearest dish to "Tandoori Starter", which IS a Tandoori Starter. The fault
    is in answering a question about a section as though it were a question
    about a dish, and that judgement is made after retrieval has spoken.
    """

    def scope(self):
        from tests.test_ordering_agent_loop import SCOPE

        return SCOPE

    def resolve(self, asked_for: str, matched: str, category: str | None):
        from types import SimpleNamespace

        from app.services import rag as ordering_rag
        from app.services.ordering_agent import tools
        from app.services.ordering_agent.tools import GetDishArgs

        item = SimpleNamespace(name=matched, category=category)
        candidate = SimpleNamespace(menu_item=item)
        with mock.patch.object(tools, "_find_exact_name_match", return_value=None),              mock.patch.object(ordering_rag, "_embed_query", return_value=[0.0]),              mock.patch.object(
                 ordering_rag, "_resolve_final_candidates",
                 return_value=([candidate], "vector", 1),
             ),              mock.patch.object(ordering_rag, "apply_dish_name_guardrail", return_value="named"),              mock.patch.object(
                 tools, "_build_dish_result",
                 side_effect=lambda row, **kw: {"found": True, "name": row.name},
             ):
            return tools._get_dish(mock.MagicMock(), self.scope(), GetDishArgs(name=asked_for))

    def test_asking_for_a_section_does_not_resolve_to_a_dish(self) -> None:
        # The live failure: "Tandoori Starter" resolved to Paneer Pahadi Tikka
        # Dry with confidence "named", and the model added it to the cart.
        result = self.resolve("Tandoori Starter", "Paneer Pahadi Tikka Dry", "Tandoori Starter")
        self.assertFalse(result["found"], "a section resolved as a dish, and was added")

    def test_it_says_which_section_so_the_section_can_be_shown(self) -> None:
        # Refusing is only half an answer. "We don't have that" to somebody who
        # named a real section of the menu would be worse than the bug.
        result = self.resolve("Tandoori Starter", "Paneer Pahadi Tikka Dry", "Tandoori Starter")
        self.assertEqual(result.get("section"), "Tandoori Starter")

    def test_a_dish_whose_name_goes_beyond_its_section_still_resolves(self) -> None:
        result = self.resolve("khaman dhokla", "Vagharela Khaman", "Khaman")
        self.assertTrue(result["found"])
        self.assertEqual(result["name"], "Vagharela Khaman")

    def test_a_dish_in_no_section_still_resolves(self) -> None:
        result = self.resolve("something", "Some Dish", None)
        self.assertTrue(result["found"])


if __name__ == "__main__":
    unittest.main()
