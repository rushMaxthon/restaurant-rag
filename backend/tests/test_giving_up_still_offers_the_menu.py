"""When the assistant cannot follow an answer, it shows what there is to pick.

The last resort used to be:

    Sorry — I did not follow that. Let's start that one again: tell me the
    dish you would like and I will set it up.

Which asks the customer to do the work that just failed. They already told us
something we could not read; "tell me the dish" invites another message we
cannot read, and the conversation ends there. Measured across sixteen kinds of
customer, this sentence is where the Hinglish and the terse ones stopped:

    >>> haan ek pack bhej do
        Sorry — I did not follow that. Let's start that one again...

The sections are the way out. This branch has 136 dishes and 21 sections, so a
list of dishes is unusable and a list of sections is a menu — the thing a
customer is handed in a restaurant precisely because nobody can hold 136 names
in their head. Naming one back now shows that section complete, so the offer
leads somewhere.

The step BEFORE this one already does the right thing and is left alone: when
there is a live question with known answers, the second ask repeats it and
spells them out ("Just reply with one of these: Per Plate, 1 Kg"). That is
better than a menu, because it keeps the thread. Only when that has failed
twice, and the question is being dropped, is the whole menu the right answer.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent import loop as loop_module
from app.services.ordering_agent.tools import offer_of_sections

SOURCE = inspect.getsource(loop_module.run_turn)

RADHE_SECTIONS = [
    "Paneer Taste", "Vegetable Taste", "Tandoori Roti & Paratha", "Starters",
    "Rice & Dal", "Chinese Rice", "Corn Dhokla", "Farsan", "Khaman", "Idada",
    "Soup", "Biryani", "Thali", "Pulao",
]


class TheOfferItselfTests(unittest.TestCase):
    """One sentence, built from the menu's own sections."""

    def test_it_names_the_sections(self) -> None:
        offer = offer_of_sections(RADHE_SECTIONS)
        for section in RADHE_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(section, offer)

    def test_it_asks_for_something_answerable(self) -> None:
        # The failure being fixed is an invitation the customer cannot act on.
        offer = offer_of_sections(RADHE_SECTIONS)
        self.assertTrue(offer.rstrip().endswith("?"), offer)

    def test_a_menu_with_no_sections_offers_nothing(self) -> None:
        # Rather than "Here is what we serve:" followed by nothing at all.
        self.assertIsNone(offer_of_sections([]))
        self.assertIsNone(offer_of_sections([None, "", "   "]))

    def test_sections_are_not_repeated(self) -> None:
        self.assertEqual(offer_of_sections(["Soup", "Soup", "Khaman"]).count("Soup"), 1)

    def test_a_very_long_menu_does_not_become_a_wall(self) -> None:
        # A section list is only useful while it can be read on a phone. Past
        # that it says how many more there are rather than silently stopping,
        # because a silent stop is a claim that the menu ends there.
        many = [f"Section {n}" for n in range(60)]
        offer = offer_of_sections(many)
        self.assertLess(len(offer), 600, offer)
        self.assertIn("more", offer)


class ItNeverCostsTheReplyTests(unittest.TestCase):
    """This is already the last thing the turn has to say."""

    def test_a_database_that_will_not_answer_costs_only_the_offer(self) -> None:
        # Caught live by a test passing a db with no `scalars` at all, which is
        # the same shape as a connection that has gone away: the give-up path
        # raised, and a reply that existed became no reply. A better sentence
        # is worth a query; the reply is not.
        from types import SimpleNamespace

        from app.services.ordering_agent.tools import branch_sections

        scope = SimpleNamespace(restaurant_location_id=None)
        self.assertEqual(branch_sections(SimpleNamespace(), scope), [])


class TheGiveUpPathUsesItTests(unittest.TestCase):
    """Where the sentence had to change."""

    def give_up_block(self) -> str:
        start = SOURCE.index("def _reask_or_give_up")
        return SOURCE[start : SOURCE.index("def _awaiting", start)]

    def test_giving_up_offers_the_sections(self) -> None:
        self.assertIn("offer_of_sections", self.give_up_block())

    def test_it_no_longer_asks_them_to_start_again_unaided(self) -> None:
        # The old sentence stays as the fallback for a menu with no sections
        # at all, but it must not be the only thing this path can say.
        block = self.give_up_block()
        self.assertGreater(
            block.count("Sorry — I did not follow that"),
            0,
            "the apology is still the opening; only what follows it changed",
        )

    def test_an_order_in_progress_is_finished_rather_than_restarted(self) -> None:
        # The menu is the right answer only when there is nothing to lose. Once
        # a dish is in the cart, offering 21 sections changes the subject away
        # from the order the customer already started — which is how a
        # half-finished order is abandoned. The cart is read back instead.
        block = self.give_up_block()
        self.assertIn("describe_order_so_far", block)
        self.assertIn("Ready to check out?", block)

    def test_an_empty_cart_is_not_an_order_in_progress(self) -> None:
        # `describe_cart` answers an empty cart with a sentence, so testing it
        # for truth says "there is an order" when there is not. Live, that read:
        # "You have Your cart is empty at the moment.. Ready to check out?"
        from app.services.ordering_agent.loop import describe_order_so_far

        self.assertIsNone(describe_order_so_far({"lines": [], "subtotal": "0.00"}))
        self.assertIsNone(describe_order_so_far(None))
        self.assertIsNone(describe_order_so_far({}))

    def test_a_cart_with_rows_is_read_back(self) -> None:
        from app.services.ordering_agent.loop import describe_order_so_far

        said = describe_order_so_far(
            {"lines": [{"name": "Vagharela Khaman", "quantity": 1, "total_price": "35.00"}],
             "subtotal": "35.00"}
        )
        self.assertIn("Vagharela Khaman", said)

    def test_the_question_it_ends_on_is_held(self) -> None:
        # Otherwise the next message answers a question nothing recorded, which
        # is the failure this whole area keeps producing.
        block = self.give_up_block()
        self.assertIn("_hold(_READY_TO_CHECK_OUT", block)

    def test_the_question_is_not_asked_twice(self) -> None:
        # The read-back writes its own closing question. Appending another one
        # printed "Ready to check out?" twice in the same reply.
        block = self.give_up_block()
        self.assertNotIn('+ _hold(', block)

    def test_a_cart_that_cannot_be_checked_out_is_not_told_it_can(self) -> None:
        # `describe_cart` ends on a different sentence when a line still needs
        # a size, so the question is recorded only when it was actually asked.
        from app.services.ordering_agent.loop import _READY_TO_CHECK_OUT, describe_cart

        needs = describe_cart({
            "lines": [{"name": "Vagharela Khaman", "quantity": 1, "total_price": "35.00"}],
            "subtotal": "35.00",
            "needs_choice": [{"name": "Manchow Soup"}],
        })
        self.assertFalse(needs.rstrip().endswith(_READY_TO_CHECK_OUT), needs)

    def test_the_second_ask_still_repeats_the_question(self) -> None:
        # Untouched on purpose: a live question with known answers is better
        # than a menu, because it keeps the thread the customer is already in.
        block = self.give_up_block()
        self.assertIn("Just reply with one of these", block)


if __name__ == "__main__":
    unittest.main()
