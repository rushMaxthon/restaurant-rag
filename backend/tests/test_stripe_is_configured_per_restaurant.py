"""A restaurant's own Stripe keys decide whether it can take a card.

`StripeProvider` is built per restaurant — `build_provider` hands it the keys
read out of `restaurant_payment_accounts` — and then answered a question about
the platform:

    def __init__(self, *, secret_key=None, webhook_secret=None):
        self._secret_key = secret_key if secret_key is not None else settings.stripe_secret_key

    def is_configured(self) -> bool:
        return settings.stripe_is_configured        # its own key, unread

So `provider_for(...)` read a restaurant's credentials, built a provider around
them, and then asked the deployment whether IT had Stripe keys. On a platform
with none — which is every deployment that has moved to per-restaurant
settlement — `available_payment_methods` dropped CARD for a restaurant whose
own Stripe account was configured and enabled.

The sibling gateway shows the shape this should always have had:

    # RazorpayProvider
    def is_configured(self) -> bool:
        return bool(self._key_id and self._key_secret)

The publishable key is part of the answer, not an extra. The platform's own
check has always required both halves, and for good reason: the secret key
creates the PaymentIntent and the publishable key is what the customer's
browser confirms it with. A restaurant holding only a secret produced an intent
on its own account while `payments/config` fell back to the platform's
publishable key — two different accounts, and a confirmation that cannot
succeed. `save_account` stores `public_key` without requiring it, so that state
is reachable; it is now honestly "card unavailable" rather than a card button
that fails at the last step.
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

from app.config import get_settings
from app.services.payments.razorpay_provider import RazorpayProvider
from app.services.payments.stripe_provider import StripeProvider

settings = get_settings()

REAL_SECRET = "sk_test_51RestaurantOwnAccount"
REAL_PUBLISHABLE = "pk_test_51RestaurantOwnAccount"


class NoPlatformKeysAtAll:
    """The deployment that made this visible: settlement is per restaurant."""

    def __enter__(self):
        self._patches = [
            mock.patch.object(settings, "stripe_secret_key", "sk_test_mock"),
            mock.patch.object(settings, "stripe_publishable_key", "pk_test_mock"),
        ]
        for patch in self._patches:
            patch.start()
        assert not settings.stripe_is_configured, "the platform must look unconfigured here"
        return self

    def __exit__(self, *exc):
        for patch in reversed(self._patches):
            patch.stop()
        return False


class ARestaurantsOwnKeysAreEnoughTests(unittest.TestCase):
    """The reported bug."""

    def test_its_own_keys_configure_it_with_no_platform_account(self) -> None:
        with NoPlatformKeysAtAll():
            provider = StripeProvider(
                secret_key=REAL_SECRET, publishable_key=REAL_PUBLISHABLE
            )
            self.assertTrue(
                provider.is_configured(),
                "a restaurant with its own Stripe account could not take a card",
            )

    def test_the_platform_having_keys_does_not_configure_a_restaurant(self) -> None:
        # The same fault pointing the other way, and the more dangerous
        # direction: a card button backed by credentials that are not there.
        with mock.patch.object(settings, "stripe_secret_key", REAL_SECRET), mock.patch.object(
            settings, "stripe_publishable_key", REAL_PUBLISHABLE
        ):
            self.assertTrue(settings.stripe_is_configured)
            provider = StripeProvider(secret_key="", publishable_key="")
            self.assertFalse(provider.is_configured())


class WhatCountsAsConfiguredTests(unittest.TestCase):
    """The same standard the platform property applies, on the instance."""

    def test_placeholder_keys_are_not_credentials(self) -> None:
        # They ship as defaults so the app boots without Stripe.
        for secret, publishable in (
            ("sk_test_mock", REAL_PUBLISHABLE),
            (REAL_SECRET, "pk_test_mock"),
            ("sk_test_mock", "pk_test_mock"),
        ):
            with self.subTest(secret=secret, publishable=publishable):
                self.assertFalse(
                    StripeProvider(
                        secret_key=secret, publishable_key=publishable
                    ).is_configured()
                )

    def test_a_secret_with_no_publishable_key_cannot_be_completed(self) -> None:
        # The intent would be created on the restaurant's account and the
        # browser handed the platform's publishable key to confirm it with.
        with NoPlatformKeysAtAll():
            self.assertFalse(
                StripeProvider(secret_key=REAL_SECRET, publishable_key="").is_configured()
            )

    def test_blank_and_whitespace_are_not_credentials(self) -> None:
        for secret, publishable in (("", ""), ("   ", "   "), (REAL_SECRET, "   ")):
            with self.subTest(secret=secret, publishable=publishable):
                self.assertFalse(
                    StripeProvider(
                        secret_key=secret, publishable_key=publishable
                    ).is_configured()
                )


class ThePlatformProviderIsUnchangedTests(unittest.TestCase):
    """`platform_provider_for` builds `StripeProvider()` with no arguments.

    Its fields then default to the deployment's settings, so reading the
    instance has to give the same answer the settings property gives — or this
    fix would have quietly changed how the platform fallback behaves.
    """

    def test_it_follows_the_deployment_when_configured(self) -> None:
        with mock.patch.object(settings, "stripe_secret_key", REAL_SECRET), mock.patch.object(
            settings, "stripe_publishable_key", REAL_PUBLISHABLE
        ):
            self.assertEqual(StripeProvider().is_configured(), settings.stripe_is_configured)
            self.assertTrue(StripeProvider().is_configured())

    def test_it_follows_the_deployment_when_not(self) -> None:
        with NoPlatformKeysAtAll():
            self.assertEqual(StripeProvider().is_configured(), settings.stripe_is_configured)
            self.assertFalse(StripeProvider().is_configured())


class TheOtherGatewayIsUntouchedTests(unittest.TestCase):
    """Razorpay already read its own credentials; this is the pin."""

    def test_razorpay_reads_its_own_keys(self) -> None:
        self.assertTrue(
            RazorpayProvider(key_id="rzp_test_own", key_secret="secret").is_configured()
        )
        self.assertFalse(RazorpayProvider(key_id="", key_secret="secret").is_configured())
        self.assertFalse(RazorpayProvider(key_id="rzp_test_own", key_secret="").is_configured())


if __name__ == "__main__":
    unittest.main()
