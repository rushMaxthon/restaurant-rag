"""The ordering chat writes prices in the restaurant's own money.

From a real WhatsApp thread on a +91 number. The customer asked for the menu
and it was read out to them:

    - Appetizer Sampler - $18.99
    - Chicken Wings - $11.99
    ...
    - Money Bags - $9.49

`_money` formatted every figure this agent ever says, and it was
`f"${float(value):.2f}"` — a literal dollar sign, from when the platform
served one restaurant in one country. The number is right and the symbol is
wrong, which is worse than either being wrong alone: it reads as a real price
a customer could agree to, and on a rupee menu it is out by two orders of
magnitude.

Bound per turn rather than passed as an argument, for the same reason the AI
Manager's narration binds its own: `_money` is called from a dozen sentence
builders and from closures inside `run_turn`, and not one of them holds a
restaurant. The currency belongs to the conversation, not to each figure in
it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent import loop


class MoneyFollowsTheBoundCurrencyTests(unittest.TestCase):
    def tearDown(self) -> None:
        loop.bind_chat_currency(None)

    def test_a_rupee_menu_is_read_out_in_rupees(self) -> None:
        loop.bind_chat_currency("INR")
        self.assertEqual(loop._money("9.49"), "₹9.49")
        self.assertEqual(loop._money(250), "₹250")

    def test_indian_grouping_is_two_two_three(self) -> None:
        # The reason this cannot be `f"{value:,.2f}"`: that is 3-3-3 and
        # writes ₹1,234,567 for a number read as ₹12,34,567.
        loop.bind_chat_currency("INR")
        self.assertEqual(loop._money(1234567), "₹12,34,567")

    def test_the_other_currencies_keep_their_own_symbols(self) -> None:
        for code, expected in (("USD", "$9.49"), ("GBP", "£9.49"), ("EUR", "€9.49")):
            with self.subTest(code=code):
                loop.bind_chat_currency(code)
                self.assertEqual(loop._money("9.49"), expected)

    def test_an_unbound_turn_still_writes_a_price(self) -> None:
        # A test drives `run_turn` with `db=None`, and a restaurant row that
        # cannot be read is not worth failing a turn over. The platform
        # default is the honest answer, not an exception.
        loop.bind_chat_currency(None)
        self.assertTrue(loop._money("9.49"))

    def test_something_that_is_not_a_number_is_passed_through(self) -> None:
        loop.bind_chat_currency("INR")
        self.assertEqual(loop._money("ask us"), "ask us")


class TheTurnBindsItFromTheRestaurantTests(unittest.TestCase):
    """Where the value comes from, and what happens when it cannot."""

    def tearDown(self) -> None:
        loop.bind_chat_currency(None)

    def test_the_restaurants_row_is_what_is_read(self) -> None:
        scope = SimpleNamespace(restaurant_id="r1")
        db = SimpleNamespace(scalar=lambda *_a, **_k: "INR")
        self.assertEqual(loop._currency_for(db, scope), "INR")

    def test_no_database_means_the_platform_default(self) -> None:
        self.assertIsNone(loop._currency_for(None, SimpleNamespace(restaurant_id="r1")))

    def test_a_failing_read_does_not_break_the_turn(self) -> None:
        def boom(*_a, **_k):
            raise RuntimeError("the pooler is having a moment")

        scope = SimpleNamespace(restaurant_id="r1")
        self.assertIsNone(loop._currency_for(SimpleNamespace(scalar=boom), scope))


class EveryPriceInTheThreadGoesThroughItTests(unittest.TestCase):
    """No raw symbol left in the file.

    The bug was not that one sentence had a dollar sign; it was that five
    did, in a file whose other twelve figures already went through `_money`.
    A sixth added later is the same bug again, so this looks for the shape.
    """

    def test_no_literal_dollar_sign_survives_in_the_loop(self) -> None:
        source = (
            Path(loop.__file__).read_text(encoding="utf-8")
            if hasattr(loop, "__file__") else ""
        )
        offenders = [
            line.strip()
            for line in source.splitlines()
            # A price written straight into an f-string, e.g. `${d['price']}`
            # or `f"${x:.2f}"`. Prose mentioning a dollar in a comment is not
            # a price and does not match.
            if '${' in line and not line.lstrip().startswith("#")
        ]
        self.assertEqual(offenders, [], "a price is being written with a hardcoded symbol")


if __name__ == "__main__":
    unittest.main()
