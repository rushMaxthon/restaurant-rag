"""A budget is a filter here too, not a thing to search the menu for.

From the live concierge, "anything under 10 dollars". The log showed the
budget read correctly — `budget=10` — and the topic canonicalised to:

    extracted_topic=under dollar

which went to pgvector and came back Sweet Lassi, Masala Cola, Butter Tea.
The number was understood and then the search went looking for a dish called
"under dollar".

The words a price limit is written in are the same kind of word as the time
words already in `TOPIC_STOPWORDS` — the list that exists because "show me
todays menu" once searched for a dish called "today" — and the same kind as
"spicy" and "veg" in `BARE_TOPIC_STOPWORDS`, which that list's own comment
describes as "the attributes this extractor treats as filters rather than
topics". A budget is exactly that.

The ordering agent's browse path was fixed separately; this is the
recommendation path, which reaches the menu through retrieval instead.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.rag import _canonicalize_topic, _extract_budget_limit


class TheBudgetIsStillReadTests(unittest.TestCase):
    """Unchanged, and worth asserting beside the topic: the number still has
    to be extracted, or dropping its words would lose the constraint."""

    def test_the_number_still_comes_out(self) -> None:
        for message, expected in (
            ("anything under 10 dollars", 10),
            ("noodles under 12 dollars", 12),
            ("something under 200 rupees", 200),
            ("biryani below 300", 300),
        ):
            with self.subTest(message=message):
                self.assertEqual(int(_extract_budget_limit(message) or 0), expected)


class ThePriceWordsDoNotBecomeTheSearchTests(unittest.TestCase):
    def test_the_reported_message_no_longer_searches_for_under_dollar(self) -> None:
        # The exact string from the transcript.
        self.assertNotEqual(_canonicalize_topic("anything under 10 dollars"), "under dollar")

    def test_a_pure_budget_request_has_no_topic_at_all(self) -> None:
        # Correct, and better than a wrong one: there is no food word in it,
        # so there is nothing to search for and the budget is the whole
        # request.
        self.assertIsNone(_canonicalize_topic("anything under 10 dollars"))

    def test_the_food_word_survives_the_budget(self) -> None:
        # The case that matters most, because it is the one people type.
        self.assertIn("noodle", _canonicalize_topic("noodles under 12 dollars") or "")
        self.assertIn("paneer", _canonicalize_topic("paneer under 200 rupees") or "")
        self.assertIn("biryani", _canonicalize_topic("biryani below 300") or "")

    def test_no_currency_this_platform_charges_in_becomes_a_topic(self) -> None:
        # Rupees, dollars, pounds, euros and dirhams are what the catalogue
        # in `services/currency.py` supports.
        for money in ("dollars", "rupees", "rs", "pounds", "euros", "dirhams"):
            with self.subTest(money=money):
                topic = _canonicalize_topic(f"anything under 100 {money}") or ""
                self.assertNotIn(money.rstrip("s"), topic)

    def test_a_dish_is_still_findable_by_its_own_name(self) -> None:
        # The cost of every stopword is a dish named after it, so this is the
        # guard on the words that were added: none of them is a food.
        for dish in ("chicken biryani", "paneer tikka", "masala dosa", "spring rolls"):
            with self.subTest(dish=dish):
                self.assertTrue(_canonicalize_topic(dish), f"{dish} still searchable")

    def test_the_time_words_this_list_was_built_for_still_go(self) -> None:
        # The bug this list already existed to fix, asserted so the additions
        # cannot quietly displace it.
        self.assertIsNone(_canonicalize_topic("show me todays menu"))


if __name__ == "__main__":
    unittest.main()
