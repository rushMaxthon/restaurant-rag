"""What a rider is paid, and the dispatch dials, both set by the super admin.

Defaults ship in code so nothing needs saving before the first trip:
Rs 25 + Rs 6 per km, never under Rs 30; offers last 30 s, five riders are
tried, and after four minutes the order goes to Pidge. A saved value that
would pay nothing or offer for zero seconds is refused, because it applies to
every trip at once.
"""

from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from app.services.fleet import config, earnings  # noqa: E402


class PayFormulaTests(unittest.TestCase):
    def test_base_plus_per_km(self) -> None:
        pay = config.RiderPay(base=Decimal("25"), per_km=Decimal("6"), minimum=Decimal("30"))
        amount, parts = earnings.earning_for(4.0, pay)
        self.assertEqual(amount, Decimal("49.00"))
        self.assertEqual(parts, {"base": "25", "per_km": "6", "km": 4.0, "minimum": "30"})

    def test_short_trip_gets_the_minimum(self) -> None:
        pay = config.RiderPay(base=Decimal("10"), per_km=Decimal("2"), minimum=Decimal("30"))
        self.assertEqual(earnings.earning_for(1.0, pay)[0], Decimal("30.00"))

    def test_km_is_rounded_to_one_decimal(self) -> None:
        self.assertEqual(earnings.earning_for(3.04, config.default_pay())[0], Decimal("43.00"))

    def test_negative_distance_pays_the_minimum_not_less(self) -> None:
        self.assertEqual(earnings.earning_for(-5, config.default_pay())[0], Decimal("30.00"))


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class SavedSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_config_test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def setUp(self) -> None:
        # One database for the class: start every test from "nothing saved".
        from sqlalchemy import delete

        from app.models.platform_setting import PlatformSetting

        with self.fdb.session() as db:
            db.execute(delete(PlatformSetting))
            db.commit()

    def test_defaults_when_nothing_saved(self) -> None:
        with self.fdb.session() as db:
            self.assertEqual(config.load_pay(db), config.default_pay())
            fleet = config.load_fleet(db)
            self.assertEqual((fleet.offer_seconds, fleet.max_offers, fleet.window_minutes), (30, 5, 5))
            self.assertEqual(fleet.location_ids, [])

    def test_admin_saves_and_reads_back(self) -> None:
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            config.save_pay(db, admin, {"base": "30", "per_km": "7", "minimum": "35"})
            self.assertEqual(config.load_pay(db).per_km, Decimal("7"))
            config.save_fleet(db, admin, {"offer_seconds": 45, "radius_km": 8})
            self.assertEqual(config.load_fleet(db).offer_seconds, 45)
            self.assertEqual(config.load_fleet(db).radius_km, 8.0)

    def test_nonsense_is_refused(self) -> None:
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            for bad in (
                {"base": "0", "per_km": "0", "minimum": "0"},
                {"base": "-1", "per_km": "6", "minimum": "30"},
                {"base": "abc", "per_km": "6", "minimum": "30"},
            ):
                with self.subTest(bad=bad), self.assertRaises(HTTPException):
                    config.save_pay(db, admin, bad)
            for bad in ({"offer_seconds": 0}, {"radius_km": 100}, {"location_ids": "all"}):
                with self.subTest(bad=bad), self.assertRaises(HTTPException):
                    config.save_fleet(db, admin, bad)


if __name__ == "__main__":
    unittest.main()
