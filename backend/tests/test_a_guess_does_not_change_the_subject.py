"""A question we are waiting on is not dropped for a guess about a dish.

Mid-build, with the crust question standing:

    Which crust for Build Your Own Pizza?
    - Classic hand tossed
    - Cheese burst (+$4.00)
    - Stuffed garlic crust (+$4.50)
    - Thin crust

    > Mozzarella and mushroom
      Did you mean Farmhouse Pizza?

Safe — nothing was bought — and the wrong thing to say. The customer was
naming toppings. The reply abandons the crust question, offers an unrelated
$329 pizza, and leaves the half-built pizza with nothing waiting on it.

The reply pipeline already knows how to say this well. When a message answers
nothing, `_reask_or_give_up` puts the standing question again with its answers
spelled out — "Sorry, I did not catch that. Which crust for Build Your Own
Pizza? Just reply with one of these: ...". That path was never reached here,
because the reading DID produce something actionable: a dish to add. It was
only a guess, and a guess is not a reason to change the subject.

So when a choice is standing, a guessed dish re-asks that choice instead of
proposing itself. A dish named exactly is untouched — "add a Thai Iced Tea
too" mid-build is a real instruction and still works.
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

SOURCE = inspect.getsource(loop_module.run_turn)


def add_named_dish() -> str:
    start = SOURCE.index("def _add_named_dish")
    return SOURCE[start : SOURCE.index("def _run_add", start)]


class TheStandingQuestionWinsTests(unittest.TestCase):
    """What the guess branch does when a choice is already waiting."""

    def test_it_looks_for_a_standing_choice(self) -> None:
        self.assertIn("_pending_choice()", add_named_dish())

    def test_it_puts_that_question_again_rather_than_its_own(self) -> None:
        # The whole point: the crust question survives a message that was not
        # an answer to it.
        body = add_named_dish()
        guess = body.index("would_be_added_without_asking")
        self.assertIn("reask_standing_choice(_pending_choice())", body[guess:])

    def test_it_still_offers_its_guess_when_nothing_is_standing(self) -> None:
        # With no question waiting, "Did you mean Farmhouse Pizza?" is the
        # best thing there is to say.
        self.assertIn("Did you mean", add_named_dish())


class TheSpelledOutAnswerTests(unittest.TestCase):
    """The sentence shared with the re-ask path."""

    def rule(self, standing):
        from app.services.ordering_agent.loop import reask_standing_choice

        return reask_standing_choice(standing)

    def test_it_names_the_question_and_its_answers(self) -> None:
        said = self.rule({
            "question": "Which crust for Build Your Own Pizza?",
            "options": [{"name": "Thin crust"}, {"name": "Cheese burst"}],
        })
        self.assertIn("Which crust for Build Your Own Pizza?", said)
        self.assertIn("Thin crust", said)
        self.assertIn("Cheese burst", said)

    def test_it_says_it_did_not_follow(self) -> None:
        # Without it, the same question arriving twice reads as a system that
        # did not hear rather than one that did not understand.
        said = self.rule({"question": "Which crust?", "options": [{"name": "Thin crust"}]})
        self.assertIn("did not catch", said.lower())

    def test_a_question_that_already_lists_them_is_not_made_to_repeat(self) -> None:
        # The size and group questions lay their options out one per line now,
        # so appending "Just reply with one of these: ..." said everything
        # twice AND glued onto the last bullet:
        #
        #     - Thin crust Just reply with one of these: Classic hand tossed,
        #       Cheese burst, Stuffed garlic crust, Thin crust.
        said = self.rule({
            "question": "Which crust for Build Your Own Pizza?\n- Thin crust\n- Cheese burst",
            "options": [{"name": "Thin crust"}, {"name": "Cheese burst"}],
        })
        self.assertNotIn("Just reply with one of these", said)
        self.assertIn("Which crust for Build Your Own Pizza?", said)
        self.assertIn("- Thin crust", said)
        self.assertTrue(said.startswith("Sorry, I did not catch that."), said)

    def test_a_one_line_question_still_gets_its_answers(self) -> None:
        # The questions that do not lay their own options out still need them.
        said = self.rule({
            "question": "Which would you like?",
            "options": [{"name": "Per Plate"}, {"name": "1 Kg"}],
        })
        self.assertIn("Just reply with one of these: Per Plate, 1 Kg.", said)

    def test_a_choice_with_no_options_is_not_worth_repeating(self) -> None:
        self.assertIsNone(self.rule({"question": "Which crust?", "options": []}))
        self.assertIsNone(self.rule(None))
        self.assertIsNone(self.rule({}))

    def test_a_choice_with_no_question_still_offers_its_answers(self) -> None:
        said = self.rule({"options": [{"name": "Thin crust"}]})
        self.assertIn("Thin crust", said)


if __name__ == "__main__":
    unittest.main()
