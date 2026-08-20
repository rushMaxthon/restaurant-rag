"""Conversational openers: greetings, thanks, and "what can you do".

A greeting answered with "I could not work out which part of your data that
question is about" is not an honest refusal — nothing was asked about the data,
so there is nothing to refuse. These tests cover the detection, the guard that
keeps a real question from being greeted away, and the replies themselves.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import unittest

from app.services.insights.router import detect_small_talk, route_with_rules
from app.services.insights.skills import SMALL_TALK_REPLIES


class SmallTalkDetectionTests(unittest.TestCase):
    def test_greetings_are_recognised(self) -> None:
        for question in (
            "hello AI Restaurant Manager",
            "hi",
            "hey there",
            "good morning",
            "Hello!",
        ):
            with self.subTest(question=question):
                self.assertEqual(detect_small_talk(question), "greeting")

    def test_the_other_openers_are_recognised(self) -> None:
        cases = {
            "how are you ?": "how_are_you",
            "how's it going": "how_are_you",
            "thanks!": "thanks",
            "thank you": "thanks",
            "bye": "goodbye",
            "what can you do": "capabilities",
            "who are you": "capabilities",
            "help": "capabilities",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(detect_small_talk(question), expected)

    def test_a_real_question_is_never_greeted_away(self) -> None:
        # The dangerous case: an opener with a question behind it. Greeting it
        # back would drop the question entirely.
        for question in (
            "hello, why are my sales down?",
            "hi, how many orders did I get",
            "good morning, which dish sells best?",
        ):
            with self.subTest(question=question):
                self.assertIsNone(detect_small_talk(question))

    def test_data_questions_that_look_conversational(self) -> None:
        # "how are my sales doing" opens like "how are you" and is not small
        # talk; the patterns are anchored to whole openers for this reason.
        for question in (
            "how are my sales doing",
            "how are the branches performing",
            "why are my sales down",
        ):
            with self.subTest(question=question):
                self.assertIsNone(detect_small_talk(question))

    def test_long_messages_are_not_small_talk(self) -> None:
        self.assertIsNone(
            detect_small_talk(
                "hello there, I was wondering whether you could tell me how the "
                "restaurant has been performing over the past few weeks"
            )
        )

    def test_small_talk_routes_ahead_of_the_refusal(self) -> None:
        routed = route_with_rules("hello AI Restaurant Manager")

        self.assertIsNotNone(routed)
        self.assertEqual(routed.skill, "small_talk")
        self.assertEqual(routed.params.topic, "greeting")


class SmallTalkReplyTests(unittest.TestCase):
    def reply(self, question: str) -> str:
        from app.services.insights.skills import SkillParams, small_talk
        from app.services.insights.router import detect_small_talk, normalize

        params = SkillParams(topic=detect_small_talk(question), subject=normalize(question))
        return small_talk(None, None, params).answer

    def test_a_greeting_gets_a_greeting_and_somewhere_to_start(self) -> None:
        answer = self.reply("hello AI Restaurant Manager")

        self.assertNotIn("could not work out", answer)
        self.assertIn("Hello", answer)
        # Three example questions, not the full capability list.
        self.assertIn("For example:", answer)

    def test_capabilities_are_explained_when_actually_asked(self) -> None:
        answer = self.reply("what can you do")

        self.assertIn("Revenue", answer)
        self.assertIn("dishes", answer)

    def test_thanks_gets_a_short_reply(self) -> None:
        answer = self.reply("thanks!")

        self.assertLess(len(answer), 120)
        self.assertNotIn("For example:", answer)

    def test_the_reply_is_reproducible_for_the_same_wording(self) -> None:
        # Varied between phrasings so it does not sound canned, but never
        # random: the same message always gets the same answer.
        self.assertEqual(self.reply("hi"), self.reply("hi"))

    def test_wordings_do_not_all_sound_identical(self) -> None:
        replies = {self.reply("hi"), self.reply("hello"), self.reply("hey there")}

        self.assertGreater(len(replies), 1)

    def test_small_talk_carries_no_facts(self) -> None:
        # Nothing to ground an answer in, so the model is never called and the
        # UI has no numbers to offer.
        from app.services.insights.skills import SkillParams, small_talk
        from app.services.insights import chat

        result = small_talk(None, None, SkillParams(topic="greeting", subject="hi"))

        self.assertFalse(result.unsupported)
        self.assertFalse(chat._has_facts(result))

    def test_every_detected_intent_has_a_reply(self) -> None:
        from app.services.insights.router import SMALL_TALK_PATTERNS

        for intent, _ in SMALL_TALK_PATTERNS:
            with self.subTest(intent=intent):
                self.assertTrue(intent == "capabilities" or intent in SMALL_TALK_REPLIES)


if __name__ == "__main__":
    unittest.main()
