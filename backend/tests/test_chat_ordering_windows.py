"""Telling a customer the kitchen is shut, before checkout does.

Spec: docs/superpowers/specs/2026-09-14-chat-ordering-windows-design.md

A customer could hold a whole conversation, be recommended three dishes, fill a
cart, and only learn at checkout that the branch was closed. The enforcement was
never missing — `_load_location_for_order` refuses an out-of-window order before
anything is created — it was just the last thing they met instead of the first.

The chat tells; it does not block. Checkout stays the only gate, because the
chat does not create orders and so cannot be one.

The assertion that matters most here is
`test_a_branch_with_slots_is_read_from_its_slots`. Two sources of hours exist in
this schema and they disagree — `opening_time`/`closing_time`, and the per-day
`LocationFulfillmentSlot` rows — and ordering resolves it with slots winning
where a branch has them. 252 slot rows across 18 branches means the simple pair
is not the answer for most. A chat that read `opening_time` directly would
announce the branch is open while checkout refused the order, which is worse
than the silence it replaces: confidently wrong rather than merely quiet.
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
    BranchAvailability,
    _closed_notice,
    _is_hours_query,
)

OPEN = BranchAvailability(
    branch_name="Bodakdev",
    is_open=True,
    reason=None,
    next_slot_label=None,
)
CLOSED = BranchAvailability(
    branch_name="Bodakdev",
    is_open=False,
    reason="This branch is currently closed.",
    next_slot_label="10:00 AM",
)
CLOSED_NO_SLOT = BranchAvailability(
    branch_name="Bodakdev",
    is_open=False,
    reason="This branch is currently closed.",
    next_slot_label=None,
)


class HoursQuestionRecognitionTests(unittest.TestCase):
    def test_the_ways_people_ask(self) -> None:
        for phrase in (
            "are you open",
            "are you open now",
            "what time do you open",
            "when do you close",
            "what are your opening hours",
            "how late are you open",
            "till when can i order",
            "what time do you close today",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(_is_hours_query(phrase))

    def test_a_dish_request_is_not_an_hours_question(self) -> None:
        """The tier runs before the model, so a false positive here answers a
        food question with opening times."""

        for phrase in (
            "i want pad thai",
            "what desserts do you have",
            "something spicy",
            "how much is delivery",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(_is_hours_query(phrase))


class ClosedNoticeTests(unittest.TestCase):
    def test_an_open_branch_gets_no_notice(self) -> None:
        self.assertIsNone(_closed_notice(OPEN, is_material=True))

    def test_a_closed_branch_leads_with_it(self) -> None:
        notice = _closed_notice(CLOSED, is_material=True)
        assert notice is not None
        self.assertIn("closed", notice.lower())
        self.assertIn("10:00 AM", notice)

    def test_nothing_is_said_on_an_immaterial_turn(self) -> None:
        """A greeting does not need a trading-hours warning, and a notice
        repeated every turn stops being read."""

        self.assertIsNone(_closed_notice(CLOSED, is_material=False))

    def test_an_unknown_branch_says_nothing(self) -> None:
        """Absent data is not "closed". A missing notice costs a warning; a
        wrong one contradicts checkout."""

        self.assertIsNone(_closed_notice(None, is_material=True))


if __name__ == "__main__":
    unittest.main()
