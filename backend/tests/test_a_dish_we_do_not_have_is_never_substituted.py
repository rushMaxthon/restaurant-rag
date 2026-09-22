"""Asking for a dish a kitchen does not sell must not return a different one.

Radhe Dhokla is a vegetarian Gujarati kitchen in Surat. Put through the real
chat path it answered:

    >>> red curry tofu
        Which size for Kaju Curry (Brown)? 300 gm (₹175), 500 gm (₹245)...

    >>> chicken biryani
        Which size for Hydrabadi Biryani? 500 gm (₹165), 1 Kg (₹320)...

Nothing in either reply says the dish asked for does not exist. A customer can
answer "500 gm" and pay for something they did not order, and in the second
case believe a vegetarian kitchen is sending them chicken.

There IS a guardrail for this, and the reason it stayed silent is measurable.
It scores the phrase as a whole against the menu, against a 0.38 cutoff:

    tofu                -> Veg. Fried Rice             0.470   absent  ✓
    red curry tofu      -> Veg. Toofani (Red)          0.364   named   ✗
    chicken biryani     -> Nawabi Pudina Ghee Biryani  0.337   named   ✗
    paneer tikka pizza  -> Paneer Tikka Masala (Red)   0.268   named   ✗
    khaman dhokla       -> Vagharela Khaman            0.319   named   ✓

"tofu" alone is correctly refused. Surround it with two words this menu is full
of — "red", "curry" — and the average drags the phrase under the cutoff. The
one word that decides the answer is exactly the one that gets averaged away,
and no threshold separates 0.337 from 0.319: a wrong match scores BETTER than a
real order.

So the phrase is not the unit to judge. A word is. If a request contains a word
this branch's menu does not contain anywhere — not in a name, a description or
a category — and that word is not simply a misspelling of one it does contain,
then the kitchen cannot serve what was asked for, however similar the rest of
the sentence sounds.

The vocabulary comes from the menu itself. Nothing here is a hand-written list
of meats or cuisines: a Gujarati kitchen that starts selling paneer tikka pizza
serves it the moment it is on the menu, with no code change, and a kitchen that
never sells chicken refuses it without anyone having written "chicken" down.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.rag import words_this_menu_cannot_serve

#: A slice of Radhe Dhokla's real menu. Names, descriptions and categories,
#: plus its SIZE names — "Per Plate", "1 Kg", "500 gm" — which are menu language
#: too. Leaving sizes out made "a plate of dhokla" read "plate" as something the
#: kitchen does not serve.
RADHE_VOCABULARY = {
    "vagharela", "khaman", "oil", "masala", "idada", "butter", "corn", "dhokla",
    "cheese", "garlic", "jain", "jeera", "khatta", "mitha", "schezwan", "tawa",
    "green", "tadka", "plain", "live", "tam", "patudi", "khandvi", "dal",
    "samosa", "paneer", "tikka", "kaju", "curry", "brown", "red", "yellow",
    "nawabi", "pudina", "ghee", "biryani", "shahi", "dum", "hydrabadi",
    "american", "fried", "rice", "bombay", "bhel", "pulao", "aloo", "mater",
    "gravy", "naan", "chapati", "fulka", "pav", "bhaji", "noodles", "manchurian",
    "veg", "toofani", "special", "chinese", "hongkong", "singapuri", "burnt",
    # sizes
    "per", "plate", "500", "300", "kg", "gm",
}


class AWordTheKitchenCannotServeTests(unittest.TestCase):
    """The rule, against one branch's real vocabulary."""

    def unserved(self, dish: str) -> list[str]:
        return words_this_menu_cannot_serve(dish, RADHE_VOCABULARY)

    def test_tofu_is_not_on_a_gujarati_menu(self) -> None:
        self.assertIn("tofu", self.unserved("red curry tofu"))

    def test_chicken_is_not_on_a_vegetarian_menu(self) -> None:
        # The one that could genuinely mislead somebody about what they are
        # eating, which is why it is not merely a quality problem.
        self.assertIn("chicken", self.unserved("chicken biryani"))

    def test_pizza_survives_two_words_that_do_match(self) -> None:
        # "paneer" and "tikka" are all over this menu and scored the phrase at
        # 0.268 — better than a real order. The word that matters is "pizza".
        self.assertEqual(self.unserved("paneer tikka pizza"), ["pizza"])

    def test_a_real_order_is_left_alone(self) -> None:
        self.assertEqual(self.unserved("khaman dhokla"), [])

    def test_every_word_of_a_real_order_is_left_alone(self) -> None:
        for dish in ("vagharela khaman", "butter corn dhokla", "kaju curry", "tawa pulao"):
            with self.subTest(dish=dish):
                self.assertEqual(self.unserved(dish), [])

    def test_a_misspelling_is_not_a_missing_ingredient(self) -> None:
        # Typing is how most people arrive. "khamn dhokla" and "dhokhla" are
        # near-misses of words this menu HAS, and refusing them would break the
        # commonest real order at this restaurant to fix a rarer wrong one.
        for dish in ("khamn dhokla", "do u hv dhokhla", "biriyani", "panner tikka"):
            with self.subTest(dish=dish):
                self.assertEqual(self.unserved(dish), [])

    def test_small_talk_around_a_dish_is_not_an_ingredient(self) -> None:
        # The rule reads the extracted dish phrase, but that phrase is not
        # always clean. Ordinary filler must never be mistaken for something
        # the kitchen lacks, or every polite order would be refused.
        for dish in ("some khaman dhokla please", "a plate of dhokla", "the dhokla"):
            with self.subTest(dish=dish):
                self.assertEqual(self.unserved(dish), [])

    def test_an_empty_request_accuses_nothing(self) -> None:
        for dish in ("", "   ", "a", "the"):
            with self.subTest(dish=dish):
                self.assertEqual(self.unserved(dish), [])

    def test_an_unknown_menu_accuses_nothing(self) -> None:
        # No vocabulary means the menu could not be read, which is the absence
        # of evidence. Refusing every dish because a cache was cold would take
        # the whole restaurant offline.
        self.assertEqual(words_this_menu_cannot_serve("chicken biryani", set()), [])


