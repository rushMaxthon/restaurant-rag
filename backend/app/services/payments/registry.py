"""Maps a payment method to the gateway that settles it.

Only CARD (Stripe) and COD are supported. COD resolves to ``None`` — it is the
absence of a provider, not a provider — and every other method is rejected at
the API boundary so a client cannot smuggle in an unimplemented gateway.
"""

from __future__ import annotations

from app.config import get_settings
from app.models.enums import PaymentMethod
from app.services.payments.base import PaymentProvider
from app.services.payments.stripe_provider import PROVIDER_NAME as STRIPE_PROVIDER_NAME
from app.services.payments.stripe_provider import StripeProvider

COD_PROVIDER_NAME = "cod"

# Methods this deployment actually settles. GOOGLE_PAY and RAZORPAY remain in
# the database enum for historical orders but are not offered or accepted.
SUPPORTED_PAYMENT_METHODS: frozenset[PaymentMethod] = frozenset(
    {PaymentMethod.CARD, PaymentMethod.COD}
)

_stripe_provider: StripeProvider | None = None


def get_stripe_provider() -> StripeProvider:
    global _stripe_provider
    if _stripe_provider is None:
        _stripe_provider = StripeProvider()
    return _stripe_provider


def resolve_provider(method: PaymentMethod) -> PaymentProvider | None:
    """Provider for a method, or ``None`` for COD."""

    if method == PaymentMethod.COD:
        return None
    if method == PaymentMethod.CARD:
        return get_stripe_provider()
    raise ValueError(f"Unsupported payment method: {method}")


def provider_name_for(method: PaymentMethod) -> str:
    if method == PaymentMethod.COD:
        return COD_PROVIDER_NAME
    if method == PaymentMethod.CARD:
        return STRIPE_PROVIDER_NAME
    raise ValueError(f"Unsupported payment method: {method}")


def is_method_supported(method: PaymentMethod) -> bool:
    return method in SUPPORTED_PAYMENT_METHODS


def available_payment_methods() -> list[PaymentMethod]:
    """Supported methods that are actually usable right now.

    CARD drops out when Stripe is unconfigured, so a deployment without keys
    reports card as unavailable rather than showing a button that cannot work.
    COD is a business decision (`enable_cash_on_delivery`) and is off by
    default: it used to be unconditional, which meant an order could complete
    with no payment step at all whenever Stripe was not set up.
    """

    methods: list[PaymentMethod] = []
    if get_stripe_provider().is_configured():
        methods.append(PaymentMethod.CARD)
    if get_settings().enable_cash_on_delivery:
        methods.append(PaymentMethod.COD)
    return methods
