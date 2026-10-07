"""The platform fee is the platform's to set, like the commission.

Found in the 2026-10-07 security review. `platform_fee` is the flat amount
per order the platform keeps (`payouts/split.py` puts it in platform_keeps),
but only `commission_percent` was guarded: an owner could send
`{"platform_fee": 0}` with their branch settings and take it away. Decided
with the platform owner: admin only, the same rule as the commission - an
owner may send the value they were shown, never a different one.
"""

from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api import restaurants  # noqa: E402
from app.models.enums import UserRole  # noqa: E402

OWNER = SimpleNamespace(role=UserRole.OWNER)
ADMIN = SimpleNamespace(role=UserRole.ADMIN)


def _branch():
    return SimpleNamespace(
        platform_fee=Decimal("5.00"),
        commission_percent=Decimal("10.00"),
        gst_in_menu_prices=False,
        delivery_fee=Decimal("0"),
    )


class WhoMaySetIt(unittest.TestCase):
    def test_an_owner_cannot_change_it(self) -> None:
        branch = _branch()
        with self.assertRaises(HTTPException) as raised:
            restaurants._apply_location_changes(None, branch, {"platform_fee": Decimal("0")}, OWNER)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(branch.platform_fee, Decimal("5.00"))

    def test_nothing_else_on_the_form_is_written_either(self) -> None:
        branch = _branch()
        with self.assertRaises(HTTPException):
            restaurants._apply_location_changes(
                None, branch, {"platform_fee": Decimal("0"), "delivery_fee": Decimal("30")}, OWNER
            )
        self.assertEqual(branch.delivery_fee, Decimal("0"))

    def test_an_owner_saving_the_form_unchanged_is_fine(self) -> None:
        branch = _branch()
        restaurants._apply_location_changes(
            None, branch, {"platform_fee": Decimal("5"), "delivery_fee": Decimal("30")}, OWNER
        )
        self.assertEqual(branch.delivery_fee, Decimal("30"))

    def test_an_explicit_null_is_no_opinion(self) -> None:
        branch = _branch()
        restaurants._apply_location_changes(None, branch, {"platform_fee": None}, OWNER)
        self.assertEqual(branch.platform_fee, Decimal("5.00"))

    def test_the_admin_can(self) -> None:
        branch = _branch()
        restaurants._apply_location_changes(None, branch, {"platform_fee": Decimal("7.50")}, ADMIN)
        self.assertEqual(branch.platform_fee, Decimal("7.50"))


if __name__ == "__main__":
    unittest.main()
