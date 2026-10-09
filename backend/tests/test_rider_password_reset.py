"""A rider who forgot their password resets it with a code to their phone.

Riders choose their own password at sign-up and nobody else can read it (it
is stored as a hash), so the alternative was a phone call to the office for
every forgotten password. The code is the sign-up machinery with its own
purpose, so a sign-up code can never be spent on a reset or the other way
round. A reset ends every other session, as the admin's reset does - a phone
that was lost must stop working the moment its owner picks a new password.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, client_for, postgres_available, reset_overrides  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.enums import RiderStatus  # noqa: E402
from app.models.rider import Rider  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import hash_password, verify_password  # noqa: E402
from sqlalchemy import select  # noqa: E402


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class PasswordResetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_rider_password_test")
        cls.n = 0

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def setUp(self) -> None:
        mock.patch("app.services.fleet.notify.riders_changed").start()
        mock.patch("app.services.rate_limit.hit").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(reset_overrides)
        self.public = client_for(self.fdb, None)

    def make_rider(self, *, active: bool = True, status: RiderStatus = RiderStatus.OFFLINE) -> str:
        type(self).n += 1
        digits = f"82000{type(self).n:05d}"
        with self.fdb.session() as db:
            user = self.fdb.make_rider(db, phone=digits, status=status)
            user.hashed_password = hash_password("oldpassword")
            user.is_active = active
            db.commit()
        return digits

    def code_for(self, digits: str) -> str:
        sent = self.public.post("/api/rider/password/code", json={"phone_number": digits})
        self.assertEqual(sent.status_code, 200, sent.text)
        return sent.json()["debug_code"]

    def user(self, db, digits: str) -> User:
        return db.scalar(select(User).where(User.phone_number == f"+91{digits}"))

    def login(self, digits: str, password: str) -> int:
        """200 when the stored hash takes this password, 401 when not - what
        /auth/login would answer, without the app client it needs."""

        with self.fdb.session() as db:
            return 200 if verify_password(password, self.user(db, digits).hashed_password) else 401

    def test_reset_end_to_end(self) -> None:
        digits = self.make_rider()
        code = self.code_for(digits)
        self.assertEqual(code, get_settings().otp_debug_code)
        checked = self.public.post("/api/rider/password/check", json={"phone_number": digits, "code": code})
        self.assertEqual(checked.status_code, 204, checked.text)
        done = self.public.post(
            "/api/rider/password/reset",
            json={"phone_number": digits, "code": code, "password": "newpassword"},
        )
        self.assertEqual(done.status_code, 200, done.text)
        self.assertTrue(done.json()["access_token"])
        self.assertEqual(self.login(digits, "newpassword"), 200)
        self.assertEqual(self.login(digits, "oldpassword"), 401)

    def test_a_number_with_no_rider_is_told_to_sign_up(self) -> None:
        sent = self.public.post("/api/rider/password/code", json={"phone_number": "8299999999"})
        self.assertEqual((sent.status_code, sent.json()["detail"]), (404, "no_account"))

    def test_a_deactivated_rider_cannot_reset_their_way_back_in(self) -> None:
        digits = self.make_rider(active=False)
        sent = self.public.post("/api/rider/password/code", json={"phone_number": digits})
        self.assertEqual((sent.status_code, sent.json()["detail"]), (403, "account_inactive"))

    def test_a_wrong_code_changes_nothing(self) -> None:
        digits = self.make_rider()
        self.code_for(digits)
        wrong = self.public.post(
            "/api/rider/password/reset",
            json={"phone_number": digits, "code": "000000", "password": "newpassword"},
        )
        self.assertEqual((wrong.status_code, wrong.json()["detail"]), (400, "code_wrong"))
        self.assertEqual(self.login(digits, "oldpassword"), 200)

    def test_a_signup_code_cannot_reset_a_password(self) -> None:
        # Different purposes: the sign-up row for a number is not a reset row.
        digits = self.make_rider()
        reset = self.public.post(
            "/api/rider/password/reset",
            json={"phone_number": digits, "code": get_settings().otp_debug_code, "password": "newpassword"},
        )
        self.assertEqual((reset.status_code, reset.json()["detail"]), (400, "code_expired"))

    def test_the_code_works_once(self) -> None:
        digits = self.make_rider()
        code = self.code_for(digits)
        body = {"phone_number": digits, "code": code, "password": "newpassword"}
        self.assertEqual(self.public.post("/api/rider/password/reset", json=body).status_code, 200)
        again = self.public.post("/api/rider/password/reset", json={**body, "password": "thirdpassword"})
        self.assertEqual((again.status_code, again.json()["detail"]), (400, "code_expired"))

    def test_the_reset_signs_out_other_phones_and_takes_the_rider_off_shift(self) -> None:
        digits = self.make_rider(status=RiderStatus.ONLINE)
        with self.fdb.session() as db:
            before = self.user(db, digits).token_version
        code = self.code_for(digits)
        self.public.post(
            "/api/rider/password/reset", json={"phone_number": digits, "code": code, "password": "newpassword"}
        )
        with self.fdb.session() as db:
            user = self.user(db, digits)
            self.assertEqual(user.token_version, before + 1)
            self.assertEqual(db.get(Rider, user.id).status, RiderStatus.OFFLINE)

    def test_a_short_password_is_refused(self) -> None:
        digits = self.make_rider()
        code = self.code_for(digits)
        short = self.public.post(
            "/api/rider/password/reset", json={"phone_number": digits, "code": code, "password": "short"}
        )
        self.assertEqual(short.status_code, 422)
        self.assertEqual(self.login(digits, "oldpassword"), 200)


if __name__ == "__main__":
    unittest.main()
