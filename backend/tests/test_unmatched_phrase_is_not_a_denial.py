"""What the menu reader says when it could not match what was asked for.

From the live concierge, Bangkok Bowl, pressing the "a light lunch under $20"
starter:

    We do not have light lunch under $20 here. This is what we do have:
    - Appetizer Sampler - $18.99
    - Chicken Wings - $11.99
    - Corn Fritters - $8.49
    ...

Eight dishes, every one of them under twenty dollars, under a sentence saying
there are none. The reply contradicts itself between its first line and its
second.

**The cause is a category error, not a bad string.** `dishes_to_show` reports
`found_by="fallback"` to mean *the search matched nothing and these rows are
simply the branch's menu* — a fact about the SEARCH. The opening turned that
into a claim about the MENU: "we do not have X here".

The two agree whenever the phrase was a dish name the kitchen genuinely does
not sell, which is the case the wording was written for ("we don't have
sushi"). They come apart the moment somebody describes what they want instead
of naming it, because a description can be perfectly satisfiable by rows the
name search could never match.

So the opening reports the failed match rather than asserting absence. That
is true in both cases, and for "sushi" it reads almost exactly as it did.

Nothing here is a word list: no phrase is classified, and the sentence is
chosen from a state the retrieval already reports.
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent import guards, loop, order_draft
from app.services.ordering_agent import tools as tools_module
from tests.test_ordering_agent_dish_choice import APPETIZERS, a_reading
from tests.test_ordering_agent_loop import (
    SCOPE,
    OrderingAgentLoopTestCase,
    ScriptedClock,
    ScriptedGenerate,
)


class TheOpeningSentenceTests(OrderingAgentLoopTestCase):
    """The menu read out, with the retrieval reporting how it found the rows."""

    def setUp(self) -> None:
        super().setUp()
        self.draft = order_draft.OrderDraft()

    def read_out(self, message: str, *, found_by: str, browse: str):
        """One turn whose `dishes_to_show` reports `found_by`.

        The real function fills the caller's `report` dict; the stub has to
        do the same or the loop reads the default and the branch under test
        never runs.
        """

        def dishes_to_show(db, scope, phrase, *, report=None, **kwargs):
            if report is not None:
                report["found_by"] = found_by
            return list(APPETIZERS)

        scope = dataclasses.replace(SCOPE, session_id=uuid.uuid4())
        with (
            mock.patch.object(order_draft, "load", lambda _sid: self.draft),
            mock.patch.object(order_draft, "save", lambda _sid, draft: None),
            mock.patch.object(loop, "read_order_intent",
                              lambda msg, **kw: a_reading(browse=browse)),
            mock.patch.object(tools_module, "dishes_to_show", dishes_to_show),
            mock.patch.object(tools_module, "dishes_to_suggest",
                              lambda *a, **k: list(APPETIZERS)),
            mock.patch.object(guards, "resolve_dish_name",
                              lambda db, scope, tool, args: (dict(args), {})),
        ):
            return loop.run_turn(
                db=SimpleNamespace(scalar=lambda *a, **k: "USD"),
                scope=scope,
                message=message,
                cart=[],
                generate=ScriptedGenerate(),
                clock=ScriptedClock(0.0),
                max_rounds=5,
                budget_seconds=1000.0,
            ).answer or ""

    def test_it_does_not_deny_having_what_it_then_lists(self) -> None:
        answer = self.read_out(
            "a light lunch under $20",
            found_by="fallback",
            browse="light lunch under $20",
        )
        # The dishes are there, so the sentence above them must not say they
        # are not. This is the exact contradiction from the transcript.
        self.assertIn("Corn Fritters", answer)
        self.assertNotIn("We do not have", answer)

    def test_it_still_acknowledges_what_was_asked_for(self) -> None:
        # The opposite failure, and the reason the denial was written in the
        # first place: the branch's whole menu under "Here is what we have",
        # to somebody who asked for something specific, reads as having been
        # ignored.
        answer = self.read_out(
            "do you have sushi", found_by="fallback", browse="sushi",
        )
        self.assertIn("sushi", answer)

    def test_it_reports_the_search_rather_than_the_menu(self) -> None:
        # `fallback` is a fact about what the search did, so that is what the
        # sentence is allowed to be about.
        answer = self.read_out(
            "do you have sushi", found_by="fallback", browse="sushi",
        )
        self.assertIn("could not find", answer.lower())

    def test_a_near_miss_still_says_it_is_a_near_miss(self) -> None:
        # The neighbouring branch, untouched: "close" means the words found
        # something under a different name, which is a different sentence.
        answer = self.read_out(
            "spring roll", found_by="close", browse="spring roll",
        )
        self.assertIn("closest", answer.lower())

    def test_a_plain_hit_claims_nothing_about_a_miss(self) -> None:
        answer = self.read_out(
            "show me the appetizers", found_by="named", browse="appetizers",
        )
        self.assertNotIn("could not find", answer.lower())
        self.assertNotIn("We do not have", answer)

    def test_the_list_and_the_question_survive_either_way(self) -> None:
        for found_by in ("fallback", "named", "close"):
            with self.subTest(found_by=found_by):
                answer = self.read_out(
                    "something nice", found_by=found_by, browse="something nice",
                )
                self.assertIn("Money Bags", answer, "the rows are still read out")
                self.assertIn("Which one would you like?", answer)


if __name__ == "__main__":
    unittest.main()
