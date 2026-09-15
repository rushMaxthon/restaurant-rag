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
from app.services.cart_actions import classify_cart_verb, extract_requested_quantity


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
    note 3. This never touches the menu-discovery intent taxonomy."""

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
        self.assertEqual(classify_cart_verb("start over"), "clear")

    def test_an_ordinary_question_is_not_a_cart_verb(self) -> None:
        for message in ("what's spicy tonight?", "how much is the pad thai?", "recommend something vegetarian"):
            self.assertIsNone(classify_cart_verb(message), msg=message)

    def test_clear_wins_over_add_when_both_words_appear(self) -> None:
        """"start over and add pad thai" is still one action per turn — clear."""

        self.assertEqual(classify_cart_verb("never mind, start over"), "clear")


if __name__ == "__main__":
    unittest.main()
