"""Two more from one screenshot: the cart question, and a leaked tool name.

    >>> Please
    Ready to check out? Your cart contains 1 x Money Bags - $9.49.
    Subtotal: $9.49. Call place_order now to proceed with payment.

    >>> Show my cart
    That is everything I need to place your order.

    >>> I want to see my cart
    That is everything I need to place your order.

"Call place_order now" is an instruction the model wrote to itself and sent
to a customer, who cannot call anything. And asking twice to SEE the cart got
the same sentence twice, neither time the cart.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.loop import names_a_tool
from app.services.ordering_agent.tools import TOOLS


class AToolNameIsNeverSaidToACustomerTests(unittest.TestCase):
    def test_the_sentence_from_the_thread(self) -> None:
        self.assertEqual(
            names_a_tool(
                "Ready to check out? Your cart contains 1 x Money Bags - $9.49. "
                "Subtotal: $9.49. Call place_order now to proceed with payment."
            ),
            "place_order",
        )

    def test_every_tool_the_agent_runs_is_caught(self) -> None:
        # Read off the registry, so a tool added later is covered without
        # this test being edited — which is the whole reason it reads the
        # registry rather than a list of names.
        for tool in TOOLS:
            if "_" not in tool:
                continue
            with self.subTest(tool=tool):
                self.assertEqual(names_a_tool(f"Let me {tool} for you."), tool)

    def test_ordinary_sentences_are_left_alone(self) -> None:
        for said in (
            "Added 1 x Money Bags to your order. Anything else?",
            "Your cart: 1 x Money Bags - $9.49. Subtotal: $9.49. Shall I place it?",
            "Here is what we have: Pad Thai Veg - $13.84.",
            "We are closed for delivery right now. The next time I can do is 11:00.",
            "Your order is placed and comes to $11.70. The payment link is just below.",
        ):
            with self.subTest(said=said[:40]):
                self.assertIsNone(names_a_tool(said))

    def test_the_words_alone_are_not_enough(self) -> None:
        # "place" and "order" are ordinary English and appear constantly. The
        # underscore is what makes a hit certain rather than likely.
        self.assertIsNone(names_a_tool("Shall I place your order?"))
        self.assertIsNone(names_a_tool("I will add that to your cart."))
        self.assertIsNone(names_a_tool("Let me view your order."))


class ThereIsAlwaysAToolToName(unittest.TestCase):
    """The guard is only worth having while the registry has underscores."""

    def test_the_registry_still_looks_the_way_the_guard_assumes(self) -> None:
        self.assertTrue(
            [tool for tool in TOOLS if "_" in tool],
            "no tool name carries an underscore any more; the guard needs rethinking",
        )


if __name__ == "__main__":
    unittest.main()
