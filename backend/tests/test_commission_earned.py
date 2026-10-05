"""What the platform earned on an order, and who may read it.

The commission is inside the menu price. Until an order recorded it, the only
way to say what was earned was to multiply by the branch's current rate - and
the rate is a dial, so the answer for last month changed whenever somebody
turned it.

**Charged twice.** 110.00 at 10% carries 10.00 of commission, not 11.00. The
rate went onto the typed price; it comes back out of the listed one.

**A restaurant that pays none.** A branch at 0% earns nothing and must not
divide by anything on the way to saying so.

**An owner reading the platform's books.** The report is the platform's. The
route is admin-only; the screen being hidden is not the rule.
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.services.auth import get_current_user  # noqa: E402
from app.services.commission import commission_in  # noqa: E402

D = Decimal


class TheCommissionInsideASubtotalTests(unittest.TestCase):
    def test_it_is_taken_back_out_not_charged_again(self) -> None:
        self.assertEqual(commission_in(D("110.00"), D("10")), D("10.00"))
        self.assertEqual(commission_in(D("55.00"), D("10")), D("5.00"))

    def test_another_rate(self) -> None:
        # Typed 100 at 12% is listed at 112.
        self.assertEqual(commission_in(D("112.00"), D("12")), D("12.00"))

    def test_a_price_that_was_rounded_when_it_was_listed(self) -> None:
        # Typed 49.95 at 10% is 54.945, listed at 54.95. The commission is 5.00.
        self.assertEqual(commission_in(D("54.95"), D("10")), D("5.00"))

    def test_a_branch_that_pays_no_commission_earns_none(self) -> None:
        self.assertEqual(commission_in(D("110.00"), D("0")), D("0.00"))
        self.assertEqual(commission_in(D("110.00"), None), D("0.00"))

    def test_nothing_sold_earns_nothing(self) -> None:
        self.assertEqual(commission_in(D("0"), D("10")), D("0.00"))
        self.assertEqual(commission_in(None, D("10")), D("0.00"))

    def test_it_is_money_to_the_paisa(self) -> None:
        earned = commission_in(D("133.33"), D("10"))
        self.assertEqual(earned, earned.quantize(D("0.01")))
        self.assertEqual(earned, D("12.12"))


class WhoMayReadTheReportTests(unittest.TestCase):
    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _as(self, role: UserRole) -> int:
        from types import SimpleNamespace
        import uuid

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(), role=role, is_active=True, restaurant_id=None
        )
        return TestClient(app).get("/api/admin/commission").status_code

    def test_an_owner_is_refused(self) -> None:
        self.assertEqual(self._as(UserRole.OWNER), 403)

    def test_a_customer_is_refused(self) -> None:
        self.assertEqual(self._as(UserRole.CUSTOMER), 403)

    def test_nobody_signed_in_is_refused(self) -> None:
        self.assertIn(TestClient(app).get("/api/admin/commission").status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
