"""The fleet's tables exist, a rider is platform staff, and the flag is off.

Platform staff is the part that bites: `ck_users_app_client_scope_matches_role`
and the platform uniqueness indexes name roles explicitly, and 0071 showed
that forgetting one leaves a role with no uniqueness at all.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.enums import OrderEventActor, UserRole  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.rider import Rider, RiderOffer, RiderPayout, RiderTrip  # noqa: E402
from app.services.order_events import actor_for_user  # noqa: E402


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class FleetSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_schema_test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def test_a_rider_is_platform_staff(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db)
            db.commit()
            self.assertEqual(rider.role, UserRole.RIDER)
            self.assertIsNone(rider.app_client_id)
            self.assertIsNotNone(db.get(Rider, rider.id))

    def test_a_riders_advance_is_logged_as_the_rider(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db)
            self.assertEqual(actor_for_user(rider), OrderEventActor.RIDER)

    def test_tables_and_otp_columns_exist(self) -> None:
        for model in (Rider, RiderOffer, RiderTrip, RiderPayout):
            self.assertIn(model.__tablename__, model.metadata.tables)
        cols = OrderDelivery.__table__.columns
        for name in ("delivery_otp_hash", "otp_attempts", "otp_locked"):
            self.assertIn(name, cols)

    def test_flag_defaults_off(self) -> None:
        self.assertFalse(get_settings().enable_own_fleet)


if __name__ == "__main__":
    unittest.main()
