"""Saying hello, and being told about an order you did not ask about.

From a live WhatsApp thread. The customer sent "Hii" and was answered:

    Your order for Thu 12:42 comes to $20.62 and is waiting to be paid.
    Pay here: ...
    Shall I keep that order?

They cancelled it. The next message surfaced a different unpaid order. They
cancelled that one too. The message after that surfaced a third. The thread
could not be escaped.

Three things were true at once, and it took all three:

1. `"Hii"` was not a greeting. The greeting set knows "hi", "hello", "hey" —
   not the stretched spellings most people actually type — so the message
   fell past the instant greeting reply and reached the ordering agent.
2. That customer had **eighteen** PAYMENT_PENDING orders, because Celery beat
   was not running in this environment and `reap_unpaid_orders_task` had never
   fired. Two days of testing had piled up.
3. The cap on how often an unpaid order may be mentioned counted in the ORDER
   DRAFT, which is wiped whenever an order is placed or cancelled. Every
   cancellation handed the next order a fresh budget.

Only the first and third are code. The second is operational, and the reason
the other two were ever visible.
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

from app.services import rag
from app.services.ordering_agent import order_draft


class StretchedGreetingsAreGreetingsTests(unittest.TestCase):
    """"Hii" is how a very large number of people say hello."""

    def test_the_message_from_the_thread(self) -> None:
        self.assertTrue(rag._is_greeting_message("Hii"))

    def test_the_family_it_belongs_to(self) -> None:
        for message in (
            "Hii", "hii", "Hiii", "Hiiii",
            "heyy", "heyyy", "Helloo", "hellooo",
            "hey there", "Hi", "hello", "Hey",
        ):
            with self.subTest(message=message):
                self.assertTrue(rag._is_greeting_message(message))

    def test_a_greeting_never_reaches_the_ordering_agent(self) -> None:
        # The instant greeting path is what keeps a hello out of the agent,
        # and it is keyed on exactly this test.
        state = rag.SessionConversationState()
        for message in ("Hii", "heyy", "Helloo"):
            with self.subTest(message=message):
                self.assertEqual(
                    rag._fallback_extract_intent(message, state).intent, "greeting"
                )


class RealWordsKeepTheirDoubleLettersTests(unittest.TestCase):
    """The flattening is narrow on purpose.

    English is full of real double letters. Collapsing them would turn a menu
    search into nonsense — and every one of these is on the menu.
    """

    def test_dishes_are_not_greetings(self) -> None:
        for message in (
            "food", "naan", "sweet", "coffee", "toffee", "jeera",
            "biryani", "bhel", "dhokla", "paneer", "menu",
        ):
            with self.subTest(message=message):
                self.assertFalse(rag._is_greeting_message(message))

    def test_a_greeting_with_a_request_is_not_just_a_greeting(self) -> None:
        # "hi can i order pizza" wants pizza, and must reach the pipeline.
        self.assertFalse(rag._is_greeting_message("hi can i order pizza"))
        self.assertFalse(rag._is_greeting_message("good food"))

    def test_the_flattener_leaves_ordinary_words_alone(self) -> None:
        for word in ("food", "naan", "sweet", "coffee", "bhel"):
            with self.subTest(word=word):
                self.assertEqual(rag._flatten_stretched_letters(word), word)

    def test_it_only_shortens_what_it_should(self) -> None:
        self.assertEqual(rag._flatten_stretched_letters("hii"), "hi")
        self.assertEqual(rag._flatten_stretched_letters("hiiii"), "hi")
        self.assertEqual(rag._flatten_stretched_letters("heyyy"), "hey")
        self.assertEqual(rag._flatten_stretched_letters("hellooo"), "hello")


class TheUnpaidOrderNoticeIsCappedPerConversationTests(unittest.TestCase):
    """Not per order, and not per draft.

    The old counter lived on `OrderDraft`. `place_order` and a cancellation
    both call `order_draft.clear`, so the budget reset every time the customer
    dealt with the order they had just been told about — which is the one
    moment it must NOT reset.
    """

    def setUp(self) -> None:
        self.session = uuid.uuid4()

    def tearDown(self) -> None:
        order_draft.cache_delete(order_draft._waiting_key(self.session))

    def test_it_starts_at_nothing(self) -> None:
        self.assertEqual(order_draft.waiting_notices(self.session), 0)

    def test_it_counts_up(self) -> None:
        order_draft.note_waiting_notice(self.session)
        self.assertEqual(order_draft.waiting_notices(self.session), 1)
        order_draft.note_waiting_notice(self.session)
        self.assertEqual(order_draft.waiting_notices(self.session), 2)

    def test_clearing_the_draft_does_not_refund_the_budget(self) -> None:
        """The exact step that produced the loop.

        Cancel the order you were just told about, and the draft goes. If the
        count went with it, the next unpaid order started from zero — and
        with eighteen of them the customer could never reach the end.
        """

        order_draft.note_waiting_notice(self.session)
        order_draft.note_waiting_notice(self.session)
        order_draft.save(self.session, order_draft.OrderDraft(contact_name="vishal"))
        order_draft.clear(self.session)

        self.assertEqual(order_draft.waiting_notices(self.session), 2)

    def test_it_is_no_longer_a_draft_field(self) -> None:
        # Leaving the old field behind would let a future change count the
        # wrong thing again without anything failing.
        self.assertFalse(hasattr(order_draft.OrderDraft(), "waiting_asks"))


if __name__ == "__main__":
    unittest.main()
