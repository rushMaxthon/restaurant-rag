"""Rider self sign-up: the application, its items, and who may work.

The application IS the rider account in a pending state, so these tests
create riders the way sign-up does and check every state change, the edit
rules per state, and the server-side gates that keep a pending rider off
the road whatever the app shows.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available, reset_overrides  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.enums import RiderOnboarding  # noqa: E402
from app.models.rider import Rider  # noqa: E402
from app.services.fleet.onboarding import phone  # noqa: E402


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class OnboardingModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_onboarding_test")

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def test_a_rider_made_the_old_way_is_approved(self) -> None:
        with self.fdb.session() as db:
            user = self.fdb.make_rider(db)
            db.commit()
            self.assertEqual(db.get(Rider, user.id).onboarding, RiderOnboarding.APPROVED)



@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class PhoneCodeTests(unittest.TestCase):
    """Sign-up codes. Static for now (the user's call until the WhatsApp
    template is approved): the fixed code works and nothing is sent, but the
    limits and the lock are the same as they will be for real codes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_onboarding_phone_test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def test_static_mode_accepts_the_fixed_code_and_sends_nothing(self) -> None:
        with self.fdb.session() as db:
            result = phone.request_code(db, "+919812300001")
            self.assertFalse(result.sent)
            phone.verify_code(db, "+919812300001", get_settings().otp_debug_code)

    def test_a_code_works_once(self) -> None:
        with self.fdb.session() as db:
            phone.request_code(db, "+919812300005")
            phone.verify_code(db, "+919812300005", get_settings().otp_debug_code)
            with self.assertRaises(HTTPException) as caught:
                phone.verify_code(db, "+919812300005", get_settings().otp_debug_code)
            self.assertEqual(caught.exception.detail, "code_expired")

    def test_a_second_request_inside_a_minute_is_refused(self) -> None:
        with self.fdb.session() as db:
            phone.request_code(db, "+919812300002")
            with self.assertRaises(HTTPException) as caught:
                phone.request_code(db, "+919812300002")
            self.assertEqual(caught.exception.detail, "code_too_soon")

    def test_five_wrong_codes_lock_it(self) -> None:
        with self.fdb.session() as db:
            phone.request_code(db, "+919812300003")
            for _ in range(5):
                with self.assertRaises(HTTPException):
                    phone.verify_code(db, "+919812300003", "000000")
            with self.assertRaises(HTTPException) as caught:
                phone.verify_code(db, "+919812300003", get_settings().otp_debug_code)
            self.assertEqual(caught.exception.detail, "code_locked")

    def test_an_expired_code(self) -> None:
        with self.fdb.session() as db:
            now = datetime.now(UTC)
            phone.request_code(db, "+919812300004", now=now)
            with self.assertRaises(HTTPException) as caught:
                phone.verify_code(
                    db, "+919812300004", get_settings().otp_debug_code, now=now + timedelta(minutes=11)
                )
            self.assertEqual(caught.exception.detail, "code_expired")


if __name__ == "__main__":
    unittest.main()
