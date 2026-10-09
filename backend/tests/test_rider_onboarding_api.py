"""Rider sign-up and review over HTTP: the contract the rider app and the
admin panel are built against.

Storage is faked at the module seam (`storage.upload` / `signed_url`), so no
test touches Supabase; everything else - auth, rate limits, the state
machine, the database - is real.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, client_for, postgres_available, reset_overrides  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.user import User  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64

PERSONAL = {
    "full_name": "Asha Applicant", "date_of_birth": "1995-05-10", "city": "Surat",
    "address_line": "12 Rander Road, Adajan", "pincode": "395009",
    "emergency_name": "Ravi", "emergency_phone": "9876500000",
}
VEHICLE = {"vehicle_type": "BIKE", "vehicle_number": "GJ05AB1234"}
DOCUMENTS = {
    "aadhaar_last4": "4321", "pan": "ABCDE1234F",
    "licence_number": "GJ0520190012345", "licence_expiry": "2030-01-01",
}
BANK = {
    "bank_holder": "Asha Applicant", "account_number": "123456789012",
    "account_number_again": "123456789012", "ifsc": "SBIN0001234",
}


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class SignupApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_onboarding_api_test")
        with cls.fdb.session() as db:
            cls.admin = cls.fdb.make_admin(db)
            db.commit()
        cls.n = 0

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def setUp(self) -> None:
        mock.patch("app.services.fleet.onboarding.storage.configured", return_value=True).start()
        mock.patch("app.services.fleet.onboarding.storage.upload").start()
        mock.patch("app.services.fleet.onboarding.storage.delete").start()
        mock.patch(
            "app.services.fleet.onboarding.storage.signed_url", side_effect=lambda path, seconds=300: f"https://signed/{path}"
        ).start()
        mock.patch("app.services.fleet.notify.application_decided").start()
        mock.patch("app.services.fleet.notify.riders_changed").start()
        # The per-IP limiter would trip on a suite that signs up many riders.
        mock.patch("app.services.rate_limit.hit").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(reset_overrides)

    def phone(self) -> str:
        type(self).n += 1
        return f"81000{type(self).n:05d}"

    def sign_up(self, digits: str | None = None) -> tuple[str, str]:
        digits = digits or self.phone()
        public = client_for(self.fdb, None)
        sent = public.post("/api/rider/signup/code", json={"phone_number": digits})
        self.assertEqual(sent.status_code, 200, sent.text)
        made = public.post(
            "/api/rider/signup",
            json={
                "phone_number": digits, "code": sent.json()["debug_code"],
                "password": "password123", "full_name": "Asha Applicant",
            },
        )
        self.assertEqual(made.status_code, 201, made.text)
        return made.json()["access_token"], made.json()["user"]["id"]

    def rider(self, token: str):
        client = client_for(self.fdb, None)
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    def admin_client(self):
        # A real token, not `client_for(fdb, admin)`: that override is global
        # to the app, and would turn the rider's client into the admin too.
        from app.services.auth import create_access_token

        with self.fdb.session() as db:
            return self.rider(create_access_token(db.get(User, self.admin.id)))

    def complete(self, client) -> None:
        for section, body in (("personal", PERSONAL), ("vehicle", VEHICLE), ("documents", DOCUMENTS), ("bank", BANK)):
            response = client.put(f"/api/rider/application/{section}", json=body)
            self.assertEqual(response.status_code, 200, response.text)
        for kind in ("SELFIE", "RC", "AADHAAR_FRONT", "AADHAAR_BACK", "PAN", "LICENCE_FRONT", "LICENCE_BACK", "BANK_PROOF"):
            response = client.post(
                f"/api/rider/application/items/{kind}", files={"file": ("photo.jpg", JPEG, "image/jpeg")}
            )
            self.assertEqual(response.status_code, 200, response.text)

    # --- sign-up ----------------------------------------------------------------

    def test_sign_up_end_to_end(self) -> None:
        token, _ = self.sign_up()
        me = self.rider(token).get("/api/rider/me")
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["onboarding"], "PENDING")
        self.assertEqual(me.json()["application_status"], "DRAFT")

    def test_the_static_code_is_handed_back_to_type(self) -> None:
        sent = client_for(self.fdb, None).post("/api/rider/signup/code", json={"phone_number": self.phone()})
        self.assertEqual(sent.json()["debug_code"], get_settings().otp_debug_code)
        self.assertFalse(sent.json()["sent"])

    def test_sign_up_with_a_taken_phone(self) -> None:
        digits = self.phone()
        self.sign_up(digits)
        again = client_for(self.fdb, None).post("/api/rider/signup/code", json={"phone_number": digits})
        self.assertEqual((again.status_code, again.json()["detail"]), (409, "phone_in_use"))

    def test_a_wrong_code_does_not_create_an_account(self) -> None:
        digits = self.phone()
        public = client_for(self.fdb, None)
        public.post("/api/rider/signup/code", json={"phone_number": digits})
        made = public.post(
            "/api/rider/signup",
            json={"phone_number": digits, "code": "000000", "password": "password123", "full_name": "X Y"},
        )
        self.assertEqual((made.status_code, made.json()["detail"]), (400, "code_wrong"))
        with self.fdb.session() as db:
            self.assertIsNone(db.query(User).filter(User.phone_number == f"+91{digits}").first())

    def test_the_code_is_checked_on_its_own_screen(self) -> None:
        """A wrong code is said on the code screen, before the rider types a
        name and password - and checking it does not use it up."""

        digits = self.phone()
        public = client_for(self.fdb, None)
        sent = public.post("/api/rider/signup/code", json={"phone_number": digits}).json()
        wrong = public.post("/api/rider/signup/check", json={"phone_number": digits, "code": "000000"})
        self.assertEqual((wrong.status_code, wrong.json()["detail"]), (400, "code_wrong"))
        right = public.post("/api/rider/signup/check", json={"phone_number": digits, "code": sent["debug_code"]})
        self.assertEqual(right.status_code, 204, right.text)
        made = public.post(
            "/api/rider/signup",
            json={"phone_number": digits, "code": sent["debug_code"], "password": "password123", "full_name": "A B"},
        )
        self.assertEqual(made.status_code, 201, made.text)

    # --- the application ---------------------------------------------------------

    def test_responses_never_carry_full_numbers(self) -> None:
        token, _ = self.sign_up()
        client = self.rider(token)
        self.complete(client)
        text = client.get("/api/rider/application").text
        for secret in ("ABCDE1234F", "123456789012", "GJ0520190012345"):
            self.assertNotIn(secret, text)
        self.assertIn("234F", text)

    def test_upload_rejects_a_renamed_pdf(self) -> None:
        token, _ = self.sign_up()
        response = self.rider(token).post(
            "/api/rider/application/items/SELFIE", files={"file": ("me.jpg", b"%PDF-1.7 hello", "image/jpeg")}
        )
        self.assertEqual((response.status_code, response.json()["detail"]), (415, "not_an_image"))

    def test_upload_rejects_a_huge_file(self) -> None:
        token, _ = self.sign_up()
        huge = JPEG + b"0" * get_settings().rider_doc_max_bytes
        response = self.rider(token).post(
            "/api/rider/application/items/SELFIE", files={"file": ("me.jpg", huge, "image/jpeg")}
        )
        self.assertEqual(response.status_code, 413)

    def test_a_pending_rider_cannot_go_online(self) -> None:
        token, _ = self.sign_up()
        response = self.rider(token).post("/api/rider/status", json={"online": True})
        self.assertEqual((response.status_code, response.json()["detail"]), (403, "rider_not_approved"))

    # --- review -------------------------------------------------------------------

    def test_admin_review_flow(self) -> None:
        token, rider_id = self.sign_up()
        client = self.rider(token)
        self.complete(client)
        self.assertEqual(client.post("/api/rider/application/submit").json()["status"], "SUBMITTED")

        admin = self.admin_client()
        queue = admin.get("/api/admin/rider-applications", params={"status": "SUBMITTED"}).json()
        self.assertIn(rider_id, [row["rider_user_id"] for row in queue])
        detail = admin.get(f"/api/admin/rider-applications/{rider_id}").json()
        self.assertTrue(detail["photos"]["PAN"].startswith("https://signed/"))

        flagged = admin.post(f"/api/admin/rider-applications/{rider_id}/items/PAN/flag", json={"reason": "Blurry"})
        self.assertEqual(flagged.status_code, 200, flagged.text)
        self.assertEqual(admin.post(f"/api/admin/rider-applications/{rider_id}/send-back").json()["status"], "CHANGES_NEEDED")

        seen = client.get("/api/rider/application").json()
        pan = next(i for i in seen["items"] if i["kind"] == "PAN")
        self.assertEqual((pan["status"], pan["reason"], pan["editable"]), ("NEEDS_CHANGE", "Blurry", True))
        client.post("/api/rider/application/items/PAN", files={"file": ("pan.jpg", JPEG, "image/jpeg")})
        self.assertEqual(client.post("/api/rider/application/submit").json()["status"], "SUBMITTED")

        for kind in detail["required"]:
            response = admin.post(f"/api/admin/rider-applications/{rider_id}/items/{kind}/accept")
            self.assertEqual(response.status_code, 200, response.text)
        approved = admin.post(f"/api/admin/rider-applications/{rider_id}/approve")
        self.assertEqual(approved.json()["status"], "APPROVED", approved.text)
        self.assertEqual(client.post("/api/rider/status", json={"online": True}).status_code, 200)

    def test_a_rider_cannot_read_the_admin_routes(self) -> None:
        token, rider_id = self.sign_up()
        response = self.rider(token).get(f"/api/admin/rider-applications/{rider_id}")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
