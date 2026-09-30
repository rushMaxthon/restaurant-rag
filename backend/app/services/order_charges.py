"""What a customer is charged, itemised, in one place.

Every food app shows a bill like this: a subtotal, a delivery fee, and then a
single line covering tax and the small charges, which opens to reveal what it is
made of. The line exists because four extra rows on a checkout look like
nickel-and-diming; the breakdown exists because a total nobody can take apart is
a total nobody trusts.

Until now this app charged a flat 5% written into `orders.py` and nothing else.
That is not a bill, it is a placeholder, and it was wrong in both directions: a
restaurant that packages its food paid for the boxes out of its margin, and the
platform earned nothing per order.

**Everything here is configured, nothing is assumed.** Four figures live on the
branch and an operator sets them. The defaults reproduce exactly what was
charged before — 5% tax, no packaging, no platform fee — so switching the code
in changes no existing restaurant's prices until somebody deliberately edits
them.

**What is taxed, and what is not.** The distinction costs money if it is wrong:

* **Food tax** applies to the subtotal AFTER discount, because a customer who
  paid less is taxed on less. Taxing before the discount overcharges them.
* **Delivery tax** applies to the delivery fee alone, at its own rate. In India
  that is 18% on the service where food is 5%, and folding them together
  produces a figure that matches no invoice.
* **The platform fee is inclusive of its own tax** and is not taxed again.
  Charging tax on top of a fee already described as inclusive is charging twice.
* **Packaging is the restaurant's charge**, taxed at the food rate because that
  is what it is part of.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


def _money(value: Decimal | float | int | None) -> Decimal:
    """Two places, rounded the way a customer expects.

    ROUND_HALF_UP rather than banker's rounding, because these figures sit in a
    column somebody adds up by eye. Half a paisa going to the nearest even
    number is correct and looks like an error.
    """

    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class ChargeLine:
    """One row of the breakdown a customer can open.

    `note` is the sentence under the row. It is not decoration: a platform fee
    with no explanation reads as a made-up number, and a tax line that does not
    say the platform has no say in the rate invites a complaint aimed at the
    wrong party.
    """

    key: str
    label: str
    amount: Decimal
    note: str = ""


@dataclass(slots=True)
class OrderCharges:
    """The whole bill, and the parts of it worth showing separately."""

    subtotal: Decimal
    discount_amount: Decimal
    delivery_fee: Decimal
    packaging_fee: Decimal
    platform_fee: Decimal
    #: Tax on the food, after discount.
    food_tax: Decimal
    #: Tax on the delivery fee, at its own rate.
    delivery_tax: Decimal
    total_amount: Decimal
    lines: list[ChargeLine] = field(default_factory=list)

    @property
    def tax_amount(self) -> Decimal:
        """Everything behind the single collapsed line.

        Named for the column it is stored in, which predates this module and
        holds the same idea: the part of the bill that is neither the food nor
        the delivery.
        """

        return _money(self.packaging_fee + self.platform_fee + self.food_tax + self.delivery_tax)


def _percent_of(amount: Decimal, percent: Decimal) -> Decimal:
    if amount <= 0 or percent <= 0:
        return Decimal("0.00")
    return _money(amount * percent / Decimal("100"))


def compute(
    *,
    subtotal: Decimal,
    delivery_fee: Decimal,
    discount_amount: Decimal,
    packaging_fee: Decimal,
    platform_fee: Decimal,
    tax_percent: Decimal,
    delivery_tax_percent: Decimal,
    currency_label: str = "",
) -> OrderCharges:
    """Work out the bill from the branch's own numbers.

    Pure arithmetic over values the caller has already read. Nothing here
    touches a database or a setting, so the rule is testable on its own and one
    reading of it is the whole truth about what a customer pays.
    """

    subtotal = _money(subtotal)
    delivery_fee = _money(delivery_fee)
    discount_amount = _money(discount_amount)
    packaging_fee = _money(packaging_fee)
    platform_fee = _money(platform_fee)

    # A discount cannot take the food below zero, and it applies to the food
    # rather than to the fees: a coupon is off the meal, not off the courier.
    taxable_food = max(Decimal("0.00"), subtotal - discount_amount) + packaging_fee
    food_tax = _percent_of(taxable_food, _money(tax_percent))
    delivery_tax = _percent_of(delivery_fee, _money(delivery_tax_percent))

    total = _money(
        subtotal
        - discount_amount
        + delivery_fee
        + packaging_fee
        + platform_fee
        + food_tax
        + delivery_tax
    )

    lines: list[ChargeLine] = []
    if packaging_fee > 0:
        lines.append(
            ChargeLine(
                key="packaging",
                label="Restaurant packaging",
                amount=packaging_fee,
                note="Charged by the restaurant for the boxes and bags your food travels in.",
            )
        )
    if platform_fee > 0:
        lines.append(
            ChargeLine(
                key="platform_fee",
                label="Platform fee",
                amount=platform_fee,
                # Said plainly because the alternative is a customer assuming it
                # is a tax, or that the restaurant is keeping it.
                note="Inclusive of tax. This is what it costs to run the service.",
            )
        )
    if food_tax > 0:
        lines.append(
            ChargeLine(
                key="food_tax",
                label="Restaurant GST",
                amount=food_tax,
                # The rate is set by government, not by anybody in this app, and
                # saying so sends the complaint to the right place.
                note="Set by the government on restaurant food. We do not choose this rate.",
            )
        )
    if delivery_tax > 0:
        lines.append(
            ChargeLine(
                key="delivery_tax",
                label="GST on delivery fee",
                amount=delivery_tax,
                note="Charged on the delivery service at its own rate.",
            )
        )

    return OrderCharges(
        subtotal=subtotal,
        discount_amount=discount_amount,
        delivery_fee=delivery_fee,
        packaging_fee=packaging_fee,
        platform_fee=platform_fee,
        food_tax=food_tax,
        delivery_tax=delivery_tax,
        total_amount=total,
        lines=lines,
    )


def for_location(
    location,
    *,
    subtotal: Decimal,
    delivery_fee: Decimal,
    discount_amount: Decimal,
) -> OrderCharges:
    """The same bill, from a branch's configured rates.

    `getattr` with a default on every rate, so a branch row written before these
    columns existed still prices correctly rather than raising in a checkout.
    The defaults are the behaviour that was there before: 5% on food, nothing
    else.
    """

    return compute(
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        discount_amount=discount_amount,
        packaging_fee=getattr(location, "packaging_fee", None) or Decimal("0.00"),
        platform_fee=getattr(location, "platform_fee", None) or Decimal("0.00"),
        tax_percent=(
            location.tax_percent
            if getattr(location, "tax_percent", None) is not None
            else Decimal("5.00")
        ),
        delivery_tax_percent=getattr(location, "delivery_tax_percent", None) or Decimal("0.00"),
    )


__all__ = ["ChargeLine", "OrderCharges", "compute", "for_location"]
