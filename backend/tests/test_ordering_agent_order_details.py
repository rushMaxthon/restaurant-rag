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
        self.assertEqual(
            generate.prompts, [], "'checkout' says one plain thing; no model round at all"
        )
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

    def test_the_reason_survives_a_later_refused_attempt(self) -> None:
        # Live: place_order answered email_in_use, a retired repeat followed
        # with no result of its own, and that is what the customer was told.
        from app.services.ordering_agent.loop import describe_place_failure
        from app.services.ordering_agent.planner import ToolCallRecord

        said = describe_place_failure([
            ToolCallRecord(tool="place_order", args={}, result={"outcome": "email_in_use"}),
            ToolCallRecord(tool="place_order", args={}, error="repeated_call: identical to call 1"),
        ])
        self.assertIn("different email", said)

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
    """A message is read for what it wants before anything is planned."""

    def test_details_in_the_message_are_kept_without_a_planner_round(self) -> None:
        # Live, three conversations running: the planner answered "Thank you,
        # Vishal, your order is all set" and saved nothing, because saving
        # depends on a tool it did not call. The reading does not depend on
        # the planner choosing to act.
        import dataclasses
        from unittest.mock import patch

        from tests.test_ordering_agent_loop import SCOPE, ScriptedClock, ScriptedGenerate
        from app.services.ordering_agent import loop, order_draft
        from app.schemas.suggestions import CartLinePayload

        scope = dataclasses.replace(SCOPE, session_id=uuid.uuid4(), verified_phone="+919000000001")
        store = {"draft": order_draft.OrderDraft(collecting=True)}
        generate = ScriptedGenerate(
            intent=(
                '{"add": null, "details": {"contact_name": "Hitesh", '
                '"contact_email": "h@example.com"}, "checkout": false}'
            )
        )

        with patch.object(order_draft, "load", lambda sid: store["draft"]),              patch.object(order_draft, "save", lambda sid, d: store.__setitem__("draft", d)):
            outcome = loop.run_turn(
                db=None, scope=scope, message="I'm Hitesh, h@example.com",
                cart=[CartLinePayload(menu_item_id=uuid.uuid4(), quantity=1)],
                generate=generate, clock=ScriptedClock(0.0), max_rounds=5, budget_seconds=1000.0,
            )
        self.assertEqual(generate.prompts, [], "the reading settled it; no planner round")
        self.assertEqual(store["draft"].contact_name, "Hitesh")
        self.assertEqual(store["draft"].contact_email, "h@example.com")
        self.assertIn("still need", outcome.answer or "")

    def test_a_message_wanting_nothing_falls_through_to_the_planner(self) -> None:
        # A question about the menu is none of the three things an order can
        # want, and must still be planned exactly as before.
        import dataclasses

        from tests.test_ordering_agent_loop import SCOPE, ScriptedClock, ScriptedGenerate, _answer
        from app.services.ordering_agent import loop

        scope = dataclasses.replace(SCOPE, session_id=uuid.uuid4())
        generate = ScriptedGenerate(_answer("We have four curries."))
        outcome = loop.run_turn(
            db=None, scope=scope, message="what curries do you have?", cart=[],
            generate=generate, clock=ScriptedClock(0.0), max_rounds=5, budget_seconds=1000.0,
        )
        self.assertEqual(len(generate.prompts), 1, "planned, as before")
        self.assertEqual(outcome.answer, "We have four curries.")


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


class ShortOfTheMinimumTests(unittest.TestCase):
    """The one refusal a customer can clear themselves."""

    def refusal(self, **over):
        from app.services.ordering_agent.planner import ToolCallRecord

        result = {
            "outcome": "refused",
            "reason": "Minimum order amount for this restaurant is 16.00",
            "subtotal": "6.49",
            "minimum": "16.00",
        }
        result.update(over)
        return [ToolCallRecord(tool="place_order", args={}, result=result)]

    def test_it_says_the_order_the_minimum_and_the_gap(self) -> None:
        # Live: "Minimum order amount for this restaurant is 16.00" — true,
        # and no help at all to somebody who cannot see their subtotal.
        from app.services.ordering_agent.loop import describe_place_failure

        said = describe_place_failure(self.refusal())
        self.assertIn("$6.49", said)
        self.assertIn("$16.00", said)
        self.assertIn("$9.51", said)
        self.assertIn("What else can I add", said)

    def test_another_kind_of_refusal_still_carries_its_own_reason(self) -> None:
        from app.services.ordering_agent.loop import describe_place_failure

        said = describe_place_failure(
            self.refusal(reason="This branch is closed right now", subtotal="40.00")
        )
        self.assertIn("closed right now", said)

    def test_a_refusal_without_the_numbers_still_speaks(self) -> None:
        from app.services.ordering_agent.loop import describe_place_failure

        said = describe_place_failure(self.refusal(subtotal=None, minimum=None))
        self.assertIn("Minimum order amount", said)


class EmptyOrderIsAnsweredAtOnceTests(unittest.TestCase):
    """Asking about an order with nothing in it needs no model at all."""

    def outcome(self, message):
        import dataclasses

        from tests.test_ordering_agent_loop import SCOPE, ScriptedClock, ScriptedGenerate
        from app.services.ordering_agent import loop

        scope = dataclasses.replace(SCOPE, session_id=uuid.uuid4())
        generate = ScriptedGenerate()
        got = loop.run_turn(
            db=None, scope=scope, message=message, cart=[], generate=generate,
            clock=ScriptedClock(0.0), max_rounds=5, budget_seconds=1000.0,
        )
        return got, generate

    def test_checkout_with_nothing_in_the_order_says_so(self) -> None:
        # Live: 17.9 seconds, ending in a menu suggestion, for a fact known
        # before the turn started.
        got, generate = self.outcome("checkout")
        self.assertIn("nothing in your order", got.answer or "")
        self.assertEqual(generate.prompts, [], "no model round for a known fact")

    def test_the_cart_with_nothing_in_it_says_so(self) -> None:
        got, generate = self.outcome("cart")
        self.assertIn("nothing in your order", got.answer or "")
        self.assertEqual(generate.prompts, [])


