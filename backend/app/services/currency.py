"""What a restaurant charges in, and how that money is written.

`payment_currency` has been a single global setting since the platform served
one restaurant. It stopped being true the moment a Surat dhokla shop was
onboarded beside a Bangkok noodle bar: the menu is priced in rupees and the
storefront rendered it as "$35.00" — the right number under the wrong symbol,
which is worse than either being wrong on its own, because it reads as a
price a customer could agree to.

Currency lives on the **restaurant**, not on the app client. It follows from
where the business operates, exactly like its address, and an app client is
the build configuration an administrator set up. It is also not an owner's
preference: changing it does not convert a single price, it relabels every one
of them, so it is admin-writable and onboarding sets it once.

**Past orders keep the currency they were charged in.** `orders.currency` is
stamped at creation and read by every payment path already; nothing here
rewrites it. A restaurant that switches currency has old orders in the old one,
which is the truth of what happened.

The catalog is closed on purpose. A free-text currency code reaches Stripe,
where a wrong one is a failed charge at the worst possible moment, and reaches
`Intl.NumberFormat`, where it silently renders the code instead of a symbol.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Currency:
    """One currency, and everything a client needs to render it."""

    code: str
    symbol: str
    # The locale carries the GROUPING rule, not the symbol. This matters more
    # than it looks: Indian grouping is 2-2-3, so ₹12,34,567 — an `en-US`
    # locale would write ₹1,234,567 and look foreign to the customer it is
    # being shown to.
    locale: str
    # Whole rupees are how an Indian menu is written: ₹35, not ₹35.00. Cents
    # are how a dollar menu is written, including $16.00. So the minimum is
    # per currency and the maximum stays at 2 either way, because a total with
    # paise still has to be printable.
    min_fraction_digits: int


CURRENCIES: dict[str, Currency] = {
    "INR": Currency(code="INR", symbol="₹", locale="en-IN", min_fraction_digits=0),
    "USD": Currency(code="USD", symbol="$", locale="en-US", min_fraction_digits=2),
    "CAD": Currency(code="CAD", symbol="$", locale="en-CA", min_fraction_digits=2),
    "GBP": Currency(code="GBP", symbol="£", locale="en-GB", min_fraction_digits=2),
    "EUR": Currency(code="EUR", symbol="€", locale="en-IE", min_fraction_digits=2),
    "AED": Currency(code="AED", symbol="د.إ", locale="en-AE", min_fraction_digits=2),
}

DEFAULT_CURRENCY_CODE = "USD"


class CurrencyNotSupported(ValueError):
    """A currency this platform will not store."""


def normalize_currency(value: str | None) -> str:
    """A submitted code as it is stored: upper case, and known.

    Refuses rather than falling back. A silent fallback here would put a
    restaurant's prices under the wrong symbol and give nobody a reason to
    look, which is the bug this module exists to fix.
    """

    code = (value or "").strip().upper()
    if not code:
        raise CurrencyNotSupported("Choose a currency.")
    if code not in CURRENCIES:
        supported = ", ".join(sorted(CURRENCIES))
        raise CurrencyNotSupported(f"'{code}' is not supported. Choose one of: {supported}.")
    return code


def currency_for(code: str | None) -> Currency:
    """The catalog entry for a stored code, or the platform default.

    Tolerant where `normalize_currency` is strict, because this reads rows
    that already exist: a code written before it was in the catalog must not
    stop a page from rendering. It renders in the default instead, which is
    visibly wrong rather than invisibly broken.
    """

    return CURRENCIES.get((code or "").strip().upper(), CURRENCIES[DEFAULT_CURRENCY_CODE])


def format_amount(amount: float, code: str | None) -> str:
    """Money as a person reads it, for the server-side text paths.

    The AI Manager's narration and the WhatsApp agent both write prices into
    sentences, so they cannot hand a number to a client formatter. Grouping is
    done here rather than with `f"{amount:,.2f}"` because that is 3-3-3 and
    would write ₹1,234,567 for a number an Indian customer reads as ₹12,34,567.
    """

    currency = currency_for(code)
    quantized = round(float(amount), 2)
    whole, fraction = divmod(round(abs(quantized) * 100), 100)
    grouped = _group(whole, currency)

    if fraction or currency.min_fraction_digits:
        grouped = f"{grouped}.{fraction:02d}"

    sign = "-" if quantized < 0 else ""
    return f"{sign}{currency.symbol}{grouped}"


def format_rounded_amount(amount: float, code: str | None) -> str:
    """The same money, to the nearest whole unit, for prose.

    "Dinner took $12,340 last week" is how a person says it; "$12,340.00" is
    how a ledger says it, and the AI Manager is writing sentences. Separate
    from `format_amount` rather than a flag on it because the two have
    different readers, and a flag would let a price list quietly lose its
    cents.

    Sign is dropped: the narration's wording carries direction ("down by"),
    and a minus in the middle of a sentence reads as a typo.
    """

    currency = currency_for(code)
    return f"{currency.symbol}{_group(round(abs(float(amount))), currency)}"


def _group(whole: int, currency: Currency) -> str:
    """Digit grouping for one currency's locale.

    Indian grouping is 2-2-3, not 3-3-3, so this cannot be `f"{whole:,}"`
    for every currency: that writes ₹1,234,567 for a number read as
    ₹12,34,567.
    """

    if currency.locale != "en-IN":
        return f"{whole:,}"

    digits = str(whole)
    if len(digits) <= 3:
        return digits
    # The last three digits group normally; everything above them goes in
    # pairs. 1234567 -> "12,34,567".
    head, tail = digits[:-3], digits[-3:]
    pairs: list[str] = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join(pairs) + "," + tail


__all__ = [
    "CURRENCIES",
    "DEFAULT_CURRENCY_CODE",
    "Currency",
    "CurrencyNotSupported",
    "currency_for",
    "format_amount",
    "normalize_currency",
]
