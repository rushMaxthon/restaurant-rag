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
from datetime import UTC, date, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available, reset_overrides  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.enums import (  # noqa: E402
    ApplicationAction,
    ApplicationItemKind,
    ApplicationStatus,
    ItemStatus,
    RiderOnboarding,
    RiderStatus,
    UserRole,
    VehicleType,
)
from app.models.rider import Rider  # noqa: E402
from app.models.rider_application import RiderApplication, RiderApplicationEvent, RiderApplicationItem  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import hash_password  # noqa: E402
from app.services.fleet.onboarding import applications, phone  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
TODAY = date(2026, 10, 9)


def make_applicant(fdb, db, digits: str) -> User:
    """A rider the way sign-up makes one: PENDING, with a DRAFT application."""

    user = User(
        email=f"rider.91{digits}@riders.invalid",
        phone_number=f"+91{digits}",
        full_name="Asha Applicant",
        hashed_password=hash_password("password123"),
        role=UserRole.RIDER,
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(Rider(user_id=user.id, vehicle_type=VehicleType.BIKE, onboarding=RiderOnboarding.PENDING))
    db.flush()
    applications.start(db, user)
    db.commit()
    return user


def fill(db, user, vehicle: VehicleType = VehicleType.BIKE) -> None:
    applications.save_section(db, user, "personal", {
        "full_name": "Asha Applicant", "date_of_birth": "1995-05-10", "city": "Surat",
        "address_line": "12 Rander Road, Adajan", "pincode": "395009",
        "emergency_name": "Ravi", "emergency_phone": "9876500000",
    }, today=TODAY)
    applications.save_section(db, user, "vehicle", {
        "vehicle_type": vehicle.value, "vehicle_number": "GJ 05 AB 1234",
    }, today=TODAY)
    applications.save_section(db, user, "documents", {
        "aadhaar_last4": "4321", "pan": "abcde1234f",
        "licence_number": "GJ0520190012345", "licence_expiry": "2030-01-01",
    }, today=TODAY)
    applications.save_section(db, user, "bank", {
        "bank_holder": "Asha Applicant", "account_number": "123456789012",
        "account_number_again": "123456789012", "ifsc": "sbin0001234",
    }, today=TODAY)
    app = db.get(RiderApplication, user.id)
    for kind in applications.required_for(app):
        if kind in applications.PHOTO_KINDS:
            applications.save_photo(db, user, kind, JPEG)


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class ApplicationFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_onboarding_flow_test")
        with cls.fdb.session() as db:
            cls.admin = cls.fdb.make_admin(db)
            cls.admin2 = cls.fdb.make_admin(db)
            db.commit()
        cls.counter = 0

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def setUp(self) -> None:
        for target in ("upload", "delete"):
            p = mock.patch(f"app.services.fleet.onboarding.storage.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.decided = mock.patch("app.services.fleet.notify.application_decided").start()
        self.riders_changed = mock.patch("app.services.fleet.notify.riders_changed").start()
        self.addCleanup(mock.patch.stopall)

    def applicant(self, db) -> User:
        type(self).counter += 1
        return make_applicant(self.fdb, db, f"70000{type(self).counter:05d}")

    def submitted(self, db) -> User:
        user = self.applicant(db)
        fill(db, user)
        applications.submit(db, user)
        return user

    def test_submit_needs_every_required_item(self) -> None:
        with self.fdb.session() as db:
            user = self.applicant(db)
            with self.assertRaises(HTTPException) as caught:
                applications.submit(db, user)
            self.assertEqual(caught.exception.status_code, 422)
            self.assertIn("PERSONAL", caught.exception.detail["missing"])

    def test_a_complete_draft_submits(self) -> None:
        with self.fdb.session() as db:
            user = self.submitted(db)
            app = db.get(RiderApplication, user.id)
            self.assertEqual(app.status, ApplicationStatus.SUBMITTED)
            self.assertIsNotNone(app.submitted_at)
            actions = [e.action for e in db.query(RiderApplicationEvent).filter_by(rider_user_id=user.id)]
            self.assertEqual(actions, [ApplicationAction.SUBMITTED])

    def test_nothing_is_editable_while_under_review(self) -> None:
        with self.fdb.session() as db:
            user = self.submitted(db)
            with self.assertRaises(HTTPException) as caught:
                applications.save_section(db, user, "personal", {"full_name": "Someone Else"}, today=TODAY)
            self.assertEqual((caught.exception.status_code, caught.exception.detail), (409, "not_editable"))

    def test_send_back_needs_a_flag(self) -> None:
        with self.fdb.session() as db:
            user = self.submitted(db)
            with self.assertRaises(HTTPException) as caught:
                applications.send_back(db, self.admin, user.id)
            self.assertEqual(caught.exception.detail, "nothing_flagged")

    def test_only_flagged_items_reopen(self) -> None:
        with self.fdb.session() as db:
            user = self.submitted(db)
            applications.review_item(db, self.admin, user.id, ApplicationItemKind.PAN, accept=False, reason="Blurry")
            applications.send_back(db, self.admin, user.id)
            self.assertEqual(db.get(RiderApplication, user.id).status, ApplicationStatus.CHANGES_NEEDED)
            applications.save_photo(db, user, ApplicationItemKind.PAN, JPEG)
            with self.assertRaises(HTTPException):
                applications.save_photo(db, user, ApplicationItemKind.SELFIE, JPEG)

    def test_resubmit_after_fixing(self) -> None:
        with self.fdb.session() as db:
            user = self.submitted(db)
            applications.review_item(db, self.admin, user.id, ApplicationItemKind.PAN, accept=False, reason="Blurry")
            applications.send_back(db, self.admin, user.id)
            with self.assertRaises(HTTPException):
                applications.submit(db, user)  # PAN still flagged
            applications.save_photo(db, user, ApplicationItemKind.PAN, JPEG)
            item = db.query(RiderApplicationItem).filter_by(rider_user_id=user.id, kind=ApplicationItemKind.PAN).one()
            self.assertEqual(item.status, ItemStatus.PENDING)
            applications.submit(db, user)
            actions = [e.action for e in db.query(RiderApplicationEvent).filter_by(rider_user_id=user.id)]
            self.assertEqual(actions[-1], ApplicationAction.RESUBMITTED)

    def test_approve_needs_everything_accepted(self) -> None:
        with self.fdb.session() as db:
            user = self.submitted(db)
            with self.assertRaises(HTTPException) as caught:
                applications.approve(db, self.admin, user.id)
            self.assertEqual(caught.exception.detail, "not_all_accepted")
            app = db.get(RiderApplication, user.id)
            for kind in applications.required_for(app):
                applications.review_item(db, self.admin, user.id, kind, accept=True)
            applications.approve(db, self.admin, user.id)
            rider = db.get(Rider, user.id)
            self.assertEqual(rider.onboarding, RiderOnboarding.APPROVED)
            self.assertEqual(rider.vehicle_number, "GJ05AB1234")
            self.assertEqual(rider.city, "Surat")
            self.decided.assert_called_with(user.id, "APPROVED")

    def test_two_admins(self) -> None:
        with self.fdb.session() as db:
            user = self.submitted(db)
            applications.review_item(db, self.admin, user.id, ApplicationItemKind.PAN, accept=False, reason="Blurry")
            applications.send_back(db, self.admin, user.id)
            with self.assertRaises(HTTPException) as caught:
                applications.approve(db, self.admin2, user.id)
            self.assertEqual((caught.exception.status_code, caught.exception.detail), (409, "state_changed"))

    def test_reject_is_final_until_reopened(self) -> None:
        with self.fdb.session() as db:
            user = self.submitted(db)
            applications.reject(db, self.admin, user.id, "Documents belong to someone else")
            self.assertEqual(db.get(Rider, user.id).onboarding, RiderOnboarding.REJECTED)
            with self.assertRaises(HTTPException):
                applications.submit(db, user)
            applications.reopen(db, self.admin, user.id)
            self.assertEqual(db.get(RiderApplication, user.id).status, ApplicationStatus.CHANGES_NEEDED)
            self.assertEqual(db.get(Rider, user.id).onboarding, RiderOnboarding.PENDING)

    def test_secrets_are_stored_encrypted(self) -> None:
        with self.fdb.session() as db:
            user = self.applicant(db)
            fill(db, user)
            app = db.get(RiderApplication, user.id)
            self.assertNotIn("ABCDE1234F", app.pan_encrypted)
            self.assertEqual(app.pan_last4, "234F")
            self.assertNotIn("123456789012", app.bank_account_encrypted)
            self.assertEqual(app.bank_account_last4, "9012")

    def test_a_bicycle_needs_no_rc(self) -> None:
        with self.fdb.session() as db:
            user = self.applicant(db)
            fill(db, user, VehicleType.CYCLE)
            self.assertNotIn(ApplicationItemKind.RC, applications.required_for(db.get(RiderApplication, user.id)))
            applications.submit(db, user)

    def test_a_too_young_rider(self) -> None:
        with self.fdb.session() as db:
            user = self.applicant(db)
            with self.assertRaises(HTTPException) as caught:
                applications.save_section(db, user, "personal", {
                    "full_name": "Kid", "date_of_birth": "2010-01-01", "city": "Surat",
                    "address_line": "x", "pincode": "395009", "emergency_name": "M", "emergency_phone": "9876500000",
                }, today=TODAY)
            self.assertEqual(caught.exception.detail, {"field": "date_of_birth", "error": "too_young"})

    def test_a_photo_that_is_not_an_image(self) -> None:
        with self.fdb.session() as db:
            user = self.applicant(db)
            with self.assertRaises(HTTPException) as caught:
                applications.save_photo(db, user, ApplicationItemKind.SELFIE, b"%PDF-1.7 ...")
            self.assertEqual((caught.exception.status_code, caught.exception.detail), (415, "not_an_image"))

    def test_a_photo_that_is_too_large(self) -> None:
        with self.fdb.session() as db:
            user = self.applicant(db)
            huge = JPEG + b"0" * (get_settings().rider_doc_max_bytes + 1)
            with self.assertRaises(HTTPException) as caught:
                applications.save_photo(db, user, ApplicationItemKind.SELFIE, huge)
            self.assertEqual((caught.exception.status_code, caught.exception.detail), (413, "too_large"))

    def test_submissions_and_decisions_are_announced(self) -> None:
        with self.fdb.session() as db:
            user = self.submitted(db)
            self.riders_changed.assert_called_with(user.id, force=True)
            applications.review_item(db, self.admin, user.id, ApplicationItemKind.PAN, accept=False, reason="Blurry")
            applications.send_back(db, self.admin, user.id)
            self.decided.assert_called_with(user.id, "CHANGES_NEEDED")


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



@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class WorkGateTests(unittest.TestCase):
    """A pending rider may sign in and fill in their application - and nothing
    else. The app shows them only the application, but these are the checks
    that hold whatever the app shows."""

    NEAR = (21.185, 72.84)

    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_onboarding_gate_test")

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def setUp(self) -> None:
        for target in ("offer_made", "offer_withdrawn", "trip_changed", "riders_changed", "delivery_changed"):
            p = mock.patch(f"app.services.fleet.notify.{target}")
            p.start()
            self.addCleanup(p.stop)
        for target in ("schedule_expiry", "queue_advance"):
            p = mock.patch(f"app.services.fleet.offers.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(reset_overrides)

    def _pending(self, db, status: RiderStatus = RiderStatus.ONLINE) -> User:
        user = self.fdb.make_rider(db, lat=self.NEAR[0], lng=self.NEAR[1], status=status)
        db.get(Rider, user.id).onboarding = RiderOnboarding.PENDING
        db.commit()
        return user

    def test_a_pending_rider_cannot_go_online(self) -> None:
        from app.services.fleet import riders

        with self.fdb.session() as db:
            user = self._pending(db, RiderStatus.OFFLINE)
            with self.assertRaises(HTTPException) as caught:
                riders.set_status(db, db.get(User, user.id), True)
            self.assertEqual((caught.exception.status_code, caught.exception.detail), (403, "rider_not_approved"))
            self.assertEqual(db.get(Rider, user.id).status, RiderStatus.OFFLINE)

    def test_a_pending_rider_may_still_go_offline(self) -> None:
        from app.services.fleet import riders

        with self.fdb.session() as db:
            user = self._pending(db, RiderStatus.ONLINE)
            riders.set_status(db, db.get(User, user.id), False)
            self.assertEqual(db.get(Rider, user.id).status, RiderStatus.OFFLINE)

    def test_a_pending_rider_is_never_offered(self) -> None:
        from app.services.fleet import offers
        from app.services.fleet.config import load_fleet

        with self.fdb.session() as db:
            user = self._pending(db)
            order = self.fdb.make_order(db)
            delivery = self.fdb.make_fleet_delivery(db, order)
            db.commit()
            found = offers.candidates(db, delivery, load_fleet(db), datetime.now(UTC))
            self.assertNotIn(user.id, [rider.user_id for rider, _ in found])

    def test_a_pending_rider_cannot_claim(self) -> None:
        from app.services.fleet import offers

        with self.fdb.session() as db:
            user = self._pending(db)
            order = self.fdb.make_order(db)
            self.fdb.make_fleet_delivery(db, order)
            db.commit()
            with self.assertRaises(HTTPException) as caught:
                offers.claim(db, db.get(User, user.id), order.id)
            self.assertEqual(caught.exception.detail, "rider_not_approved")

    def test_a_pending_rider_sees_no_board(self) -> None:
        from app.services.fleet import offers

        with self.fdb.session() as db:
            user = self._pending(db)
            order = self.fdb.make_order(db)
            self.fdb.make_fleet_delivery(db, order)
            db.commit()
            self.assertEqual(offers.open_orders(db, db.get(User, user.id)), [])


if __name__ == "__main__":
    unittest.main()
