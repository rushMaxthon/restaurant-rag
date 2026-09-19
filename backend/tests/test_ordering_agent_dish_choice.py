"""Naming a dish from the list we just read out.

From a real WhatsApp thread. The assistant listed eight appetizers and asked
"Which one would you like?". The customer answered:

    Money Bags

which is the name of one of the eight. They were answered:

    Hello, Money Bags! It seems you're interested in placing an order. To
    proceed, I need to check the details required for placing your order.

The dish went into `contact_name`. Nothing went into the cart — "That's all"
a minute later got "There is nothing in your order yet." — and saying "Money
Bags" a second time produced the same paragraph again, word for word.

**The cause is one missing write.** `_show_dishes` reads the menu out and
ends on a question, recording that question through `_hold`, which stores the
WORDS of the question and nothing else. It never records the dishes it just
listed. Everything downstream that handles "the customer picked one of the
things we offered" hangs off `pending_choice`:

* the reader's prompt gets `choice_question` + `choice_options` from it, and
  that is what teaches the model this message is a pick;
* `_answer_choice` maps the pick onto what was offered;
* the never-ask-twice guard refuses to repeat a question verbatim.

With `pending_choice` unset, all three were inert. So the message fell
through to the general reader, which is given a `details` schema containing
"the customer's name" and a capitalised two-word phrase — and did the only
thing left open to it. From there `loop.py` sets `collecting = True`
("giving your name is starting to check out"), which is why the reply was
about placing an order, and why the state was identical on the repeat.

`_suggest_more` ends on the same kind of question ("Tell me the name and I
will add it") and had the same gap behind it.
"""

from __future__ import annotations

import dataclasses
import json
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
from app.services.ordering_agent.tools import CartLineArgs
from tests.test_ordering_agent_loop import (
    SCOPE,
    OrderingAgentLoopTestCase,
    ScriptedClock,
    ScriptedGenerate,
)

# The eight from the transcript, in the order they were read out.
APPETIZERS = [
    {"name": "Appetizer Sampler", "price": "18.99", "is_veg": False},
    {"name": "Chicken Wings", "price": "11.99", "is_veg": False},
    {"name": "Corn Fritters", "price": "8.49", "is_veg": True},
    {"name": "Crispy Spring Rolls", "price": "7.99", "is_veg": True},
    {"name": "Grilled Pork Skewers", "price": "11.49", "is_veg": False},
    {"name": "Money Bags", "price": "9.49", "is_veg": False},
    {"name": "Prawn Tempura", "price": "12.49", "is_veg": False},
    {"name": "Roti Canai", "price": "6.49", "is_veg": True},
]

MENU_IDS = {dish["name"]: uuid.uuid4() for dish in APPETIZERS}


def a_reading(**over):
    """What `read_order_intent` returns, with everything switched off."""

    base = {
        "add": None, "details": {}, "checkout": False, "when": None,
        "chose": None, "confirms": None, "browse": None, "asks_hours": False,
        "category": None, "wants_to_add": False, "cancel_order": False,
        "pay_now": False,
    }
    base.update(over)
    return base


def a_dish_question(asks: int = 1) -> str:
    return json.dumps({
        "kind": "dish",
        "question": "Which one would you like?",
        "options": [{"name": dish["name"]} for dish in APPETIZERS],
        "asks": asks,
    })


class DishChoiceTestCase(OrderingAgentLoopTestCase):
    """A turn driven end to end with the menu, the reading and the cart
    scripted — no Ollama, no database, no Redis."""

    def setUp(self) -> None:
        super().setUp()
        self.draft = order_draft.OrderDraft()
        self.added: list[dict] = []
        self.register("add_to_cart", CartLineArgs, self._add_handler)

    def _add_handler(self, db, scope, args):
        line = {"menu_item_id": str(args.menu_item_id), "quantity": args.quantity}
        self.added.append(line)
        return {"outcome": "applied", "action": {"type": "add", **line}}

    def _matching(self, db, scope, phrase, is_veg=None):
        wanted = phrase.strip().casefold()
        return [
            (str(MENU_IDS[d["name"]]), d["name"])
            for d in APPETIZERS
            if d["name"].casefold() == wanted
        ]

    def _resolve(self, db, scope, tool, args):
        return dict(args), {"menu_item_id": args["menu_item_id"]}

    def turn(self, message, *, reading, shown=None, cart=(), replies=()):
        """`replies` is only for a turn that reaches the planner — one that
        settled nothing has a model round left to spend."""

        scope = dataclasses.replace(SCOPE, session_id=uuid.uuid4())
        self.seen_kwargs: dict = {}

        def read(msg, **kwargs):
            self.seen_kwargs.update(kwargs)
            return reading

        with (
            mock.patch.object(order_draft, "load", lambda _sid: self.draft),
            mock.patch.object(
                order_draft, "save",
                lambda _sid, draft: setattr(self, "draft", draft),
            ),
            mock.patch.object(loop, "read_order_intent", read),
            mock.patch.object(tools_module, "dishes_to_show", lambda *a, **k: shown or []),
            mock.patch.object(tools_module, "dishes_to_suggest", lambda *a, **k: shown or []),
            mock.patch.object(tools_module, "dishes_matching_words", self._matching),
            mock.patch.object(guards, "resolve_dish_name", self._resolve),
        ):
            return loop.run_turn(
                # A stub that can answer the one read `run_turn` makes of
                # it before anything else: what this restaurant charges in.
                db=SimpleNamespace(scalar=lambda *a, **k: "USD"),
                scope=scope,
                message=message,
                cart=list(cart),
                generate=ScriptedGenerate(*replies),
                clock=ScriptedClock(0.0),
                max_rounds=5,
                budget_seconds=1000.0,
            )


