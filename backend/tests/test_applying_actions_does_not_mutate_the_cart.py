"""Carrying out cart actions must not rewrite the cart it was handed.

Every caller saves the same way — the WhatsApp task, the dry run, the flow
check:

    updated, proposed = session_cart.apply_actions(cart, actions)
    if updated != cart:
        session_cart.save(session_id, updated)

`apply_actions` took a SHALLOW copy (`current = list(lines)`), so the
`CartLinePayload` objects were shared with the caller, and merging into an
existing line did `existing.quantity += quantity` — on the caller's own
object. Both sides of `updated != cart` then held the same mutated line, the
comparison said nothing had changed, and the save was skipped.

What that cost, silently:

* Ordering the same dish a second time. The reply said "Added 1 x Vagharela
  Khaman" and the stored cart still read one.
* Every change of count. "Make it 3" answered "that dish is now x3" over a
  cart that stayed at one.

A new dish was unaffected — that appends a line, so the lists differ and the
save happens — which is why carts fill at all and why this survived.
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

from app.schemas.suggestions import CartLinePayload
from app.services.ordering_agent import session_cart

DISH = str(uuid.uuid4())
OTHER = str(uuid.uuid4())


def add(menu_item_id=DISH, quantity=1, size=None):
    return {
        "kind": "add",
        "status": "applied",
        "menu_item_id": menu_item_id,
        "quantity": quantity,
        "menu_item_size_id": size,
        "selected_option_ids": [],
    }


def set_to(quantity, menu_item_id=DISH):
    return {
        "kind": "set_quantity",
        "status": "applied",
        "menu_item_id": menu_item_id,
        "quantity": quantity,
        "menu_item_size_id": None,
        "selected_option_ids": [],
    }


class TheCallersCartIsLeftAloneTests(unittest.TestCase):
    """The caller compares against it afterwards, so it has to be unchanged."""

    def test_merging_into_a_line_does_not_touch_the_original(self) -> None:
        cart = [CartLinePayload(menu_item_id=DISH, quantity=1)]
        session_cart.apply_actions(cart, [add()])
        self.assertEqual(cart[0].quantity, 1, "the caller's own line was rewritten")

    def test_a_change_of_count_does_not_touch_the_original(self) -> None:
        cart = [CartLinePayload(menu_item_id=DISH, quantity=1)]
        session_cart.apply_actions(cart, [set_to(3)])
        self.assertEqual(cart[0].quantity, 1)

    def test_the_caller_can_tell_something_changed(self) -> None:
        # The whole point: this comparison is what decides whether the cart is
        # written back at all.
        cart = [CartLinePayload(menu_item_id=DISH, quantity=1)]
        updated, _ = session_cart.apply_actions(cart, [add()])
        self.assertNotEqual(updated, cart, "the save would be skipped")

    def test_the_change_itself_still_happens(self) -> None:
        cart = [CartLinePayload(menu_item_id=DISH, quantity=1)]
        updated, _ = session_cart.apply_actions(cart, [add()])
        self.assertEqual(updated[0].quantity, 2)

    def test_a_count_is_set_not_added(self) -> None:
        cart = [CartLinePayload(menu_item_id=DISH, quantity=1)]
        updated, _ = session_cart.apply_actions(cart, [set_to(3)])
        self.assertEqual(updated[0].quantity, 3)


class WhatAlreadyWorkedStillDoesTests(unittest.TestCase):
    """A new dish appends a line, which is why carts filled at all."""

    def test_a_new_dish_is_added(self) -> None:
        cart = [CartLinePayload(menu_item_id=DISH, quantity=1)]
        updated, _ = session_cart.apply_actions(cart, [add(menu_item_id=OTHER)])
        self.assertEqual(len(updated), 2)
        self.assertEqual(len(cart), 1, "the caller's list grew under it")

    def test_a_different_size_is_its_own_line(self) -> None:
        size = str(uuid.uuid4())
        cart = [CartLinePayload(menu_item_id=DISH, quantity=1)]
        updated, _ = session_cart.apply_actions(cart, [add(size=size)])
        self.assertEqual(len(updated), 2)

    def test_a_proposed_action_changes_nothing(self) -> None:
        cart = [CartLinePayload(menu_item_id=DISH, quantity=1)]
        proposal = {**add(), "status": "proposed"}
        updated, proposed = session_cart.apply_actions(cart, [proposal])
        self.assertEqual(updated[0].quantity, 1)
        self.assertEqual(cart[0].quantity, 1)
        self.assertEqual(proposed, [proposal])


if __name__ == "__main__":
    unittest.main()
