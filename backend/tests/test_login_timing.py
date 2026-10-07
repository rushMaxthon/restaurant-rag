"""Login takes as long for an unknown email as for a wrong password.

Found in the 2026-10-07 security review: when no account matched, login
answered without checking any password, which costs bcrypt's ~100 ms. That
difference tells whoever is timing it which emails and phone numbers have
accounts. Now a password is always checked once - against a fixed dummy hash
when there is nobody to check it against.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import auth  # noqa: E402


def _db_with(candidates):
    db = mock.MagicMock()
    db.scalars.return_value.all.return_value = candidates
    return db


class AlwaysOneCheck(unittest.TestCase):
    def test_no_account_still_checks_a_password(self) -> None:
        with mock.patch.object(auth, "verify_password", return_value=False) as checked:
            result = auth.authenticate_user(
                _db_with([]), "some-password", email="nobody@example.com", phone_number=None,
                app_client_id=None, allow_platform_users=True,
            )
        self.assertIsNone(result)
        self.assertEqual(checked.call_count, 1)
        self.assertEqual(checked.call_args.args[1], auth.DUMMY_PASSWORD_HASH)

    def test_the_dummy_hash_never_matches_anything_typed(self) -> None:
        self.assertFalse(auth.verify_password("", auth.DUMMY_PASSWORD_HASH))
        self.assertFalse(auth.verify_password("password123", auth.DUMMY_PASSWORD_HASH))


if __name__ == "__main__":
    unittest.main()
