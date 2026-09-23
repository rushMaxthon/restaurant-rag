"""A dish sold in sizes has no single price to quote.

    > Build Your Own Pizza
      Build Your Own Pizza is $14.99. Shall I add one?

$14.99 is the Small. The Large is $24.49. Saying one number for a dish that
has three, and offering to add it on a yes, is a quote a customer can act on
and be charged something else for — the same fault that put a Large in a cart
at the base price and then asked for the size all over again.

The read-back used for ONE matching dish took `price` off the row and said it.
That is right for a dish with one price and wrong for every sized one, and
nothing in the sentence distinguished them.

There is no wrong number now: a sized dish is offered, and the size question
that follows carries every price. `has_sizes` is a column on `menu_items`, so
this costs no extra query — the row being read out already knows.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.loop import bind_chat_currency, describe_single_dish


class ADishWithOnePriceTests(unittest.TestCase):
    """Unchanged, and the common case."""

    def setUp(self) -> None:
        bind_chat_currency("USD")

    def test_it_is_quoted_and_offered(self) -> None:
        said = describe_single_dish({"name": "Farmhouse Pizza", "price": "329.00"})
        self.assertIn("Farmhouse Pizza", said)
        self.assertIn("$329.00", said)
        self.assertIn("Shall I add one?", said)

    def test_an_explicit_no_sizes_is_the_same(self) -> None:
        said = describe_single_dish(
            {"name": "Farmhouse Pizza", "price": "329.00", "has_sizes": False}
        )
        self.assertIn("$329.00", said)


class ADishWithSeveralPricesTests(unittest.TestCase):
    """The one that could overcharge somebody."""

    def setUp(self) -> None:
        bind_chat_currency("USD")

    def dish(self) -> dict:
        return {"name": "Build Your Own Pizza", "price": "14.99", "has_sizes": True}

    def test_no_price_is_quoted(self) -> None:
        # $14.99 is the Small of three. Any single figure here is a number the
        # customer can be charged something else for.
        said = describe_single_dish(self.dish())
        self.assertNotIn("14.99", said)
        self.assertNotIn("$", said)

    def test_it_still_names_the_dish(self) -> None:
        self.assertIn("Build Your Own Pizza", describe_single_dish(self.dish()))

    def test_it_still_moves_the_order_forward(self) -> None:
        # Naming a dish and being told only that it exists is a dead end.
        said = describe_single_dish(self.dish())
        self.assertTrue(said.rstrip().endswith("?"), said)

    def test_it_says_there_are_sizes_rather_than_picking_one(self) -> None:
        self.assertIn("size", describe_single_dish(self.dish()).lower())

    def test_it_asks_one_thing(self) -> None:
        self.assertEqual(describe_single_dish(self.dish()).count("?"), 1)


if __name__ == "__main__":
    unittest.main()
