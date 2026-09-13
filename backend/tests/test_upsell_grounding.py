"""Detecting the upsell the retrieval never supplied.

The case this was written from, observed on the first test of the selling
prompt. Asked for something spicy and vegetarian, the model recommended:

    Paneer Chilli Momos (8 pcs) | Momos tossed in a spicy paneer chilli sauce.

and offered them "with the spicy chutney on the side". There is no chutney on
that dish. Exactly one dish in the whole menu mentions chutney — Fried Chicken
Momos — and the model had reached for it.

Nothing about that sentence reads as invented, which is the point: every word is
a real menu word, attached to the wrong dish. A rule in the prompt cannot catch
it, because the model is not breaking a rule it understands itself to be
breaking. What distinguishes the claim is provenance — the term is in the menu
corpus and absent from the context for this request, so it was recalled rather
than retrieved.

These tests lock the detector to that distinction, and to the false positives
that would make it unusable: a word the context did supply, and a word that
describes every dish on the menu equally.
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
from app.services.rag import ungrounded_menu_terms


# Stands in for the learned vocabulary: distinctive dish words, none of them
# common enough across the menu to be filtered out by document frequency.
VOCABULARY = frozenset(
    {
        "chutney",
        "momos",
        "paneer",
        "tamarind",
        "tiramisu",
        "noodles",
        "pandan",
    }
)

# One context line, exactly as `_format_context_line` builds it.
MOMO_CONTEXT = (
    "Paneer Chilli Momos (8 pcs) | $8.50 | Veg | Starters | Momo Mountain | "
    "Momos tossed in a spicy paneer chilli sauce."
)


class UngroundedTermTests(unittest.TestCase):
    def test_the_chutney_that_started_this(self) -> None:
        reply = (
            "The Paneer Chilli Momos are a standout — tossed in a spicy paneer "
            "chilli sauce. Would you like them with the spicy chutney on the side?"
        )
        self.assertEqual(ungrounded_menu_terms(reply, MOMO_CONTEXT, VOCABULARY), {"chutney"})

    def test_a_reply_that_stays_inside_its_context_is_clean(self) -> None:
        reply = "The Paneer Chilli Momos come tossed in a spicy paneer chilli sauce. Shall I add them?"
        self.assertEqual(ungrounded_menu_terms(reply, MOMO_CONTEXT, VOCABULARY), set())

    def test_a_dish_from_another_cuisine_is_caught(self) -> None:
        """The cross-restaurant version of the same mistake."""

        reply = "If you want something sweet after, the Tiramisu is lovely."
        self.assertEqual(ungrounded_menu_terms(reply, MOMO_CONTEXT, VOCABULARY), {"tiramisu"})

    def test_several_borrowed_terms_are_all_reported(self) -> None:
        reply = "Pair the momos with tamarind noodles and finish with pandan."
        self.assertEqual(
            ungrounded_menu_terms(reply, MOMO_CONTEXT, VOCABULARY),
            {"tamarind", "noodles", "pandan"},
        )

    def test_words_outside_the_vocabulary_are_not_the_detector_s_business(self) -> None:
        """Ordinary prose must not be mistaken for a menu claim.

        "delicious" and "tonight" are not dishes. Only terms the menu itself
        made distinctive are candidates, which is what keeps this from flagging
        every adjective the model reaches for.
        """

        reply = "These are absolutely delicious tonight, genuinely worth ordering."
        self.assertEqual(ungrounded_menu_terms(reply, MOMO_CONTEXT, VOCABULARY), set())

    def test_an_empty_vocabulary_disables_the_check(self) -> None:
        """A menu that has not loaded must not make every reply look invented."""

        reply = "Would you like them with the spicy chutney on the side?"
        self.assertEqual(ungrounded_menu_terms(reply, MOMO_CONTEXT, frozenset()), set())


if __name__ == "__main__":
    unittest.main()
