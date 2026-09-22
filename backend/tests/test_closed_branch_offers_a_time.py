"""A closed kitchen offers a time; it does not end the conversation.

"I could not place that order just now" to somebody who has filled a cart and
typed their name, phone, email and address is the worst sentence this system
can produce. They did nothing wrong, there is nothing for them to fix, and
the order they built is gone.

The invitation already existed — "We are closed for delivery right now. The
next time I can do is 11:00 — shall I place it for then?" — but it was only
offered when the customer had named NO time. Name one the branch could not
keep and the offer was skipped entirely, which left exactly the wall the
invitation was written to avoid.

Two things are tested here, because they are the two shapes the refusal takes:

* closed with no time named — offer the next slot from now;
* a named time that cannot be kept — say which time, and offer the closest
  slot to THAT, not to now. Somebody asking for Monday lunch is not helped by
  being offered this morning.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.loop import describe_place_failure
from app.services.ordering_agent.planner import ToolCallRecord


def refusal(**over) -> list[ToolCallRecord]:
    result = {"outcome": "refused", "reason": "Delivery is outside the branch schedule"}
    result.update(over)
    return [ToolCallRecord(tool="place_order", args={}, result=result)]


class ClosedWithNoTimeNamedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.said = describe_place_failure(
            refusal(
                next_open="2026-09-19T11:00:00+05:30",
                fulfillment_label="delivery",
            )
        )

    def test_it_offers_the_next_slot(self) -> None:
        self.assertIn("11:00", self.said)

    def test_it_says_the_order_can_still_be_taken(self) -> None:
        # The difference between a refusal and an invitation is one clause.
        self.assertIn("still take this for later", self.said)

    def test_it_asks_rather_than_assuming(self) -> None:
        # The time is offered, never chosen for them: a scheduled order they
        # did not agree to is food arriving when nobody is home.
        self.assertIn("shall I place it for then", self.said)
        self.assertIn("another time", self.said)

    def test_it_never_says_the_dead_end(self) -> None:
        self.assertNotIn("could not place", self.said)


class ATimeTheBranchCannotKeepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.said = describe_place_failure(
            refusal(
                next_open="2026-09-21T11:00:00+05:30",
                wanted_time="2026-09-21T03:30:00+05:30",
                fulfillment_label="delivery",
            )
        )

    def test_it_names_the_time_they_asked_for(self) -> None:
        # "That will not work" about an unnamed time reads as a refusal of
        # the whole order rather than of one detail of it.
        self.assertIn("03:30", self.said)

    def test_it_offers_the_closest_slot_to_what_they_wanted(self) -> None:
        self.assertIn("11:00", self.said)

    def test_it_still_asks(self) -> None:
        self.assertIn("shall I make it that", self.said)
        self.assertIn("another time", self.said)

    def test_it_never_says_the_dead_end(self) -> None:
        self.assertNotIn("could not place", self.said)


class WithoutASlotToOfferTests(unittest.TestCase):
    """A branch with no schedule at all still owes a reason.

    There is nothing to offer here, so the reason the backend gave IS the
    answer — that is honest, and the customer can act on "this branch is
    closed" in a way they cannot act on "just now".
    """

    def test_the_reason_is_said(self) -> None:
        said = describe_place_failure(refusal(reason="This branch is currently closed"))
        self.assertIn("This branch is currently closed", said)


class TheOtherRefusalsAreUnchangedTests(unittest.TestCase):
    """Each one a customer can act on, and none of them about time."""

    def test_a_short_order_says_both_numbers(self) -> None:
        said = describe_place_failure(
            refusal(subtotal="12.00", minimum="16.00", reason="Below the minimum")
        )
        self.assertIn("12.00", said)
        self.assertIn("16.00", said)

    def test_an_empty_cart(self) -> None:
        said = describe_place_failure(
            [ToolCallRecord(tool="place_order", args={}, result={"outcome": "empty_cart"})]
        )
        self.assertIn("nothing in your order", said)

    def test_an_email_already_in_use(self) -> None:
        said = describe_place_failure(
            [ToolCallRecord(tool="place_order", args={}, result={"outcome": "email_in_use"})]
        )
        self.assertIn("different email", said)


if __name__ == "__main__":
    unittest.main()
