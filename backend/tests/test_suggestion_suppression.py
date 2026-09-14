"""When the waiter stops talking.

The cadence was a product decision, not an implementation detail: one
suggestion per reply, never the same item twice, and silence after two
declines. A waiter who asks a third time after two noes is the reason people
stop reading suggestions at all.

Memory is keyed by session and shared by BOTH transports. A prompt dismissed
on the home page must not reappear in the chat — that is the same session and
the same customer, and being asked twice reads as not listening.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.cache import cache_get_json, cache_set_json
from app.services.suggestions import (
    DECLINE_LIMIT,
    SellSuggestion,
    SuggestionMemory,
    is_suppressed,
    load_memory,
    record_decline,
    record_offer,
    store_memory,
)

TEA = uuid.uuid4()
RICE = uuid.uuid4()


def _redis_is_live() -> bool:
    """One throwaway round-trip, used only to gate the real-Redis test.

    `cache_get_json`/`cache_set_json` degrade to a miss whenever Redis is
    down, by design (see `app.services.cache`), so a round-trip test would
    fail for an environmental reason on a machine with no Redis rather than
    for a real regression. This probe lets that test skip cleanly instead of
    reporting a false failure.
    """

    probe_key = f"suggestions:memory:probe:{uuid.uuid4()}"
    if not cache_set_json(probe_key, {"ok": True}, ttl_seconds=5):
        return False
    return cache_get_json(probe_key) == {"ok": True}


def _suggestion(item_id=TEA) -> SellSuggestion:
    return SellSuggestion(kind="cross_sell", basis="co_occurrence", menu_item_id=item_id)


class SuppressionTests(unittest.TestCase):
    def test_a_fresh_session_suppresses_nothing(self) -> None:
        self.assertFalse(
            is_suppressed(_suggestion(), memory=SuggestionMemory(), cart_item_ids=set())
        )

    def test_an_item_already_offered_is_not_offered_again(self) -> None:
        memory = record_offer(SuggestionMemory(), _suggestion())

        self.assertTrue(is_suppressed(_suggestion(), memory=memory, cart_item_ids=set()))

    def test_an_item_already_in_the_cart_is_never_offered(self) -> None:
        self.assertTrue(
            is_suppressed(_suggestion(), memory=SuggestionMemory(), cart_item_ids={TEA})
        )

    def test_two_declines_silence_everything(self) -> None:
        memory = record_decline(record_decline(SuggestionMemory(), TEA), RICE)

        self.assertEqual(DECLINE_LIMIT, 2)
        # Even an item never offered before is suppressed once the session is done.
        self.assertTrue(
            is_suppressed(
                _suggestion(uuid.uuid4()), memory=memory, cart_item_ids=set()
            )
        )

    def test_one_decline_does_not_silence_a_different_item(self) -> None:
        memory = record_decline(SuggestionMemory(), RICE)

        self.assertFalse(is_suppressed(_suggestion(TEA), memory=memory, cart_item_ids=set()))

    def test_a_declined_item_stays_declined(self) -> None:
        memory = record_decline(SuggestionMemory(), TEA)

        self.assertTrue(is_suppressed(_suggestion(TEA), memory=memory, cart_item_ids=set()))

    def test_recording_is_pure(self) -> None:
        """The caller decides whether to persist; the rule never mutates in place."""

        original = SuggestionMemory()
        record_offer(original, _suggestion())

        self.assertEqual(original.offered_item_ids, frozenset())

    def test_an_upsell_on_an_item_already_in_the_cart_is_not_suppressed(self) -> None:
        """size_upgrade and add_on both target the item the customer just ordered.

        The in-cart check exists to stop offering a *new* item the customer
        already has — it cannot apply to up-sells, whose entire premise is a
        bigger size or an extra on a line that is, by definition, in the cart
        already. Applying it there would silence choose_upsell's whole ladder.
        """

        up_sell = SellSuggestion(
            kind="up_sell", basis="size_upgrade", menu_item_id=TEA, size_id=uuid.uuid4()
        )

        self.assertFalse(
            is_suppressed(up_sell, memory=SuggestionMemory(), cart_item_ids={TEA})
        )

    def test_a_combo_upgrade_is_remembered_by_its_combo_id(self) -> None:
        """combo_upgrade suggestions carry combo_id but no menu_item_id.

        Keying suppression on menu_item_id alone would mean a combo offer can
        never be recorded, so it would come back on every single turn —
        exactly the "never the same thing twice" rule this module exists to
        enforce.
        """

        combo_id = uuid.uuid4()
        combo_suggestion = SellSuggestion(
            kind="up_sell", basis="combo_upgrade", combo_id=combo_id, saving=None
        )

        memory = record_offer(SuggestionMemory(), combo_suggestion)

        self.assertTrue(
            is_suppressed(combo_suggestion, memory=memory, cart_item_ids=set())
        )


class MemoryPersistenceTests(unittest.TestCase):
    def test_a_corrupt_cache_payload_yields_a_fresh_memory_rather_than_raising(self) -> None:
        """A payload Redis hands back is not guaranteed to be one this code wrote.

        Silent failure here looks like nothing at all in production: every
        request would deserialize to a fresh, empty SuggestionMemory, so the
        site would re-offer an item a customer just declined, or ask a third
        time after two noes — the exact pestering this module exists to stop.
        Nothing crashes, nothing logs an error a person notices; the bug is
        indistinguishable from the feature quietly not working. This test
        pins the recovery path so the day the payload shape changes (a schema
        edit, a bad migration, a hand-rolled cache flush) the fallback still
        lands on "fresh memory," not an unhandled exception mid-request.
        """

        user_id = uuid.uuid4()
        session_id = uuid.uuid4()

        with self.subTest("non-dict payload"), patch(
            "app.services.suggestions.cache_get_json", return_value=["not", "a", "dict"]
        ):
            self.assertEqual(load_memory(user_id, session_id), SuggestionMemory())

        with self.subTest("dict with junk list contents"), patch(
            "app.services.suggestions.cache_get_json",
            return_value={
                "offered": [123, "definitely-not-a-uuid"],
                "declined": ["also-not-a-uuid"],
                "decline_count": 0,
            },
        ):
            self.assertEqual(load_memory(user_id, session_id), SuggestionMemory())

    def test_a_missing_session_is_a_no_op_at_both_ends(self) -> None:
        """`GET /api/suggestions` can fire before a chat session exists.

        load_memory must hand that caller something usable rather than None,
        and store_memory must not explode trying to persist state for a
        session that was never established — both ends of the contract that
        lets the page-render transport work without a conversation.
        """

        user_id = uuid.uuid4()

        self.assertEqual(load_memory(user_id, None), SuggestionMemory())
        store_memory(user_id, None, SuggestionMemory(decline_count=1))  # must not raise

    @unittest.skipUnless(_redis_is_live(), "Redis is not reachable on this machine")
    def test_storing_and_loading_a_memory_round_trips_through_redis(self) -> None:
        """The only test in this file that talks to real Redis.

        Everything else here exercises the pure rules and the corrupt-payload
        fallback with a mock, which proves the parsing logic but not that a
        `SuggestionMemory` written today reads back as the same value later —
        that is the actual promise `load_memory`/`store_memory` make to Tasks
        5 and 6, and only a real round trip can check it.
        """

        user_id = uuid.uuid4()
        session_id = uuid.uuid4()  # unique per run, so no leftover key can collide
        memory = SuggestionMemory(
            offered_item_ids=frozenset({TEA, RICE}),
            declined_item_ids=frozenset({uuid.uuid4()}),
            decline_count=2,
        )

        store_memory(user_id, session_id, memory)

        self.assertEqual(load_memory(user_id, session_id), memory)


if __name__ == "__main__":
    unittest.main()
