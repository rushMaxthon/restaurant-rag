"""Asking a rider network to take an order, after Pidge has it.

Pidge's Create Order puts an order in Pending and stops there unless the
account's token is configured to auto-allocate. Ours created orders and never
asked anybody to carry them: the delivery sat on "Waiting for a rider" until
it was cancelled. Found reading the collection before the first live test
order, not from a customer - which is the order these things should be found
in.

Allocation is two calls: which networks can take this order (charged per
call, which is why nothing here loops), then fulfill with the one chosen.
An order Pidge already allocated by itself is left alone.
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

from app.services.delivery.base import DeliveryProviderError  # noqa: E402
from app.services.delivery.pidge_provider import PidgeProvider, pick_network, pidge_mobile  # noqa: E402

PENDING = {"data": {"id": "P1", "status": "pending"}}
ALLOCATED = {"data": {"id": "P1", "status": "fulfilled", "fulfillment": {"status": "CREATED"}}}


def network(name: str, price: float | None, *, error=None, token="tok", network_id="6", pickup_now=True):
    return {
        "network_id": network_id,
        "network_name": name,
        "service": name,
        "pickup_now": pickup_now,
        "quote": None if price is None else {"price": price},
        "error": error,
        "token": token,
    }


class PickingANetworkTests(unittest.TestCase):
    def test_the_cheapest_network_that_answered(self) -> None:
        items = [network("dunzo", 80), network("pidge", 70.8), network("zomato", 49, error={"message": "busy"})]
        self.assertEqual(pick_network(items)["network_name"], "pidge")

    def test_a_preferred_network_wins_when_it_can_take_the_order(self) -> None:
        items = [network("zomato", 49), network("pidge", 70.8)]
        self.assertEqual(pick_network(items, preferred="pidge")["network_name"], "pidge")

    def test_a_preferred_network_that_cannot_take_it_is_passed_over(self) -> None:
        items = [network("zomato", 49), network("pidge", 70.8, error={"message": "no riders"})]
        self.assertEqual(pick_network(items, preferred="pidge")["network_name"], "zomato")

    def test_a_network_without_a_price_is_not_chosen_blind(self) -> None:
        self.assertIsNone(pick_network([network("pidge", None)]))
        self.assertIsNone(pick_network([]))


class AllocatingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = PidgeProvider(base_url="https://api.pidge.in", username="u", password="p")

    def _run(self, *replies):
        calls = []

        def fake(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return replies[len(calls) - 1]

        with mock.patch.object(self.provider, "_call", side_effect=fake):
            outcome = self.provider.allocate("P1")
        return outcome, calls

    def test_an_order_pidge_already_allocated_is_left_alone(self) -> None:
        outcome, calls = self._run(ALLOCATED)
        self.assertEqual(outcome, "")
        self.assertEqual(len(calls), 1)  # one status read, no charged call

    def test_a_pending_order_is_offered_to_the_chosen_network(self) -> None:
        services = {"data": {"items": [network("dunzo", 80, network_id="9"), network("pidge", 70.8, network_id="-1")]}}
        outcome, calls = self._run(PENDING, services, {})
        method, path, kwargs = calls[1]
        self.assertEqual((method, path), ("GET", "/v1.0/store/channel/vendor/order/fulfillment/services"))
        self.assertEqual(kwargs["params"], {"ids": "P1"})
        method, path, kwargs = calls[2]
        self.assertEqual((method, path), ("POST", "/v1.0/store/channel/vendor/order/fulfill"))
        self.assertEqual(
            kwargs["json"],
            {"ids": ["P1"], "service": "pidge", "pickup_now": True, "network_id": "-1", "token": "tok"},
        )
        self.assertIn("pidge", outcome)
        self.assertIn("70.8", outcome)

    def test_nobody_able_to_take_it_is_said_plainly(self) -> None:
        services = {"data": {"items": [network("pidge", 70.8, error={"message": "Rider Not Available"})]}}
        with self.assertRaises(DeliveryProviderError) as raised:
            self._run(PENDING, services)
        self.assertIn("Rider Not Available", str(raised.exception))
        self.assertTrue(raised.exception.retryable)



class PhoneNumbersTests(unittest.TestCase):
    """Pidge's own examples are ten digits. Ours were stored three ways: a
    branch as "0" + ten digits, a customer as "+91" + ten, a few with spaces.
    Found checking the live test branch before booking anything."""

    def test_every_way_an_indian_mobile_is_written_becomes_ten_digits(self) -> None:
        for written in ("09876543210", "+919876543210", "919876543210", "98765 43210", "+91 98765-43210", "9876543210"):
            self.assertEqual(pidge_mobile(written), "9876543210", written)

    def test_something_that_is_not_an_indian_mobile_is_sent_as_it_was(self) -> None:
        # Refusing here would lose the order; Pidge says what is wrong with it.
        self.assertEqual(pidge_mobile("+14165550123"), "+14165550123")
        self.assertEqual(pidge_mobile(""), "")

if __name__ == "__main__":
    unittest.main()
