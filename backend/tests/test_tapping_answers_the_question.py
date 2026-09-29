"""A tapped button or list row is read as the words it stands for.

WhatsApp can send a question with tappable answers. Two reasons to use it
here, and the second is the one that matters:

1. Tapping "Pizza" beats typing it.
2. The yes/no turns are where reading the answer goes wrong. Measured, "2" in
   reply to "Take all 2 items off your order?" was read as a yes — a number
   that could only have meant the second line. A tap carries an id we wrote,
   so on those turns nothing is asked to interpret anything.

The design rule is that tapping adds NO new path. A tap arrives as exactly
the message a customer typing the same answer would have sent — "yes", or a
position — so every guard, reader and test that already covers typing covers
tapping too. Nothing that works by typing can break by tapping.

The id carries the answer, never the title: Meta truncates a row title at 24
characters, so "Iced Matcha Coconut Latte" comes back cut short and a
truncated dish name matches nothing. A position does not truncate.

Ten rows is Meta's cap and several of this menu's lists are longer — Bodakdev
has eleven sections and eleven pizzas — so the numbered text version stays the
answer for those. A tappable list improves a message that already worked; it
is never the only way to answer.
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

from app.services import whatsapp as wa
from app.tasks.whatsapp import buttons_for, rows_that_fit


def a_tap(kind: str, reply_id: str, title: str = "") -> dict:
    return {"type": kind, kind: {"id": reply_id, "title": title}}


def an_inbound(message: dict) -> dict:
    value = {
        "metadata": {"phone_number_id": "111"},
        "messages": [{"from": "919876500000", "id": "wamid.1", **message}],
    }
    return {"entry": [{"changes": [{"value": value}]}]}


class ATapIsReadAsWordsTests(unittest.TestCase):
    def test_a_button_says_what_its_id_says(self) -> None:
        self.assertEqual(wa.tapped_answer(a_tap("button_reply", "say:yes", "Check out")), "yes")
        self.assertEqual(wa.tapped_answer(a_tap("button_reply", "say:no", "Not yet")), "no")

    def test_a_row_says_its_position(self) -> None:
        # Which is what a customer typing "3" would have sent, and the list it
        # counts along is already written down.
        self.assertEqual(wa.tapped_answer(a_tap("list_reply", "pick:3", "Rice")), "3")

    def test_the_title_is_not_what_is_read(self) -> None:
        # A row title is truncated by Meta at 24 characters; the id is not.
        tap = a_tap("list_reply", "pick:2", "Iced Matcha Coconut Lat…")
        self.assertEqual(wa.tapped_answer(tap), "2")

    def test_an_id_that_is_not_ours_falls_back_to_the_title(self) -> None:
        # A template or a flow added later is still an answer, and reading it
        # beats dropping it.
        self.assertEqual(wa.tapped_answer(a_tap("button_reply", "other", "Track order")), "Track order")

    def test_a_reply_that_does_not_name_its_own_shape_is_still_found(self) -> None:
        odd = {"type": "nfm_reply", "list_reply": {"id": "pick:1", "title": "x"}}
        self.assertEqual(wa.tapped_answer(odd), "1")

    def test_nothing_readable_is_nothing(self) -> None:
        self.assertEqual(wa.tapped_answer(None), "")
        self.assertEqual(wa.tapped_answer({}), "")
        self.assertEqual(wa.tapped_answer({"type": "button_reply"}), "")


class TheWebhookAcceptsATapTests(unittest.TestCase):
    def test_a_tapped_reply_arrives_like_a_typed_one(self) -> None:
        found = wa.inbound_messages(an_inbound(
            {"type": "interactive", "interactive": a_tap("button_reply", "say:yes", "Check out")}
        ))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].text, "yes")
        self.assertEqual(found[0].from_number, "919876500000")

    def test_typed_messages_are_untouched(self) -> None:
        found = wa.inbound_messages(an_inbound({"type": "text", "text": {"body": "menu"}}))
        self.assertEqual([m.text for m in found], ["menu"])

    def test_a_tap_that_says_nothing_is_not_a_question(self) -> None:
        found = wa.inbound_messages(an_inbound({"type": "interactive", "interactive": {}}))
        self.assertEqual(found, [])

    def test_other_message_types_are_still_ignored(self) -> None:
        # Delivery receipts, reactions and media come through the same webhook.
        self.assertEqual(wa.inbound_messages(an_inbound({"type": "image"})), [])


class WhatGetsOfferedAsATapTests(unittest.TestCase):
    def test_a_yes_no_question_gets_two_buttons(self) -> None:
        self.assertEqual(
            buttons_for({"yes": "clear_cart"}),
            [("say:yes", "Yes, clear it"), ("say:no", "Keep it")],
        )

    def test_a_question_wanting_a_name_gets_none(self) -> None:
        # Two buttons cannot offer a dish, and pretending otherwise would put
        # the customer back where they started.
        self.assertEqual(buttons_for({"yes": "name_one"}), [])
        self.assertEqual(buttons_for({"yes": "time_on_day"}), [])
        self.assertEqual(buttons_for(None), [])
        self.assertEqual(buttons_for({}), [])

    def test_a_list_that_fits_is_offered_whole(self) -> None:
        rows = [("pick:1", "Small", "$14.99"), ("pick:2", "Large", "$24.49")]
        self.assertEqual(rows_that_fit(rows), rows)

    def test_a_list_too_long_for_meta_stays_as_text(self) -> None:
        # Eleven sections, eleven pizzas: both real, both over the cap. None
        # rather than the first ten, because stopping silently at ten of
        # eleven is a claim that the menu ends there.
        self.assertEqual(rows_that_fit([(f"pick:{n}", f"D{n}", "") for n in range(11)]), [])

    def test_a_list_of_one_is_not_a_list(self) -> None:
        self.assertEqual(rows_that_fit([("pick:1", "Only", "")]), [])
        self.assertEqual(rows_that_fit([]), [])


class ThePayloadMetaReceivesTests(unittest.TestCase):
    def sent(self, call) -> dict:
        with mock.patch.object(wa, "_send", return_value=True) as send:
            call()
        self.assertTrue(send.called, "nothing was sent")
        return send.call_args[0][1]

    def test_buttons_carry_their_ids(self) -> None:
        payload = self.sent(
            lambda: wa.send_buttons("91", "Ready?", [("say:yes", "Yes"), ("say:no", "No")])
        )
        self.assertEqual(payload["type"], "interactive")
        self.assertEqual(payload["interactive"]["type"], "button")
        ids = [b["reply"]["id"] for b in payload["interactive"]["action"]["buttons"]]
        self.assertEqual(ids, ["say:yes", "say:no"])

    def test_a_long_button_title_is_cut_to_fit(self) -> None:
        payload = self.sent(
            lambda: wa.send_buttons("91", "?", [("say:yes", "Yes, please go ahead and do that")])
        )
        title = payload["interactive"]["action"]["buttons"][0]["reply"]["title"]
        self.assertLessEqual(len(title), wa.BUTTON_TITLE_CHARS)

    def test_more_than_three_buttons_is_three(self) -> None:
        payload = self.sent(
            lambda: wa.send_buttons("91", "?", [(f"say:{n}", f"B{n}") for n in range(5)])
        )
        self.assertEqual(len(payload["interactive"]["action"]["buttons"]), wa.MOST_BUTTONS)

    def test_a_list_carries_its_rows(self) -> None:
        payload = self.sent(
            lambda: wa.send_list("91", "Which one?", [("pick:1", "Salads", ""), ("pick:2", "Curry", "")])
        )
        rows = payload["interactive"]["action"]["sections"][0]["rows"]
        self.assertEqual([r["id"] for r in rows], ["pick:1", "pick:2"])
        self.assertEqual([r["title"] for r in rows], ["Salads", "Curry"])
        # No description key at all rather than an empty one.
        self.assertNotIn("description", rows[0])

    def test_a_long_row_title_is_cut_to_fit(self) -> None:
        payload = self.sent(
            lambda: wa.send_list("91", "?", [("pick:1", "Iced Matcha Coconut Latte Grande", "")])
        )
        title = payload["interactive"]["action"]["sections"][0]["rows"][0]["title"]
        self.assertLessEqual(len(title), wa.ROW_TITLE_CHARS)

    def test_nothing_to_offer_degrades_to_words(self) -> None:
        # A caller never has to check first, and a question with no tappable
        # answers is still a question that gets asked.
        with mock.patch.object(wa, "send_text", return_value=True) as text:
            wa.send_buttons("91", "Ready?", [])
            wa.send_list("91", "Which one?", [])
        self.assertEqual(text.call_count, 2)


class TheRowsSayWhatTheTextSaidTests(unittest.TestCase):
    """Rows come from the PRINTED lines, which is what makes them true.

    Built from the draft instead, two things went wrong and both were
    measured: a stale choice attached seven topping rows to "There is nothing
    in your order yet", and every price vanished — the draft holds names and
    ids, and 'Small (8") — $14.99' only exists in the printed line.
    """

    def test_the_lines_become_rows_and_leave_the_question(self) -> None:
        body = "Here is our Pizza:\n1. Margherita - $11.99\n2. Farmhouse - $17.49\n\nWhich one would you like?"
        said, rows = wa.split_printed_list(body)
        self.assertEqual(said, "Here is our Pizza:\n\nWhich one would you like?")
        self.assertEqual(
            rows, [("pick:1", "Margherita", "$11.99"), ("pick:2", "Farmhouse", "$17.49")]
        )

    def test_a_size_keeps_its_price(self) -> None:
        # The money bug this app already fixed once, in the other direction: a
        # size chosen without its price is a Large bought at the Small's.
        _, rows = wa.split_printed_list(
            'Which size?\n1. Small (8") — $14.99\n2. Large (14") — $24.49'
        )
        self.assertEqual(rows[0], ("pick:1", 'Small (8")', "$14.99"))
        self.assertEqual(rows[1], ("pick:2", 'Large (14")', "$24.49"))

    def test_an_extra_keeps_its_plus(self) -> None:
        # "$1.00" beside a topping reads as its price, not as what it adds.
        _, rows = wa.split_printed_list("Which sauce?\n1. Tomato\n2. Green curry (+$1.00)")
        self.assertEqual(rows, [("pick:1", "Tomato", ""), ("pick:2", "Green curry", "+$1.00")])

    def test_the_invitation_to_type_a_number_comes_out_too(self) -> None:
        body = (
            "Here is what we serve:\n1. Salads\n2. Curry\n\n"
            "Which one would you like to see? Reply with the number or the name."
        )
        said, rows = wa.split_printed_list(body)
        self.assertNotIn("Reply with the number", said)
        self.assertIn("Which one would you like to see?", said)
        self.assertEqual(len(rows), 2)

    def test_a_message_with_no_list_offers_no_rows(self) -> None:
        # The measured failure: a stale choice put topping rows under this.
        body = "There is nothing in your order yet. Tell me what you would like and I will add it."
        self.assertEqual(wa.split_printed_list(body), (body, []))

    def test_one_numbered_line_is_not_a_list(self) -> None:
        body = "Your order:\n1. Margherita - $11.99\n\nReady to check out?"
        self.assertEqual(wa.split_printed_list(body), (body, []))

    def test_a_body_that_is_only_a_list_keeps_its_words(self) -> None:
        # Stripping everything would leave Meta no body, which it refuses and
        # the customer reads as silence.
        body = "1. Salads\n2. Curry\n3. Rice"
        self.assertEqual(wa.split_printed_list(body), (body, []))


if __name__ == "__main__":
    unittest.main()
