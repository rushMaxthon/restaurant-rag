"""Only the super admin hires and lets go of riders, and letting go is immediate.

A rider is a login that sees customers' addresses and phone numbers while a
trip is live, so deactivation must end the session at once (token_version),
take the rider off shift, and hand any open offer to the next rider rather
than leave it ticking down on a phone that no longer works.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, client_for, postgres_available, reset_overrides  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.models.enums import OfferOutcome, RiderStatus, UserRole  # noqa: E402
from app.models.rider import Rider, RiderOffer  # noqa: E402
from app.models.user import User  # noqa: E402


def _body(**over):
    body = {
        "full_name": "Ravi Kumar",
        "phone_number": "9876543210",
        "password": "s3cret-pass",
        "vehicle_type": "BIKE",
        "vehicle_number": "gj05ab1234",
        "city": "Surat",
    }
    body.update(over)
    return body


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class RiderAdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_riders_admin_test")
        with cls.fdb.session() as db:
            cls.admin = cls.fdb.make_admin(db)
            cls.owner = cls.fdb.make_owner(db)
            cls.fdb.ensure_marketplace(db)
            db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def tearDown(self) -> None:
        reset_overrides()

    def test_admin_creates_a_rider_who_can_sign_in_by_phone(self) -> None:
        r = client_for(self.fdb, self.admin).post("/api/admin/riders", json=_body())
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["vehicle_number"], "GJ05AB1234")
        self.assertEqual(r.json()["status"], "OFFLINE")
        self.assertEqual(r.json()["phone_number"], "+919876543210")
        login = client_for(self.fdb, None).post(
            "/api/auth/login", json={"phone_number": "+919876543210", "password": "s3cret-pass"}
        )
        # The app always signs in with +91; the admin typed ten digits.
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(login.json()["user"]["role"], "RIDER")

    def test_same_phone_twice_is_409(self) -> None:
        body = _body(phone_number="9876500001")
        self.assertEqual(client_for(self.fdb, self.admin).post("/api/admin/riders", json=body).status_code, 201)
        again = client_for(self.fdb, self.admin).post("/api/admin/riders", json=body)
        self.assertEqual(again.status_code, 409, again.text)

    def test_only_the_admin_reaches_the_roster(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db)
            db.commit()
        for user in (self.owner, rider):
            with self.subTest(role=user.role):
                self.assertEqual(client_for(self.fdb, user).get("/api/admin/riders").status_code, 403)

    def test_short_password_is_refused(self) -> None:
        r = client_for(self.fdb, self.admin).post("/api/admin/riders", json=_body(phone_number="9876500002", password="123"))
        self.assertEqual(r.status_code, 422)

    def test_list_shows_riders(self) -> None:
        client_for(self.fdb, self.admin).post("/api/admin/riders", json=_body(phone_number="9876500003", full_name="Listed"))
        names = [r["full_name"] for r in client_for(self.fdb, self.admin).get("/api/admin/riders").json()]
        self.assertIn("Listed", names)

    def test_deactivation_ends_shift(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.ONLINE)
            order = self.fdb.make_order(db)
            delivery = self.fdb.make_fleet_delivery(db, order)
            now = datetime.now(UTC)
            db.add(RiderOffer(order_delivery_id=delivery.id, rider_user_id=rider.id, offered_at=now,
                              expires_at=now + timedelta(seconds=30)))
            db.commit()
            version = rider.token_version
        with mock.patch("app.services.fleet.offers.queue_advance") as advance:
            r = client_for(self.fdb, self.admin).patch(f"/api/admin/riders/{rider.id}", json={"is_active": False})
        self.assertEqual(r.status_code, 200, r.text)
        with self.fdb.session() as db:
            self.assertEqual(db.get(Rider, rider.id).status, RiderStatus.OFFLINE)
            self.assertGreater(db.get(User, rider.id).token_version, version)
            outcome = db.scalar(select(RiderOffer.outcome).where(RiderOffer.rider_user_id == rider.id))
            self.assertEqual(outcome, OfferOutcome.WITHDRAWN)
        advance.assert_called_once_with(delivery.id)

    def test_unknown_rider_is_404(self) -> None:
        r = client_for(self.fdb, self.admin).patch(f"/api/admin/riders/{self.owner.id}", json={"city": "X"})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
