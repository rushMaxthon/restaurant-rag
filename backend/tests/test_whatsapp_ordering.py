"""Ordering over WhatsApp, where there is no browser and no sign-in.

The agent is the same, the tools are the same, the rules are the same. Two
things a browser normally supplies have to come from somewhere else: the
cart, which lives against the conversation instead of in localStorage, and
the customer's identity, which is the phone number Meta verified before it
delivered the message.
"""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.main import app  # noqa: F401 - imported first to settle import order
from app.schemas.suggestions import CartLinePayload
from app.services.ordering_agent import session_cart
from app.tasks import whatsapp as wa


def action(kind: str, **over):
    base = {
        "kind": kind,
        "status": "applied",
        "reason": "named",
        "menu_item_id": str(uuid.uuid4()),
        "menu_item_size_id": None,
        "selected_option_ids": [],
        "quantity": 1,
    }
    base.update(over)
    return base


class SessionCartTests(unittest.TestCase):
    """The cart for a customer with nowhere to keep one."""

    def test_the_same_dish_twice_is_one_line_with_a_bigger_number(self) -> None:
        # The web store merges; a cart that disagrees across channels is a
        # bug waiting for a customer to find.
        dish = str(uuid.uuid4())
        cart, _ = session_cart.apply_actions([], [action("add", menu_item_id=dish, quantity=2)])
        cart, _ = session_cart.apply_actions(cart, [action("add", menu_item_id=dish, quantity=1)])
        self.assertEqual(len(cart), 1)
        self.assertEqual(cart[0].quantity, 3)

    def test_the_same_dish_in_another_size_is_its_own_line(self) -> None:
        dish, size = str(uuid.uuid4()), str(uuid.uuid4())
        cart, _ = session_cart.apply_actions([], [action("add", menu_item_id=dish)])
        cart, _ = session_cart.apply_actions(
            cart, [action("add", menu_item_id=dish, menu_item_size_id=size)]
        )
        self.assertEqual(len(cart), 2)

    def test_set_quantity_is_the_final_count_not_a_delta(self) -> None:
        dish = str(uuid.uuid4())
        cart, _ = session_cart.apply_actions([], [action("add", menu_item_id=dish, quantity=2)])
        cart, _ = session_cart.apply_actions(
            cart, [action("set_quantity", menu_item_id=dish, quantity=5)]
        )
        self.assertEqual(cart[0].quantity, 5)

    def test_a_removal_takes_the_dish_out(self) -> None:
        dish = str(uuid.uuid4())
        cart, _ = session_cart.apply_actions([], [action("add", menu_item_id=dish)])
        cart, _ = session_cart.apply_actions(cart, [action("remove", menu_item_id=dish)])
        self.assertEqual(cart, [])

    def test_a_clear_is_never_carried_out_however_it_is_labelled(self) -> None:
        # Emptying somebody's cart is the customer's decision, and a status
        # saying otherwise is a drifted shape, not an instruction.
        cart = [CartLinePayload(menu_item_id=uuid.uuid4(), quantity=1)]
        after, proposed = session_cart.apply_actions(cart, [action("clear", status="applied")])
        self.assertEqual(len(after), 1)
        self.assertEqual(len(proposed), 1)

    def test_anything_not_marked_applied_is_a_question_not_an_instruction(self) -> None:
        for status in ("proposed", None, "weird"):
            _, proposed = session_cart.apply_actions([], [action("add", status=status)])
            self.assertEqual(len(proposed), 1, status)


