"""Tests for how an answer is shaped, and for what shaping must not break.

Two things are being protected. The first is that formatting adapts: a single
fact stays a sentence, several parallel facts become a list, and a
recommendation keeps its action separate from its reason. The second, and the
one that would be expensive to get wrong, is that formatting is *only*
formatting — the digits a guardrail extracts have to survive it untouched, or
emphasis around a figure would start failing answers that were correct.
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
from app.services.insights.chat import _claims_causation, chunk_answer
from app.services.insights.facts import extract_numbers, unsupported_numbers
from app.services.insights.presentation import (
    action,
    blocks,
    bold,
    bullets,
    heading,
    labelled,
    numbered,
    paragraph,
)


class PresentationTests(unittest.TestCase):
    def test_blocks_are_separated_by_a_blank_line(self) -> None:
        # A blank line is what makes the next line a new block rather than a
        # continuation of the last one.
        self.assertEqual(blocks("one", "two"), "one\n\ntwo")

    def test_empty_sections_disappear_entirely(self) -> None:
        # A caller can pass an optional section unguarded and not leave a gap
        # where it would have been.
        self.assertEqual(blocks("one", "", None, "two"), "one\n\ntwo")

    def test_bullets_and_numbers_are_one_per_line(self) -> None:
        self.assertEqual(bullets(["a", "b"]), "- a\n- b")
        self.assertEqual(numbered(["a", "b"]), "1. a\n2. b")

    def test_an_action_puts_the_reason_on_its_own_indented_line(self) -> None:
        # The indent is what the renderer uses to keep the reason attached to
        # the action rather than starting a new point.
        rendered = action("Promote Pad Thai Veg", "It fell by ₹1,329.")
        self.assertEqual(rendered, "**Promote Pad Thai Veg**\n   It fell by ₹1,329.")

    def test_labelled_leads_with_the_label(self) -> None:
        self.assertEqual(labelled("Dish", "Pad Thai fell"), "**Dish** — Pad Thai fell")

    def test_heading_and_paragraph(self) -> None:
        self.assertEqual(heading("What changed"), "### What changed")
        self.assertEqual(paragraph("a.", "b."), "a. b.")


class NumbersSurviveFormattingTests(unittest.TestCase):
    """Emphasis must not change what a number check sees."""

    def test_bold_leaves_the_digits_intact(self) -> None:
        self.assertEqual(extract_numbers(bold("1,578.92")), [1578.92])

    def test_a_bolded_figure_still_validates_against_its_fact(self) -> None:
        # The guardrail rejects any figure the data does not support. If bolding
        # changed what it extracts, correct answers would start being rejected.
        allowed = {1578.92, 35.8}
        self.assertEqual(
            unsupported_numbers(f"Revenue was {bold('₹1,578.92')}, down 35.8%.", allowed),
            [],
        )

    def test_an_unsupported_figure_is_still_caught_through_formatting(self) -> None:
        allowed = {1578.92}
        self.assertEqual(
            unsupported_numbers(f"Revenue was {bold('₹9,999.00')}.", allowed),
            [9999.0],
        )

    def test_markup_characters_are_not_read_as_numbers(self) -> None:
        self.assertEqual(extract_numbers("### Heading\n- bullet\n**bold**"), [])


class ChunkingTests(unittest.TestCase):
    """Streaming must not damage what the formatter built."""

    def test_chunks_reassemble_to_the_original_exactly(self) -> None:
        answer = blocks(
            "Revenue was **₹739**, up 35.9%. It moved on two dishes.",
            "Here is what moved most:",
            bullets(["**Dish** — Pad Thai fell by ₹1,329", "**Category** — Rice grew"]),
            "Order volume is low.",
        )
        self.assertEqual("".join(chunk_answer(answer)), answer)

    def test_a_list_item_is_never_split_across_chunks(self) -> None:
        # A bullet arriving in halves renders as a broken list until the rest of
        # it lands.
        answer = bullets(["one thing. and more", "two"])
        chunks = list(chunk_answer(answer))
        self.assertEqual(chunks, ["- one thing. and more\n", "- two"])

    def test_a_heading_is_not_given_a_full_stop(self) -> None:
        # The previous chunker appended ". " to every piece, turning a heading
        # into "### What changed. ".
        self.assertEqual(list(chunk_answer(heading("What changed"))), ["### What changed"])

    def test_prose_still_streams_a_sentence_at_a_time(self) -> None:
        self.assertEqual(
            list(chunk_answer("One. Two. Three.")), ["One. ", "Two. ", "Three."]
        )

    def test_blank_lines_are_preserved(self) -> None:
        self.assertIn("\n", "".join(chunk_answer("a\n\nb")))


if __name__ == "__main__":
    unittest.main()


class CausalClaimGuardrailTests(unittest.TestCase):
    """The facts show what moved together, never why.

    Rule 5 of the answer prompt forbids causal phrasing, and that was enough for
    qwen3. It is not enough for every model: gpt-oss wrote "driven by" in roughly
    a third of accepted answers during Ollama Cloud validation. A rule the
    product depends on has to be enforced in code, not only asked for.
    """

    def test_causal_phrases_are_rejected(self) -> None:
        for phrase in (
            "Revenue rose, driven by Paneer Tikka.",
            "Sales drove the increase.",
            "Revenue fell because of the closure.",
            "The lift was caused by the new menu.",
            "Growth was due to weekend trade.",
            "Revenue is up thanks to the offer.",
            "The rise came as a result of the promotion.",
            "The discount led to more orders.",
            "The campaign resulted in higher sales.",
            "The gain is attributable to lunch trade.",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(_claims_causation(phrase))

    def test_correlational_wording_is_allowed(self) -> None:
        for phrase in (
            "Paneer Tikka contributed most of the increase.",
            "Revenue was Rs 48,210, up Rs 6,320 alongside a rise in orders.",
            "Lunch added the most, made up most of the change.",
            "Afternoon trade rose, which may be related to the offer.",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(_claims_causation(phrase))

    def test_word_boundaries_do_not_produce_false_positives(self) -> None:
        # "overdue" contains "due", "Droverton" contains "drove". Neither is a
        # causal claim, and a substring match would discard a correct answer.
        self.assertFalse(_claims_causation("Two invoices are overdue this week."))
        self.assertFalse(_claims_causation("The Droverton branch took Rs 900."))


if __name__ == "__main__":
    unittest.main()
