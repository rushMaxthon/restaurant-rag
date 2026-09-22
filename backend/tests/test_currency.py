"""What a restaurant charges in, and how that money is written.

`payment_currency` was one global setting, which was right while the platform
served one restaurant. It stopped being right the moment a Surat dhokla shop
was onboarded beside a Bangkok noodle bar: the menu is priced in rupees and
every price rendered as "$35.00" — the right number under the wrong symbol,
which is worse than either being wrong alone, because it reads as a price a
customer could agree to.

Two things here are load-bearing rather than cosmetic. The catalog is closed,
because a currency code reaches Stripe, where a wrong one is a declined charge
at checkout rather than a rendering glitch. And the grouping comes from the
currency, not from a global locale: Indian grouping is 2-2-3, so a number an
Indian customer reads as ₹12,34,567 would otherwise be written ₹1,234,567.
"""

from __future__ import annotations

import unittest

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.currency import (
    CURRENCIES,
    DEFAULT_CURRENCY_CODE,
    CurrencyNotSupported,
    currency_for,
    format_amount,
    normalize_currency,
)


class AcceptingACurrencyTests(unittest.TestCase):
    def test_a_supported_code_is_stored_upper_case(self) -> None:
        self.assertEqual(normalize_currency("inr"), "INR")
        self.assertEqual(normalize_currency("  Inr  "), "INR")

    def test_an_unsupported_code_is_refused_not_defaulted(self) -> None:
        """Refusing is the point.

        A silent fallback would put a restaurant's whole menu under the wrong
        symbol and give nobody a reason to look — the exact bug this module
        exists to fix, reintroduced by its own error handling.
        """

        with self.assertRaises(CurrencyNotSupported) as caught:
            normalize_currency("XYZ")
        # The message names what IS allowed, so the fix is obvious.
        self.assertIn("INR", str(caught.exception))

    def test_nothing_is_refused_rather_than_guessed(self) -> None:
        for value in (None, "", "   "):
            with self.assertRaises(CurrencyNotSupported):
                normalize_currency(value)


class ReadingAStoredCurrencyTests(unittest.TestCase):
    """Tolerant where accepting is strict, because these are existing rows."""

    def test_a_known_code_reads_back(self) -> None:
        self.assertEqual(currency_for("inr").code, "INR")

    def test_an_unknown_code_falls_back_rather_than_raising(self) -> None:
        # A row written before a code was in the catalog must not stop a page
        # from rendering. Visibly wrong beats invisibly broken.
        self.assertEqual(currency_for("XYZ").code, DEFAULT_CURRENCY_CODE)
        self.assertEqual(currency_for(None).code, DEFAULT_CURRENCY_CODE)

    def test_every_catalog_entry_is_complete(self) -> None:
        for code, currency in CURRENCIES.items():
            self.assertEqual(currency.code, code)
            self.assertTrue(currency.symbol, code)
            self.assertTrue(currency.locale, code)
            self.assertIn(currency.min_fraction_digits, (0, 2), code)


class WritingMoneyTests(unittest.TestCase):
    def test_indian_grouping_is_two_two_three(self) -> None:
        # The whole reason locale is stored per currency. An `en-US` grouping
        # writes this as ₹1,234,567, which an Indian reader has to count.
        self.assertEqual(format_amount(1234567, "INR"), "₹12,34,567")
        self.assertEqual(format_amount(12345, "INR"), "₹12,345")
        self.assertEqual(format_amount(123456789, "INR"), "₹12,34,56,789")

    def test_western_grouping_is_threes(self) -> None:
        self.assertEqual(format_amount(1234567, "USD"), "$1,234,567.00")

    def test_whole_rupees_carry_no_decimal(self) -> None:
        """₹35, not ₹35.00 — which is how an Indian menu is written."""

        self.assertEqual(format_amount(35, "INR"), "₹35")
        self.assertEqual(format_amount(0, "INR"), "₹0")

    def test_paise_still_print_when_there_are_any(self) -> None:
        # Dropping the minimum must not mean dropping real fractions: a total
        # of ₹240.50 is not ₹240.
        self.assertEqual(format_amount(240.5, "INR"), "₹240.50")

    def test_dollars_always_carry_cents(self) -> None:
        self.assertEqual(format_amount(16, "USD"), "$16.00")

    def test_a_negative_keeps_its_sign_outside_the_symbol(self) -> None:
        self.assertEqual(format_amount(-99, "INR"), "-₹99")
        self.assertEqual(format_amount(-99, "USD"), "-$99.00")

    def test_an_unknown_currency_writes_in_the_default(self) -> None:
        self.assertEqual(format_amount(10, "XYZ"), format_amount(10, DEFAULT_CURRENCY_CODE))


if __name__ == "__main__":
    unittest.main()
