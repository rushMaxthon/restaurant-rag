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
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.restaurant_brand import (  # noqa: E402
    BODY_LIMIT,
    HEADING_LIMIT,
    MAX_FAQS,
    MAX_HIGHLIGHTS,
    MAX_SECTIONS,
    MAX_SPECIALITIES,
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


#: What `read_brand` answers for a restaurant that has written nothing. Stated
#: once so the three tests that assert the whole shape cannot drift apart as
#: keys are added — and asserted whole on purpose, because a key that stops
#: being returned is a block that silently disappears from a storefront.
EMPTY_BRAND = {
    "about_sections": [],
    "faqs": [],
    "established_year": None,
    "specialities": [],
    "highlights": [],
}


class NothingIsInventedTests(unittest.TestCase):
    def test_a_restaurant_that_has_written_nothing_has_nothing(self) -> None:
        read = read_brand(SimpleNamespace(brand={}))
        self.assertEqual(read, EMPTY_BRAND)

    def test_every_key_is_always_present_so_no_client_has_to_decide(self) -> None:
        read = read_brand(SimpleNamespace(brand=None))
        self.assertEqual(sorted(read), sorted(EMPTY_BRAND))
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
        restaurant = SimpleNamespace(
            brand={
                "about_sections": ["a string", 7, None],
                "faqs": 3,
                "established_year": "not a year",
                "specialities": "not a list",
                "highlights": [{"value": "4.6"}, 9],
            }
        )
        self.assertEqual(read_brand(restaurant), EMPTY_BRAND)



class TheFactsAboveTheFoldTests(unittest.TestCase):
    """The year founded, what they are known for, and the figures beside it.

    All three were added for a storefront whose home page had the owner's
    three paragraphs and nothing else to say — and whose business has been
    trading since 1999, which is the single most persuasive thing about it and
    was nowhere on their own website.
    """

    def test_a_year_is_stored_as_a_year_not_as_a_duration(self) -> None:
        # The listing sites publish "26 Years in Business". That is right on
        # the day it is typed and wrong every year after.
        resolved = resolve_brand({"established_year": 1999})
        self.assertEqual(resolved["established_year"], 1999)

    def test_a_year_arrives_from_a_form_as_a_string(self) -> None:
        self.assertEqual(resolve_brand({"established_year": " 1999 "})["established_year"], 1999)

    def test_a_year_that_is_not_one_is_refused(self) -> None:
        for bad in ("nineteen ninety nine", "19 99", 1700, date.today().year + 1):
            with self.subTest(bad=bad), self.assertRaises(BrandValidationError):
                resolve_brand({"established_year": bad})

    def test_this_year_is_allowed_because_restaurants_open(self) -> None:
        this_year = date.today().year
        self.assertEqual(
            resolve_brand({"established_year": this_year})["established_year"], this_year
        )

    def test_clearing_the_year_removes_it(self) -> None:
        existing = {"established_year": 1999}
        self.assertNotIn("established_year", resolve_brand({"established_year": None}, existing=existing))
        self.assertNotIn("established_year", resolve_brand({"established_year": ""}, existing=existing))

    def test_a_year_survives_an_edit_that_does_not_mention_it(self) -> None:
        existing = {"established_year": 1999}
        self.assertEqual(resolve_brand({"faqs": []}, existing=existing)["established_year"], 1999)

    def test_specialities_are_trimmed_and_the_empty_ones_dropped(self) -> None:
        resolved = resolve_brand({"specialities": ["  Khari biscuit ", "", "   ", "Nankhatai"]})
        self.assertEqual(resolved["specialities"], ["Khari biscuit", "Nankhatai"])

    def test_too_many_specialities_are_refused(self) -> None:
        with self.assertRaises(BrandValidationError):
            resolve_brand({"specialities": ["x"] * (MAX_SPECIALITIES + 1)})

    def test_a_highlight_needs_both_a_figure_and_a_caption(self) -> None:
        # A number with no caption says nothing; a caption with no number is a
        # tile with a hole in it.
        resolved = resolve_brand(
            {
                "highlights": [
                    {"value": "4.6", "label": ""},
                    {"value": "", "label": "Rated"},
                    {"value": "1999", "label": "Baking since"},
                ]
            }
        )
        self.assertEqual(resolved["highlights"], [{"value": "1999", "label": "Baking since"}])

    def test_a_borrowed_figure_keeps_its_attribution(self) -> None:
        # A rating earned on a listing site is a real fact and not this
        # platform's measurement. Without the note it reads as ours.
        resolved = resolve_brand(
            {"highlights": [{"value": "4.6", "label": "Rated", "note": "85 reviews on JustDial"}]}
        )
        self.assertEqual(resolved["highlights"][0]["note"], "85 reviews on JustDial")

    def test_too_many_highlights_are_refused(self) -> None:
        with self.assertRaises(BrandValidationError):
            resolve_brand({"highlights": [{"value": "1", "label": "a"}] * (MAX_HIGHLIGHTS + 1)})

    def test_a_row_written_before_the_caps_existed_is_cut_on_the_way_out(self) -> None:
        restaurant = SimpleNamespace(
            brand={
                "specialities": ["ok"] * (MAX_SPECIALITIES + 5),
                "highlights": [{"value": "1", "label": "a"}] * (MAX_HIGHLIGHTS + 3),
            }
        )
        read = read_brand(restaurant)
        self.assertEqual(len(read["specialities"]), MAX_SPECIALITIES)
        self.assertEqual(len(read["highlights"]), MAX_HIGHLIGHTS)


if __name__ == "__main__":
    unittest.main()