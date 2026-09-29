"""A closed kitchen offers a time that can actually be kept, and asks one thing.

Live, on WhatsApp, at 2:57 PM on a Wednesday, with a full cart:

    > yes
      I cannot do Wed 11:00 for delivery. The closest I can do is Wed 11:30
      — shall I make it that, or would you like another time?
    > no
      It seems you're not ready to check out. What would you like to do next?
    > confirm
      I cannot do Wed 11:00 for delivery. The closest I can do is Wed 11:30 ...
    > go with wed 11:30
      That time will not work: Please choose a time at least 20 minutes from
      now. The earliest I can do is Wed 15:30 — shall I make it that?

Three faults in one exchange.

**The 11:00 came from yesterday.** The draft keeps `scheduled_at` for 24 hours
and refreshes that on every save, so a time chosen the evening before was still
there the next afternoon — already past — and the placement reused it.
`_parse_when` already refuses a past time on the way IN ("that time has
already passed"); nothing refused one on the way OUT. `load` drops it now.

**The 11:30 was measured from the 11:00.** `next_available_slot_start` treats
`reference_dt` as "now", and the placement passes the time the customer asked
for — rightly, since somebody asking for tomorrow lunch is not helped by being
offered this morning. But a time already gone by is not a reference; it is
history. The reference is the LATER of what they asked for and now, so the
offer is one the validator will then accept.

**"...or would you like another time?" is two questions.** "No" answered the
second and the model took the turn. One question — "shall I make it that?" —
and a no already has its own path: the offer is held and a time is asked for.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent import order_draft
from app.services.ordering_agent.loop import ToolCallRecord, describe_place_failure
from app.services.ordering_agent.tools import reference_for_next_slot

IST = timezone(timedelta(hours=5, minutes=30))


def at(hour, minute=0, day_offset=0):
    base = datetime(2026, 9, 23, hour, minute, tzinfo=IST)
    return base + timedelta(days=day_offset)


class AStaleTimeIsDroppedOnLoadTests(unittest.TestCase):
    """The draft forgets a time that has gone by."""

    def loaded(self, stored: dict) -> order_draft.OrderDraft:
        with mock.patch.object(order_draft, "cache_get_json", return_value=stored):
            return order_draft.load("session")

    def test_a_time_already_past_is_gone(self) -> None:
        yesterday = (datetime.now(IST) - timedelta(days=1)).isoformat()
        draft = self.loaded({"scheduled_at": yesterday, "contact_name": "Hitesh"})
        self.assertIsNone(draft.scheduled_at, "yesterday's time was reused")
        self.assertEqual(draft.contact_name, "Hitesh", "the details were thrown out with it")

    def test_an_offer_made_for_that_time_goes_with_it(self) -> None:
        # An offer was computed from the stale time, so it is stale too.
        yesterday = (datetime.now(IST) - timedelta(days=1)).isoformat()
        draft = self.loaded({"scheduled_at": yesterday, "offered_scheduled_at": yesterday})
        self.assertIsNone(draft.offered_scheduled_at)

    def test_a_time_still_ahead_is_kept(self) -> None:
        later = (datetime.now(IST) + timedelta(hours=3)).isoformat()
        draft = self.loaded({"scheduled_at": later})
        self.assertEqual(draft.scheduled_at, later)

    def test_a_time_that_cannot_be_read_is_left_for_the_placement_to_refuse(self) -> None:
        # Not this function's call. `_parse_iso` at the placement already
        # treats an unreadable time as no time.
        draft = self.loaded({"scheduled_at": "whenever"})
        self.assertEqual(draft.scheduled_at, "whenever")


class TheOfferIsMeasuredFromNowOrLaterTests(unittest.TestCase):
    """Where the next slot is counted from."""

    def test_a_time_already_gone_by_defers_to_now(self) -> None:
        # The thread: asked-for 11:00, now 14:57. Measuring from 11:00
        # offered 11:30, which the validator then refused as being in the
        # past.
        self.assertEqual(reference_for_next_slot(at(11), now=at(14, 57)), at(14, 57))

    def test_a_time_still_ahead_is_measured_from_itself(self) -> None:
        # Somebody asking for tomorrow lunch is not helped by being offered
        # this morning. That reasoning was right and is kept.
        tomorrow_lunch = at(13, day_offset=1)
        self.assertEqual(reference_for_next_slot(tomorrow_lunch, now=at(14, 57)), tomorrow_lunch)

    def test_no_time_asked_for_means_now(self) -> None:
        self.assertEqual(reference_for_next_slot(None, now=at(14, 57)), at(14, 57))


class OneQuestionAboutTheTimeTests(unittest.TestCase):
    """The sentence the customer answers."""

    def refused(self, *, wanted=None):
        result = {
            "outcome": "refused",
            "next_open": at(15, 30).isoformat(),
            "fulfillment_label": "delivery",
        }
        if wanted is not None:
            result["wanted_time"] = wanted.isoformat()
        return describe_place_failure([ToolCallRecord(tool="place_order", args={}, result=result)])

    def test_a_named_time_that_cannot_be_kept_asks_one_thing(self) -> None:
        said = self.refused(wanted=at(11))
        self.assertEqual(said.count("?"), 1, said)
        self.assertNotIn(", or ", said)

    def test_a_closed_kitchen_asks_one_thing(self) -> None:
        said = self.refused()
        self.assertEqual(said.count("?"), 1, said)
        self.assertNotIn(", or ", said)

    def test_the_offer_is_still_named(self) -> None:
        # Cutting the question back must not cut the time out with it.
        self.assertIn("15:30", self.refused(wanted=at(11)))
        self.assertIn("15:30", self.refused())

    def test_what_they_asked_for_is_still_named_back(self) -> None:
        self.assertIn("11:00", self.refused(wanted=at(11)))


if __name__ == "__main__":
    unittest.main()
