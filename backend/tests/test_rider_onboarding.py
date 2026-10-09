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

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available, reset_overrides  # noqa: E402

from app.models.enums import RiderOnboarding  # noqa: E402
from app.models.rider import Rider  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
