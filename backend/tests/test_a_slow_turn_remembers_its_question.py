"""The assistant remembers the question it just asked, even on a slow turn.

From a live WhatsApp thread, 2026-09-21:

    assistant  Added 1 x Red Curry Tofu to your order. Anything else?
    customer   No
    assistant  We don't have that on the menu — but the Tom Yum Noodle Bowl
               is a crowd-pleaser... [six noodle dishes]

The plainest possible answer to its own question, read as the name of a dish.

The worker log named the cause. The turn that asked had taken 54 seconds and
blown its time budget, so the sentence came from the budget-exceeded path
rather than from `_settled`:

    Ordering agent asked the needs_choice question itself after budget_exceeded
    Ordering agent turn fallback_reason=None records=1 actions=1 elapsed=54.14s

Both paths compose that sentence from the same rows. Only `_settled` called
`_hold`, so nothing recorded that a question had been asked. The next turn
found no standing question, settled nothing —

    Ordering agent turn fallback_reason=None records=0 actions=0

— and the reply fell through to retrieval, which searched the menu for "No"
and answered with what "no" is nearest to in vector space.

The handling of "no" was never broken: `_answer_standing`'s `more` branch
sets `wanted["checkout"] = True`, and a clean replay of the same three
messages answers "Thanks. I still need whether you want delivery or pickup."
What was broken was that the question went unrecorded when the turn was slow
— and slow is the normal case on a machine running the model locally.
"""

from __future__ import annotations

import inspect
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent import loop as loop_module

SOURCE = inspect.getsource(loop_module.run_turn)


def body_of(name: str) -> str:
    """One nested function's source, from `run_turn`'s own text.

    These live inside `run_turn` and close over its state, so there is no
    way to import them. Reading the source is how the two paths get compared
    at all — and a comparison is the point, because the bug was that they
    had drifted apart.
    """

    match = re.search(rf"\n    def {name}\(.*?(?=\n    def |\Z)", SOURCE, re.S)
    assert match, f"{name} not found in run_turn"
    return match.group(0)


class BothPathsRecordWhatTheyAskedTests(unittest.TestCase):
    """The two places that end a turn on a question."""

    def test_the_rule_exists_in_one_place(self) -> None:
        self.assertIn("def _hold_the_question(", SOURCE)

    def test_the_settled_path_uses_it(self) -> None:
        self.assertIn("_hold_the_question(", body_of("_settled"))

    def slow_path(self) -> str:
        """The budget-exceeded block, from its log line to what it returns.

        Bounded at the `return`, not by a character count: a loose window ran
        past the end of the block and matched the DEFINITION of
        `_hold_the_question` further down the file, so the first version of
        this test passed with the call removed.
        """

        start = SOURCE.index("asked the needs_choice question itself")
        return SOURCE[start : SOURCE.index("return TurnOutcome(", start)]

    def test_the_slow_path_uses_it_too(self) -> None:
        # This is the one that was missing, and the whole bug.
        self.assertIn("_hold_the_question(", self.slow_path())

    def test_neither_path_holds_its_own_way_any_more(self) -> None:
        # Two copies of one rule is how they drifted the first time. `_hold`
        # is still called for other questions, but not for these two.
        for path in ("_settled",):
            with self.subTest(path=path):
                text = body_of(path)
                self.assertNotIn('_hold("Anything else?"', text)
                self.assertNotIn('_hold("Ready to check out?"', text)

    def test_the_questions_are_still_the_ones_held(self) -> None:
        rule = body_of("_hold_the_question")
        self.assertIn('_hold("Anything else?", yes="more")', rule)
        self.assertIn('_hold("Ready to check out?", yes="checkout")', rule)

    def test_it_decides_by_identity_not_by_matching_the_words(self) -> None:
        # The composers build these strings from live rows. Comparing against
        # a literal would go quietly wrong the first time one was reworded,
        # and quietly is how this bug behaved for as long as it existed.
        rule = body_of("_hold_the_question")
        self.assertIn("answer is applied", rule)
        self.assertIn("answer is summary", rule)

    def test_the_slow_path_computes_each_sentence_once(self) -> None:
        # Identity only means anything if the string handed to the rule is
        # the same object that was put in the reply. `describe_applied` twice
        # returns two equal strings that are not the same object.
        block = SOURCE[SOURCE.index("Computed once and reused") : SOURCE.index("asked the needs_choice")]
        # Counted on the call, not on its arguments: it grew a `goes_with`
        # when an add started offering something alongside it, and the point
        # here is that it is called ONCE — a second call returns an equal
        # string that is not the same object, and the identity check below
        # would stop recognising it.
        self.assertEqual(block.count("describe_applied("), 1)


class AnsweringNoIsStillHandledTests(unittest.TestCase):
    """The half that was never broken, asserted so a fix here cannot break it."""

    def test_declining_more_moves_on_to_the_order(self) -> None:
        standing = body_of("_answer_standing")
        more = standing[standing.index('if kind == "more":') :][:420]
        self.assertIn('wanted["checkout"] = True', more)


if __name__ == "__main__":
    unittest.main()