class ReplyCompositionTests(unittest.TestCase):
    """What actually gets sent back to the phone."""

    def answer(self, **over):
        base = {
            "reply": "Our Pad Thai is a favourite.",
            "suggestions": [],
            "agent_reply": None,
            "agent_asks": False,
            "order_ready": False,
            "placed_order": None,
        }
        base.update(over)
        return SimpleNamespace(**base)

    def test_a_menu_answer_is_the_pipelines(self) -> None:
        self.assertIn("Pad Thai", wa._compose_reply(self.answer(), []))

    def test_the_agent_wins_when_it_owns_the_turn(self) -> None:
        # The pipeline has no cart; asked about one it searches the menu for
        # a dish called "cart".
        body = wa._compose_reply(
            self.answer(
                agent_asks=True, agent_reply="You have 2 x Corn Fritters. Subtotal $16.98."
            ),
            [],
        )
        self.assertIn("Corn Fritters", body)
        self.assertNotIn("Pad Thai", body)

    def test_a_payment_link_goes_on_its_own_line_untouched(self) -> None:
        # A link a phone cannot turn into something tappable is an order the
        # customer cannot pay for.
        url = "https://checkout.stripe.com/c/pay/cs_test_abc#fragment"
        body = wa._compose_reply(
            self.answer(
                agent_asks=True,
                agent_reply="Your order is placed.",
                placed_order={"payment_url": url},
            ),
            [],
        )
        self.assertIn(url, body)
        self.assertIn("\n" + url, body, "nothing wrapped around it")

    def test_a_ready_but_unplaced_order_makes_no_promise_about_the_next_message(self) -> None:
        # Ready orders are placed on the turn the details land. Ready and
        # not placed means it was tried and could not be; the agent's line
        # says why, and "reply YES" was a promise the next message broke.
        body = wa._compose_reply(
            self.answer(
                agent_asks=True, agent_reply="There is nothing in your order yet.", order_ready=True
            ),
            [],
        )
        self.assertNotIn("YES", body)
        self.assertIn("nothing in your order", body)

    def test_a_placed_order_does_not_also_ask_for_confirmation(self) -> None:
        body = wa._compose_reply(
            self.answer(order_ready=True, placed_order={"payment_url": "https://example.test/pay"}),
            [],
        )
        self.assertNotIn("YES", body)


class TaskWiringTests(unittest.TestCase):
    def test_a_placed_order_empties_the_stored_cart(self) -> None:
        # The items are on the order now; a cart outliving it is how somebody
        # orders the same thing twice.
        stored: dict = {}
        answer = SimpleNamespace(
            reply="done",
            suggestions=[],
            agent_reply="Your order is placed.",
            agent_asks=True,
            order_ready=False,
            placed_order={"payment_url": "https://example.test/pay"},
            cart_actions=[],
        )
        with patch.object(wa.settings, "whatsapp_enabled", True), patch.object(
            wa, "handle_chat_message", return_value=answer
        ), patch.object(wa, "send_text", return_value=True), patch.object(
            wa.session_cart, "load", return_value=[CartLinePayload(menu_item_id=uuid.uuid4(), quantity=1)]
        ), patch.object(
            wa.session_cart, "save", lambda sid, lines: stored.__setitem__("saved", lines)
        ), patch.object(
            wa.session_cart, "clear", lambda sid: stored.__setitem__("cleared", True)
        ):
            result = wa.answer_whatsapp_message.__wrapped__(
                from_number="+919876543210", text="yes"
            )
        self.assertEqual(result["status"], "sent")
        self.assertTrue(stored.get("cleared"))

    def test_the_verified_number_reaches_the_turn(self) -> None:
        # It is the whole basis on which an order can be placed here.
        seen: dict = {}

        def fake_turn(db, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                reply="hi",
                suggestions=[],
                agent_reply=None,
                agent_asks=False,
                order_ready=False,
                placed_order=None,
                cart_actions=[],
            )

        with patch.object(wa.settings, "whatsapp_enabled", True), patch.object(
            wa, "handle_chat_message", fake_turn
        ), patch.object(wa, "send_text", return_value=True), patch.object(
            wa.session_cart, "load", return_value=[]
        ):
            wa.answer_whatsapp_message.__wrapped__(from_number="+919876543210", text="hello")
        self.assertEqual(seen.get("verified_phone"), "+919876543210")


if __name__ == "__main__":
    unittest.main()


class SuggestionNoiseTests(ReplyCompositionTests):
    def test_dishes_are_not_listed_under_a_cart_answer(self) -> None:
        # Live: "what's in my cart?" came back with the subtotal and then
        # three unrelated dishes, which is a second conversation nobody
        # started. The web dropped the same list for the same reason.
        body = wa._compose_reply(
            self.answer(
                agent_asks=True,
                agent_reply="You have 3 x Corn Fritters - $25.47.",
                suggestions=[SimpleNamespace(name="Red Curry Tofu", price="14.64")],
            ),
            [],
        )
        self.assertIn("Corn Fritters", body)
        self.assertNotIn("Red Curry Tofu", body)

    def test_dishes_still_go_under_a_menu_answer(self) -> None:
        body = wa._compose_reply(
            self.answer(suggestions=[SimpleNamespace(name="Red Curry Tofu", price="14.64")]), []
        )
        self.assertIn("Red Curry Tofu", body)


