"""A ticket never silently drops text.

These exist because the first dry run of a realistic order printed this, with
thirty-two renderer tests passing:

    NO PEANUTS - severe allergy. Ring the bell twice
    A-31 Rangdarshan Society, Near Dhanmora, Katarga

The note lost its final character and the address lost "Surat, Gujarat,
395004" — the part a rider actually needs. The renderer was correct: the
DOCUMENT held every word. The layout truncated at the paper's width, and
nothing asserted on what the paper shows.

That is the gap these close. The failure mode is specific and nasty: a
truncated ticket looks deliberate. Nobody reading "Near Dhanmora, Katarga"
thinks "this is cut off", they think that is the address.

The agent reimplements this in ESC/POS, and its own tests compare line breaks
against these for the same documents, so the two cannot drift into disagreeing
about where a long address breaks.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.print.document import (  # noqa: E402
    Document,
    blank,
    cut,
    item,
    kv,
    rule,
    text,
)
from app.services.print.layout import lay_out  # noqa: E402


def rows(*lines, width: int = 32) -> list[str]:
    return lay_out(Document(width=width, lines=list(lines))).split("\n")


class NothingIsEverTruncated(unittest.TestCase):
    def test_a_long_note_keeps_its_last_word(self) -> None:
        note = "NO PEANUTS - severe allergy. Ring the bell twice."
        out = rows(text(note))
        self.assertEqual(" ".join(out), note)
        # And the bug, stated: it used to end "Ring the bell twice" with the
        # full stop gone, on one line of exactly 48 characters.
        self.assertTrue(out[-1].endswith("twice."))

    def test_a_long_address_keeps_its_city_and_postcode(self) -> None:
        address = (
            "A-31 Rangdarshan Society, Near Dhanmora, Katargam, "
            "Surat, Gujarat, 395004"
        )
        out = rows(text(address))
        joined = " ".join(out)
        self.assertEqual(joined, address)
        for part in ("Surat", "Gujarat", "395004"):
            self.assertIn(part, joined, f"{part} fell off the ticket")

    def test_every_row_fits_the_paper(self) -> None:
        # The other half of not truncating: wrapping that overflows is just
        # truncation done by the printer instead, where we cannot see it.
        for width in (32, 42, 48):
            out = rows(
                text("A-31 Rangdarshan Society, Near Dhanmora, Katargam, Surat 395004"),
                item(2, "Paneer Butter Masala with extra gravy and two parathas"),
                kv("Phone", "9825322860"),
                width=width,
            )
            for row in out:
                self.assertLessEqual(len(row), width, f"{row!r} overflows {width}")

    def test_a_word_longer_than_the_paper_is_split_not_lost(self) -> None:
        # It has to break somewhere. Breaking it beats losing its tail.
        out = rows(text("Chandrashekharpuramkattupakkamthiruvananthapuram"), width=32)
        self.assertEqual("".join(out), "Chandrashekharpuramkattupakkamthiruvananthapuram")

    def test_an_empty_line_still_occupies_its_row(self) -> None:
        # The document asked for a row. Collapsing it would close up spacing
        # the renderer put there deliberately.
        self.assertEqual(rows(text("")), [""])


class ADoubleSizeLineGetsHalfThePaper(unittest.TestCase):
    """ESC/POS double height is also double WIDTH.

    Missing this is how the void slip broke: "*** CANCELLED ***" is 17
    characters, a double line on 58mm paper has 16, and the printer wrapped it
    itself — mid-banner, wherever it landed. Wrapping here means we choose.
    """

    def test_it_wraps_at_half_the_column_count(self) -> None:
        out = rows(text("ABCDEFGHIJKLMNOPQRSTUVWX", size="double"), width=32)
        # 24 characters at double width needs 24 of 16 columns, so two rows.
        self.assertEqual(len(out), 2)
        self.assertEqual("".join(row.strip() for row in out), "ABCDEFGHIJKLMNOPQRSTUVWX")

    def test_cancelled_fits_at_double_size_on_the_narrowest_paper(self) -> None:
        # The fix for the void slip, pinned. "CANCELLED" is nine characters
        # and must stay on one row at 32 columns, or the loudest ticket in the
        # system is the one that looks broken.
        out = rows(text("CANCELLED", align="center", size="double"), width=32)
        self.assertEqual(len(out), 1)
        self.assertIn("CANCELLED", out[0])

    def test_a_normal_line_gets_the_whole_paper(self) -> None:
        out = rows(text("ABCDEFGHIJKLMNOP"), width=16)
        self.assertEqual(out, ["ABCDEFGHIJKLMNOP"])


class AValueIsNeverShortened(unittest.TestCase):
    def test_the_label_gives_way_not_the_value(self) -> None:
        # Half a phone number is a rider who cannot call. A shortened label
        # still reads.
        out = rows(kv("Customer phone number", "9825322860"), width=20)
        self.assertEqual(len(out), 1)
        self.assertIn("9825322860", out[0])
        self.assertEqual(len(out[0]), 20)

    def test_a_value_stays_on_one_row(self) -> None:
        # Wrapping a total onto two rows would make "₹1,2" and "34.00" look
        # like two numbers.
        out = rows(kv("TOTAL", "₹462.50"), width=32)
        self.assertEqual(len(out), 1)

    def test_the_value_is_flush_right(self) -> None:
        out = rows(kv("Order", "#6373B312"), width=32)
        self.assertTrue(out[0].endswith("#6373B312"))
        self.assertTrue(out[0].startswith("Order"))


class AnItemReadsAsOneItem(unittest.TestCase):
    def test_modifiers_are_indented_under_their_dish(self) -> None:
        # A cook scanning the left edge is counting dishes, so nothing but a
        # quantity starts at column zero.
        out = rows(
            item(1, "Build Your Own Pizza", mods=["Left: Olives", "Right: Paneer"]),
            width=48,
        )
        self.assertEqual(out[0], "1 x Build Your Own Pizza")
        self.assertTrue(all(row.startswith("    ") for row in out[1:]))

    def test_a_wrapped_dish_name_hangs_rather_than_restarting(self) -> None:
        # Flush-left continuation would read as a second dish with no quantity.
        out = rows(item(2, "Paneer Butter Masala with extra gravy", mods=[]), width=24)
        self.assertEqual(out[0], "2 x Paneer Butter Masala")
        self.assertTrue(out[1].startswith("    "))

    def test_a_long_modifier_wraps_deeper_than_its_own_indent(self) -> None:
        out = rows(
            item(1, "Pizza", mods=["Left: Olives, Jalapeno, Mushroom, Paneer, Corn"]),
            width=32,
        )
        continuations = [row for row in out[2:]]
        self.assertTrue(continuations, "the modifier should have wrapped")
        self.assertTrue(all(row.startswith("      ") for row in continuations))


class TheStructuralLinesDrawFullWidth(unittest.TestCase):
    def test_a_rule_spans_the_paper(self) -> None:
        self.assertEqual(rows(rule(), width=12), ["-" * 12])

    def test_a_rule_can_be_drawn_in_another_character(self) -> None:
        # What makes the void slip's banner wrap-proof.
        self.assertEqual(rows(rule("*"), width=12), ["*" * 12])

    def test_a_blank_is_one_empty_row(self) -> None:
        self.assertEqual(rows(blank()), [""])

    def test_a_cut_prints_nothing(self) -> None:
        # It is an instruction to the printer, not a mark on the paper. The
        # preview used to draw "=====  <cut>", which is fine to look at and
        # wrong as the spooler's output — this module IS the WINDOWS
        # transport's text.
        self.assertEqual(rows(cut()), [""])


class AlignmentIsAboutThePaperNotTheText(unittest.TestCase):
    def test_centering_uses_the_full_width_even_for_a_double_line(self) -> None:
        # The text wraps at half the width but is centred on the whole paper,
        # or a double-size banner would sit in the left half of the ticket.
        out = rows(text("CANCELLED", align="center", size="double"), width=32)
        self.assertEqual(len(out[0]), 32)
        self.assertTrue(out[0].startswith(" "))
        self.assertTrue(out[0].endswith(" "))

    def test_right_alignment_reaches_the_edge(self) -> None:
        out = rows(text("12.50", align="right"), width=16)
        self.assertTrue(out[0].endswith("12.50"))
        self.assertEqual(len(out[0]), 16)


if __name__ == "__main__":
    unittest.main()
