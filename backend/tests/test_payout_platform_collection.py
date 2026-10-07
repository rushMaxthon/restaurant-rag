"""The platform's Razorpay account takes a restaurant's payment only when it
can pay that restaurant out, and every attempt remembers whose account it was.

Before this, `registry.platform_provider_for` was Stripe only, so a restaurant
without its own Razorpay keys was simply not offered Razorpay — six of the
seven real kitchens. Route needs the platform to collect; the rule here is
that it collects only for a restaurant it can pay.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_payout_ledger import LedgerDatabase, postgres_available  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.enums import PaymentMethod, PaymentStatus, PayoutAccountStatus  # noqa: E402
from app.models.payment import PaymentTransaction  # noqa: E402
from app.services.payments import registry  # noqa: E402
from app.services.payments import service as payments  # noqa: E402

PLATFORM = dict(enable_restaurant_payouts=True, razorpay_key_id="rzp_test_platform",
                razorpay_key_secret="platform_secret", razorpay_webhook_secret="whsec_platform")


def settings_with(**overrides):
    return mock.patch("app.services.payments.registry.get_settings",
                      return_value=get_settings().model_copy(update=overrides))


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class PlatformCollectionTests(LedgerDatabase):
    def provider(self):
        return registry.provider_for(self.db, restaurant_id=self.restaurant.id, method=PaymentMethod.RAZORPAY)

    def test_no_linked_account_means_no_platform_razorpay(self) -> None:
        with settings_with(**PLATFORM):
            self.assertIsNone(self.provider())

    def test_an_active_linked_account_lets_the_platform_collect(self) -> None:
        self.make_active_account()
        with settings_with(**PLATFORM):
            provider = self.provider()
        self.assertTrue(provider.is_platform)
        self.assertEqual(provider.public_key, "rzp_test_platform")

    def test_payouts_off_means_the_platform_never_collects(self) -> None:
        self.make_active_account()
        with settings_with(**dict(PLATFORM, enable_restaurant_payouts=False)):
            self.assertIsNone(self.provider())

    def test_the_mock_default_key_is_not_an_account(self) -> None:
        self.make_active_account()
        with settings_with(**dict(PLATFORM, razorpay_key_id="rzp_test_mock")):
            self.assertIsNone(self.provider())

    def test_an_account_under_review_cannot_collect_yet(self) -> None:
        account = self.make_active_account()
        account.status = PayoutAccountStatus.UNDER_REVIEW.value
        self.db.commit()
        with settings_with(**PLATFORM):
            self.assertIsNone(self.provider())

    def test_a_platform_payment_still_confirms_with_the_flag_off(self) -> None:
        order = self.make_order(platform=True)
        transaction = self.db.query(PaymentTransaction).filter_by(order_id=order.id).one()
        with settings_with(**dict(PLATFORM, enable_restaurant_payouts=False)):
            provider = payments.provider_for_transaction(self.db, order=order, transaction=transaction)
        self.assertTrue(provider.is_platform)

    def test_the_browsers_confirmation_records_the_payment_id(self) -> None:
        order = self.make_order(platform=True, payment_id="")
        order.payment_status = PaymentStatus.PENDING
        transaction = self.db.query(PaymentTransaction).filter_by(order_id=order.id).one()
        transaction.status = PaymentStatus.PENDING
        self.db.commit()
        signature = hmac.new(b"platform_secret", f"{transaction.provider_intent_id}|pay_777".encode(),
                             hashlib.sha256).hexdigest()
        with settings_with(**PLATFORM), mock.patch.object(payments, "_confirm_in_chat"), \
                mock.patch("app.services.orders.run_order_placed_side_effects"):
            payments.confirm_razorpay_checkout(self.db, order=order,
                                               razorpay_order_id=transaction.provider_intent_id,
                                               razorpay_payment_id="pay_777", razorpay_signature=signature)
        self.db.refresh(transaction)
        self.assertEqual(transaction.provider_payment_id, "pay_777")

    def test_the_platform_webhook_is_verified_with_the_platform_secret(self) -> None:
        body = json.dumps({"id": "evt_1", "event": "transfer.processed", "payload": {}}).encode()
        good = hmac.new(b"whsec_platform", body, hashlib.sha256).hexdigest()
        with settings_with(**PLATFORM):
            self.assertEqual(payments.handle_platform_razorpay_webhook(
                self.db, payload=body, signature=good)["event_id"], "evt_1")
            with self.assertRaises(Exception):
                payments.handle_platform_razorpay_webhook(self.db, payload=body, signature="0" * 64)


    def test_the_checkout_is_given_the_platforms_key_to_open_razorpay(self) -> None:
        self.make_active_account()
        with settings_with(**PLATFORM):
            config = payments.payment_config(self.db, restaurant_id=self.restaurant.id)
        self.assertEqual(config["gateway_keys"].get("RAZORPAY"), "rzp_test_platform")

    def test_each_route_event_is_its_own_event(self) -> None:
        # Razorpay puts the event id in a header, not the body: without one,
        # every transfer event read as "transfer.processed:None" and all but
        # the first were dropped as duplicates.
        from app.services.payments.razorpay_provider import RazorpayProvider
        provider = RazorpayProvider(key_id="k", key_secret="s", webhook_secret="w")
        ids = set()
        for transfer in ("trf_1", "trf_2"):
            body = json.dumps({"event": "transfer.processed",
                               "payload": {"transfer": {"entity": {"id": transfer}}}}).encode()
            signature = hmac.new(b"w", body, hashlib.sha256).hexdigest()
            ids.add(provider.parse_webhook(payload=body, signature=signature).event_id)
        self.assertEqual(len(ids), 2)

    def test_a_replay_with_a_new_header_is_still_the_same_event(self) -> None:
        # The X-Razorpay-Event-Id header is not covered by the signature, so
        # keying on it let a captured body be replayed past de-duplication
        # under a fresh header - re-running transfers and reversals
        # (2026-10-07 security review). The key now comes from the signed body.
        from app.services.payments.razorpay_provider import RazorpayProvider
        provider = RazorpayProvider(key_id="k", key_secret="s", webhook_secret="w")
        body = json.dumps({"event": "transfer.reversed", "created_at": 1791000000,
                           "payload": {"transfer": {"entity": {"id": "trf_9"}}}}).encode()
        signature = hmac.new(b"w", body, hashlib.sha256).hexdigest()
        first = provider.parse_webhook(payload=body, signature=signature, event_id="evt_A").event_id
        replay = provider.parse_webhook(payload=body, signature=signature, event_id="evt_FORGED").event_id
        self.assertEqual(first, replay)


if __name__ == "__main__":
    unittest.main()
