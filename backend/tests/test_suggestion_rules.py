"""The rules that decide what a waiter offers next.

Pure over their inputs on purpose. The selling rules are the part most likely
to be argued about later, and a rule that needs a database and a session to
exercise is a rule nobody re-checks after changing it.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.suggestions import (
    CandidateItem,
    PairingPattern,
    choose_pairing,
)

CURRY = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
TEA = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
RICE = uuid.UUID("00000000-0000-0000-0000-0000000000b1")


def _candidate(item_id: uuid.UUID, *, is_veg: bool = True, available: bool = True) -> CandidateItem:
    return CandidateItem(
        menu_item_id=item_id,
        category="Beverages",
        is_veg=is_veg,
        is_available=available,
    )


class PairingRuleTests(unittest.TestCase):
    def test_a_pattern_missing_exactly_one_item_yields_that_item(self) -> None:
        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("9"))

        result = choose_pairing(
            [pattern],
            {CURRY},
            candidates={TEA: _candidate(TEA)},
            diet=None,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.menu_item_id, TEA)
        self.assertEqual(result.basis, "co_occurrence")
        self.assertEqual(result.kind, "cross_sell")

    def test_a_pattern_missing_two_items_is_not_a_pairing(self) -> None:
        """Suggesting two things at once is a menu, not a waiter's nudge."""

        pattern = PairingPattern(item_ids=(CURRY, TEA, RICE), confidence_score=Decimal("9"))

        self.assertIsNone(
            choose_pairing(
                [pattern],
                {CURRY},
                candidates={TEA: _candidate(TEA), RICE: _candidate(RICE)},
                diet=None,
            )
        )

    def test_a_pattern_that_does_not_touch_the_cart_is_ignored(self) -> None:
        pattern = PairingPattern(item_ids=(TEA, RICE), confidence_score=Decimal("9"))

        self.assertIsNone(
            choose_pairing([pattern], {CURRY}, candidates={TEA: _candidate(TEA)}, diet=None)
        )

    def test_the_highest_confidence_pattern_wins(self) -> None:
        weak = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("3"))
        strong = PairingPattern(item_ids=(CURRY, RICE), confidence_score=Decimal("11"))

        result = choose_pairing(
            [weak, strong],
            {CURRY},
            candidates={TEA: _candidate(TEA), RICE: _candidate(RICE)},
            diet=None,
        )

        self.assertEqual(result.menu_item_id, RICE)

    def test_a_veg_customer_is_never_offered_a_non_veg_pairing(self) -> None:
        """The business-rule filter runs BEFORE ranking, everywhere in this repo."""

        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("99"))

        self.assertIsNone(
            choose_pairing(
                [pattern],
                {CURRY},
                candidates={TEA: _candidate(TEA, is_veg=False)},
                diet="VEG",
            )
        )

    def test_an_unavailable_item_is_never_offered(self) -> None:
        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("99"))

        self.assertIsNone(
            choose_pairing(
                [pattern],
                {CURRY},
                candidates={TEA: _candidate(TEA, available=False)},
                diet=None,
            )
        )

    def test_an_empty_cart_yields_nothing(self) -> None:
        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("9"))

        self.assertIsNone(
            choose_pairing([pattern], set(), candidates={TEA: _candidate(TEA)}, diet=None)
        )


if __name__ == "__main__":
    unittest.main()