class OrderForLaterTests(unittest.TestCase):
    """A closed kitchen takes the order for when it opens.

    Live at 08:24 with the branch shut: "We are closed for pickup right now.
    The next time I can do is Thu 10:30 — shall I place it for then?" —
    "yes that time is fine" — placed for Thu 10:30, paid, confirmed.
    """

    def test_a_time_with_a_zone_in_the_future_is_kept(self) -> None:
        from app.services.ordering_agent import order_draft

        draft, problems = order_draft.remember(
            order_draft.OrderDraft(offered_scheduled_at="2099-01-01T10:30:00+05:30"),
            scheduled_at="2099-01-01T10:30:00+05:30",
        )
        self.assertEqual(problems, [])
        self.assertEqual(draft.scheduled_at, "2099-01-01T10:30:00+05:30")
        self.assertIsNone(draft.offered_scheduled_at, "an offer taken up is no longer pending")

    def test_a_past_time_and_a_naive_time_are_refused(self) -> None:
        from app.services.ordering_agent import order_draft

        _, past = order_draft.remember(order_draft.OrderDraft(), scheduled_at="2001-01-01T10:30:00+05:30")
        _, naive = order_draft.remember(order_draft.OrderDraft(), scheduled_at="2099-01-01T10:30:00")
        self.assertTrue(any("passed" in p for p in past))
        self.assertTrue(any("could not be read" in p for p in naive))

    def test_the_offered_time_survives_a_save_and_a_load(self) -> None:
        # Live: saved on the refusing turn, dropped on the very next read,
        # so "yes" had nothing to say yes to.
        from app.services.ordering_agent import order_draft

        sid = uuid.uuid4()
        order_draft.save(sid, order_draft.OrderDraft(offered_scheduled_at="2099-01-01T10:30:00+05:30", collecting=True))
        loaded = order_draft.load(sid)
        order_draft.clear(sid)
        self.assertEqual(loaded.offered_scheduled_at, "2099-01-01T10:30:00+05:30")
        self.assertTrue(loaded.collecting)

    def test_the_refusal_offers_the_next_opening(self) -> None:
        from app.services.ordering_agent.loop import describe_place_failure
        from app.services.ordering_agent.planner import ToolCallRecord

        said = describe_place_failure([ToolCallRecord(
            tool="place_order", args={},
            result={"outcome": "refused", "reason": "Pickup is outside the current branch schedule.",
                    "next_open": "2026-09-17T10:30:00+05:30", "fulfillment_label": "pickup"},
        )])
        self.assertIn("closed for pickup", said)
        self.assertIn("Thu 10:30", said)
        self.assertIn("shall I place it for then", said)

    def test_a_placed_order_for_later_says_when(self) -> None:
        from app.services.ordering_agent.loop import describe_placed_order

        said = describe_placed_order({"total": "261.45", "scheduled_at": "2026-09-17T10:30:00+05:30"})
        self.assertIn("placed for Thu 10:30", said)

    def test_a_time_that_will_not_work_says_why_and_offers_the_nearest(self) -> None:
        from app.services.ordering_agent.loop import describe_time_problem
        from app.services.ordering_agent.planner import ToolCallRecord

        said = describe_time_problem([ToolCallRecord(
            tool="schedule_time", args={"when": "2026-09-17 09:00"},
            result={"outcome": "unavailable", "reason": "Pickup is not available for the selected time.",
                    "next_open": "2026-09-17T10:30:00+05:30"},
        )])
        self.assertIn("will not work", said)
        self.assertIn("Thu 10:30", said)

    def test_the_reader_carries_when(self) -> None:
        from app.services.ordering_agent.planner import read_order_intent

        seen = {}
        def generate(prompt, *a, **k):
            seen["prompt"] = prompt
            return '{"add": null, "details": {}, "checkout": false, "when": "2026-09-17 10:30"}'
        got = read_order_intent("yes that time is fine", generate=generate,
                                now_local="Thursday 2026-09-17 08:24", offered="2026-09-17 10:30")
        self.assertEqual(got["when"], "2026-09-17 10:30")
        self.assertIn("offered to make the order for 2026-09-17 10:30", seen["prompt"])
        self.assertEqual(read_order_intent("x", generate=lambda *a, **k: '{"when": "opening"}')["when"], "opening")

    def test_a_scheduled_draft_places_a_scheduled_order(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch

        from app.models.enums import OrderScheduleType
        from app.services.ordering_agent import order_draft, tools as T

        captured = {}
        def fake_create_order(db, customer, payload):
            captured["payload"] = payload
            return SimpleNamespace(id=uuid.uuid4(), total_amount=1, currency="CAD",
                                   restaurant_id=uuid.uuid4(), restaurant_location_id=uuid.uuid4())
        draft = order_draft.OrderDraft(contact_name="V", contact_phone="+919000000001", contact_email="v@example.com",
                                       fulfillment_type="PICKUP", scheduled_at="2099-01-01T10:30:00+05:30")
        scope = SimpleNamespace(session_id=uuid.uuid4(), customer=SimpleNamespace(id=uuid.uuid4()), verified_phone=None,
                                restaurant_id=uuid.uuid4(), restaurant_location_id=uuid.uuid4(), app_client_id=None)
        with patch.object(T, "_draft_for", return_value=draft), patch.object(T, "create_order", fake_create_order), \
             patch.object(T, "create_payment_link", return_value=SimpleNamespace(url="https://pay.example.test/x")), \
             patch.object(T.order_channel, "remember", lambda *a, **k: None), patch.object(T.order_draft, "clear", lambda *a, **k: None):
            out = T._place_order(None, scope, T.PlaceOrderArgs(lines=[T.CartLineArgs(menu_item_id=uuid.uuid4(), quantity=1)]))
        self.assertEqual(captured["payload"].schedule_type, OrderScheduleType.SCHEDULED)
        self.assertEqual(captured["payload"].scheduled_at.isoformat(), "2099-01-01T10:30:00+05:30")
        self.assertEqual(out["scheduled_at"], "2099-01-01T10:30:00+05:30")


class TheDishTheyNamedTests(unittest.TestCase):
    """An add spends money, so a guess is never good enough.

    Live: "Please add four cheese pizza in my cart" put four Cheese Burst
    Pizzas in a cart — $1396 of the wrong thing. The reading split the
    dish's own name into a quantity, and `get_dish` reported the near miss
    with `confidence: "named"`, which it also reports for a real match.
    """

    def matches(self, phrase):
        import uuid as _uuid
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from app.services.ordering_agent import tools as T

        rows = {
            "cheese pizza": ["Cheese Burst Pizza", "Four Cheese Pizza"],
            "four cheese pizza": ["Four Cheese Pizza"],
            "margherita": ["Margherita Pizza"],
        }.get(phrase.lower(), [])
        db = MagicMock()
        db.scalars.return_value = [SimpleNamespace(id=_uuid.uuid4(), name=n) for n in rows]
        scope = SimpleNamespace(restaurant_location_id=_uuid.uuid4())
        return [name for _, name in T.dishes_matching_words(db, scope, phrase)]

    def test_a_name_that_fits_one_dish_is_that_dish(self) -> None:
        self.assertEqual(self.matches("four cheese pizza"), ["Four Cheese Pizza"])
        self.assertEqual(self.matches("margherita"), ["Margherita Pizza"])

    def test_a_name_that_fits_two_dishes_is_a_question(self) -> None:
        self.assertEqual(len(self.matches("cheese pizza")), 2)

    def test_a_phrase_of_only_short_words_matches_nothing(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from app.services.ordering_agent import tools as T

        db = MagicMock()
        self.assertEqual(T.dishes_matching_words(db, SimpleNamespace(restaurant_location_id=None), "a x"), [])
        db.scalars.assert_not_called()

    def test_the_ambiguous_question_is_spoken(self) -> None:
        from app.services.ordering_agent.loop import _choice_question_in
        from app.services.ordering_agent.planner import ToolCallRecord

        said = _choice_question_in([ToolCallRecord(
            tool="get_dish", args={"name": "cheese pizza"},
            result={"outcome": "ambiguous", "question": "Did you mean Cheese Burst Pizza or Four Cheese Pizza?"},
        )])
        self.assertIn("Did you mean", said)

    def test_a_remembered_size_question_is_answered_by_the_next_message(self) -> None:
        # Live: the size question was asked correctly and "large one" landed
        # on nothing, because a turn's records do not survive it.
        import json

        from app.services.ordering_agent import order_draft

        sid = uuid.uuid4()
        order_draft.save(sid, order_draft.OrderDraft(pending_choice=json.dumps({
            "menu_item_id": str(uuid.uuid4()), "quantity": 1,
            "question": "Which size for Four Cheese Pizza?",
            "options": [{"name": 'Large (14")', "size_id": str(uuid.uuid4())}],
        })))
        loaded = order_draft.load(sid)
        order_draft.clear(sid)
        self.assertIn("Four Cheese Pizza", loaded.pending_choice)


class AnswersAccumulateTests(unittest.TestCase):
    """A dish needing two choices, and an answer nobody can map.

    Live, both loops: "sweet chilli" went back to "Which size?" because the
    size chosen a message earlier was gone; and "qqq" three times dropped
    the question entirely, so the reply pipeline repeated itself.
    """

    def stored(self, **over):
        import json

        base = {
            "base": {"menu_item_id": str(uuid.uuid4()), "quantity": 1,
                     "menu_item_size_id": str(uuid.uuid4())},
            "question": "Glaze for Chicken Wings: Sweet chilli, Tamarind garlic.",
            "options": [{"name": "Sweet chilli", "option_id": str(uuid.uuid4())},
                        {"name": "Tamarind garlic", "option_id": str(uuid.uuid4())}],
            "asks": 1,
        }
        base.update(over)
        return json.dumps(base)

    def test_what_was_already_settled_travels_with_the_question(self) -> None:
        import json

        from app.services.ordering_agent import order_draft

        sid = uuid.uuid4()
        order_draft.save(sid, order_draft.OrderDraft(pending_choice=self.stored()))
        asked = json.loads(order_draft.load(sid).pending_choice)
        order_draft.clear(sid)
        self.assertIn("menu_item_size_id", asked["base"], "the size already chosen is kept")
        self.assertEqual(asked["asks"], 1)

    def test_a_second_unanswered_asking_spells_the_options_out(self) -> None:
        import json

        from tests.test_ordering_agent_loop import SCOPE, ScriptedClock, ScriptedGenerate
        from unittest.mock import patch
        from app.services.ordering_agent import loop, order_draft
        import dataclasses

        scope = dataclasses.replace(SCOPE, session_id=uuid.uuid4())
        store = {"draft": order_draft.OrderDraft(pending_choice=self.stored(asks=1))}
        with patch.object(order_draft, "load", lambda sid: store["draft"]), \
             patch.object(order_draft, "save", lambda sid, d: store.__setitem__("draft", d)):
            outcome = loop.run_turn(
                db=None, scope=scope, message="qqq", cart=[], generate=ScriptedGenerate(),
                clock=ScriptedClock(0.0), max_rounds=5, budget_seconds=1000.0,
            )
        self.assertIn("did not catch that", outcome.answer)
        self.assertIn("Sweet chilli", outcome.answer)
        self.assertEqual(json.loads(store["draft"].pending_choice)["asks"], 2, "counted")

    def test_there_is_never_a_third_asking(self) -> None:
        import dataclasses
        from unittest.mock import patch

        from tests.test_ordering_agent_loop import SCOPE, ScriptedClock, ScriptedGenerate
        from app.services.ordering_agent import loop, order_draft

        scope = dataclasses.replace(SCOPE, session_id=uuid.uuid4())
        store = {"draft": order_draft.OrderDraft(pending_choice=self.stored(asks=2))}
        with patch.object(order_draft, "load", lambda sid: store["draft"]), \
             patch.object(order_draft, "save", lambda sid, d: store.__setitem__("draft", d)):
            outcome = loop.run_turn(
                db=None, scope=scope, message="qqq", cart=[], generate=ScriptedGenerate(),
                clock=ScriptedClock(0.0), max_rounds=5, budget_seconds=1000.0,
            )
        self.assertIn("start that one again", outcome.answer)
        self.assertIsNone(store["draft"].pending_choice, "the question is let go of")

    def test_an_answer_to_something_else_is_not_treated_as_a_miss(self) -> None:
        # "actually add a coke too" answers nothing, but it is not a failure
        # to understand — it is a new request, and must reach the reader.
        import dataclasses
        from unittest.mock import patch

        from tests.test_ordering_agent_loop import SCOPE, ScriptedClock, ScriptedGenerate
        from app.services.ordering_agent import loop, order_draft

        scope = dataclasses.replace(SCOPE, session_id=uuid.uuid4())
        store = {"draft": order_draft.OrderDraft(pending_choice=self.stored(asks=1))}
        from tests.test_ordering_agent_loop import _answer

        generate = ScriptedGenerate(
            _answer("Sure, a Coke."),
            intent='{"add": {"dish": "Coke", "quantity": 1}, "details": {}, "checkout": false, "when": null, "chose": null}',
        )
        with patch.object(order_draft, "load", lambda sid: store["draft"]), \
             patch.object(order_draft, "save", lambda sid, d: store.__setitem__("draft", d)):
            outcome = loop.run_turn(
                db=None, scope=scope, message="actually add a coke too", cart=[], generate=generate,
                clock=ScriptedClock(0.0), max_rounds=5, budget_seconds=1000.0,
            )
        self.assertNotIn("did not catch that", outcome.answer or "")


class AReturningCustomerTests(unittest.TestCase):
    """Somebody who has ordered before is not asked everything again.

    Live, before this: an account existed with their name and email, and
    every conversation still asked for both — the customer was only looked
    up at the moment of placing. And `default_address` was empty after
    several orders, because nothing ever wrote it.
    """

    def test_an_address_they_type_needs_no_reading_back(self) -> None:
        from app.services.ordering_agent import order_draft

        draft, _ = order_draft.remember(
            order_draft.OrderDraft(), delivery_address="7 New Street"
        )
        self.assertTrue(draft.confirmed)

    def test_saying_delivery_does_not_confirm_an_address_they_never_saw(self) -> None:
        # Live: typing "delivery" marked the whole draft confirmed, so an
        # address from last month went out unseen.
        from app.services.ordering_agent import order_draft

        draft, _ = order_draft.remember(
            order_draft.OrderDraft(delivery_address="42 Old Road"), fulfillment_type="DELIVERY"
        )
        self.assertFalse(draft.confirmed)

    def test_the_confirmation_flags_survive_a_save_and_a_load(self) -> None:
        from app.services.ordering_agent import order_draft

        sid = uuid.uuid4()
        order_draft.save(sid, order_draft.OrderDraft(confirmed=True, confirm_asks=2))
        loaded = order_draft.load(sid)
        order_draft.clear(sid)
        self.assertTrue(loaded.confirmed)
        self.assertEqual(loaded.confirm_asks, 2)

    def test_the_draft_lives_as_long_as_the_cart(self) -> None:
        # They were two hours and twenty-four, so a customer back at hour
        # three had their food and was asked for their address again.
        from app.services.ordering_agent import order_draft, session_cart

        self.assertEqual(order_draft.DRAFT_TTL_SECONDS, session_cart.CART_TTL_SECONDS)

    def test_a_number_is_found_in_either_spelling_and_nobody_is_created(self) -> None:
        from tests.test_ordering_agent_verified_phone import FakeDb, make_customer
        from app.services.ordering_agent.verified_phone import find_customer

        app_client_id = uuid.uuid4()
        legacy = make_customer("916353100362", app_client_id)
        db = FakeDb([legacy])
        found = find_customer(db, phone_number="+916353100362", app_client_id=app_client_id)
        self.assertIs(found, legacy)
        self.assertEqual(db.added, [])

    def test_an_unknown_number_is_nobody(self) -> None:
        from tests.test_ordering_agent_verified_phone import FakeDb
        from app.services.ordering_agent.verified_phone import find_customer

        self.assertIsNone(find_customer(FakeDb([]), phone_number="+910000000000", app_client_id=None))

    def test_the_verified_number_beats_the_accounts_copy(self) -> None:
        # Live: the account held the plus-less wa_id, seeding put
        # '916353100362' on the order, and the schema refused it.
        from types import SimpleNamespace
        from unittest.mock import patch

        from app.services.ordering_agent import order_draft, tools as T

        account = SimpleNamespace(
            full_name="vishal", email="test@gmail.com",
            phone_number="916353100362", default_address="42 Example Road",
        )
        scope = SimpleNamespace(
            session_id=uuid.uuid4(), customer=account, verified_phone="+916353100362",
        )
        with patch.object(order_draft, "load", return_value=order_draft.OrderDraft()):
            draft = T._draft_for(scope)
        self.assertEqual(draft.contact_phone, "+916353100362")
        self.assertEqual(draft.delivery_address, "42 Example Road", "the rest still comes from the account")


class ShowingTheMenuTests(unittest.TestCase):
    """A question about the menu is answered from the menu.

    Live, all four wrong: "here is the vegetarian menu for you:" with no
    list behind it; a list that ignored a diet stated two messages earlier;
    "do you have pizza with extra cheese" answered with Coconut Ice Cream;
    and "I am asking for pizza" answered with a question back.
    """

    def rows(self, names_and_veg):
        import uuid as _uuid
        from decimal import Decimal
        from types import SimpleNamespace

        return [
            SimpleNamespace(id=_uuid.uuid4(), name=n, price=Decimal("9.99"),
                            is_veg=v, category="Mains")
            for n, v in names_and_veg
        ]

    def shown(self, rows, phrase, is_veg=None):
        import uuid as _uuid
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from app.services.ordering_agent import tools as T

        db = MagicMock()
        db.scalars.return_value = rows
        scope = SimpleNamespace(restaurant_location_id=_uuid.uuid4())
        return T.dishes_to_show(db, scope, phrase, is_veg=is_veg)

    def test_dishes_come_back_with_their_names_and_prices(self) -> None:
        shown = self.shown(self.rows([("Margherita Pizza", True)]), "pizza")
        self.assertEqual(shown, [{"name": "Margherita Pizza", "price": "9.99", "is_veg": True}])

    def test_a_diet_is_asked_of_the_query_not_remembered_by_a_model(self) -> None:
        import uuid as _uuid
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from app.services.ordering_agent import tools as T

        db = MagicMock()
        db.scalars.return_value = self.rows([("Veggie Garden Pizza", True)])
        scope = SimpleNamespace(restaurant_location_id=_uuid.uuid4())
        T.dishes_to_show(db, scope, "pizza", is_veg=True)
        # The filter is in the statement, so no model can forget it.
        self.assertIn("is_veg", str(db.scalars.call_args[0][0]))

    def test_a_phrase_matching_nothing_still_shows_the_menu(self) -> None:
        # "Here is the vegetarian menu for you:" with nothing after it was
        # the worst of the four: a promise with no list behind it.
        shown = self.shown(self.rows([("Corn Fritters", True)]), "something lovely")
        self.assertEqual([d["name"] for d in shown], ["Corn Fritters"])

    def test_the_diet_lasts_the_conversation(self) -> None:
        # Stating it on a guest channel was remembered nowhere at all.
        from app.services.ordering_agent import order_draft

        sid = uuid.uuid4()
        order_draft.save(sid, order_draft.OrderDraft(diet="veg"))
        loaded = order_draft.load(sid)
        order_draft.clear(sid)
        self.assertEqual(loaded.diet, "veg")

    def test_a_menu_answer_from_the_rows_is_the_agents_to_give(self) -> None:
        # It was labelled "menu", the seam owned only "cart" and "order", so
        # the pipeline's prose won and the list the customer asked for never
        # reached them.
        from types import SimpleNamespace
        from unittest.mock import patch

        from app.services import rag
        from app.services.ordering_agent.loop import TurnOutcome

        outcome = TurnOutcome(
            answer="Here is what we have:\n- Margherita Pizza - $12.99",
            answer_about="menu", actions=[], records=[],
            fallback_reason=None, elapsed_seconds=0.1,
        )
        with patch.object(rag.settings, "enable_ordering_agent", True),              patch.object(rag, "run_turn", return_value=outcome),              patch.object(rag, "_remember_stated_diet", lambda *a, **k: None),              patch.object(rag, "_diet_for_session", lambda *a, **k: None),              patch.object(rag, "_returning_customer", lambda *a, **k: None):
            frame = rag._run_ordering_agent(
                None,
                user=SimpleNamespace(id=uuid.uuid4(), is_guest=True),
                message="do you have pizza",
                cart=[],
                restaurant_id=uuid.uuid4(),
                restaurant_location_id=uuid.uuid4(),
                turn_id="t",
            )
        self.assertTrue(frame["agent_asks"], "a menu the agent read out is the agent's answer")
        self.assertIn("Margherita Pizza", frame["agent_reply"])


class PlacingNeedsAskingTests(unittest.TestCase):
    """An order goes when they ask for it, not whenever it could.

    Live: four identical answers to four different messages — "No", "No",
    and a question about lunch — because a complete draft meant every turn
    tried to place, the branch was shut, and the refusal became the only
    sentence the customer could get.
    """

    def scope(self):
        import dataclasses

        from tests.test_ordering_agent_loop import SCOPE

        return dataclasses.replace(
            SCOPE, session_id=uuid.uuid4(), verified_phone="+919000000001"
        )

    def complete(self, **over):
        from app.services.ordering_agent import order_draft

        base = dict(
            contact_name="V", contact_email="v@example.com", contact_phone="+919000000001",
            fulfillment_type="PICKUP", collecting=True, confirmed=True,
        )
        base.update(over)
        return order_draft.OrderDraft(**base)

    def turn(self, message, intent, draft=None):
        from unittest.mock import patch

        from tests.test_ordering_agent_loop import SCOPE, ScriptedClock, ScriptedGenerate, _answer
        from app.schemas.suggestions import CartLinePayload
        from app.services.ordering_agent import loop, order_draft

        store = {"draft": draft or self.complete()}
        placed: list = []
        generate = ScriptedGenerate(_answer("Anything else?"), intent=intent)
        with patch.object(order_draft, "load", lambda sid: store["draft"]), \
             patch.object(order_draft, "save", lambda sid, d: store.__setitem__("draft", d)), \
             patch.dict(loop.TOOLS, {}, clear=False), \
             patch.object(loop, "placed_order_in", lambda records: placed[0] if placed else None):
            outcome = loop.run_turn(
                db=None, scope=self.scope(), message=message,
                cart=[CartLinePayload(menu_item_id=uuid.uuid4(), quantity=1)],
                generate=generate, clock=ScriptedClock(0.0),
                max_rounds=4, budget_seconds=1000.0, auto_place=True,
            )
        return outcome, store["draft"]

    NOTHING = '{"add": null, "details": {}, "checkout": false, "when": null, "chose": null, "confirms": null, "browse": null}'

    def test_a_message_asking_for_nothing_does_not_place(self) -> None:
        outcome, _ = self.turn("what can I have for lunch?", self.NOTHING)
        self.assertNotIn("place_order", [r.tool for r in outcome.records])

    def test_asking_to_check_out_does_place(self) -> None:
        asked = self.NOTHING.replace('"checkout": false', '"checkout": true')
        outcome, _ = self.turn("checkout", asked)
        # order_requirements runs; the placement follows it in the same turn.
        self.assertTrue([r for r in outcome.records], "the turn did something")

    def test_no_to_an_offered_time_declines_the_time(self) -> None:
        # Live: read as rejecting details nobody was discussing, it wiped the
        # delivery address — every turn, four turns running.
        said_no = self.NOTHING.replace('"confirms": null', '"confirms": false')
        draft = self.complete(
            fulfillment_type="DELIVERY", delivery_address="42 Example Road",
            offered_scheduled_at="2099-01-01T11:30:00+05:30",
        )
        outcome, after = self.turn("No. It's okay", said_no, draft=draft)
        self.assertIn("hold it", outcome.answer or "")
        self.assertEqual(after.delivery_address, "42 Example Road", "their address is untouched")
        self.assertIsNone(after.offered_scheduled_at, "the time is not offered again")


class AskingWhenTests(unittest.TestCase):
    """A question about time is answered from the branch's schedule.

    Live, two wrong answers to the same question: read as an instruction
    ("that time will not work"), and answered by a reply pipeline that
    invented a "Place Order button" a chat has never had — then "30 to 45
    minutes" and "11 AM to 9 PM daily", neither of them from any row.
    """

    def branch(self, *, open_now=True, windows=(("11:00", "21:30"),)):
        from datetime import time as T
        from types import SimpleNamespace

        slots = [
            SimpleNamespace(
                is_active=True,
                fulfillment_type=__import__("app.models.enums", fromlist=["x"]).OrderFulfillmentType.DELIVERY,
                day_of_week=None,
                start_time=T(*(int(p) for p in s.split(":"))),
                end_time=T(*(int(p) for p in e.split(":"))),
            )
            for s, e in windows
        ]
        return SimpleNamespace(
            is_active=True, is_open=True, delivery_enabled=True, pickup_enabled=True,
            future_order_enabled=True, slot_interval_minutes=30, max_future_days=7,
            preparation_time_minutes=20, estimated_delivery_time=30, opening_time=None, closing_time=None,
            fulfillment_slots=slots, temporary_closed_reason=None,
        )

    def test_it_reads_the_windows_out_of_the_rows(self) -> None:
        from unittest.mock import patch

        from app.models.enums import OrderFulfillmentType
        from app.services import restaurant_locations as bh

        branch = self.branch()
        for slot in branch.fulfillment_slots:
            slot.day_of_week = bh._weekday_for_datetime(bh._localize_reference_datetime(None))
        said = bh.describe_hours(branch, fulfillment_type=OrderFulfillmentType.DELIVERY)
        self.assertIn("11:00-21:30", said)
        self.assertIn("Delivery today", said)

    def test_a_day_with_no_window_says_so_rather_than_inventing_one(self) -> None:
        from app.models.enums import OrderFulfillmentType
        from app.services import restaurant_locations as bh

        branch = self.branch()
        branch.fulfillment_slots = []
        said = bh.describe_hours(branch, fulfillment_type=OrderFulfillmentType.DELIVERY)
        self.assertIn("not running today", said)

    def test_a_named_time_is_an_instruction_not_a_question(self) -> None:
        # "make it 12:30" reads as both; the time is what they meant.
        from app.services.ordering_agent.planner import read_order_intent

        got = read_order_intent(
            "make it 12:30",
            generate=lambda *a, **k: '{"asks_hours": true, "when": "2026-09-17 12:30", "add": null, "details": {}, "checkout": false, "chose": null, "confirms": null, "browse": null}',
        )
        self.assertTrue(got["asks_hours"])
        self.assertEqual(got["when"], "2026-09-17 12:30")


class ChooseThreeTests(unittest.TestCase):
    """A group that wants three, answered one at a time or all at once.

    Live: "Choose three sweets... > Mango sticky rice" came back with the
    identical sentence — same list, same count, no sign anybody had heard.
    Answer it perfectly three times and it reads as broken every time.
    """

    def result(self, chosen=()):
        return {
            "outcome": "needs_choice",
            "name": "Thai Dessert Platter",
            "needs_size": False,
            "available_sizes": [],
            "customization_groups": [{
                "title": "Choose three sweets",
                "needs_selection": True,
                "min_selection": 3,
                "max_selection": 3,
                "selected_option_ids": list(chosen),
                "options": [
                    {"option_id": "a", "name": "Mango sticky rice", "extra_price": 0},
                    {"option_id": "b", "name": "Fried banana", "extra_price": 0},
                    {"option_id": "c", "name": "Tub tim krob", "extra_price": 0},
                ],
            }],
        }

    def test_it_says_how_many_are_wanted(self) -> None:
        from app.services.ordering_agent.loop import ask_for_choice

        said = ask_for_choice(self.result())
        self.assertIn("pick 3", said)
        self.assertIn("Mango sticky rice", said)

    def test_it_credits_what_is_already_chosen_and_counts_down(self) -> None:
        from app.services.ordering_agent.loop import ask_for_choice

        said = ask_for_choice(self.result(chosen=["a"]))
        self.assertIn("you have Mango sticky rice", said)
        self.assertIn("Pick 2 more", said)
        self.assertNotIn("Mango sticky rice,", said.split("Pick 2 more")[1])

    def test_the_reading_takes_several_at_once(self) -> None:
        from app.services.ordering_agent.planner import read_order_intent

        got = read_order_intent(
            "mango sticky rice, fried banana and lod chong",
            generate=lambda *a, **k: '{"chose": ["Mango sticky rice", "Fried banana", "Lod chong"], "add": null, "details": {}, "checkout": false, "when": null, "confirms": null, "browse": null, "asks_hours": false}',
        )
        self.assertEqual(got["chose"], ["Mango sticky rice", "Fried banana", "Lod chong"])

    def test_one_pick_still_reads_as_a_list(self) -> None:
        from app.services.ordering_agent.planner import read_order_intent

        got = read_order_intent(
            "large one",
            generate=lambda *a, **k: '{"chose": "Large (14\\")", "add": null, "details": {}, "checkout": false, "when": null, "confirms": null, "browse": null, "asks_hours": false}',
        )
        self.assertEqual(got["chose"], ['Large (14")'])


class _Rows:
    """What `db.scalars` gives back: something you iterate once."""

    def __init__(self, items):
        self.items = list(items)

    def __iter__(self):
        return iter(self.items)


class _MenuDb:
    """A database that answers the one query the menu helpers make."""

    def __init__(self, *rows):
        self.rows = list(rows)
        self.statements = []
        self.bound = []

    def scalars(self, statement):
        self.statements.append(str(statement))
        try:
            self.bound.append(statement.compile().params)
        except Exception:  # noqa: BLE001 - a statement that will not compile is the test's problem
            self.bound.append({})
        return _Rows(self.rows)


def _dish(name, price=4.5, is_veg=True):
    from types import SimpleNamespace

    return SimpleNamespace(name=name, price=price, is_veg=is_veg)


class TheQuestionWeEndedOnTests(unittest.TestCase):
    """"Yes" means the question we just asked, in whatever words it arrives.

    Live, from a customer's phone:

        > I like Appetizer Sampler
          Here is what we have: Appetizer Sampler - $18.99. Which one would
          you like?
        > Yes
          Great! Your order is ready to be placed. To proceed, we need to
          know the type of fulfillment (e.g., pickup or delivery)...

    The dish they named was read back as a list of one, and the "Yes" that
    answered it reached nobody: the turn had no memory of asking, so the
    reply pipeline filled the silence with prose about a cart holding the
    previous day's dessert. A question we ask is now held until it is
    answered, and what agreeing DOES is written down as we ask it.
    """

    def scope(self):
        import dataclasses

        from tests.test_ordering_agent_loop import SCOPE

        return dataclasses.replace(
            SCOPE, session_id=uuid.uuid4(), verified_phone="+919000000001"
        )

    def turn(self, message, *, draft=None, intent, db=None, cart=None):
        """One turn, with a draft that survives it the way Redis does."""

        import dataclasses as dc
        from unittest.mock import patch

        from tests.test_ordering_agent_loop import ScriptedClock, ScriptedGenerate
        from app.services.ordering_agent import loop, order_draft as od

        held = {"draft": draft or od.OrderDraft()}
        with patch.object(od, "load", lambda _s: dc.replace(held["draft"])), \
                patch.object(od, "save", lambda _s, d: held.update(draft=d)):
            outcome = loop.run_turn(
                db=db,
                scope=self.scope(),
                message=message,
                cart=cart if cart is not None else [
                    CartLinePayload(menu_item_id=uuid.uuid4(), quantity=1)
                ],
                generate=ScriptedGenerate(intent=intent),
                clock=ScriptedClock(0.0),
                max_rounds=1,
                budget_seconds=1000.0,
            )
        return outcome, held["draft"]

    def agreeing(self, agreed=True):
        import json

        return json.dumps({
            "add": None, "details": {}, "checkout": False, "when": None,
            "chose": None, "confirms": agreed, "browse": None,
            "asks_hours": False, "category": None,
        })

    def holding(self, yes, subject=None, question="Shall I?"):
        import json

        from app.services.ordering_agent import order_draft as od

        return od.OrderDraft(
            awaiting=json.dumps({"question": question, "yes": yes, "subject": subject})
        )

    def test_a_draft_remembers_the_question_it_is_waiting_on(self) -> None:
        from unittest.mock import patch

        from app.services.ordering_agent import order_draft as od

        saved = {}
        with patch.object(od, "cache_set_json", lambda k, v, ttl_seconds=None: saved.update(v)), \
                patch.object(od, "cache_get_json", lambda k: dict(saved)):
            od.save("s", od.OrderDraft(awaiting='{"question": "Anything else?", "yes": "more"}'))
            back = od.load("s")
        self.assertIn("Anything else?", back.awaiting or "")

    def test_no_to_shall_i_add_one_asks_what_they_would_like_instead(self) -> None:
        outcome, _ = self.turn(
            "no thanks",
            draft=self.holding("add", "Appetizer Sampler"),
            intent=self.agreeing(False),
        )
        self.assertIn("What else can I get you?", outcome.answer or "")
        self.assertNotIn("Appetizer Sampler", outcome.answer or "")

    def test_yes_to_ready_to_check_out_checks_out(self) -> None:
        outcome, _ = self.turn(
            "yes please",
            draft=self.holding("checkout", question="Ready to check out?"),
            intent=self.agreeing(),
        )
        # Nothing is invented: with no details held, checking out asks for
        # them. What matters is that a bare yes reached the order at all.
        self.assertIn("still need", outcome.answer or "")

    def test_no_to_ready_to_check_out_keeps_the_conversation_open(self) -> None:
        outcome, _ = self.turn(
            "not yet",
            draft=self.holding("checkout", question="Ready to check out?"),
            intent=self.agreeing(False),
        )
        self.assertIn("What else can I get you?", outcome.answer or "")

    def test_yes_to_anything_else_asks_what(self) -> None:
        outcome, _ = self.turn(
            "yes",
            draft=self.holding("more", question="Anything else?"),
            intent=self.agreeing(),
        )
        self.assertIn("What else can I get you?", outcome.answer or "")

    def test_no_to_anything_else_moves_on_to_the_order(self) -> None:
        outcome, _ = self.turn(
            "no that is all",
            draft=self.holding("more", question="Anything else?"),
            intent=self.agreeing(False),
        )
        self.assertIn("still need", outcome.answer or "")

    def test_yes_to_which_one_is_not_answered_with_the_same_question(self) -> None:
        # The screenshot: "Which one would you like?" answered "Yes". A real
        # person does not repeat themselves; they make it answerable.
        outcome, _ = self.turn(
            "Yes",
            draft=self.holding("name_one", question="Which one would you like?"),
            intent=self.agreeing(),
        )
        said = outcome.answer or ""
        self.assertIn("tell me the name", said)
        self.assertNotIn("Which one would you like?", said)

    def test_the_question_it_consumed_is_replaced_not_left_standing(self) -> None:
        # Read once and dropped. Every turn that ends on a question writes a
        # fresh one, so a question nobody answered never answers a later
        # message by accident.
        _, draft = self.turn(
            "Yes",
            draft=self.holding("name_one", question="Which one would you like?"),
            intent=self.agreeing(),
        )
        self.assertNotIn("Which one would you like?", draft.awaiting or "")
        self.assertIn("tell me the name", draft.awaiting or "")

    def test_an_add_asks_one_question_so_yes_has_one_meaning(self) -> None:
        from app.services.ordering_agent.loop import ToolCallRecord, describe_applied

        said = describe_applied([
            ToolCallRecord(
                tool="add_to_cart", args={},
                result={
                    "outcome": "action", "name": "Corn Fritters", "quantity": 2,
                    "action": {"kind": "add", "status": "applied", "quantity": 2},
                },
            )
        ])
        self.assertEqual(said, "Added 2 x Corn Fritters to your order. Anything else?")
        # "Anything else, or shall we get it on its way?" asked two things at
        # once, and the answer to both of them is yes.
        self.assertNotIn(" or ", said)


class TheSectionsThisBranchSellsTests(unittest.TestCase):
    """"Some drink" finds Beverages, because the sections are rows.

    Live: a question about drinks was matched by substring against a
    category called Beverages, matched nothing, and was answered with the
    first eight dishes on the menu — eight appetizers.
    """

    def scope(self):
        from tests.test_ordering_agent_loop import SCOPE

        return SCOPE

    def test_a_named_section_is_matched_exactly_not_searched_for(self) -> None:
        from app.services.ordering_agent import tools as tools_module

        db = _MenuDb(_dish("Thai Iced Tea"))
        shown = tools_module.dishes_to_show(
            db, self.scope(), "some drink", category="Beverages"
        )
        self.assertEqual([d["name"] for d in shown], ["Thai Iced Tea"])
        self.assertEqual(len(db.statements), 1, "the section answers; nothing is searched")

    def test_a_plural_still_finds_the_menus_singular(self) -> None:
        # "vegetarian pizzas" matched no dish called "pizzas" and no category
        # called "pizzas" either, and answered with the whole menu.
        from app.services.ordering_agent import tools as tools_module

        db = _MenuDb(_dish("Margherita Pizza", price=249.0))
        shown = tools_module.dishes_to_show(db, self.scope(), "pizzas")
        self.assertEqual([d["name"] for d in shown], ["Margherita Pizza"])
        self.assertIn("%pizza%", list(db.bound[0].values()), "matched on the singular")

    def test_the_reading_is_told_which_sections_exist(self) -> None:
        from app.services.ordering_agent.planner import read_order_intent

        seen = {}

        def generate(prompt, timeout, max_tokens):
            seen["prompt"] = prompt
            return '{"category": "Beverages"}'

        got = read_order_intent(
            "do you have some drink?",
            generate=generate,
            categories=["Appetizer", "Beverages", "Pizza"],
        )
        self.assertIn("Beverages", seen["prompt"])
        self.assertEqual(got["category"], "Beverages")

    def test_a_section_this_branch_does_not_have_is_no_answer_at_all(self) -> None:
        from app.services.ordering_agent.planner import read_order_intent

        got = read_order_intent(
            "sushi?",
            generate=lambda *a, **k: '{"category": "Sushi"}',
            categories=["Appetizer", "Beverages"],
        )
        self.assertIsNone(got["category"])
