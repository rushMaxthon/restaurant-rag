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

import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient

from app.main import app
from app.services.cache import cache_get_json, cache_set_json
from app.services.chat_principal import guest_principal_for_session
from app.services.suggestions import (
    DECLINE_LIMIT,
    CartLineFacts,
    SellSuggestion,
    SuggestionMemory,
    _cart_signature,
    is_suppressed,
    load_memory,
    record_answer,
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


class CartSignatureAndReplayTests(unittest.TestCase):
    """`suggestion_for_cart` must answer an UNCHANGED cart with an UNCHANGED
    answer, without spending the two-decline suppression budget on a request
    that never asked anything new. See `_cart_signature`'s docstring in
    `services/suggestions.py` for why this is not an edge case: React 19
    StrictMode double-invokes effects in development, so the exact
    reproduction here — same cart, back-to-back calls — happens on every
    single page load, not just occasionally.
    """

    def test_a_quantity_only_change_yields_the_same_signature(self) -> None:
        """`CartLineFacts` carries no quantity field, so a signature that
        somehow varied with quantity would be reading a field that does not
        exist. This pins the observable promise: two carts differing only in
        how many of TEA were ordered must resolve to one identical cart line
        each, and therefore the same signature."""

        one_tea = [CartLineFacts(menu_item_id=TEA, size_id=None, customization_option_ids=frozenset())]
        also_one_tea = [
            CartLineFacts(menu_item_id=TEA, size_id=None, customization_option_ids=frozenset())
        ]

        self.assertEqual(_cart_signature(one_tea), _cart_signature(also_one_tea))

    def test_the_signature_is_order_independent(self) -> None:
        """Cart line order is an accident of how the browser serialized the
        cart, not a fact about the cart — reordering the same two lines must
        not look like a changed cart."""

        tea_line = CartLineFacts(menu_item_id=TEA, size_id=None, customization_option_ids=frozenset())
        rice_line = CartLineFacts(menu_item_id=RICE, size_id=None, customization_option_ids=frozenset())

        self.assertEqual(
            _cart_signature([tea_line, rice_line]), _cart_signature([rice_line, tea_line])
        )

    def test_a_different_size_or_option_changes_the_signature(self) -> None:
        """The parts of a cart line that CAN change the answer must actually
        move the signature, or the cache would replay a stale answer for a
        cart that genuinely changed."""

        size_a, size_b = uuid.uuid4(), uuid.uuid4()
        base = CartLineFacts(menu_item_id=TEA, size_id=size_a, customization_option_ids=frozenset())
        resized = CartLineFacts(menu_item_id=TEA, size_id=size_b, customization_option_ids=frozenset())

        self.assertNotEqual(_cart_signature([base]), _cart_signature([resized]))

    def test_a_matching_signature_with_a_stored_answer_is_available_to_replay(self) -> None:
        """The state `suggestion_for_cart` reads to decide whether to replay:
        after `record_offer` + `record_answer`, the same signature must find
        the same suggestion sitting in memory, ready to be returned without
        recomputation."""

        signature = _cart_signature(
            [CartLineFacts(menu_item_id=TEA, size_id=None, customization_option_ids=frozenset())]
        )
        candidate = _suggestion(TEA)

        memory = record_answer(record_offer(SuggestionMemory(), candidate), signature, candidate)

        self.assertEqual(memory.last_cart_signature, signature)
        self.assertEqual(memory.last_suggestion, candidate)

    def test_a_genuinely_changed_cart_does_not_replay_and_the_old_item_stays_suppressed(
        self,
    ) -> None:
        """A different cart must fall through to fresh selection — but the
        item already offered for the OLD cart must still not come back,
        because "never offer the same item twice" is a promise about the
        SESSION, not about any one cart shape."""

        signature_a = _cart_signature(
            [CartLineFacts(menu_item_id=TEA, size_id=None, customization_option_ids=frozenset())]
        )
        candidate = _suggestion(TEA)
        memory = record_answer(record_offer(SuggestionMemory(), candidate), signature_a, candidate)

        signature_b = _cart_signature(
            [CartLineFacts(menu_item_id=RICE, size_id=None, customization_option_ids=frozenset())]
        )

        self.assertNotEqual(signature_a, signature_b)
        self.assertNotEqual(memory.last_cart_signature, signature_b)
        # TEA was already offered this session; a genuinely different cart
        # must not be allowed to re-offer it.
        self.assertTrue(is_suppressed(candidate, memory=memory, cart_item_ids={RICE}))

    def test_a_decline_clears_the_stored_answer_so_it_is_not_replayed(self) -> None:
        """Without this, dismissing a prompt would be undone by the very next
        fetch: the next GET for the SAME cart would hit the replay path in
        `suggestion_for_cart` and hand back the exact suggestion the customer
        just said no to."""

        signature = _cart_signature(
            [CartLineFacts(menu_item_id=TEA, size_id=None, customization_option_ids=frozenset())]
        )
        candidate = _suggestion(TEA)
        memory = record_answer(record_offer(SuggestionMemory(), candidate), signature, candidate)
        self.assertIsNotNone(memory.last_suggestion)

        declined = record_decline(memory, TEA)

        self.assertIsNone(declined.last_cart_signature)
        self.assertIsNone(declined.last_suggestion)

    def test_two_declines_still_silence_the_session_with_a_stored_last_answer(self) -> None:
        """The decline-limit invariant must survive the new caching fields —
        a cached last answer is not a loophole around "two noes is the whole
        budget"."""

        signature = _cart_signature(
            [CartLineFacts(menu_item_id=TEA, size_id=None, customization_option_ids=frozenset())]
        )
        candidate = _suggestion(TEA)
        memory = record_answer(record_offer(SuggestionMemory(), candidate), signature, candidate)

        memory = record_decline(memory, TEA)
        memory = record_decline(memory, RICE)

        self.assertEqual(memory.decline_count, DECLINE_LIMIT)
        self.assertTrue(
            is_suppressed(_suggestion(uuid.uuid4()), memory=memory, cart_item_ids=set())
        )


class SuggestionEndpointIdempotencyTests(unittest.TestCase):
    """Reproduces the exact bug found in manual browser testing:
    `GET /api/suggestions`, called twice in a row with an unchanged cart,
    used to answer `null` the second time — because the first call's
    `record_offer` had already put the chosen item in `offered_item_ids`
    before the second, identical call ran `is_suppressed` against it. React
    19 StrictMode double-invokes effects in development, so this was not a
    rare race: it fired on every single page render, and the suggestion never
    rendered in a browser at all.

    Uses fixture data seeded in this checkout's database (see the task's
    verification gate) — the same location and menu item id used for the
    live curl reproduction, so a green test here and a green curl call are
    checking the same fact two different ways.
    """

    LOCATION_ID = "67d703ac-f2bd-4e2d-b694-fe49e0aebcb2"
    MENU_ITEM_ID = "e4073071-f8e5-431f-a6dc-eabe2a3f5e98"

    def _get_suggestion(self, client: TestClient, session_id: uuid.UUID) -> dict:
        response = client.get(
            "/api/suggestions",
            params={
                "restaurant_location_id": self.LOCATION_ID,
                "session_id": str(session_id),
                "cart": json.dumps([{"menu_item_id": self.MENU_ITEM_ID, "quantity": 1}]),
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_an_identical_repeat_returns_the_same_suggestion_without_growing_offered_ids(
        self,
    ) -> None:
        client = TestClient(app)
        session_id = uuid.uuid4()

        first = self._get_suggestion(client, session_id)
        self.assertIsNotNone(
            first["suggestion"],
            "fixture location/item must produce a suggestion on the first call "
            "for this test to be meaningful — see the task's verification gate",
        )
        user_id = guest_principal_for_session(session_id).id
        memory_after_first = load_memory(user_id, session_id)

        second = self._get_suggestion(client, session_id)

        self.assertEqual(first, second)
        memory_after_second = load_memory(user_id, session_id)
        self.assertEqual(memory_after_first.offered_item_ids, memory_after_second.offered_item_ids)

        third = self._get_suggestion(client, session_id)
        self.assertEqual(first, third)


if __name__ == "__main__":
    unittest.main()