class TheListWeReadOutIsRememberedTests(DishChoiceTestCase):
    """The missing write, stated directly."""

    def test_showing_dishes_records_what_was_shown(self) -> None:
        outcome = self.turn(
            "show me the appetizers",
            reading=a_reading(browse="appetizers"),
            shown=APPETIZERS,
        )

        self.assertIn("Which one would you like?", outcome.answer or "")
        self.assertIsNotNone(
            self.draft.pending_choice,
            "the dishes just read out were not written down, so the next "
            "message has nothing to be read against",
        )
        asked = json.loads(self.draft.pending_choice)
        self.assertEqual(asked["kind"], "dish")
        self.assertEqual(
            [o["name"] for o in asked["options"]],
            [d["name"] for d in APPETIZERS],
            "every dish offered is an answer the customer may give",
        )

    def test_suggesting_more_records_them_too(self) -> None:
        # "Tell me the name and I will add it" is the same question in
        # different words, and had the same gap behind it.
        outcome = self.turn(
            "I want to add more",
            reading=a_reading(wants_to_add=True),
            shown=APPETIZERS[:3],
        )

        self.assertIn("Tell me the name", outcome.answer or "")
        asked = json.loads(self.draft.pending_choice or "{}")
        self.assertEqual(asked.get("kind"), "dish")
        self.assertEqual(len(asked["options"]), 3)

    def test_one_dish_is_not_a_list_to_pick_from(self) -> None:
        # Naming the only match asks "Shall I add one?", which is a yes/no
        # and already carried by `_hold`. Recording a choice of one would
        # put the customer in front of a list with a single entry.
        outcome = self.turn(
            "appetizer sampler",
            reading=a_reading(browse="appetizer sampler"),
            shown=APPETIZERS[:1],
        )

        self.assertIn("Shall I add one?", outcome.answer or "")
        self.assertIsNone(self.draft.pending_choice)


class OnlyACompleteListSaysItIsOneTests(DishChoiceTestCase):
    """"Here is what we have" is a claim about the menu.

    Eight rows were read out under it to a customer whose restaurant has 136
    dishes. The list is capped so a chat message stays readable, which is
    right; saying the cap is the menu is not.
    """

    def test_a_truncated_list_says_a_few(self) -> None:
        # Nine come back for a cap of eight, which is how the turn learns
        # there is a ninth without reading the whole menu.
        outcome = self.turn(
            "show me everything",
            reading=a_reading(browse="everything"),
            shown=APPETIZERS + [{"name": "Satay Skewers", "price": "10.99", "is_veg": False}],
        )

        self.assertIn("Here are a few", outcome.answer or "")
        self.assertNotIn("Here is what we have", outcome.answer or "")
        self.assertNotIn("Satay Skewers", outcome.answer or "", "the ninth is not read out")

    def test_a_complete_list_still_says_so(self) -> None:
        outcome = self.turn(
            "show me the appetizers",
            reading=a_reading(browse="appetizers"),
            shown=APPETIZERS,
        )

        self.assertIn("Here is what we have", outcome.answer or "")

    def test_only_what_was_read_out_can_be_picked(self) -> None:
        # The ninth dish was never shown, so it is not one of the answers
        # the customer may give.
        self.turn(
            "show me everything",
            reading=a_reading(browse="everything"),
            shown=APPETIZERS + [{"name": "Satay Skewers", "price": "10.99", "is_veg": False}],
        )
        asked = json.loads(self.draft.pending_choice)
        self.assertEqual(len(asked["options"]), 8)
        self.assertNotIn("Satay Skewers", [o["name"] for o in asked["options"]])


