"""The AI Manager writes each restaurant's figures in that restaurant's money.

`money()` used to read `settings.payment_currency`, a single global from when
the platform served one restaurant. Every owner therefore read their takings
under the same symbol: a Surat kitchen's ₹1,20,000 week was narrated as
"$120,000" — the right number under the wrong symbol, which reads as a real
figure and is wrong by two orders of magnitude.

The currency is now bound once where a restaurant is resolved and read from a
ContextVar by the 116 call sites that build sentences. What is tested here is
the part that can silently rot:

- the symbol and the grouping follow the bound currency, including India's
  2-2-3 grouping, which `f"{x:,}"` gets wrong;
- an unbound path still writes something, in the platform default, rather
  than raising in the middle of a briefing;
- and — the shape of the bug most likely to come back — a loop that walks
  several restaurants rebinds for each one, instead of binding above the loop
  and stamping the first restaurant's currency on everybody's numbers.
"""

from __future__ import annotations

import unittest

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.currency import format_rounded_amount
from app.services.insights import rules


class MoneyFollowsTheBoundCurrencyTests(unittest.TestCase):
    def tearDown(self) -> None:
        rules.bind_narration_currency(None)

    def test_the_symbol_is_the_bound_restaurants(self) -> None:
        rules.bind_narration_currency("INR")
        self.assertEqual(rules.money(35), "₹35")

        rules.bind_narration_currency("GBP")
        self.assertEqual(rules.money(35), "£35")

    def test_indian_grouping_is_two_two_three(self) -> None:
        # The reason this cannot be `f"{value:,}"`: that writes ₹1,234,567 for
        # a number an Indian owner reads as ₹12,34,567.
        rules.bind_narration_currency("INR")
        self.assertEqual(rules.money(1234567), "₹12,34,567")

        rules.bind_narration_currency("USD")
        self.assertEqual(rules.money(1234567), "$1,234,567")

    def test_prose_gets_whole_units_and_no_sign(self) -> None:
        """A sentence says "down by $980", not "-$980.40"."""

        rules.bind_narration_currency("USD")
        self.assertEqual(rules.money(-980.4), "$980")
        self.assertEqual(rules.money(980.6), "$981")

    def test_an_unbound_path_falls_back_rather_than_failing(self) -> None:
        rules.bind_narration_currency(None)
        self.assertEqual(rules.narration_currency(), rules.settings.payment_currency)
        # Still a figure, not an exception — no briefing is worth failing over
        # a symbol.
        self.assertTrue(rules.money(100))

    def test_an_unknown_code_renders_rather_than_raising(self) -> None:
        """Written before the catalog knew it, or written by hand.

        `currency_for` is deliberately tolerant where `normalize_currency` is
        strict: this reads rows that already exist, and a code the catalog does
        not hold must not stop a briefing from rendering.
        """

        rules.bind_narration_currency("XYZ")
        self.assertTrue(rules.money(100))


class ABatchRebindsPerRestaurantTests(unittest.TestCase):
    """The shape of the mistake, not the call site that made it.

    Binding above a loop rather than inside it is invisible on a platform
    where every restaurant shares a currency, and wrong on every figure the
    moment one does not.
    """

    def tearDown(self) -> None:
        rules.bind_narration_currency(None)

    def test_each_restaurant_in_a_run_gets_its_own_symbol(self) -> None:
        platform = [("INR", 1200), ("USD", 1200), ("GBP", 1200)]

        written = []
        for code, amount in platform:
            rules.bind_narration_currency(code)
            written.append(rules.money(amount))

        self.assertEqual(written, ["₹1,200", "$1,200", "£1,200"])
        # If the binding had been hoisted out of the loop these would all be
        # the same string, which is exactly what the bug looked like.
        self.assertEqual(len(set(written)), 3)


class OneSymbolTableTests(unittest.TestCase):
    def test_the_narration_uses_the_currency_catalog(self) -> None:
        """There used to be a second symbol table inside `rules.py`.

        Two tables drift: the one in `rules` knew AUD and not AED, so a Dubai
        restaurant's briefing would have said "USD 400" while its menu said
        "د.إ400".
        """

        self.assertFalse(hasattr(rules, "CURRENCY_SYMBOLS"))
        rules.bind_narration_currency("AED")
        self.assertEqual(rules.money(400), format_rounded_amount(400, "AED"))


if __name__ == "__main__":
    unittest.main()
