"""The contact details an order needs, gathered a sentence at a time.

A signed-in customer has most of this on file. A customer on WhatsApp has a
verified phone number and nothing else, and gives the rest over several
turns — so it accumulates in a draft until it is complete.

The rule these tests exist to hold: the draft reports WHICH details are
held, never what they are. A home address belongs on the order and in the
kitchen ticket; putting it in a prompt would send it to the model again on
every later turn of the conversation.
"""

from __future__ import annotations

import dataclasses
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.ordering_agent import order_draft
from app.schemas.suggestions import CartLinePayload
from app.services.ordering_agent.tools import (
    CartLineArgs,
    OrderingScope,
    OrderRequirementsArgs,
    SaveOrderDetailsArgs,
    TOOLS,
)


class DraftStoreTests(unittest.TestCase):
    def test_a_fresh_draft_wants_everything(self) -> None:
        self.assertEqual(
            order_draft.OrderDraft().missing_fields(),
            ["fulfillment_type", "contact_name", "contact_phone", "contact_email", "delivery_address"],
        )

    def test_pickup_does_not_ask_for_an_address(self) -> None:
        # Asking is how a customer ends up typing their home address to a
        # restaurant they are walking to.
        draft = order_draft.OrderDraft(fulfillment_type="PICKUP")
        self.assertNotIn("delivery_address", draft.missing_fields())

    def test_delivery_asks_for_one(self) -> None:
        draft = order_draft.OrderDraft(fulfillment_type="DELIVERY")
        self.assertIn("delivery_address", draft.missing_fields())

    def test_each_bad_value_is_refused_on_its_own(self) -> None:
        # One bad field must not throw away three good ones: the customer is
        # asked again for that field, not for the whole set.
        draft, problems = order_draft.remember(
            order_draft.OrderDraft(),
            contact_name="Hitesh",
            contact_email="not-an-email",
            contact_phone="12",
            fulfillment_type="PICKUP",
        )
        self.assertEqual(draft.contact_name, "Hitesh")
        self.assertEqual(draft.fulfillment_type, "PICKUP")
        self.assertIsNone(draft.contact_email)
        self.assertIsNone(draft.contact_phone)
        self.assertEqual(len(problems), 2)

    def test_a_phone_is_stored_the_way_the_order_endpoint_stores_it(self) -> None:
        # Two normalisations disagreeing is how a draft becomes an order that
        # will not save.
        draft, problems = order_draft.remember(order_draft.OrderDraft(), contact_phone="(415) 555-0132")
        self.assertEqual(problems, [])
        self.assertTrue(draft.contact_phone)
        self.assertNotIn("(", draft.contact_phone)

    def test_an_unknown_fulfillment_is_refused(self) -> None:
        _, problems = order_draft.remember(order_draft.OrderDraft(), fulfillment_type="TELEPORT")
        self.assertEqual(len(problems), 1)

    def test_the_account_fills_what_it_knows_without_overwriting(self) -> None:
        # What they typed tonight wins: the reason to type an address is
        # usually that the one on file is not where they are.
        customer = SimpleNamespace(
            full_name="Hitesh K", phone_number="+919876543210",
            email="h@example.com", default_address="12 Old Street",
        )
        draft = order_draft.seed_from_profile(
            order_draft.OrderDraft(delivery_address="tonight's address, flat 4"), customer
        )
        self.assertEqual(draft.contact_name, "Hitesh K")
        self.assertEqual(draft.delivery_address, "tonight's address, flat 4")

    def test_a_guest_is_seeded_with_nothing(self) -> None:
        draft = order_draft.seed_from_profile(order_draft.OrderDraft(), None)
        self.assertEqual(draft.known_fields(), [])


