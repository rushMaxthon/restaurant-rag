"""Asking for the menu gets the menu, not a pitch for one dish.

From a live WhatsApp thread with Bangkok Bowl:

    > Menu
      Looking for something delicious? Let's start with the Tom Yum Prawn
      Pizza — a fiery mix of tom yum cream, prawns, mushrooms, and lemongrass
      on a crispy crust. It's a crowd-pleaser, and the price is right at
      $19.49. Want something lighter, or are you ready to order? 🍕🔥

Somebody asked to see the menu and was sold a prawn pizza.

`quick_read("Menu")` already returns "menu" — the agent knows exactly what was
asked. It then handed the turn to the reply pipeline on a stated belief:

    # The reply pipeline answers about the menu, and better; this turn
    # simply has nothing to add and should not spend a model round
    # discovering that.

That belief is what the thread above disproves. The pipeline has no handler for
this at all: "Menu" reached retrieval as a search query, matched no keyword,
vector-matched eight arbitrary dishes, and the model wrote prose over them. Nor
is it a phrasing problem — "the menu", "show me the menu", "menu please" and
"what is on the menu" all miss `_is_menu_question_message`, which is about a
specific item's price rather than about the menu.

The branch's sections are the answer, for the same reason a restaurant hands
over a menu with sections rather than reciting 136 dishes. And since naming a
section back now reads out that whole section, the answer leads somewhere.
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
from app.services.ordering_agent.planner import quick_read

SOURCE = inspect.getsource(loop_module.run_turn)


class TheRequestIsRecognisedTests(unittest.TestCase):
    """Unchanged, and pinned: the reading was never the broken part."""

    def test_the_ways_people_ask(self) -> None:
        for message in ("Menu", "menu", "the menu", "show me the menu", "menu please"):
            with self.subTest(message=message):
                self.assertEqual(quick_read(message), "menu")


class TheAgentAnswersItTests(unittest.TestCase):
    """It used to decline the turn and let the pipeline invent something."""

    def menu_branch(self) -> str:
        start = SOURCE.index('if plain == "menu":')
        return SOURCE[start : SOURCE.index("now_local", start)]

    def test_it_answers_rather_than_standing_aside(self) -> None:
        # The whole bug: `answer=None` handed "Menu" to a pipeline with no
        # handler for it, which sold a prawn pizza.
        branch = self.menu_branch()
        self.assertIn("offer_of_sections", branch)

    def test_it_reads_the_sections_off_this_branch(self) -> None:
        # Not a fixed list, and not the model's idea of what a menu contains.
        self.assertIn("branch_sections", self.menu_branch())

    def test_the_question_it_ends_on_is_held(self) -> None:
        # Otherwise the next message answers a question nothing recorded —
        # which is the failure that produced the thread this file is about.
        self.assertIn("_hold(", self.menu_branch())

    def test_the_model_is_given_the_short_question_not_the_whole_list(self) -> None:
        # `_hold` records a SHORT question on purpose: a long read-back handed
        # to the model as "the question" got mined for its contents. A list of
        # every section is exactly that shape, so `asks` carries the question
        # and the customer gets the list.
        self.assertIn("asks=", self.menu_branch())

    def test_a_branch_with_no_sections_still_defers(self) -> None:
        # Nothing to show is the one case the old behaviour was right for.
        self.assertIn("answer=None", self.menu_branch())


if __name__ == "__main__":
    unittest.main()
