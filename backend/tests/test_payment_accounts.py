"""Storing a restaurant's gateway keys, and what the screen is told about them.

The rule that matters most here is a negative one: **no endpoint returns a
stored secret.** Not to an admin, not to the owner who typed it. A screen that
can display a live API key is a screen that leaks one to anyone who gets a
look at it, and there is no product reason to be able to read one back — the
person who has the key already has it.

Which forces the shape of everything else. The form cannot prefill a secret,
so it submits an empty one whenever nobody retypes it, so an empty secret has
to mean "leave it alone" — and if it ever meant "clear it", every operator who
toggled a gateway off and on would silently wipe a live restaurant's payments.
"""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.main import app  # noqa: F401 - imported first to settle import order
from app.models.enums import PaymentGateway
from app.services import payment_accounts


class FakeSession:
    """Holds one account row, the way the real session does by primary key."""

    def __init__(self, row: object | None = None) -> None:
        self.row = row
        self.added: list[object] = []
        self.deleted: list[object] = []

    def get(self, _model: object, _pk: object) -> object | None:
        return self.row

    def add(self, instance: object) -> None:
        self.added.append(instance)
        self.row = instance

    def delete(self, instance: object) -> None:
        self.deleted.append(instance)
        self.row = None


def a_row(**overrides):
    base = {
        "restaurant_id": uuid.uuid4(),
        "gateway": PaymentGateway.RAZORPAY,
        "is_enabled": True,
        "public_key": "rzp_test_publickey",
        "secret_key_encrypted": "ciphertext-of-the-secret",
        "webhook_secret_encrypted": "ciphertext-of-the-webhook",
        "secret_last4": "abcd",
        "updated_by_user_id": None,
        "updated_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class StoringKeysTests(unittest.TestCase):
    def setUp(self) -> None:
        # Encryption is stubbed so the test pins the *policy*, not Fernet.
        self.encrypt = patch.object(
            payment_accounts, "encrypt_secret", lambda value: f"enc:{value}"
        )
        self.encrypt.start()
        self.addCleanup(self.encrypt.stop)

    def test_a_new_gateway_requires_a_secret(self) -> None:
        with self.assertRaises(ValueError):
            payment_accounts.save_account(
                FakeSession(),
                restaurant_id=uuid.uuid4(),
                gateway=PaymentGateway.RAZORPAY,
                public_key="rzp_test_publickey",
                secret_key=None,
                webhook_secret=None,
                is_enabled=True,
                updated_by_user_id=None,
            )

    def test_the_secret_is_encrypted_before_it_is_stored(self) -> None:
        db = FakeSession()
        row = payment_accounts.save_account(
            db,
            restaurant_id=uuid.uuid4(),
            gateway=PaymentGateway.RAZORPAY,
            public_key="rzp_test_publickey",
            secret_key="the-real-secret",
            webhook_secret=None,
            is_enabled=True,
            updated_by_user_id=None,
        )
        self.assertEqual(row.secret_key_encrypted, "enc:the-real-secret")
        # And the plaintext is nowhere on the row.
        self.assertNotIn("the-real-secret", row.public_key)
        self.assertEqual(row.secret_last4, "cret")

    def test_an_empty_secret_keeps_the_stored_one(self) -> None:
        """The behaviour the whole form depends on.

        The screen cannot show a stored secret, so it submits nothing whenever
        nobody retyped one. If that cleared the key, every operator toggling a
        gateway off and on would wipe a live restaurant's payments.
        """

        row = a_row()
        payment_accounts.save_account(
            FakeSession(row),
            restaurant_id=row.restaurant_id,
            gateway=PaymentGateway.RAZORPAY,
            public_key="rzp_test_publickey",
            secret_key=None,
            webhook_secret=None,
            is_enabled=False,
            updated_by_user_id=None,
        )
        self.assertEqual(row.secret_key_encrypted, "ciphertext-of-the-secret")
        self.assertEqual(row.webhook_secret_encrypted, "ciphertext-of-the-webhook")
        # The one thing that did change.
        self.assertFalse(row.is_enabled)

    def test_an_explicitly_empty_webhook_secret_clears_it(self) -> None:
        # None means "unchanged"; "" means "remove it". The distinction is the
        # only way to unset a webhook without deleting the whole gateway.
        row = a_row()
        payment_accounts.save_account(
            FakeSession(row),
            restaurant_id=row.restaurant_id,
            gateway=PaymentGateway.RAZORPAY,
            public_key="rzp_test_publickey",
            secret_key=None,
            webhook_secret="",
            is_enabled=True,
            updated_by_user_id=None,
        )
        self.assertIsNone(row.webhook_secret_encrypted)

    def test_a_deployment_that_cannot_encrypt_refuses_the_key(self) -> None:
        """Storing a gateway secret in plaintext is not a degraded mode.

        `encrypt_secret` raises when no encryption key is configured, and
        `save_account` deliberately does not catch it.
        """

        with patch.object(
            payment_accounts, "encrypt_secret", side_effect=RuntimeError("no key")
        ):
            with self.assertRaises(RuntimeError):
                payment_accounts.save_account(
                    FakeSession(),
                    restaurant_id=uuid.uuid4(),
                    gateway=PaymentGateway.RAZORPAY,
                    public_key="rzp_test_publickey",
                    secret_key="the-real-secret",
                    webhook_secret=None,
                    is_enabled=True,
                    updated_by_user_id=None,
                )


class WhatTheScreenIsToldTests(unittest.TestCase):
    def test_a_summary_carries_no_secret(self) -> None:
        row = a_row()
        db = SimpleNamespace(
            scalars=lambda _s: SimpleNamespace(all=lambda: [row]),
        )
        summaries = payment_accounts.describe_accounts(db, restaurant_id=row.restaurant_id)

        self.assertEqual(len(summaries), 1)
        rendered = repr(summaries[0])
        self.assertNotIn("ciphertext-of-the-secret", rendered)
        self.assertNotIn("ciphertext-of-the-webhook", rendered)
        # What it does carry: enough to identify the key, and nothing more.
        self.assertEqual(summaries[0].secret_last4, "abcd")
        self.assertTrue(summaries[0].has_webhook_secret)
        self.assertEqual(summaries[0].public_key, "rzp_test_publickey")


class ReadingKeysBackTests(unittest.TestCase):
    def test_a_disabled_gateway_yields_no_credentials(self) -> None:
        row = a_row(is_enabled=False)
        self.assertIsNone(
            payment_accounts.read_credentials(
                FakeSession(row),
                restaurant_id=row.restaurant_id,
                gateway=PaymentGateway.RAZORPAY,
            )
        )

    def test_credentials_that_will_not_decrypt_read_as_absent(self) -> None:
        """An encryption key changed under a stored secret.

        Loud in the log, because it means somebody has to re-enter every key.
        Silent to the customer, because a 500 on a checkout screen helps
        nobody: they simply see the methods that still work.
        """

        row = a_row()
        with patch.object(
            payment_accounts, "decrypt_secret", side_effect=ValueError("bad token")
        ):
            self.assertIsNone(
                payment_accounts.read_credentials(
                    FakeSession(row),
                    restaurant_id=row.restaurant_id,
                    gateway=PaymentGateway.RAZORPAY,
                )
            )

    def test_working_credentials_come_back_decrypted(self) -> None:
        row = a_row()
        with patch.object(
            payment_accounts, "decrypt_secret", lambda value: value.replace("ciphertext-of-the-", "")
        ):
            credentials = payment_accounts.read_credentials(
                FakeSession(row),
                restaurant_id=row.restaurant_id,
                gateway=PaymentGateway.RAZORPAY,
            )

        self.assertIsNotNone(credentials)
        self.assertEqual(credentials.secret_key, "secret")
        self.assertEqual(credentials.webhook_secret, "webhook")
        self.assertEqual(credentials.public_key, "rzp_test_publickey")


if __name__ == "__main__":
    unittest.main()
