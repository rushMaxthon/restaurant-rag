"""What a customer's sentence does to their cart, and whether it is safe to
apply without asking.

Deterministic on purpose — see "The tier-2 seam" in the design spec. Every
rule here is pure over plain inputs, the same discipline `suggestions.py`
uses for the selling rules, and for the same reason: a rule that needs a
database and a live model to exercise is a rule nobody re-checks after
changing it, and this one decides whether an item silently lands in
someone's cart.
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
from app.services.cart_actions import (
    CartAction,
    ExistingCartLine,
    ResolvedDish,
    classify_cart_verb,
    extract_requested_quantity,
    resolve_cart_actions,
)


class QuantityExtractionTests(unittest.TestCase):
    def test_a_bare_digit_is_read_as_the_quantity(self) -> None:
        self.assertEqual(extract_requested_quantity("add 3 chicken satay"), 3)

    def test_number_words_are_understood(self) -> None:
        self.assertEqual(extract_requested_quantity("two pad thai please"), 2)
        self.assertEqual(extract_requested_quantity("a couple of spring rolls"), 2)
        self.assertEqual(extract_requested_quantity("just one"), 1)

    def test_a_multiplier_form_is_understood(self) -> None:
        self.assertEqual(extract_requested_quantity("2x pad thai"), 2)
        self.assertEqual(extract_requested_quantity("pad thai x3"), 3)

    def test_no_quantity_mentioned_yields_none(self) -> None:
        """None, not a default of 1 — the caller decides what silence means."""

        self.assertIsNone(extract_requested_quantity("add the pad thai"))

    def test_a_dollar_amount_is_not_read_as_a_quantity(self) -> None:
        """"under $15" must not extract 15 satay."""

        self.assertIsNone(extract_requested_quantity("something under $15"))

    def test_a_larger_number_word_wins_over_a_shorter_substring(self) -> None:
        """"a couple of" must not stop at "a" and return 1."""

        self.assertEqual(extract_requested_quantity("a couple of pad thai"), 2)

    def test_a_spelled_out_currency_amount_is_not_read_as_a_quantity(self) -> None:
        self.assertIsNone(extract_requested_quantity("keep it under two dollars"))
        self.assertIsNone(extract_requested_quantity("just two dollars"))

    def test_a_currency_mention_elsewhere_in_the_message_does_not_swallow_a_real_quantity(self) -> None:
        """The currency guard must be proximity-based, not message-global —
        a customer stating both a quantity and a budget in one sentence is
        plausible, and the quantity must still be read."""

        self.assertEqual(extract_requested_quantity("add 2 chicken satay under $15 budget"), 2)


class CartVerbClassificationTests(unittest.TestCase):
    """Independent of `ExtractedIntent` on purpose — see the plan's refinement
    note 3. This never touches the menu-discovery intent taxonomy.

    Fix round 1 (review, 2026-09-15): the original patterns were bare-keyword
    matches with no notion of "is this actually about the cart", so they fired
    on plain conversation — "cancel my order" read as add, "do you do take
    out?" read as remove, a bare "never mind" read as clear. The tests below
    pin down the false positives the review found, alongside the phrasings
    that must still work.
    """

    def test_add_phrasings_are_recognised(self) -> None:
        for message in ("add pad thai", "order two spring rolls", "i'll have the curry", "give me a coke"):
            self.assertEqual(classify_cart_verb(message), "add", msg=message)

    def test_remove_phrasings_are_recognised(self) -> None:
        for message in ("remove the pad thai", "delete the curry", "take the rice out"):
            self.assertEqual(classify_cart_verb(message), "remove", msg=message)

    def test_set_quantity_phrasings_are_recognised(self) -> None:
        self.assertEqual(classify_cart_verb("make it 3"), "set_quantity")
        self.assertEqual(classify_cart_verb("change the quantity to 2"), "set_quantity")

    def test_clear_phrasings_are_recognised(self) -> None:
        self.assertEqual(classify_cart_verb("clear my cart"), "clear")
        self.assertEqual(classify_cart_verb("start over with my order"), "clear")

    def test_an_ordinary_question_is_not_a_cart_verb(self) -> None:
        for message in ("what's spicy tonight?", "how much is the pad thai?", "recommend something vegetarian"):
            self.assertIsNone(classify_cart_verb(message), msg=message)

    def test_start_over_without_cart_context_still_reads_a_real_add_cue(self) -> None:
        """Replaces a prior version of this test whose docstring ("start over
        and add pad thai") and assertion (a completely different string, with
        no add cue at all) disagreed. "start over" carries no cart-mutation
        signal without a nearby cart/order/basket word — see
        test_bare_destructive_cues_need_cart_context below — so it doesn't
        shadow the genuine "add" cue elsewhere in the same sentence."""

        self.assertEqual(classify_cart_verb("start over and add pad thai"), "add")

    def test_bare_destructive_cues_need_cart_context(self) -> None:
        """A bare "never mind" or "start over" with no cart/order/basket word
        anywhere nearby is ordinary conversation, not a cart action — clearing
        someone's cart because they said "actually, never mind" about
        something unrelated is the worst failure mode this module has."""

        for message in ("actually, never mind", "can we start over"):
            self.assertIsNone(classify_cart_verb(message), msg=message)

    def test_order_as_a_noun_is_not_an_add_cue(self) -> None:
        """"order" meaning "my existing order" (status, cancellation) is far
        more common in this domain than the imperative "order X" — matching
        it bare turned every order-status question into an add."""

        for message in ("what's the status of my order?", "cancel my order"):
            self.assertIsNone(classify_cart_verb(message), msg=message)

    def test_wanting_an_action_is_not_wanting_an_item(self) -> None:
        """"I want to <verb>" is a request for staff to do something, not a
        request for a dish — only "i want <a thing>" is an add cue."""

        self.assertIsNone(classify_cart_verb("I want to speak to a manager"))

    def test_get_me_a_non_item_is_not_an_add_cue(self) -> None:
        self.assertIsNone(classify_cart_verb("can you get me the wifi password"))

    def test_take_out_the_fulfillment_type_is_not_a_remove_cue(self) -> None:
        """Take-out is a fulfillment type on this site, not a request to
        remove something from the cart — "take the rice out" is; "do you do
        take out?" is not, and the difference is whether there's an object
        between "take" and "out"."""

        for message in ("do you do take out?", "is this for take out or delivery?"):
            self.assertIsNone(classify_cart_verb(message), msg=message)

    def test_cart_scoped_phrasings_still_classify(self) -> None:
        """The genuine requests the review specifically asked to keep
        working, gathered here for direct traceability against that list."""

        cases = [
            ("clear my cart", "clear"),
            ("start over with my order", "clear"),
            ("remove the pizza from my cart", "remove"),
            ("add two spring rolls", "add"),
        ]
        for message, expected in cases:
            self.assertEqual(classify_cart_verb(message), expected, msg=message)

    def test_a_genuine_two_verb_conflict_yields_none(self) -> None:
        """"remove the pizza and add a coke" asks for two different cart
        mutations in one turn. Silently doing one and dropping the other is
        the failure mode nobody notices, so a real conflict between action
        categories returns None and lets a later tier ask, rather than the
        classifier guessing which half of the request mattered more."""

        self.assertIsNone(classify_cart_verb("remove the pizza and add a coke"))


PAD_THAI = uuid.uuid4()
CURRY = uuid.uuid4()


class ActionResolverTests(unittest.TestCase):
    """One customer sentence, at most one cart action — never a guessed list."""

    def _dish(self, *, has_sizes: bool = False, has_customizations: bool = False, item_id=PAD_THAI) -> ResolvedDish:
        return ResolvedDish(menu_item_id=item_id, has_sizes=has_sizes, has_customizations=has_customizations)

    def test_a_plain_named_add_is_applied(self) -> None:
        actions = resolve_cart_actions(
            "add the pad thai",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[],
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].kind, "add")
        self.assertEqual(actions[0].status, "applied")
        self.assertEqual(actions[0].reason, "named")
        self.assertEqual(actions[0].menu_item_id, PAD_THAI)
        self.assertEqual(actions[0].quantity, 1)

    def test_a_quantity_is_carried_through(self) -> None:
        actions = resolve_cart_actions(
            "add two pad thai", dish_reference="named", resolved_dish=self._dish(), existing_lines=[]
        )

        self.assertEqual(actions[0].quantity, 2)

    def test_a_choice_bearing_item_is_never_blind_added(self) -> None:
        """Same rule dish-card.tsx and suggestionNeedsChoice already enforce."""

        actions = resolve_cart_actions(
            "add the pad thai",
            dish_reference="named",
            resolved_dish=self._dish(has_sizes=True),
            existing_lines=[],
        )

        self.assertEqual(actions[0].status, "proposed")
        self.assertEqual(actions[0].reason, "needs_choice")

    def test_an_unrecognised_dish_name_yields_no_action(self) -> None:
        actions = resolve_cart_actions(
            "add the moon rock curry", dish_reference="absent", resolved_dish=None, existing_lines=[]
        )

        self.assertEqual(actions, [])

    def test_an_unresolved_reference_yields_no_action(self) -> None:
        """`unknown` (no distance to judge by) is not evidence either way."""

        actions = resolve_cart_actions(
            "add it", dish_reference="unknown", resolved_dish=None, existing_lines=[]
        )

        self.assertEqual(actions, [])

    def test_a_message_with_no_cart_verb_yields_no_action(self) -> None:
        actions = resolve_cart_actions(
            "what's spicy tonight?", dish_reference="named", resolved_dish=self._dish(), existing_lines=[]
        )

        self.assertEqual(actions, [])

    def test_removing_the_one_matching_line_is_applied(self) -> None:
        actions = resolve_cart_actions(
            "remove the pad thai",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[ExistingCartLine(menu_item_id=PAD_THAI)],
        )

        self.assertEqual(actions[0].kind, "remove")
        self.assertEqual(actions[0].status, "applied")

    def test_removing_nothing_present_yields_no_action(self) -> None:
        actions = resolve_cart_actions(
            "remove the pad thai", dish_reference="named", resolved_dish=self._dish(), existing_lines=[]
        )

        self.assertEqual(actions, [])

    def test_removing_a_dish_with_two_lines_is_always_proposed(self) -> None:
        """Two sizes of the same dish — which one? Destructive, so ask, always."""

        actions = resolve_cart_actions(
            "remove the pad thai",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[ExistingCartLine(menu_item_id=PAD_THAI), ExistingCartLine(menu_item_id=PAD_THAI)],
        )

        self.assertEqual(actions[0].status, "proposed")
        self.assertEqual(actions[0].reason, "destructive")

    def test_clear_is_always_proposed_regardless_of_confidence(self) -> None:
        actions = resolve_cart_actions(
            "clear my cart", dish_reference="unknown", resolved_dish=None, existing_lines=[]
        )

        self.assertEqual(actions[0].kind, "clear")
        self.assertEqual(actions[0].status, "proposed")
        self.assertEqual(actions[0].reason, "destructive")

    def test_set_quantity_on_one_matching_line_is_applied(self) -> None:
        actions = resolve_cart_actions(
            "make it 3",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[ExistingCartLine(menu_item_id=PAD_THAI)],
        )

        self.assertEqual(actions[0].kind, "set_quantity")
        self.assertEqual(actions[0].status, "applied")
        self.assertEqual(actions[0].quantity, 3)

    def test_set_quantity_with_no_number_yields_no_action(self) -> None:
        actions = resolve_cart_actions(
            "change the quantity to",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[ExistingCartLine(menu_item_id=PAD_THAI)],
        )

        self.assertEqual(actions, [])

    def test_set_quantity_on_two_matching_lines_is_ambiguous(self) -> None:
        actions = resolve_cart_actions(
            "make it 3",
            dish_reference="named",
            resolved_dish=self._dish(),
            existing_lines=[ExistingCartLine(menu_item_id=PAD_THAI), ExistingCartLine(menu_item_id=PAD_THAI)],
        )

        self.assertEqual(actions[0].status, "proposed")
        self.assertEqual(actions[0].reason, "ambiguous")

    def test_a_line_of_a_different_item_does_not_count_as_a_match(self) -> None:
        actions = resolve_cart_actions(
            "remove the pad thai",
            dish_reference="named",
            resolved_dish=self._dish(item_id=PAD_THAI),
            existing_lines=[ExistingCartLine(menu_item_id=CURRY)],
        )

        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