class WaIdShapeTests(unittest.TestCase):
    """The shape Meta actually delivers, which is not the shape we tested."""

    def test_a_wa_id_becomes_a_number_an_order_can_carry(self) -> None:
        # Live: '916353100362' reached OrderCreateRequest and was refused as
        # a malformed 10-digit Canadian number. Every test until now passed
        # a number that already had its plus.
        from app.schemas.order import OrderCreateRequest

        self.assertEqual(wa.e164("916353100362"), "+916353100362")
        self.assertEqual(
            OrderCreateRequest.normalize_contact_phone(wa.e164("916353100362")),
            "+916353100362",
        )

    def test_a_number_that_already_has_its_plus_is_unchanged(self) -> None:
        self.assertEqual(wa.e164("+916353100362"), "+916353100362")

    def test_nothing_in_means_nothing_out(self) -> None:
        self.assertEqual(wa.e164(""), "")

    def test_the_turn_is_given_the_converted_number(self) -> None:
        seen: dict = {}

        def fake_turn(db, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                reply="hi", suggestions=[], agent_reply=None, agent_asks=False,
                order_ready=False, placed_order=None, cart_actions=[],
            )

        with patch.object(wa.settings, "whatsapp_enabled", True), patch.object(
            wa, "handle_chat_message", fake_turn
        ), patch.object(wa, "send_text", return_value=True), patch.object(
            wa.session_cart, "load", return_value=[]
        ):
            wa.answer_whatsapp_message.__wrapped__(from_number="916353100362", text="hello")
        self.assertEqual(seen.get("verified_phone"), "+916353100362")


class TypingIndicatorTests(unittest.TestCase):
    """The blue ticks and the bubble, while the agent thinks.

    A turn takes four to eight seconds. Without this the customer's screen
    shows nothing — not even a read receipt — and a message sent twice
    starts a second turn on a conversation still finishing its first.
    """

    def test_it_marks_read_and_asks_for_the_bubble_in_one_call(self) -> None:
        from unittest.mock import patch

        from app.services import whatsapp as service

        posted: dict = {}

        class Response:
            status_code = 200
            text = ""

        def fake_post(url, **kwargs):
            posted["url"] = url
            posted["json"] = kwargs["json"]
            return Response()

        with patch.object(service.settings, "whatsapp_access_token", "t"), patch.object(
            service.settings, "whatsapp_phone_number_id", "123"
        ), patch.object(service.httpx, "post", fake_post):
            self.assertTrue(service.show_typing("wamid.TEST"))

        self.assertEqual(posted["json"]["status"], "read")
        self.assertEqual(posted["json"]["message_id"], "wamid.TEST")
        self.assertEqual(posted["json"]["typing_indicator"], {"type": "text"})

    def test_no_message_id_means_no_call(self) -> None:
        from unittest.mock import patch

        from app.services import whatsapp as service

        def explode(*a, **k):
            raise AssertionError("should not be called")

        with patch.object(service.httpx, "post", explode):
            self.assertFalse(service.show_typing(""))

    def test_a_refusal_never_reaches_the_customer(self) -> None:
        # A bubble is a courtesy; the answer behind it is not.
        from unittest.mock import patch

        from app.services import whatsapp as service

        with patch.object(service.settings, "whatsapp_access_token", "t"), patch.object(
            service.settings, "whatsapp_phone_number_id", "123"
        ), patch.object(service.httpx, "post", side_effect=service.httpx.ConnectError("down")):
            self.assertFalse(service.show_typing("wamid.TEST"))

    def test_the_turn_shows_it_before_doing_the_work(self) -> None:
        from unittest.mock import patch

        order: list = []

        def fake_typing(message_id):
            order.append(("typing", message_id))
            return True

        def fake_turn(db, **kwargs):
            order.append(("worked", None))
            return SimpleNamespace(
                reply="hi", suggestions=[], agent_reply=None, agent_asks=False,
                order_ready=False, placed_order=None, cart_actions=[],
            )

        with patch.object(wa.settings, "whatsapp_enabled", True), patch.object(
            wa, "show_typing", fake_typing
        ), patch.object(wa, "handle_chat_message", fake_turn), patch.object(
            wa, "send_text", return_value=True
        ), patch.object(wa.session_cart, "load", return_value=[]):
            wa.answer_whatsapp_message.__wrapped__(
                from_number="916353100362", text="hello", message_id="wamid.ABC"
            )

        self.assertEqual(order, [("typing", "wamid.ABC"), ("worked", None)])
