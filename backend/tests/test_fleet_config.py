"""What a rider is paid, and the dispatch dials, both set by the super admin.

Defaults ship in code so nothing needs saving before the first trip:
the owner's rate card (Rs 25 up to 3 km ... Rs 50 up to 8 km, Rs 5 more for
every delivery, priced by hand past 8 km); offers last 30 s, five riders are
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


class PaySlabTests(unittest.TestCase):
    """The owner's rate card (2026-10-10): a slab by distance, plus Rs 5 a delivery."""

    def test_the_default_is_the_owners_rate_card(self) -> None:
        pay = config.default_pay()
        self.assertEqual(
            [(s.up_to_km, s.amount) for s in pay.slabs],
            [(3.0, Decimal("25")), (3.5, Decimal("25")), (4.0, Decimal("30")), (4.5, Decimal("30")),
             (5.0, Decimal("35")), (5.5, Decimal("35")), (6.0, Decimal("40")), (6.5, Decimal("40")),
             (7.0, Decimal("45")), (7.5, Decimal("45")), (8.0, Decimal("50"))],
        )
        self.assertEqual((pay.incentive, pay.minimum), (Decimal("5"), Decimal("25")))

    def test_a_trip_pays_its_slab_plus_the_incentive(self) -> None:
        amount, parts = earnings.earning_for(4.2, config.default_pay())
        self.assertEqual(amount, Decimal("35.00"))  # 4-4.5 km slab Rs 30 + Rs 5
        self.assertEqual(parts, {"km": 4.2, "slab_km": 4.5, "slab": "30", "incentive": "5"})

    def test_the_top_of_a_slab_belongs_to_it(self) -> None:
        pay = config.default_pay()
        self.assertEqual(earnings.earning_for(3.0, pay)[0], Decimal("30.00"))
        self.assertEqual(earnings.earning_for(3.04, pay)[0], Decimal("30.00"))  # rounds to 3.0
        self.assertEqual(earnings.earning_for(3.6, pay)[0], Decimal("35.00"))  # 3.5-4 km: Rs 30

    def test_a_very_short_or_negative_trip_pays_the_first_slab(self) -> None:
        pay = config.default_pay()
        self.assertEqual(earnings.earning_for(0.4, pay)[0], Decimal("30.00"))
        self.assertEqual(earnings.earning_for(-5, pay)[0], Decimal("30.00"))

    def test_past_the_last_slab_the_admin_prices_it(self) -> None:
        amount, parts = earnings.earning_for(8.3, config.default_pay())
        self.assertIsNone(amount)
        self.assertEqual(parts, {"km": 8.3, "manual": True, "over_km": 8.0, "incentive": "5"})
        self.assertEqual(earnings.earning_for(8.0, config.default_pay())[0], Decimal("55.00"))


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
            config.save_pay(db, admin, {"slabs": [{"up_to_km": 3, "amount": "30"}, {"up_to_km": 6, "amount": "45"}], "incentive": "7", "minimum": "20"})
            pay = config.load_pay(db)
            self.assertEqual([(s.up_to_km, s.amount) for s in pay.slabs], [(3.0, Decimal("30")), (6.0, Decimal("45"))])
            self.assertEqual((pay.incentive, pay.minimum), (Decimal("7"), Decimal("20")))
            config.save_fleet(db, admin, {"offer_seconds": 45, "radius_km": 8})
            self.assertEqual(config.load_fleet(db).offer_seconds, 45)
            self.assertEqual(config.load_fleet(db).radius_km, 8.0)

    def test_the_old_formula_row_reads_as_the_rate_card(self) -> None:
        """A row saved before 2026-10-10 (base + per km) is not a rate card."""

        from app.models.platform_setting import PlatformSetting

        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            db.add(PlatformSetting(key=config.PAY_KEY, value={"base": "25", "per_km": "6", "minimum": "30"},
                                   updated_by_user_id=admin.id))
            db.commit()
            self.assertEqual(config.load_pay(db), config.default_pay())

    def test_nonsense_is_refused(self) -> None:
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            for bad in (
                {"slabs": [], "incentive": "5", "minimum": "25"},
                {"slabs": [{"up_to_km": 3, "amount": "0"}], "incentive": "0", "minimum": "0"},
                {"slabs": [{"up_to_km": 3, "amount": "-1"}], "incentive": "5", "minimum": "25"},
                {"slabs": [{"up_to_km": 3, "amount": "abc"}], "incentive": "5", "minimum": "25"},
                {"slabs": [{"up_to_km": 5, "amount": "30"}, {"up_to_km": 4, "amount": "35"}], "incentive": "5", "minimum": "25"},
                {"slabs": [{"up_to_km": 3, "amount": "30"}, {"up_to_km": 4, "amount": "25"}], "incentive": "5", "minimum": "25"},
                {"slabs": [{"up_to_km": 0, "amount": "30"}], "incentive": "5", "minimum": "25"},
                {"slabs": [{"up_to_km": 3, "amount": "30"}], "incentive": "-1", "minimum": "25"},
                {"base": "25", "per_km": "6", "minimum": "30"},
            ):
                with self.subTest(bad=bad), self.assertRaises(HTTPException):
                    config.save_pay(db, admin, bad)
            for bad in ({"offer_seconds": 0}, {"radius_km": 100}, {"location_ids": "all"}):
                with self.subTest(bad=bad), self.assertRaises(HTTPException):
                    config.save_fleet(db, admin, bad)


if __name__ == "__main__":
    unittest.main()
