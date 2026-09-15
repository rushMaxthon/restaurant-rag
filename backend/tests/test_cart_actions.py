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
from app.services.cart_actions import extract_requested_quantity


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


if __name__ == "__main__":
    unittest.main()
