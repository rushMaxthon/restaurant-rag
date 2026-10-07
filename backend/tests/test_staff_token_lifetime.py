"""An admin's or owner's login lasts a working day, not a whole one.

From the 2026-10-07 security review: every login lasted 24 hours, and login
tokens live in browser storage until the platform has its own domain and can
use httpOnly cookies. An ADMIN or OWNER token can spend marketing budget,
change prices and read every order and payout, so a stolen one should stop
working sooner. A kitchen tablet on a wall and a customer keep 24 hours:
signing a cook out mid-service, or a customer mid-checkout, costs more than
it protects.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from types import SimpleNamespace

import jwt

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.services.auth import create_access_token  # noqa: E402


def _hours(role: UserRole) -> float:
    user = SimpleNamespace(id=uuid.uuid4(), role=role, app_client_id=None, token_version=0)
    settings = get_settings()
    claims = jwt.decode(
        create_access_token(user), settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )
    return (claims["exp"] - claims["iat"]) / 3600


class HowLongALoginLasts(unittest.TestCase):
    def test_admin_and_owner_get_eight_hours(self) -> None:
        self.assertAlmostEqual(_hours(UserRole.ADMIN), 8, delta=0.01)
        self.assertAlmostEqual(_hours(UserRole.OWNER), 8, delta=0.01)

    def test_kitchen_and_customers_keep_a_day(self) -> None:
        expected = get_settings().jwt_access_token_expire_minutes / 60
        self.assertAlmostEqual(_hours(UserRole.KITCHEN), expected, delta=0.01)
        self.assertAlmostEqual(_hours(UserRole.CUSTOMER), expected, delta=0.01)


if __name__ == "__main__":
    unittest.main()
