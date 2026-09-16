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
from app.services.ordering_agent.tools import (
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

    def requirements(self, scope=None):
        return TOOLS["order_requirements"].handler(None, scope or self.scope, OrderRequirementsArgs())

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
