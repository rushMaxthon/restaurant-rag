"""A list of accounts shows every stored account, valid sign-up or not.

`UserResponse` inherited the sign-up form's rules (a name of two or more
characters, an email that validates, an eight-digit phone). Those are right
for what somebody types and wrong for what is already stored: a customer who
signed in by phone OTP on 2026-10-06 had no name yet, and that one row turned
`GET /admin/users` into a 500 for everybody - which the browser reported as a
CORS error, because a 500 leaves without CORS headers. The sign-up rules stay
on `UserRegister`.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError  # noqa: E402

from app.models.enums import UserRole  # noqa: E402
from app.schemas.auth import UserRegister, UserResponse  # noqa: E402


def a_user(**over):
    fields = dict(id=uuid.uuid4(), full_name="Vishal", email="v@x.in", phone_number="9876543210",
                  default_address=None, role=UserRole.CUSTOMER, is_active=True, is_verified=True,
                  created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    fields.update(over)
    return SimpleNamespace(**fields)


class UserResponseTests(unittest.TestCase):
    def test_a_customer_with_no_name_yet_is_still_listed(self) -> None:
        self.assertEqual(UserResponse.model_validate(a_user(full_name="")).full_name, "")

    def test_an_odd_stored_email_or_short_phone_is_still_listed(self) -> None:
        UserResponse.model_validate(a_user(email="otp-user@local", phone_number="12345"))

    def test_sign_up_still_refuses_a_one_letter_name(self) -> None:
        with self.assertRaises(ValidationError):
            UserRegister(full_name="V", email="v@x.in", password="password123")


if __name__ == "__main__":
    unittest.main()
