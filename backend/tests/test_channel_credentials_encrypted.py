"""Marketing channel secrets are stored encrypted, like payment keys.

Found in the 2026-10-07 security review: an SMTP password, a Meta page token
or an SMS gateway key was written to `restaurant_channel_connections.
credentials` as plain JSON. A database dump, a backup or a dashboard read
handed over the ability to post and send as every connected restaurant.
`services/secrets.py` already encrypted payment and payout secrets; these
now go through it too.

Rows saved before this have plaintext values. They keep working - a value
without the marker is read as it is - and are encrypted the next time the
connection is saved.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

from cryptography.fernet import Fernet

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings  # noqa: E402
from app.services import secrets as secrets_module  # noqa: E402
from app.services.marketing import connections  # noqa: E402


class _WithKey(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {"SECRETS_ENCRYPTION_KEY": Fernet.generate_key().decode()})
        patcher.start()
        self.addCleanup(patcher.stop)
        get_settings.cache_clear()
        secrets_module._cipher.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self.addCleanup(secrets_module._cipher.cache_clear)


class SealingAndOpening(_WithKey):
    def test_a_sealed_value_is_not_the_secret(self) -> None:
        sealed = connections.seal_credentials({"smtp_password": "hunter2-hunter2"})
        self.assertNotIn("hunter2", sealed["smtp_password"])
        self.assertTrue(sealed["smtp_password"].startswith(connections.SEALED_PREFIX))

    def test_opening_gives_the_secret_back(self) -> None:
        sealed = connections.seal_credentials({"api_key": "k-123", "smtp_password": "p"})
        self.assertEqual(connections.open_credentials(sealed), {"api_key": "k-123", "smtp_password": "p"})

    def test_sealing_twice_does_not_wrap_twice(self) -> None:
        once = connections.seal_credentials({"api_key": "k-123"})
        self.assertEqual(connections.seal_credentials(once), once)

    def test_a_row_saved_before_encryption_still_reads(self) -> None:
        self.assertEqual(connections.open_credentials({"api_key": "plain-old"}), {"api_key": "plain-old"})

    def test_an_empty_value_stays_empty(self) -> None:
        self.assertEqual(connections.seal_credentials({"app_secret": ""}), {"app_secret": ""})


class WithoutAKey(unittest.TestCase):
    def test_a_secret_is_refused_rather_than_stored_in_the_clear(self) -> None:
        with mock.patch.dict(os.environ, {"SECRETS_ENCRYPTION_KEY": ""}):
            get_settings.cache_clear()
            secrets_module._cipher.cache_clear()
            try:
                with self.assertRaises(connections.ConnectionError_) as raised:
                    connections.seal_credentials({"api_key": "k"})
                self.assertIn("SECRETS_ENCRYPTION_KEY", str(raised.exception))
            finally:
                get_settings.cache_clear()
                secrets_module._cipher.cache_clear()


class TheProviderGetsThePlainValue(_WithKey):
    def test_provider_for_opens_the_credentials(self) -> None:
        from types import SimpleNamespace

        from app.models.enums import MarketingChannel
        from app.services.marketing import providers

        seen = {}

        def builder(*, config, credentials):
            seen.update(credentials)
            return object()

        connection = SimpleNamespace(
            config={}, credentials=connections.seal_credentials({"api_key": "k-123"}), is_sendable=lambda: True
        )
        with mock.patch.dict(providers._BUILDERS, {MarketingChannel.SMS: builder}):
            providers.provider_for(MarketingChannel.SMS, connection)
        self.assertEqual(seen, {"api_key": "k-123"})


if __name__ == "__main__":
    unittest.main()