class TheVerdictIsActedOnTests(unittest.TestCase):
    """Knowing is not enough — the dish has to stop being carried forward.

    `enable_dish_name_guardrail` is off, and for a good reason the setting
    states plainly: "a threshold that is slightly wrong refuses real orders,
    which is worse than the bug it fixes."

    That reasoning is about the DISTANCE threshold, and it still holds — 0.38
    sits between a wrong match at 0.337 and a right one at 0.319, so it will go
    wrong in both directions. It does not describe the word rule, which is not a
    threshold at all: it asks whether this menu contains any version of a word,
    including a misspelt one. So the word rule enforces and the threshold waits,
    which is exactly the line the setting's own comment draws.

    Without this, the tool refuses correctly and the chat pipeline carries the
    dish anyway. Live, that read:

        >>> red curry tofu
            The Red Curry Tofu is a standout dish — tender tofu in a rich,
            aromatic curry... one of our most popular vegetarian picks.
    """

    def guardrail(self, dish: str, vocabulary: set[str], *, distance: float | None):
        from app.services import rag

        intent = rag.ExtractedIntent(intent="dish_lookup", dish=dish)
        candidates = []
        if distance is not None:
            candidates = [
                rag.RetrievedMenuCandidate(
                    menu_item=mock.MagicMock(),
                    restaurant=mock.MagicMock(),
                    distance=distance,
                    source="vector",
                )
            ]
        with mock.patch.object(rag, "menu_vocabulary", lambda *a, **k: vocabulary),              mock.patch.object(rag.settings, "enable_dish_name_guardrail", False):
            verdict = rag.apply_dish_name_guardrail(
                intent,
                candidates,
                message=dish,
                db=mock.MagicMock(),
                query_embedding=[0.0],
            )
        return verdict, intent

    def test_a_word_we_cannot_serve_stops_being_carried_forward(self) -> None:
        # The flag is off and this still enforces. That is the whole point.
        verdict, intent = self.guardrail("red curry tofu", RADHE_VOCABULARY, distance=0.364)
        self.assertEqual(verdict, "absent")
        self.assertIsNone(intent.dish, "the dish reached the model and was described")

    def test_a_merely_distant_dish_still_waits_for_the_flag(self) -> None:
        # Unchanged behaviour, asserted so this change cannot be mistaken for
        # turning the threshold on by the back door.
        verdict, intent = self.guardrail("something odd", RADHE_VOCABULARY | {"something", "odd"}, distance=0.9)
        self.assertEqual(verdict, "absent")
        self.assertEqual(intent.dish, "something odd")

    def test_a_real_order_is_untouched(self) -> None:
        verdict, intent = self.guardrail("khaman dhokla", RADHE_VOCABULARY, distance=0.319)
        self.assertEqual(verdict, "named")
        self.assertEqual(intent.dish, "khaman dhokla")


if __name__ == "__main__":
    unittest.main()
