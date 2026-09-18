"""A short reply is a reply, not gibberish.

From a real WhatsApp thread. The assistant opened with "I can help with
dishes by cuisine, budget, spice level, offers, or meal mood." The customer
answered:

    Please

and was told "I didn't quite catch that. Ask me about food, restaurants,
menus, combos, offers, or something like dinner under a budget." — the second
message of the conversation, to a person who had done nothing wrong.

The cause is in `_is_invalid_or_spam_message`: it tokenises the message,
drops every word shorter than three characters and every word on the query
stopword list, and calls what is left the evidence. "Please" is a stopword.
"ok", "go on", "do it" are made of two-letter words. All of them tokenise to
nothing, and an empty token list was being read as "this message is
unparseable" when what it actually means is "this message is short and
ordinary".

Nothing else in that function needs the token list to catch real gibberish:
a message of pure punctuation, a mashed key, and an empty string are each
caught by their own rule above it. So the token check was the only rule that
could fire on plain English, and plain English is the only thing it fired on.

The one-line version: a message made of real words is never gibberish,
however short those words are.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import rag


class ShortRepliesAreNotGibberishTests(unittest.TestCase):
    """The exact messages, and the family they belong to."""

    def test_please_is_not_gibberish(self) -> None:
        """The message from the transcript."""

        self.assertFalse(rag._is_invalid_or_spam_message("Please"))

    def test_the_ordinary_ways_of_saying_go_ahead(self) -> None:
        # Every one of these tokenises to nothing, and every one of them is
        # something a person types into a chat several times a day.
        for message in (
            "Please",
            "please",
            "ok",
            "OK",
            "okay",
            "go on",
            "do it",
            "go ahead",
            "yes do",
            "any",
            "sure go on",
        ):
            with self.subTest(message=message):
                self.assertFalse(rag._is_invalid_or_spam_message(message))

    def test_they_no_longer_reach_the_did_not_catch_that_reply(self) -> None:
        """The whole point: the classifier's verdict, not just the guard."""

        state = rag.SessionConversationState()
        for message in ("Please", "go on", "do it"):
            with self.subTest(message=message):
                intent = rag._fallback_extract_intent(message, state)
                self.assertNotEqual(intent.intent, "invalid_input")


class RealGibberishStillIsTests(unittest.TestCase):
    """The guard is narrowed, not removed.

    Each of these was caught before this change and has to stay caught, or
    the fix has traded one wrong answer for another.
    """

    def test_punctuation_alone(self) -> None:
        for message in ("!!!", "???", "...", "@@@@", "-_-_-_"):
            with self.subTest(message=message):
                self.assertTrue(rag._is_invalid_or_spam_message(message))

    def test_a_held_down_key(self) -> None:
        self.assertTrue(rag._is_invalid_or_spam_message("aaaaaaaaaa"))
        self.assertTrue(rag._is_invalid_or_spam_message("hhhhhhhhhhhh"))

    def test_nothing_at_all(self) -> None:
        self.assertTrue(rag._is_invalid_or_spam_message(""))
        self.assertTrue(rag._is_invalid_or_spam_message(" "))
        self.assertTrue(rag._is_invalid_or_spam_message("x"))

    def test_digits_with_no_words(self) -> None:
        # Not letters, so nothing here is a word. A bare number answering a
        # question is handled by the agent, which knows what it asked.
        self.assertTrue(rag._is_invalid_or_spam_message("12"))

    def test_a_long_mash_is_still_not_words(self) -> None:
        # Long enough to survive tokenising, so it never reached the token
        # rule in the first place — pinned so the narrowing above cannot be
        # read as making this pass.
        self.assertFalse(rag._is_invalid_or_spam_message("asdkjhqwe"))


class TheFoodSignalEscapeStillWorksTests(unittest.TestCase):
    """The comment in the function records the last time this broke.

    "what do you recommend" is every word a stopword, reached this guard, and
    was answered "I didn't quite catch that". It was fixed by checking for a
    food signal first. That fix stays load-bearing.
    """

    def test_what_do_you_recommend(self) -> None:
        self.assertFalse(rag._is_invalid_or_spam_message("what do you recommend"))


if __name__ == "__main__":
    unittest.main()