class DetailToolTests(unittest.TestCase):
    def setUp(self) -> None:
        store = {}

        def fake_get(key):
            return store.get(key)

        def fake_set(key, value, ttl_seconds=None):
            store[key] = value
            return True

        def fake_delete(*keys):
            return sum(bool(store.pop(key, None)) for key in keys)

        self.patches = [
            patch.object(order_draft, "cache_get_json", fake_get),
            patch.object(order_draft, "cache_set_json", fake_set),
            patch.object(order_draft, "cache_delete", fake_delete),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        self.scope = OrderingScope(
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
        )

    def requirements(self, scope=None, lines=None):
        # A cart by default: an order needs food before it needs an address,
        # and every one of these tests is about an order that has some.
        if lines is None:
            lines = [CartLineArgs(menu_item_id=uuid.uuid4(), quantity=1)]
        return TOOLS["order_requirements"].handler(
            None, scope or self.scope, OrderRequirementsArgs(lines=lines)
        )

    def save(self, scope=None, **kwargs):
        return TOOLS["save_order_details"].handler(
            None, scope or self.scope, SaveOrderDetailsArgs(**kwargs)
        )

    def test_details_survive_from_one_turn_to_the_next(self) -> None:
        # The point of the draft: a customer gives their name, then two turns
        # later their address, and both are still there.
        self.save(contact_name="Hitesh")
        self.save(fulfillment_type="DELIVERY")
        result = self.save(delivery_address="42 Example Road, Ahmedabad")
        self.assertIn("contact_name", result["have"])
        self.assertIn("delivery_address", result["have"])
        self.assertEqual(self.requirements()["have"], result["have"])

    def test_the_values_never_leave_the_store(self) -> None:
        # The rule this whole design turns on: the model learns that the
        # address is held, not what it is.
        self.save(contact_name="Hitesh", delivery_address="42 Example Road, Ahmedabad")
        reported = repr(self.requirements()) + repr(self.save(contact_name="Hitesh"))
        self.assertNotIn("42 Example Road", reported)
        self.assertNotIn("Hitesh", reported)

    def test_a_refusal_names_the_problem_without_losing_the_rest(self) -> None:
        result = self.save(contact_name="Hitesh", contact_email="nope")
        self.assertIn("contact_name", result["have"])
        self.assertEqual(len(result["problems"]), 1)
        self.assertIn("contact_email", result["missing"])

    def test_a_guest_is_never_ready_to_place_however_complete_the_draft(self) -> None:
        # Identity is the account, not the details typed in. A guest with a
        # perfect address still cannot have an order placed for them.
        self.save(
            contact_name="Hitesh", contact_phone="+919876543210",
            contact_email="h@example.com", delivery_address="42 Example Road",
            fulfillment_type="DELIVERY",
        )
        self.assertFalse(self.requirements()["ready_to_place"])
        self.assertFalse(self.requirements()["identified"])

    def test_a_signed_in_customer_with_everything_is_ready(self) -> None:
        # The scope is frozen — it is built by the caller from the session,
        # never edited underneath a running turn.
        scope = dataclasses.replace(
            self.scope,
            customer=SimpleNamespace(
                full_name="Hitesh K", phone_number="+919876543210",
                email="h@example.com", default_address="12 Old Street, Ahmedabad",
            ),
        )
        self.save(scope, fulfillment_type="DELIVERY")
        result = self.requirements(scope)
        self.assertEqual(result["missing"], [])
        self.assertTrue(result["ready_to_place"])

    def test_without_a_conversation_there_is_nowhere_to_keep_a_draft(self) -> None:
        scope = dataclasses.replace(self.scope, session_id=None)
        self.assertEqual(self.requirements(scope)["outcome"], "no_session")
        self.assertEqual(self.save(scope, contact_name="x")["outcome"], "no_session")


if __name__ == "__main__":
    unittest.main()


class PlaceOrderTests(DetailToolTests):
    """Placing is gated on identity and on a complete draft.

    The order is created unpaid on purpose: that is what makes it safe to do
    from a sentence rather than a button, since nothing is charged until the
    customer opens the payment link.
    """

    def place(self, scope=None, lines=None):
        from app.services.ordering_agent.tools import CartLineArgs, PlaceOrderArgs

        args = PlaceOrderArgs(
            lines=lines
            if lines is not None
            else [CartLineArgs(menu_item_id=uuid.uuid4(), quantity=1)]
        )
        return TOOLS["place_order"].handler(None, scope or self.scope, args)

    def test_an_empty_cart_places_nothing(self) -> None:
        self.assertEqual(self.place(lines=[])["outcome"], "empty_cart")

    def test_an_incomplete_draft_names_what_is_missing_and_nothing_else(self) -> None:
        self.save(contact_name="Hitesh", fulfillment_type="DELIVERY")
        result = self.place()
        self.assertEqual(result["outcome"], "needs_details")
        self.assertIn("delivery_address", result["missing"])
        self.assertNotIn("Hitesh", repr(result), "names what is missing, never what is held")

    def test_a_guest_with_a_complete_draft_still_cannot_place(self) -> None:
        # Identity is the account. Details typed into a chat are contact
        # details, not proof of who is ordering.
        self.save(
            contact_name="Hitesh", contact_phone="+919876543210",
            contact_email="h@example.com", delivery_address="42 Example Road",
            fulfillment_type="DELIVERY",
        )
        self.assertEqual(self.place()["outcome"], "not_identified")


class ActionSpeaksTests(unittest.TestCase):
    """An action that happened can always say so.

    Live on WhatsApp: a turn added three corn fritters and had nothing to
    say, so the reply pipeline filled the silence — and what it says about a
    message it cannot classify is "that one's outside my kitchen".
    """

    def record(self, kind: str, **over):
        from app.services.ordering_agent.planner import ToolCallRecord

        result = {
            "outcome": "action",
            "action": {"kind": kind, "status": "applied", "menu_item_id": str(uuid.uuid4())},
            "name": "Corn Fritters",
            "quantity": 3,
        }
        result.update(over)
        return ToolCallRecord(tool="add_to_cart", args={}, result=result)

    def test_an_add_says_what_went_in(self) -> None:
        from app.services.ordering_agent.loop import describe_applied

        said = describe_applied([self.record("add")])
        self.assertIn("3 x Corn Fritters", said)

    def test_a_proposal_says_nothing_since_nothing_happened(self) -> None:
        from app.services.ordering_agent.loop import describe_applied

        record = self.record("add")
        record.result["action"]["status"] = "proposed"
        self.assertIsNone(describe_applied([record]))

    def test_a_turn_that_did_nothing_says_nothing(self) -> None:
        from app.services.ordering_agent.loop import describe_applied

        self.assertIsNone(describe_applied([]))


class AddressImpliesDeliveryTests(unittest.TestCase):
    def test_an_address_settles_the_question_nobody_needs_asked(self) -> None:
        # Live on WhatsApp: "deliver to 42 Example Road" was answered with
        # "do you want delivery or pickup?".
        draft, problems = order_draft.remember(
            order_draft.OrderDraft(), delivery_address="42 Example Road, Ahmedabad"
        )
        self.assertEqual(problems, [])
        self.assertEqual(draft.fulfillment_type, "DELIVERY")

    def test_a_stated_pickup_is_not_overridden_by_an_address(self) -> None:
        draft, _ = order_draft.remember(
            order_draft.OrderDraft(),
            fulfillment_type="PICKUP",
            delivery_address="42 Example Road, Ahmedabad",
        )
        self.assertEqual(draft.fulfillment_type, "PICKUP")


class SettledByTheRowsTests(unittest.TestCase):
    """A result that decides the turn ends it; no model round is spent after."""

    def test_a_requirements_result_with_gaps_ends_the_turn_asking_for_them(self) -> None:
        # Live: order_requirements ran, then ran again (2.5s) before the
        # read-back said what was missing.
        import dataclasses
        from unittest.mock import patch

        from tests.test_ordering_agent_loop import SCOPE, ScriptedClock, ScriptedGenerate, _tool_call
        from app.services.ordering_agent import loop, order_draft

        scope = dataclasses.replace(SCOPE, session_id=uuid.uuid4(), verified_phone="+919000000001")
        generate = ScriptedGenerate(
            _tool_call("order_requirements", {}),
            _tool_call("order_requirements", {}),  # never reached
        )
        with patch.object(order_draft, "load", return_value=order_draft.OrderDraft()),              patch.object(order_draft, "save", lambda *a, **k: None):
            outcome = loop.run_turn(
                db=None, scope=scope, message="checkout",
                # Something to order: an empty cart collects nothing now.
                cart=[CartLinePayload(menu_item_id=uuid.uuid4(), quantity=1)],
                generate=generate,
                clock=ScriptedClock(0.0), max_rounds=5, budget_seconds=1000.0,
            )
        self.assertEqual(len(generate.prompts), 1, "one model round: the result settled the turn")
        self.assertIn("still need", outcome.answer or "")
        self.assertEqual(outcome.answer_about, "order")


class PlaceFailureIsSpokenTests(unittest.TestCase):
    """Every way place_order can fail is said, from its own result."""

    def record(self, **result):
        from app.services.ordering_agent.planner import ToolCallRecord

        return ToolCallRecord(tool="place_order", args={}, result=result)

    def test_an_empty_cart_is_said(self) -> None:
        # Live on a real phone: empty_cart, unspoken, "That is everything I
        # need" after YES, Yes and yes.
        from app.services.ordering_agent.loop import describe_place_failure

        self.assertIn("nothing in your order", describe_place_failure([self.record(outcome="empty_cart")]))

    def test_a_taken_email_asks_for_another(self) -> None:
        from app.services.ordering_agent.loop import describe_place_failure

        self.assertIn("different email", describe_place_failure([self.record(outcome="email_in_use")]))

    def test_a_refusal_carries_the_backends_own_reason(self) -> None:
        from app.services.ordering_agent.loop import describe_place_failure

        said = describe_place_failure([self.record(outcome="refused", reason="Minimum order amount is 16.00")])
        self.assertIn("Minimum order amount is 16.00", said)

    def test_a_placement_that_raised_is_not_silent(self) -> None:
        # Live: the schema refused the phone number on every attempt and the
        # customer read "That is everything I need to place your order" with
        # no order behind it, six times.
        from app.services.ordering_agent.loop import describe_place_failure
        from app.services.ordering_agent.planner import ToolCallRecord

        said = describe_place_failure(
            [ToolCallRecord(tool="place_order", args={}, error="tool_error: 1 validation error")]
        )
        self.assertIn("could not place", said)

    def test_a_placed_order_is_not_a_failure(self) -> None:
        from app.services.ordering_agent.loop import describe_place_failure

        self.assertIsNone(describe_place_failure([self.record(outcome="placed", order_id="x")]))


class DetailsReadFirstTests(unittest.TestCase):
    """A mid-checkout message is read for details before any planning."""

    def test_details_in_the_message_are_kept_without_a_planner_round(self) -> None:
        # Live: the planner answered "your details have been saved" and
        # saved nothing. The narrow reading saves them; the turn settles on
        # what is still missing with no planner round spent.
        import dataclasses
        from unittest.mock import patch

        from tests.test_ordering_agent_loop import SCOPE, ScriptedClock
        from app.services.ordering_agent import loop, order_draft

        scope = dataclasses.replace(SCOPE, session_id=uuid.uuid4(), verified_phone="+919000000001")
        store = {"draft": order_draft.OrderDraft(collecting=True)}
        calls = []

        def generate(prompt, *a, **k):
            calls.append(prompt)
            if "Fields:" in prompt:
                return '{"contact_name": "Hitesh", "contact_email": "h@example.com", "delivery_address": null, "fulfillment_type": null}'
            raise AssertionError("no planner round expected")

        with patch.object(order_draft, "load", lambda sid: store["draft"]), \
             patch.object(order_draft, "save", lambda sid, d: store.__setitem__("draft", d)):
            outcome = loop.run_turn(
                db=None, scope=scope, message="I'm Hitesh, h@example.com",
                cart=[__import__("app.schemas.suggestions", fromlist=["CartLinePayload"]).CartLinePayload(menu_item_id=uuid.uuid4(), quantity=1)],
                generate=generate, clock=ScriptedClock(0.0), max_rounds=5, budget_seconds=1000.0,
            )
        self.assertEqual(len(calls), 1, "one narrow reading, no planner round")
        self.assertEqual(store["draft"].contact_name, "Hitesh")
        self.assertEqual(store["draft"].contact_email, "h@example.com")
        self.assertIn("still need", outcome.answer or "")


class AnOrderNeedsFoodTests(unittest.TestCase):
    """Checkout details are not collected for an empty cart."""

    def test_an_empty_cart_collects_nothing(self) -> None:
        # Live, to a real customer: asked for a name, an email and a
        # delivery address while their pizza had never been added, then
        # told the total was Rs 150.
        import uuid as _uuid
        from types import SimpleNamespace

        from app.services.ordering_agent.tools import TOOLS, OrderRequirementsArgs

        scope = SimpleNamespace(
            session_id=_uuid.uuid4(), customer=None, verified_phone=None,
            restaurant_id=_uuid.uuid4(), restaurant_location_id=_uuid.uuid4(),
        )
        result = TOOLS["order_requirements"].handler(None, scope, OrderRequirementsArgs(lines=[]))
        self.assertEqual(result["outcome"], "empty_cart")
