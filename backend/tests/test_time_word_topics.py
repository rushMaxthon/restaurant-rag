"""A time reference is not a dish.

Reported from the app: "What is menu for today?" answered

    We don't have a specific "today" menu — but we've got a few crowd
    favourites that are always worth trying...

which is the assistant telling a customer that the thing they asked about is
not on the menu. Nothing was wrong with retrieval and the model was not
hallucinating; it was answering the question it was handed.

`TOPIC_STOPWORDS` already strips the meta words a person wraps a request in —
"menu", "dish", "food", "item", "option" — so that "what food do you have"
does not go looking for a dish called "food". It had no time words. Tokenising
"what is menu for today" drops "what", "is", "for" as query stopwords and
"menu" as a topic stopword, leaving exactly one token standing: "today". That
became the dish, and the whole turn proceeded as a search for it.

The failure is quiet, which is what makes it worth a test. A search for a dish
that does not exist still returns popular fallbacks, so the reply looks helpful
and reads fluently — it just opens by denying something the customer never
asked for.

No dish on this menu contains a time word in its name, checked across all 189
before adding them here.
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
    SessionConversationState,
    _canonicalize_topic,
    _fallback_extract_intent,
)


class TimeWordTopicTests(unittest.TestCase):
    def test_today_is_not_a_dish(self) -> None:
        """The reported case, at the layer that produced it."""

        intent = _fallback_extract_intent("What is menu for today?", SessionConversationState())
        self.assertNotEqual(intent.dish, "today")
        self.assertNotIn("today", intent.items or [])

    def test_time_words_never_survive_as_a_topic(self) -> None:
        for phrase in (
            "what is menu for today",
            "whats on the menu tonight",
            "show me the menu for tomorrow",
            "what food do you have right now",
            "menu for this evening",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(_canonicalize_topic(phrase))

    def test_a_real_craving_still_survives(self) -> None:
        """The stopwords must strip the wrapper, never the request.

        "tonight" going quiet must not take "pad thai" with it — otherwise this
        fix trades a wrong answer for no answer.

        Asserted as a property rather than an exact string on purpose. The topic
        is stemmed ("momos" -> "momo") and some filler the parser does not strip
        rides along ("want", "there"); pinning the whole string here would lock
        in behaviour this change never touched, and the next person to improve
        the filler list would have to edit a test about time words to do it.
        """

        for phrase, wanted, unwanted in (
            ("what is on the menu for pad thai tonight", "thai", "tonight"),
            ("i want momos today", "momo", "today"),
        ):
            with self.subTest(phrase=phrase):
                topic = _canonicalize_topic(phrase) or ""
                self.assertIn(wanted, topic)
                self.assertNotIn(unwanted, topic)

    def test_meal_words_are_still_meaningful(self) -> None:
        """Dayparts are not time noise.

        "breakfast" and "lunch" name a category the menu actually has, so they
        must keep working as topics even though they sound temporal. This is the
        line the added stopwords must not cross.
        """

        self.assertIn("breakfast", _canonicalize_topic("what is there for breakfast") or "")
        self.assertEqual(_canonicalize_topic("show me lunch"), "lunch")


if __name__ == "__main__":
    unittest.main()
