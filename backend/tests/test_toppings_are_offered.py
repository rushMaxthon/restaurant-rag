"""An optional group is offered before the dish lands, and never holds it.

Bangkok Bowl's Build Your Own Pizza has a Toppings group — MULTI, max 7 — that
no customer has ever been shown. That is correct one layer down:
`_applicable_groups_and_unmet` does not count an optional group as unmet,
because "an optional group's default IS the empty selection", so it never
blocks. `add_to_cart` therefore applies the moment the required things are
settled, and the pizza is in the cart before anything could ask.

The first attempt at this offered the group and then waited for an answer, and
it lost pizzas. `no`, `none`, `skip` and `no thanks` all left a dish that had
taken four questions to build sitting unadded. Measured against the real
reading, the cause was that there is no single shape for "no":

    no                       confirms=False
    no thanks                confirms=False
    none                     confirms=None    (nothing set at all)
    skip                     confirms=None
    Mozzarella               chose=['Mozzarella']
    Mozzarella and mushroom  add=[('Mozzarella and mushroom', 1)]

— and the same topping came back as `chose` on one run and `add` on the next,
because the reading is a model. Branching on which key was set works in a test
and fails in front of a customer.

So the message is matched against the offered options HERE, deterministically,
and anything that names none of them means "no". The dish is added either way.
An optional group is an offer, not a gate: the worst it may cost a customer is
a pizza without toppings, never the pizza.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.loop import (
    next_optional_group,
    options_named_in,
    storable_group,
)

TOPPINGS = {
    "group_id": "g-top",
    "title": "Toppings",
    "is_required": False,
    "min_selection": 0,
    "max_selection": 7,
    "options": [
        {"option_id": "t1", "name": "Mozzarella", "extra_price": "1.75"},
        {"option_id": "t2", "name": "Mushroom", "extra_price": "1.50"},
        {"option_id": "t3", "name": "Thai basil", "extra_price": "0.75"},
        {"option_id": "t4", "name": "Bird's eye chilli", "extra_price": "0.50"},
    ],
}

OFFERED = {"options": [{"name": o["name"], "option_id": o["option_id"]} for o in TOPPINGS["options"]]}


def asked(**over) -> dict:
    """The question just answered, as `_remember_choice` writes it down."""

    stored = {
        "name": "Build Your Own Pizza",
        "needs_size": False,
        # Each required group's option ids, so "is everything required
        # settled?" is answerable without going back to the database.
        "required": [["c1", "c2"]],
        "later": [TOPPINGS],
    }
    stored.update(over)
    return stored


def args(**over) -> dict:
    built = {"menu_item_id": "m1", "quantity": 1, "selected_options": [{"option_id": "c1"}]}
    built.update(over)
    return built


class OnceEverythingRequiredIsSettledTests(unittest.TestCase):
    """The moment the dish would otherwise land."""

    def test_the_optional_group_is_offered(self) -> None:
        self.assertEqual(next_optional_group(asked(), args()), TOPPINGS)

    def test_nothing_is_offered_when_there_is_nothing_left(self) -> None:
        self.assertIsNone(next_optional_group(asked(later=[]), args()))
        self.assertIsNone(next_optional_group(asked(later=None), args()))


class NotBeforeTheRequiredOnesTests(unittest.TestCase):
    """Asking about toppings before the sauce is interrupting yourself."""

    def test_a_required_group_still_unanswered_waits(self) -> None:
        stored = asked(required=[["c1", "c2"], ["s1", "s2"]])
        self.assertIsNone(next_optional_group(stored, args()))

    def test_a_size_still_needed_waits(self) -> None:
        self.assertIsNone(next_optional_group(asked(needs_size=True), args()))

    def test_a_size_already_chosen_does_not(self) -> None:
        self.assertEqual(
            next_optional_group(asked(needs_size=True), args(menu_item_size_id="sz1")),
            TOPPINGS,
        )

    def test_no_required_groups_at_all_is_settled(self) -> None:
        self.assertEqual(next_optional_group(asked(required=[]), args()), TOPPINGS)


class WhatIsNotWorthOfferingTests(unittest.TestCase):
    """A question with no answers in it is not a question."""

    def test_a_group_with_no_options_is_skipped(self) -> None:
        self.assertIsNone(next_optional_group(asked(later=[{**TOPPINGS, "options": []}]), args()))

    def test_the_first_with_options_is_taken(self) -> None:
        empty = {**TOPPINGS, "group_id": "g-empty", "options": []}
        self.assertEqual(next_optional_group(asked(later=[empty, TOPPINGS]), args()), TOPPINGS)

    def test_nothing_readable_offers_nothing(self) -> None:
        self.assertIsNone(next_optional_group(None, args()))
        self.assertIsNone(next_optional_group(asked(), None))
        self.assertIsNone(next_optional_group({}, {}))


class ReadingTheAnswerOurselvesTests(unittest.TestCase):
    """Which options a message names, decided without asking the model."""

    def test_one_topping(self) -> None:
        self.assertEqual(options_named_in("Mozzarella", OFFERED), ["Mozzarella"])

    def test_several_in_one_message(self) -> None:
        # The case the model returned as `add=[('Mozzarella and mushroom', 1)]`
        # — one dish named "Mozzarella and mushroom", which does not exist.
        self.assertEqual(
            options_named_in("Mozzarella and mushroom", OFFERED), ["Mozzarella", "Mushroom"]
        )

    def test_case_and_punctuation_do_not_matter(self) -> None:
        self.assertEqual(
            options_named_in("mozzarella, MUSHROOM please!", OFFERED),
            ["Mozzarella", "Mushroom"],
        )

    def test_an_option_whose_name_has_punctuation(self) -> None:
        self.assertEqual(
            options_named_in("birds eye chilli", OFFERED), ["Bird's eye chilli"]
        )

    def test_a_multi_word_option(self) -> None:
        self.assertEqual(options_named_in("thai basil", OFFERED), ["Thai basil"])

    def test_the_order_offered_is_the_order_returned(self) -> None:
        # So the read-back reads the way the question did.
        self.assertEqual(
            options_named_in("mushroom and mozzarella", OFFERED), ["Mozzarella", "Mushroom"]
        )

    def test_each_option_once_however_often_it_is_said(self) -> None:
        self.assertEqual(
            options_named_in("mozzarella mozzarella", OFFERED), ["Mozzarella"]
        )


class EveryWayOfSayingNoTests(unittest.TestCase):
    """All of these named no option, and all of them must mean the same."""

    def test_the_refusals_name_nothing(self) -> None:
        for message in ("no", "none", "skip", "no thanks", "nope", "that's all", "nothing"):
            with self.subTest(message=message):
                self.assertEqual(options_named_in(message, OFFERED), [])

    def test_an_unrelated_message_names_nothing(self) -> None:
        for message in ("what time do you close", "actually make it large", ""):
            with self.subTest(message=message):
                self.assertEqual(options_named_in(message, OFFERED), [])

    def test_a_word_inside_another_word_is_not_a_pick(self) -> None:
        # "Tofu" must not be found inside a longer word, or a refusal could
        # accidentally buy a topping.
        offered = {"options": [{"name": "Tofu", "option_id": "t"}]}
        self.assertEqual(options_named_in("tofurkey sandwich", offered), [])

    def test_nothing_offered_matches_nothing(self) -> None:
        self.assertEqual(options_named_in("Mozzarella", {"options": []}), [])
        self.assertEqual(options_named_in("Mozzarella", None), [])


class TheStoredFormSurvivesJsonTests(unittest.TestCase):
    """The pending choice is stored as JSON, and the rows are not JSON.

    Caught by driving a real order, not by the suite: every fixture here uses
    strings for ids, and the live rows carry UUIDs and Decimals. Writing a
    group through unchanged raised `TypeError: Object of type UUID is not JSON
    serializable` on every turn that asked for a size.
    """

    def live_shaped_group(self) -> dict:
        import uuid
        from decimal import Decimal

        return {
            "group_id": uuid.uuid4(),
            "title": "Toppings",
            "is_required": False,
            "min_selection": 0,
            "max_selection": 7,
            "options": [
                {"option_id": uuid.uuid4(), "name": "Mozzarella", "extra_price": Decimal("1.75")},
            ],
        }

    def test_a_live_group_can_be_written_down(self) -> None:
        import json

        json.dumps(storable_group(self.live_shaped_group()))  # must not raise

    def test_the_fields_the_rest_of_this_file_relies_on_survive(self) -> None:
        stored = storable_group(self.live_shaped_group())
        self.assertEqual(stored["title"], "Toppings")
        self.assertEqual(stored["max_selection"], 7)
        self.assertFalse(stored["is_required"])
        self.assertEqual(stored["options"][0]["name"], "Mozzarella")
        self.assertEqual(stored["options"][0]["extra_price"], "1.75")

    def test_a_stored_group_is_still_offerable(self) -> None:
        stored = storable_group(self.live_shaped_group())
        self.assertEqual(next_optional_group(asked(later=[stored]), args()), stored)

    def test_nothing_readable_stores_nothing(self) -> None:
        self.assertEqual(storable_group(None), {})


if __name__ == "__main__":
    unittest.main()
