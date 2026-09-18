"""Which gateway settles a method, for which restaurant.

This used to be a module-level singleton built from one set of keys, which is
correct for a platform with one restaurant and cannot be made correct for a
platform with many: the account varies per order.

**`resolve_provider(method)` was deleted rather than kept working.** It took no
restaurant, so every call site that still used it would have quietly charged
the platform's account instead of the restaurant's — a misroute that produces
no error, no log line and no failing test, and is discovered when somebody
reconciles a bank statement. Removing the name turns every one of those sites
into an ImportError the moment the file is loaded. That is the whole reason it
is gone instead of deprecated.

Two layers, deliberately:

- `provider_for(db, restaurant_id, method)` — the restaurant's own account.
- `platform_provider_for(method)` — this deployment's keys, used only while
  `payments_require_restaurant_account` is off. That is the transition: every
  restaurant onboarded before gateway accounts existed keeps taking payments,
  and the admin screen says plainly which account is settling them. Turning
  the setting on makes a restaurant without its own account unable to take
  card, which is the correct end state and a deliberate switch to throw.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import PaymentGateway, PaymentMethod
from app.models.restaurant_location import RestaurantLocation
from app.services.payments.base import PaymentProvider
from app.services.payments.razorpay_provider import PROVIDER_NAME as RAZORPAY_PROVIDER_NAME
from app.services.payments.razorpay_provider import RazorpayProvider
from app.services.payments.stripe_provider import PROVIDER_NAME as STRIPE_PROVIDER_NAME
from app.services.payments.stripe_provider import StripeProvider

COD_PROVIDER_NAME = "cod"

# Methods this deployment settles. GOOGLE_PAY stays out on purpose: Razorpay's
# own checkout already offers Google Pay through UPI, so a separate button
# would be a second door to the same place, with its own integration to keep
# working. It remains in the database enum for historical orders.
SUPPORTED_PAYMENT_METHODS: frozenset[PaymentMethod] = frozenset(
    {PaymentMethod.CARD, PaymentMethod.RAZORPAY, PaymentMethod.COD}
)

# Which gateway settles which method. CARD is Stripe's card sheet; RAZORPAY is
# Razorpay's own checkout, which covers UPI, netbanking, wallets and Indian
# cards behind one button — that is why it is a method here and not just a
# gateway.
GATEWAY_FOR_METHOD: dict[PaymentMethod, PaymentGateway] = {
    PaymentMethod.CARD: PaymentGateway.STRIPE,
    PaymentMethod.RAZORPAY: PaymentGateway.RAZORPAY,
}


def build_provider(gateway: PaymentGateway, credentials) -> PaymentProvider:
    """A provider bound to one restaurant's credentials.

    Public because the webhook path needs it too: it has already resolved the
    restaurant from the URL and holds the credentials, so it builds directly
    rather than going back through `provider_for`, which would re-read them
    and apply the enabled check a webhook must not apply.
    """

    if gateway == PaymentGateway.STRIPE:
        return StripeProvider(
            secret_key=credentials.secret_key,
            webhook_secret=credentials.webhook_secret,
        )
    return RazorpayProvider(
        key_id=credentials.public_key,
        key_secret=credentials.secret_key,
        webhook_secret=credentials.webhook_secret,
    )


def platform_provider_for(method: PaymentMethod) -> PaymentProvider | None:
    """This deployment's own account, for a restaurant that has none yet.

    Only Stripe: there is no platform Razorpay account and there should not be
    one. A restaurant taking UPI is taking its own money, and the fallback
    exists for continuity with what already shipped, not as a way to route a
    new gateway's payments through the platform.
    """

    if method == PaymentMethod.CARD:
        return StripeProvider()
    return None


def provider_for(
    db: Session,
    *,
    restaurant_id: uuid.UUID | None,
    method: PaymentMethod,
) -> PaymentProvider | None:
    """The gateway that settles this method for this restaurant.

    None means the restaurant cannot take this method — no account, switched
    off, or credentials that no longer decrypt. Callers treat None as "not
    available" rather than as an error, because that is what the customer
    needs to be told.

    COD resolves to None too, and always has: it is the absence of a gateway,
    not a gateway. Callers distinguish the two by the method, never by the
    return value.
    """

    if method == PaymentMethod.COD:
        return None

    gateway = GATEWAY_FOR_METHOD.get(method)
    if gateway is None:
        raise ValueError(f"Unsupported payment method: {method}")

    if restaurant_id is not None:
        # Imported here rather than at module scope: `payment_accounts` imports
        # the secrets service, which imports settings, and a cycle through this
        # module is easy to create and annoying to find.
        from app.services.payment_accounts import read_credentials

        credentials = read_credentials(db, restaurant_id=restaurant_id, gateway=gateway)
        if credentials is not None:
            provider = build_provider(gateway, credentials)
            return provider if provider.is_configured() else None

    if get_settings().payments_require_restaurant_account:
        return None

    # Configured, not merely present. Returning an unconfigured provider makes
    # `available_payment_methods` truthy and puts a card button on a checkout
    # that has no keys behind it — which is the exact failure the deployment
    # check was written to prevent, reintroduced one level up.
    fallback = platform_provider_for(method)
    return fallback if fallback is not None and fallback.is_configured() else None


def settles_with_own_account(
    db: Session, *, restaurant_id: uuid.UUID | None, method: PaymentMethod
) -> bool:
    """Whether this restaurant's own account takes the money.

    Read by the admin screen so "you are still being settled through the
    platform" is visible rather than something an operator finds out later.
    """

    if restaurant_id is None or method == PaymentMethod.COD:
        return False
    gateway = GATEWAY_FOR_METHOD.get(method)
    if gateway is None:
        return False

    from app.services.payment_accounts import read_credentials

    return read_credentials(db, restaurant_id=restaurant_id, gateway=gateway) is not None


def available_payment_methods(
    db: Session,
    *,
    restaurant_id: uuid.UUID | None = None,
    location: RestaurantLocation | None = None,
) -> list[PaymentMethod]:
    """What this restaurant can actually take right now.

    Two things have to agree, and both are deliberate:

    - the branch has the method switched on (`RestaurantLocation` has carried
      these toggles all along), and
    - a gateway is configured that can settle it.

    A method missing either is not offered, rather than shown as a button that
    fails at the last step. Which is the answer to "show the methods that are
    enabled": enabled means both halves, because a toggle with no credentials
    behind it is not an enabled payment method, it is a promise.
    """

    methods: list[PaymentMethod] = []

    card_allowed = location.card_payment_enabled if location is not None else True
    if card_allowed and provider_for(db, restaurant_id=restaurant_id, method=PaymentMethod.CARD):
        methods.append(PaymentMethod.CARD)

    razorpay_allowed = location.razorpay_enabled if location is not None else True
    if razorpay_allowed and provider_for(
        db, restaurant_id=restaurant_id, method=PaymentMethod.RAZORPAY
    ):
        methods.append(PaymentMethod.RAZORPAY)

    # COD needs no gateway, so it is the one method a branch toggle decides on
    # its own — under the deployment-wide switch, which exists because an
    # always-available COD once meant an order could complete with no payment
    # step at all whenever the gateway was unconfigured.
    cod_allowed = location.cash_on_delivery_enabled if location is not None else True
    if cod_allowed and get_settings().enable_cash_on_delivery:
        methods.append(PaymentMethod.COD)

    return methods


def provider_name_for(method: PaymentMethod) -> str:
    if method == PaymentMethod.COD:
        return COD_PROVIDER_NAME
    if method == PaymentMethod.CARD:
        return STRIPE_PROVIDER_NAME
    if method == PaymentMethod.RAZORPAY:
        return RAZORPAY_PROVIDER_NAME
    raise ValueError(f"Unsupported payment method: {method}")


def is_method_supported(method: PaymentMethod) -> bool:
    return method in SUPPORTED_PAYMENT_METHODS


__all__ = [
    "COD_PROVIDER_NAME",
    "build_provider",
    "GATEWAY_FOR_METHOD",
    "SUPPORTED_PAYMENT_METHODS",
    "available_payment_methods",
    "is_method_supported",
    "platform_provider_for",
    "provider_for",
    "provider_name_for",
    "settles_with_own_account",
]