class TheReaderIsToldWhatWasOfferedTests(DishChoiceTestCase):
    """The root cause: what the model was given on the "Money Bags" turn.

    `read_order_intent` learns that a pick is possible only from
    `choice_question`/`choice_options`. Without them its prompt describes a
    `details` object containing "the customer's name" and nothing that would
    make a capitalised two-word phrase mean anything else.
    """

    def test_the_offered_dishes_reach_the_reading(self) -> None:
        self.draft = order_draft.OrderDraft(pending_choice=a_dish_question())
        self.turn("Money Bags", reading=a_reading(chose=["Money Bags"]))

        self.assertEqual(self.seen_kwargs.get("choice_question"), "Which one would you like?")
        self.assertIn("Money Bags", self.seen_kwargs.get("choice_options") or [])


class APickIsNotANameTests(DishChoiceTestCase):
    """The symptom the customer saw."""

    def setUp(self) -> None:
        super().setUp()
        self.draft = order_draft.OrderDraft(pending_choice=a_dish_question())

    def test_the_dish_is_added_and_the_name_is_not_kept(self) -> None:
        outcome = self.turn("Money Bags", reading=a_reading(chose=["Money Bags"]))

        self.assertEqual(
            [line["menu_item_id"] for line in self.added],
            [str(MENU_IDS["Money Bags"])],
            "the dish the customer picked never reached the cart",
        )
        self.assertIsNone(
            self.draft.contact_name,
            "a dish on the menu was filed as the customer's name",
        )
        self.assertFalse(self.draft.collecting, "naming a dish started checking out")
        self.assertTrue(outcome.actions, "nothing reached the cart")
        self.assertIsNone(self.draft.pending_choice, "the question was answered")

    def test_a_name_nobody_offered_is_refused(self) -> None:
        # The rule `_answer_choice` already holds for sizes: an answer to a
        # question nobody asked must not put something in somebody's cart.
        # Nothing was settled, so the turn spends its planner round; the
        # reply itself is not what this test is about.
        self.turn(
            "Lobster Thermidor",
            reading=a_reading(chose=["Lobster Thermidor"]),
            replies=(json.dumps({"answer": "I could not find that one."}),),
        )
        self.assertEqual(self.added, [])

    def test_several_at_once(self) -> None:
        # A group orders for a group, and the reading returns a list.
        self.turn(
            "corn fritters and roti canai",
            reading=a_reading(chose=["Corn Fritters", "Roti Canai"]),
        )
        self.assertEqual(
            sorted(line["menu_item_id"] for line in self.added),
            sorted([str(MENU_IDS["Corn Fritters"]), str(MENU_IDS["Roti Canai"])]),
        )

    def test_the_same_dish_named_twice_is_added_once(self) -> None:
        """One message, one order for that dish.

        Live, on the real model: picking "Money Bags" from a list came back
        as BOTH `chose: ["Money Bags"]` and `add: [("Money Bags", 1)]`. Each
        path added it, so the customer got two and was told "Added 1 x Money
        Bags to your order." twice in one breath.
        """

        self.turn(
            "Money Bags",
            reading=a_reading(chose=["Money Bags"], add=[("Money Bags", 1)]),
        )
        self.assertEqual(len(self.added), 1, "added once, not once per path")

    def test_a_pick_and_a_different_dish_both_land(self) -> None:
        # The dedupe is by dish, not a cap of one: "the first one and a roti"
        # is two orders.
        self.turn(
            "Money Bags and a Roti Canai",
            reading=a_reading(chose=["Money Bags"], add=[("Roti Canai", 1)]),
        )
        self.assertEqual(
            sorted(line["menu_item_id"] for line in self.added),
            sorted([str(MENU_IDS["Money Bags"]), str(MENU_IDS["Roti Canai"])]),
        )

    def test_a_loose_answer_still_lands(self) -> None:
        # "money bags" lower case, as anybody types it.
        self.turn("money bags", reading=a_reading(chose=["money bags"]))
        self.assertEqual(len(self.added), 1)


class TheSameSentenceIsNeverSentTwiceTests(DishChoiceTestCase):
    """The third symptom, which the same missing write caused.

    The never-ask-twice guard is keyed on `pending_choice`. With it unset the
    guard could not fire, so "Money Bags" produced the identical paragraph on
    both turns, six minutes apart.
    """

    def test_an_unreadable_answer_spells_the_options_out_instead(self) -> None:
        self.draft = order_draft.OrderDraft(pending_choice=a_dish_question())
        outcome = self.turn("qqq", reading=a_reading())

        self.assertIn("Money Bags", outcome.answer or "", "the options are spelled out")
        self.assertEqual(json.loads(self.draft.pending_choice)["asks"], 2, "counted")

    def test_and_there_is_never_a_third(self) -> None:
        self.draft = order_draft.OrderDraft(pending_choice=a_dish_question(asks=2))
        outcome = self.turn("qqq", reading=a_reading())

        self.assertIn("start that one again", outcome.answer or "")
        self.assertIsNone(self.draft.pending_choice, "the question is let go of")


if __name__ == "__main__":
    unittest.main()
