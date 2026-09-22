"""Saying hello gets you a restaurant, a question, and something to eat.

The greeting used to be "Good morning 👋 What sounds good right now? I can
help with breakfast picks, spice levels, budgets, or quick cravings." — a
description of a search tool, from a business that never said which business
it was, to somebody who had just walked in and said hello.

A restaurant answers a greeting by naming itself, asking what you fancy, and
showing you what people are having. The dishes are real rows, ordered by
popularity, and because every reply records what it showed (see
`remember_shown_dishes`) "the first one" works on the very next message.

**The dangerous part is the cache.** Greetings are cached so the path can
answer in a tenth of a second, and the key used to be the message alone —
correct while the greeting was one generic sentence, and a cross-tenant leak
the moment it started naming a restaurant. It was caught live: with the key
unchanged, a Bangkok Bowl customer was greeted "You're through to Radhe
Dhokla" and shown four Gujarati dishes priced in dollars.
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

from app.services import rag


class TheGreetingNamesTheRestaurantTests(unittest.TestCase):
    def test_it_says_whose_kitchen_answered(self) -> None:
        reply = rag._build_greeting_reply("Hi", restaurant_name="Radhe Dhokla")
        self.assertIn("Radhe Dhokla", reply)

    def test_it_asks_what_they_are_in_the_mood_for(self) -> None:
        reply = rag._build_greeting_reply("Hi", restaurant_name="Radhe Dhokla")
        self.assertIn("mood", reply.lower())

    def test_the_marketplace_names_nobody(self) -> None:
        # It is not a restaurant, and claiming to be one would be a lie about
        # which business the customer reached.
        reply = rag._build_greeting_reply("Hi", restaurant_name=None)
        self.assertNotIn("through to", reply)
        self.assertIn("mood", reply.lower())

    def test_the_daypart_still_decides_the_opener(self) -> None:
        self.assertTrue(
            rag._build_greeting_reply("Good morning").startswith("Good morning")
        )
        self.assertTrue(
            rag._build_greeting_reply("Good evening").startswith("Good evening")
        )

    def test_the_customers_name_still_fits(self) -> None:
        # `_greeting_with_name` splits on the wave, so the opener has to keep
        # ending in one.
        reply = rag._build_greeting_reply("Hi", restaurant_name="Radhe Dhokla")
        self.assertIn("\U0001f44b", reply)
        self.assertTrue(rag._greeting_with_name(reply, "Vishal").startswith("Good"))
        self.assertIn("Vishal", rag._greeting_with_name(reply, "Vishal"))


class ItOnlyPromisesDishesItHasTests(unittest.TestCase):
    """"Here is what people are ordering:" with nothing under it is a lie."""

    def test_the_lead_in_appears_only_with_dishes(self) -> None:
        with_food = rag._build_greeting_reply("Hi", restaurant_name="X", has_dishes=True)
        without = rag._build_greeting_reply("Hi", restaurant_name="X", has_dishes=False)
        self.assertIn("what people are ordering", with_food)
        self.assertNotIn("what people are ordering", without)

    def test_a_greeting_with_no_database_still_greets(self) -> None:
        self.assertEqual(rag._greeting_suggestions(None, None, None), [])
        self.assertTrue(rag._build_greeting_reply("Hi"))


class OneCachedGreetingPerBranchTests(unittest.TestCase):
    """The leak this key exists to prevent, measured live before the fix."""

    def setUp(self) -> None:
        self.bangkok = uuid.uuid4()
        self.radhe = uuid.uuid4()

    def test_two_restaurants_never_share_an_entry(self) -> None:
        self.assertNotEqual(
            rag._greeting_response_cache_key("Hi", self.bangkok, None),
            rag._greeting_response_cache_key("Hi", self.radhe, None),
        )

    def test_two_branches_of_one_restaurant_do_not_either(self) -> None:
        # Branches of one restaurant have different menus — Radhe Dhokla's
        # 136 items are all on a single branch — so the dishes a greeting
        # shows differ by branch as well.
        first, second = uuid.uuid4(), uuid.uuid4()
        self.assertNotEqual(
            rag._greeting_response_cache_key("Hi", self.radhe, first),
            rag._greeting_response_cache_key("Hi", self.radhe, second),
        )

    def test_the_same_branch_and_message_is_one_entry(self) -> None:
        # Otherwise there is no cache at all, and the tenth-of-a-second
        # greeting becomes a query every time.
        branch = uuid.uuid4()
        self.assertEqual(
            rag._greeting_response_cache_key("Hi", self.radhe, branch),
            rag._greeting_response_cache_key("Hi", self.radhe, branch),
        )

    def test_the_marketplace_has_its_own(self) -> None:
        self.assertNotEqual(
            rag._greeting_response_cache_key("Hi", None, None),
            rag._greeting_response_cache_key("Hi", self.radhe, None),
        )

    def test_the_version_moved_so_old_entries_are_not_read(self) -> None:
        # Entries written under the old key have no restaurant in them. Left
        # readable, the first one found would be served to everybody.
        key = rag._greeting_response_cache_key("Hi", self.radhe, None)
        self.assertIn(":v4:", key)
        self.assertNotIn(":v3:", key)


if __name__ == "__main__":
    unittest.main()
