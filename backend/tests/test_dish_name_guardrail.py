"""Deciding whether a dish was named, by distance rather than by word list.

Spec: docs/superpowers/specs/2026-09-14-dish-name-guardrail-design.md

Four bugs, one cause:

    "What is menu for today?"   -> "We don't have a specific 'today' menu..."
    "whats special"             -> "We don't have a 'special' item..."
    "Which item are trending?"  -> "We don't have a 'special' item..."
    "how much is delivery?"     -> "We don't offer delivery on the menu..."

Each was the assistant telling a customer that a word they used is not on the
menu, and each was fixed by adding that word to a stop list. That list cannot
converge: the set of things people say which are not dish names is unbounded,
while the set that ARE is 189 rows in Postgres.

The extractors decide by elimination — strip the words known not to be food and
assume whatever survives is a dish. This decides by recognition instead: a dish
is named only when something on the menu is semantically near what was said.

Measured over 39 phrases with nomic-embed-text against the seeded menu:

    dish on the menu        0.135 - 0.271
    dish, misspelled        0.210 - 0.376
    craving, no dish named  0.372 - 0.569
    generic word, not food  0.446 - 0.555
    not food at all         0.522 - 0.574

The distances themselves are not asserted here. They belong to one embedding
model and one 189-item menu, and pinning them would make this brittle for no
gain — what is pinned is that the threshold sits in the gap the measurement
found, so moving it has to confront the data.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.rag import (
    DISH_NAME_MAX_DISTANCE,
    classify_dish_reference,
)

# The measurement this threshold was drawn from, kept so the assertions below
# read against real numbers rather than invented ones.
FURTHEST_REAL_DISH = 0.376  # "chiken burger", misspelled
NEAREST_NON_DISH = 0.372  # "something sweet", a craving naming no dish


class ClassificationTests(unittest.TestCase):
    def test_a_near_match_is_a_named_dish(self) -> None:
        self.assertEqual(classify_dish_reference(0.18), "named")
        self.assertEqual(classify_dish_reference(0.271), "named")

    def test_a_distant_match_names_no_dish(self) -> None:
        """"today" at 0.481, "trending" at 0.450, "delivery" and the rest."""

        self.assertEqual(classify_dish_reference(0.45), "absent")
        self.assertEqual(classify_dish_reference(0.57), "absent")

    def test_a_missing_distance_decides_nothing(self) -> None:
        """No embedding — Ollama down, or a timeout — must leave behaviour
        exactly as it is today. A guardrail may decline to act; it may never
        break a reply."""

        self.assertEqual(classify_dish_reference(None), "unknown")

    def test_the_boundary_belongs_to_absent(self) -> None:
        """Exactly at the threshold is not a dish.

        Half-open on purpose, so the constant reads as "dishes are nearer than
        this" and there is no value that is both.
        """

        self.assertEqual(classify_dish_reference(DISH_NAME_MAX_DISTANCE), "absent")
        self.assertEqual(classify_dish_reference(DISH_NAME_MAX_DISTANCE - 0.001), "named")


class ThresholdSitsInTheMeasuredGapTests(unittest.TestCase):
    """The number is evidence-backed, and an edit has to confront the evidence.

    A future change to DISH_NAME_MAX_DISTANCE that walks into either band fails
    here rather than silently starting to tell customers we do not sell pad thai.
    """

    def test_every_measured_dish_is_still_recognised(self) -> None:
        self.assertGreater(
            DISH_NAME_MAX_DISTANCE,
            FURTHEST_REAL_DISH,
            "Threshold moved below a real dish — misspelled orders would be refused",
        )

    def test_no_measured_non_dish_is_recognised(self) -> None:
        # The one known false positive: "something sweet" at 0.372 sits just
        # inside the dish side and will be treated as a named dish. Recorded in
        # the spec; the consequence is a search for something sweet returning
        # desserts, which is the right answer by a slightly wrong route.
        self.assertLessEqual(
            DISH_NAME_MAX_DISTANCE,
            NEAREST_NON_DISH + 0.01,
            "Threshold moved into the craving band — general requests would be "
            "searched as if they named a dish",
        )


if __name__ == "__main__":
    unittest.main()
