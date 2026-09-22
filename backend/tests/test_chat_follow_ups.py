"""Answering the assistant, in the words people actually use.

Everything here was found by talking to the live assistant through
`dryrun_whatsapp.py` — the real `handle_chat_message`, the real qwen3:8b, the
real menu — rather than by reading the code. Each test names the exchange that
produced it.

The theme is one sentence long: **the assistant kept asking questions and then
failing to recognise the answers.** It showed six dishes and could not resolve
"the first one". It asked "would you like the Butter or Oil version?" and read
"yes" as a request to check out. It read "add one" as a dish called "one". In
every case the customer replied exactly as anybody would, and the fault was on
our side of the conversation.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import rag
from app.services.ordering_agent.planner import (
    _NOT_A_DISH_NAME,
    question_asked_in,
)
from app.services.whatsapp import format_for_whatsapp, render_reply


class TheQuestionAReplyEndedOnTests(unittest.TestCase):
    """A bare "yes" needs a referent, and the pipeline never left one.

        >>> food
        ... the Butter Pavbhaji is a crowd-pleaser. Would you like to go for
        ... the Butter or Oil version? 🥟
        >>> yes
        Great! It looks like you're ready to proceed. Let me check what
        details we need to finalize your order.      <- on an empty cart
    """

    def test_the_question_is_the_last_sentence(self) -> None:
        self.assertEqual(
            question_asked_in(
                "Morning! The **Butter Pavbhaji** is a must-try. "
                "Would you like the Butter or Oil version?"
            ),
            "Would you like the Butter or Oil version?",
        )

    def test_a_trailing_emoji_does_not_hide_it(self) -> None:
        # The reply pipeline ends on one constantly, and an `endswith("?")`
        # test missed every single one.
        self.assertEqual(
            question_asked_in("Would you like the Butter or Oil version? 🥟"),
            "Would you like the Butter or Oil version?",
        )

    def test_markdown_emphasis_is_stripped(self) -> None:
        # The model should read the words, not the asterisks.
        self.assertEqual(
            question_asked_in("Shall I add the **Butter Pavbhaji**?"),
            "Shall I add the Butter Pavbhaji?",
        )

    def test_a_reply_that_carried_on_past_its_question_has_none(self) -> None:
        # "What sounds good right now? I can help with breakfast picks..." —
        # the question is not the thing being answered when the reply kept
        # talking after it.
        self.assertIsNone(
            question_asked_in("What sounds good? I can help with picks and budgets.")
        )

    def test_a_reply_that_asked_nothing_has_none(self) -> None:
        self.assertIsNone(question_asked_in("Here are a few options from the menu."))
        self.assertIsNone(question_asked_in(""))
        self.assertIsNone(question_asked_in(None))

    def test_a_read_backs_details_never_come_along(self) -> None:
        """The failure this is shaped to avoid.

        `_hold` records a SHORT question on purpose: a long read-back handed
        to the model as "the question" got mined for its contents, and a
        "yes" arrived carrying a delivery address which was read as a new
        instruction.

        Taking only the FINAL SENTENCE is what makes prose safe to use the
        same way — the question comes through and the paragraph in front of
        it does not.
        """

        asked = question_asked_in(
            "Your cart: 3 x Corn Fritters, 1 x Pad Thai, delivered to 42 Example "
            "Road Ahmedabad, for Hitesh on +919876543210, total 52.40, paid by "
            "card, arriving about 19:40 this evening. Shall I place it?"
        )
        self.assertEqual(asked, "Shall I place it?")
        for detail in ("Example Road", "919876543210", "52.40", "Corn Fritters"):
            self.assertNotIn(detail, asked)

    def test_a_question_too_long_to_be_one_is_refused(self) -> None:
        # No sentence ender to cut at, so the whole paragraph would arrive as
        # "the question". The cap is the backstop for exactly that.
        self.assertIsNone(
            question_asked_in(
                "Would you like the Butter version which comes with four soft pav "
                "and a rich creamy bhaji, or the Oil version which is lighter and "
                "a little sharper, or perhaps something else entirely from the "
                "rest of the menu that I have not mentioned yet?"
            )
        )


class APronounIsNotADishTests(unittest.TestCase):
    """    >>> do you have biryani
        Here is what we have: Hydrabadi Biryani, ... Which one would you like?
        >>> add one
        Your cart is empty at the moment.        <- after 33 seconds
    """

    def test_the_words_that_name_nothing(self) -> None:
        for word in ("one", "it", "that", "this", "them", "some"):
            with self.subTest(word=word):
                self.assertIn(word, _NOT_A_DISH_NAME)

    def test_the_placeholders_it_grew_out_of_are_still_there(self) -> None:
        # A model with nothing to report says so in the only vocabulary it
        # has; both spellings were already being dropped.
        self.assertIn("null", _NOT_A_DISH_NAME)
        self.assertIn("none", _NOT_A_DISH_NAME)

    def test_a_real_dish_is_not_in_it(self) -> None:
        for name in ("biryani", "pav", "bhel", "naan", "khaman"):
            with self.subTest(name=name):
                self.assertNotIn(name, _NOT_A_DISH_NAME)


class AReplyCannotDenyTheMenuItIsShowingTests(unittest.TestCase):
    """    >>> no
        We don't have anything on the menu — but I've got a few tasty options
        that might just hit the spot. What's your craving? 🍛
        • Dal Samosa — ₹240   • Plain Naan — ₹26   ...

    Six real dishes, under a sentence saying there are none. The model copied
    the shape of a worked example in the prompt ("We don't have sushi on the
    menu — but the Penne Arrabbiata...") onto a message that named nothing.
    """

    def setUp(self) -> None:
        self.some = [SimpleNamespace(name="Plain Naan")]

    def test_denying_the_menu_while_showing_it(self) -> None:
        self.assertTrue(
            rag._denies_the_whole_menu(
                "We don't have anything on the menu — but I've got a few options.",
                self.some,
            )
        )

    def test_denying_one_named_dish_is_fine(self) -> None:
        # The house style, and true: this is a fact about sushi.
        self.assertFalse(
            rag._denies_the_whole_menu(
                "We don't have sushi on the menu — but the Penne Arrabbiata is "
                "one of our bestsellers.",
                self.some,
            )
        )

    def test_nothing_shown_means_nothing_to_contradict(self) -> None:
        self.assertFalse(
            rag._denies_the_whole_menu("We don't have anything on the menu.", [])
        )


class PricesInTheRestaurantsOwnMoneyTests(unittest.TestCase):
    """The dishes listed under a WhatsApp answer used to carry a bare number.

        • Kaju Khoya (Yellow, Sweet) — 185.00
        • Oil Masala Khaman — 35.00

    A figure with no unit is read as whatever the reader expects.
    """

    def setUp(self) -> None:
        self.items = [
            SimpleNamespace(name="Oil Masala Khaman", price=35),
            SimpleNamespace(name="Kaju Khoya", price=185.5),
        ]

    def test_a_rupee_menu_reads_in_rupees(self) -> None:
        body = render_reply("Here you go:", self.items, "INR")
        self.assertIn("— ₹35", body)
        self.assertIn("— ₹185.50", body)

    def test_each_currency_keeps_its_own_symbol(self) -> None:
        for code, expected in (("CAD", "$35.00"), ("GBP", "£35.00"), ("EUR", "€35.00")):
            with self.subTest(code=code):
                self.assertIn(expected, render_reply("x", self.items, code))

    def test_no_currency_still_renders_a_price(self) -> None:
        self.assertIn("35", render_reply("x", self.items, None))

    def test_a_rupee_amount_gets_bolded_like_a_dollar_one(self) -> None:
        # `_MONEY_RE` only knew "$", so the one figure a customer acts on was
        # the one figure never emphasised — and INR is written without paise,
        # so the fractional part had to become optional too.
        self.assertIn("*₹35*", format_for_whatsapp(render_reply("x", self.items, "INR")))
        self.assertIn("*$35.00*", format_for_whatsapp(render_reply("x", self.items, "CAD")))


class NoHardcodedSymbolSurvivesTests(unittest.TestCase):
    """The shape of the bug, in the three files that write prices into text.

    Each of these had a literal "$" from when the platform served one
    restaurant in one country. A fourth added later is the same bug again.
    """

    def _prices_written_with_a_literal(self, module) -> list[str]:
        source = Path(module.__file__).read_text(encoding="utf-8")
        return [
            line.strip()
            for line in source.splitlines()
            if "${" in line and not line.lstrip().startswith("#")
        ]

    def test_the_reply_pipeline(self) -> None:
        self.assertEqual(self._prices_written_with_a_literal(rag), [])

    def test_the_ordering_loop(self) -> None:
        from app.services.ordering_agent import loop

        self.assertEqual(self._prices_written_with_a_literal(loop), [])

    def test_the_whatsapp_renderer(self) -> None:
        from app.services import whatsapp

        self.assertEqual(self._prices_written_with_a_literal(whatsapp), [])


if __name__ == "__main__":
    unittest.main()
