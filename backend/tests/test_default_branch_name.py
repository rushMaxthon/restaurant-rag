"""A restaurant's first branch is named after the restaurant.

It was "Main Branch" for every restaurant, and that word reached the
customer's branch picker, the kitchen board, receipts, and the rider: the
first live Pidge booking (2026-10-06) told the rider to collect from "Main
Branch" with no restaurant named. A second branch is named by the owner.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.restaurant_locations import build_default_location_for_restaurant  # noqa: E402


def a_restaurant(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), name=name, address_line_1="1 Road", address_line_2=None, city="Surat",
        state="Gujarat", postal_code="395004", phone_number="9876500000", delivery_fee=0,
        minimum_order_amount=0, is_open=True, is_active=True,
    )


class DefaultBranchNameTests(unittest.TestCase):
    def test_the_first_branch_takes_the_restaurants_name(self) -> None:
        location = build_default_location_for_restaurant(a_restaurant("Bhagwati Bakery"))
        self.assertEqual(location.branch_name, "Bhagwati Bakery")

    def test_a_restaurant_with_no_name_yet_still_gets_a_branch_name(self) -> None:
        location = build_default_location_for_restaurant(a_restaurant("  "))
        self.assertTrue(location.branch_name.strip())


if __name__ == "__main__":
    unittest.main()
