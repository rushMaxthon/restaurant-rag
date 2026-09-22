"""Razorpay, and the per-restaurant gateway routing around it.

Every charge on this platform used to settle into one Stripe account. That is
not an arrangement a restaurant would agree to — the money is theirs — so a
restaurant now holds its own credentials and the registry resolves a gateway
per restaurant rather than per deployment.

Four things here would each cost real money if they were wrong, which is why
they are the four things tested:

- **Amounts.** Razorpay has no decimal amounts at all. Everything is integer
  paise, and `int(amount * 100)` truncates, so ₹240.55 becomes ₹240.54 and
  every order reconciles a paisa short forever.
- **Signatures.** Both the checkout signature and the webhook signature are
  HMACs, and they use *different secrets*. Verifying a webhook with the API
  key silently fails every time; verifying a checkout with the webhook secret
  silently accepts nothing. Both fail closed, which is safe and invisible.
- **Whose account.** `provider_for` must answer with the restaurant's own
  gateway, and must answer None rather than falling through to somebody
  else's when it cannot.
- **What the customer is offered.** A method appears only when the branch has
  it switched on *and* a configured gateway can settle it. A toggle with no
  credentials behind it is not an enabled payment method, it is a promise.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.main import app  # noqa: F401 - imported first to settle import order
from app.models.enums import PaymentGateway, PaymentMethod
from app.services.payments import registry
from app.services.payments.base import WebhookVerificationError
from app.services.payments.razorpay_provider import (
    RazorpayProvider,
    _from_minor_units,
    _to_minor_units,
)

KEY_ID = "rzp_test_notarealkey"
KEY_SECRET = "not-a-real-secret"
WEBHOOK_SECRET = "not-a-real-webhook-secret"


def a_provider(**overrides) -> RazorpayProvider:
    return RazorpayProvider(
        key_id=overrides.pop("key_id", KEY_ID),
        key_secret=overrides.pop("key_secret", KEY_SECRET),
        webhook_secret=overrides.pop("webhook_secret", WEBHOOK_SECRET),
    )


class AmountsTests(unittest.TestCase):
    def test_rupees_become_paise(self) -> None:
        self.assertEqual(_to_minor_units(Decimal("240.00")), 24000)
        self.assertEqual(_to_minor_units(Decimal("35")), 3500)

    def test_a_half_paisa_does_not_vanish(self) -> None:
        """`int(x * 100)` truncates. This is the money that goes missing.

        ₹240.55 truncates to 24054 — one paisa short on every order, forever,
        and reconciling it means finding this line.
        """

        self.assertEqual(_to_minor_units(Decimal("240.55")), 24055)
        self.assertEqual(_to_minor_units(Decimal("0.01")), 1)

    def test_paise_come_back_as_rupees(self) -> None:
        self.assertEqual(_from_minor_units(24055), Decimal("240.55"))
        self.assertEqual(_from_minor_units(3500), Decimal("35.00"))

    def test_junk_reads_as_nothing_rather_than_zero(self) -> None:
        # A webhook missing an amount is not a webhook for ₹0.
        for value in (None, "", "abc", {}):
            self.assertIsNone(_from_minor_units(value))


class CheckoutSignatureTests(unittest.TestCase):
    """The browser reports a success; this is what makes it worth believing.

    Without it, a customer could post a made-up payment id and have an order
    marked paid.
    """

    def signed(self, order_id: str, payment_id: str, secret: str = KEY_SECRET) -> str:
        return hmac.new(
            secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
        ).hexdigest()

    def test_a_genuine_signature_is_accepted(self) -> None:
        provider = a_provider()
        self.assertTrue(
            provider.verify_checkout_signature(
                razorpay_order_id="order_1",
                razorpay_payment_id="pay_1",
                razorpay_signature=self.signed("order_1", "pay_1"),
            )
        )

    def test_a_forged_signature_is_refused(self) -> None:
        provider = a_provider()
        self.assertFalse(
            provider.verify_checkout_signature(
                razorpay_order_id="order_1",
                razorpay_payment_id="pay_1",
                razorpay_signature="0" * 64,
            )
        )

    def test_a_signature_for_another_payment_is_refused(self) -> None:
        # The signature covers order AND payment, so one cannot be swapped.
        provider = a_provider()
        self.assertFalse(
            provider.verify_checkout_signature(
                razorpay_order_id="order_1",
                razorpay_payment_id="pay_2",
                razorpay_signature=self.signed("order_1", "pay_1"),
            )
        )

    def test_the_webhook_secret_does_not_verify_a_checkout(self) -> None:
        """The two secrets are not interchangeable, and mixing them fails closed.

        Which is safe and completely silent, so it is worth a test rather than
        a comment.
        """

        provider = a_provider()
        self.assertFalse(
            provider.verify_checkout_signature(
                razorpay_order_id="order_1",
                razorpay_payment_id="pay_1",
                razorpay_signature=self.signed("order_1", "pay_1", secret=WEBHOOK_SECRET),
            )
        )


class WebhookTests(unittest.TestCase):
    def body(self, event: str = "payment.captured") -> bytes:
        return json.dumps(
            {
                "id": "evt_1",
                "event": event,
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_1",
                            "order_id": "order_1",
                            "amount": 24055,
                            "currency": "INR",
                        }
                    }
                },
            }
        ).encode()

    def sign(self, payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
        return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    def test_a_verified_webhook_is_normalised(self) -> None:
        payload = self.body()
        event = a_provider().parse_webhook(payload=payload, signature=self.sign(payload))

        self.assertEqual(event.event_type, "succeeded")
        # The ORDER id, not the payment id: that is what `create_intent`
        # stored, and the only one an order here can be found by.
        self.assertEqual(event.intent_id, "order_1")
        self.assertEqual(event.amount, Decimal("240.55"))
        self.assertEqual(event.currency, "INR")

    def test_a_failed_payment_carries_its_reason(self) -> None:
        body = json.loads(self.body("payment.failed"))
        body["payload"]["payment"]["entity"]["error_description"] = "Card declined"
        payload = json.dumps(body).encode()

        event = a_provider().parse_webhook(payload=payload, signature=self.sign(payload))
        self.assertEqual(event.event_type, "failed")
        self.assertEqual(event.failure_message, "Card declined")

    def test_a_tampered_body_is_refused(self) -> None:
        payload = self.body()
        signature = self.sign(payload)
        tampered = payload.replace(b"24055", b"1")

        with self.assertRaises(WebhookVerificationError):
            a_provider().parse_webhook(payload=tampered, signature=signature)

    def test_the_api_secret_does_not_verify_a_webhook(self) -> None:
        payload = self.body()
        with self.assertRaises(WebhookVerificationError):
            a_provider().parse_webhook(payload=payload, signature=self.sign(payload, KEY_SECRET))

    def test_a_restaurant_with_no_webhook_secret_refuses_rather_than_trusts(self) -> None:
        payload = self.body()
        provider = a_provider(webhook_secret=None)
        with self.assertRaises(WebhookVerificationError):
            provider.parse_webhook(payload=payload, signature=self.sign(payload))

    def test_a_missing_signature_header_is_refused(self) -> None:
        with self.assertRaises(WebhookVerificationError):
            a_provider().parse_webhook(payload=self.body(), signature=None)


class WhoseAccountTests(unittest.TestCase):
    """The question that used to have one answer for the whole platform."""

    def credentials(self, gateway: PaymentGateway):
        return SimpleNamespace(
            gateway=gateway,
            public_key=KEY_ID,
            secret_key=KEY_SECRET,
            webhook_secret=WEBHOOK_SECRET,
        )

    def test_a_restaurant_with_its_own_razorpay_gets_its_own_provider(self) -> None:
        restaurant_id = uuid.uuid4()
        with patch(
            "app.services.payment_accounts.read_credentials",
            lambda db, *, restaurant_id, gateway: self.credentials(gateway),
        ):
            provider = registry.provider_for(
                None, restaurant_id=restaurant_id, method=PaymentMethod.RAZORPAY
            )

        self.assertIsInstance(provider, RazorpayProvider)
        self.assertTrue(provider.is_configured())

    def test_a_restaurant_without_an_account_cannot_take_razorpay(self) -> None:
        """No falling through to somebody else's gateway.

        There is no platform Razorpay account and there should not be one: a
        restaurant taking UPI is taking its own money.
        """

        with patch(
            "app.services.payment_accounts.read_credentials",
            lambda db, *, restaurant_id, gateway: None,
        ):
            provider = registry.provider_for(
                None, restaurant_id=uuid.uuid4(), method=PaymentMethod.RAZORPAY
            )

        self.assertIsNone(provider)

    def test_requiring_an_account_removes_the_platform_fallback(self) -> None:
        with (
            patch(
                "app.services.payment_accounts.read_credentials",
                lambda db, *, restaurant_id, gateway: None,
            ),
            patch.object(registry, "get_settings") as settings_mock,
        ):
            settings_mock.return_value.payments_require_restaurant_account = True
            provider = registry.provider_for(
                None, restaurant_id=uuid.uuid4(), method=PaymentMethod.CARD
            )

        self.assertIsNone(provider)

    def test_cod_is_not_a_gateway(self) -> None:
        self.assertIsNone(
            registry.provider_for(None, restaurant_id=uuid.uuid4(), method=PaymentMethod.COD)
        )


class WhatTheCustomerIsOfferedTests(unittest.TestCase):
    """Both halves have to agree: the branch toggle and the credentials."""

    def a_branch(self, **flags):
        base = {
            "card_payment_enabled": True,
            "razorpay_enabled": True,
            "cash_on_delivery_enabled": True,
        }
        base.update(flags)
        return SimpleNamespace(**base)

    def methods(self, *, branch, configured_gateways, cod_enabled=False):
        def fake_credentials(db, *, restaurant_id, gateway):
            if gateway in configured_gateways:
                return SimpleNamespace(
                    gateway=gateway,
                    public_key=KEY_ID,
                    secret_key=KEY_SECRET,
                    webhook_secret=None,
                )
            return None

        with (
            patch("app.services.payment_accounts.read_credentials", fake_credentials),
            patch.object(registry, "get_settings") as settings_mock,
        ):
            settings_mock.return_value.enable_cash_on_delivery = cod_enabled
            settings_mock.return_value.payments_require_restaurant_account = True
            return registry.available_payment_methods(
                None, restaurant_id=uuid.uuid4(), location=branch
            )

    def test_a_branch_toggle_off_hides_the_method_even_with_credentials(self) -> None:
        methods = self.methods(
            branch=self.a_branch(razorpay_enabled=False),
            configured_gateways={PaymentGateway.RAZORPAY, PaymentGateway.STRIPE},
        )
        self.assertNotIn(PaymentMethod.RAZORPAY, methods)
        self.assertIn(PaymentMethod.CARD, methods)

    def test_credentials_missing_hides_the_method_even_with_the_toggle_on(self) -> None:
        """The failure this is really about.

        A branch with `razorpay_enabled` and no Razorpay account would have
        shown the customer a button that fails at the last step — after they
        have chosen their food and entered their address.
        """

        methods = self.methods(branch=self.a_branch(), configured_gateways=set())
        self.assertEqual(methods, [])

    def test_both_halves_present_offers_the_method(self) -> None:
        methods = self.methods(
            branch=self.a_branch(),
            configured_gateways={PaymentGateway.RAZORPAY},
        )
        self.assertEqual(methods, [PaymentMethod.RAZORPAY])

    def test_cod_needs_no_gateway_but_still_needs_both_switches(self) -> None:
        self.assertEqual(
            self.methods(branch=self.a_branch(), configured_gateways=set(), cod_enabled=True),
            [PaymentMethod.COD],
        )
        self.assertEqual(
            self.methods(
                branch=self.a_branch(cash_on_delivery_enabled=False),
                configured_gateways=set(),
                cod_enabled=True,
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
