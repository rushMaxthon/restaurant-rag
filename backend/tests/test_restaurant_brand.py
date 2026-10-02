"""What a restaurant says about itself, and what this platform will store.

Two rules carry most of the weight here, and they are both the OPPOSITE of
what `restaurant_storefront.py` does — so the obvious intuition, carried over
from that module, is wrong in both cases:

- **Nothing is derived.** Empty stays empty. A generated paragraph about a real
  business's standards is a claim nobody there made, and it would be the same
  paragraph under every restaurant's name — the bug the storefront copy exists
  to have fixed.
- **Only the keys sent are changed**, so editing the FAQ cannot blank the about
  sections. Sending a key as an empty list DOES clear it, because that is a
  deliberate act and not the same as leaving it out.

Pure: no database, no session. These are rules about text.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.restaurant_brand import (  # noqa: E402
    BODY_LIMIT,
    HEADING_LIMIT,
    MAX_FAQS,
    MAX_SECTIONS,
    BrandValidationError,
    read_brand,
    resolve_brand,
)

SECTION = {"heading": "Overview", "body": "We bake every morning from four."}
FAQ = {"question": "Do you make eggless cakes?", "answer": "Every cake we bake is eggless."}


class OnlyWhatWasSentChangesTests(unittest.TestCase):
    def test_editing_the_questions_leaves_the_sections_alone(self) -> None:
        existing = {"about_sections": [SECTION], "faqs": []}
        resolved = resolve_brand({"faqs": [FAQ]}, existing=existing)
        self.assertEqual(resolved["about_sections"], [SECTION])
        self.assertEqual(resolved["faqs"], [FAQ])

    def test_an_empty_payload_changes_nothing(self) -> None:
        existing = {"about_sections": [SECTION], "faqs": [FAQ]}
        self.assertEqual(resolve_brand({}, existing=existing), existing)

    def test_an_empty_list_clears_that_half_deliberately(self) -> None:
        # Distinct from not mentioning it, which is the whole reason the two
        # are told apart.
        existing = {"about_sections": [SECTION], "faqs": [FAQ]}
        resolved = resolve_brand({"faqs": []}, existing=existing)
        self.assertEqual(resolved["about_sections"], [SECTION])
        self.assertNotIn("faqs", resolved)


class NothingIsInventedTests(unittest.TestCase):
    def test_a_restaurant_that_has_written_nothing_has_nothing(self) -> None:
        read = read_brand(SimpleNamespace(brand={}))
        self.assertEqual(read, {"about_sections": [], "faqs": []})

    def test_both_keys_are_always_present_so_no_client_has_to_decide(self) -> None:
        read = read_brand(SimpleNamespace(brand=None))
        self.assertEqual(sorted(read), ["about_sections", "faqs"])
        self.assertIsInstance(read["about_sections"], list)


class HalfFilledRowsAreDroppedTests(unittest.TestCase):
    """A blank row at the bottom of an editor is normal; it must not refuse."""

    def test_a_heading_with_nothing_under_it_is_dropped(self) -> None:
        resolved = resolve_brand({"about_sections": [{"heading": "Overview", "body": ""}]})
        self.assertNotIn("about_sections", resolved)

    def test_a_body_with_no_heading_is_dropped(self) -> None:
        resolved = resolve_brand({"about_sections": [{"heading": "", "body": "Words."}]})
        self.assertNotIn("about_sections", resolved)

    def test_bullets_alone_are_enough_to_keep_a_section(self) -> None:
        resolved = resolve_brand(
            {"about_sections": [{"heading": "What we do", "body": "", "bullets": ["Cakes"]}]}
        )
        self.assertEqual(resolved["about_sections"][0]["bullets"], ["Cakes"])

    def test_a_question_with_no_answer_is_dropped(self) -> None:
        # Published, it reads as an oversight on the restaurant's website.
        resolved = resolve_brand({"faqs": [{"question": "Vegan cakes?", "answer": "  "}]})
        self.assertNotIn("faqs", resolved)

    def test_the_rows_that_are_complete_survive_their_blank_neighbours(self) -> None:
        resolved = resolve_brand(
            {"about_sections": [SECTION, {"heading": "", "body": ""}, {"heading": "x", "body": ""}]}
        )
        self.assertEqual(resolved["about_sections"], [SECTION])


class TooMuchIsRefusedNotTruncatedTests(unittest.TestCase):
    """A save that reports success while losing content is how people stop
    trusting a form. The owner is told the limit instead."""

    def test_too_many_sections_is_refused(self) -> None:
        with self.assertRaises(BrandValidationError) as caught:
            resolve_brand({"about_sections": [SECTION] * (MAX_SECTIONS + 1)})
        self.assertIn(str(MAX_SECTIONS), str(caught.exception))

    def test_too_many_questions_is_refused(self) -> None:
        with self.assertRaises(BrandValidationError):
            resolve_brand({"faqs": [FAQ] * (MAX_FAQS + 1)})

    def test_an_over_long_heading_is_refused(self) -> None:
        with self.assertRaises(BrandValidationError) as caught:
            resolve_brand({"about_sections": [{"heading": "x" * (HEADING_LIMIT + 1), "body": "y"}]})
        self.assertIn(str(HEADING_LIMIT), str(caught.exception))

    def test_an_over_long_body_is_refused(self) -> None:
        with self.assertRaises(BrandValidationError):
            resolve_brand({"about_sections": [{"heading": "h", "body": "x" * (BODY_LIMIT + 1)}]})

    def test_something_that_is_not_a_list_is_refused(self) -> None:
        with self.assertRaises(BrandValidationError):
            resolve_brand({"faqs": "not a list"})


class ProseKeepsItsShapeTests(unittest.TestCase):
    def test_paragraph_breaks_survive(self) -> None:
        # Unlike the short copy, which collapses whitespace because a page
        # title carrying a newline breaks the <title> it lands in. A body is
        # prose, and flattening it turns three paragraphs into one wall.
        body = "First paragraph.\n\nSecond paragraph."
        resolved = resolve_brand({"about_sections": [{"heading": "About", "body": body}]})
        self.assertEqual(resolved["about_sections"][0]["body"], body)

    def test_windows_line_endings_are_normalised(self) -> None:
        # Pasted from Word, these would otherwise render with doubled blanks.
        resolved = resolve_brand(
            {"about_sections": [{"heading": "About", "body": "One.\r\n\r\nTwo."}]}
        )
        self.assertEqual(resolved["about_sections"][0]["body"], "One.\n\nTwo.")

    def test_surrounding_whitespace_goes(self) -> None:
        resolved = resolve_brand({"about_sections": [{"heading": "  About  ", "body": " x "}]})
        self.assertEqual(resolved["about_sections"][0]["heading"], "About")


class StoredRowsAreRevalidatedOnTheWayOutTests(unittest.TestCase):
    """The column is JSONB and the rules have changed before.

    A row written under a looser rule must not be able to put a 4,000-character
    paragraph on a live page because it got in before the cap existed.
    """

    def test_an_over_long_stored_body_is_not_served(self) -> None:
        restaurant = SimpleNamespace(
            brand={"about_sections": [{"heading": "About", "body": "x" * (BODY_LIMIT + 500)}]}
        )
        self.assertEqual(read_brand(restaurant)["about_sections"], [])

    def test_more_sections_than_allowed_are_cut_to_the_cap(self) -> None:
        restaurant = SimpleNamespace(brand={"about_sections": [SECTION] * (MAX_SECTIONS + 4)})
        self.assertEqual(len(read_brand(restaurant)["about_sections"]), MAX_SECTIONS)

    def test_rubbish_in_the_column_does_not_reach_a_page(self) -> None:
        restaurant = SimpleNamespace(brand={"about_sections": ["a string", 7, None], "faqs": 3})
        self.assertEqual(read_brand(restaurant), {"about_sections": [], "faqs": []})


if __name__ == "__main__":
    unittest.main()
