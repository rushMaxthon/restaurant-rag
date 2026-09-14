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

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.suggestions import (
    DECLINE_LIMIT,
    SellSuggestion,
    SuggestionMemory,
    is_suppressed,
    record_decline,
    record_offer,
)

TEA = uuid.uuid4()
RICE = uuid.uuid4()


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


if __name__ == "__main__":
    unittest.main()
