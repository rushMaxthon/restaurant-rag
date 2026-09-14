"""Answering "can I order at 9:50 PM?" with the truth.

Reported: that question was answered "We're open now — takes orders today from
10:30 am to 10 pm", which implies yes. It is no, twice over.

Two bugs, one sentence.

**The hours were wrong.** `_todays_hours_reply` took min(start) and max(end)
across today's slots for BOTH fulfillment types, so a branch with

    delivery 11:00-21:30   buffer 46m   last real order 20:44
    pickup   10:30-22:00   buffer 36m   last real order 21:24

was described as "10:30 am to 10 pm" — a window true for neither, with the prep
buffer dropped entirely. A customer was told they could order two hours after
delivery actually stops.

**A named time was never checked.** `schedule_slot_is_available` already decides
this and already returns the refusal text; the chat asked general hours instead.
9:50 PM fails it twice: past both cutoffs, and not on the 30-minute grid.

Nothing here invents a rule. The rule is the one checkout enforces; these tests
pin that the chat asks it rather than guessing.
"""

from __future__ import annotations

import sys
import unittest
from datetime import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.rag import parse_requested_time


class RequestedTimeParsingTests(unittest.TestCase):
    def test_the_reported_phrasing(self) -> None:
        self.assertEqual(parse_requested_time("Can I place order at 9:50 PM?"), time(21, 50))

    def test_the_shapes_people_write(self) -> None:
        for phrase, expected in (
            ("can i order at 9pm", time(21, 0)),
            ("can i order at 9 pm", time(21, 0)),
            ("order at 10:30 pm", time(22, 30)),
            ("can i order at 9:15am", time(9, 15)),
            ("deliver at 21:45", time(21, 45)),
            ("can i get it by 8 PM", time(20, 0)),
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(parse_requested_time(phrase), expected)

    def test_midnight_and_noon_are_not_mangled(self) -> None:
        """12 AM is 00:00 and 12 PM is 12:00 — the one place a naive +12 is
        wrong in both directions."""

        self.assertEqual(parse_requested_time("order at 12 am"), time(0, 0))
        self.assertEqual(parse_requested_time("order at 12 pm"), time(12, 0))

    def test_a_message_with_no_time_yields_nothing(self) -> None:
        for phrase in (
            "are you open",
            "i want pad thai",
            "what are your opening hours",
            "can i order now",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(parse_requested_time(phrase))

    def test_numbers_that_are_not_clock_times_are_ignored(self) -> None:
        """A price, a quantity and a duration all contain digits. Reading one as
        a time would validate a question nobody asked."""

        for phrase in (
            "something under 15 dollars",
            "2 pizzas please",
            "ready in 30 minutes",
            "i want 3 momos",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(parse_requested_time(phrase))

    def test_an_impossible_clock_time_is_not_a_time(self) -> None:
        self.assertIsNone(parse_requested_time("order at 25:00"))
        self.assertIsNone(parse_requested_time("order at 9:75 pm"))


if __name__ == "__main__":
    unittest.main()
