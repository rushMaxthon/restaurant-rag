"""Who may see and change which payouts. Owners see their own, without the
platform's half; only an admin touches a linked account."""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_payout_ledger import D, LedgerDatabase, postgres_available  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.config.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import PayoutStatus, UserRole  # noqa: E402
from app.models.restaurant_payout import RestaurantPayout  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import get_current_user  # noqa: E402

PREFIX = get_settings().api_v1_prefix.rstrip("/")


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class PayoutApiTests(LedgerDatabase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = User(id=uuid.uuid4(), email=f"a{uuid.uuid4().hex[:6]}@x.in", full_name="Admin",
                          hashed_password="x", role=UserRole.ADMIN)
        self.db.add(self.admin)
        self.db.commit()
        order = self.make_order()
        self.payout = RestaurantPayout(order_id=order.id, restaurant_id=self.restaurant.id,
                                       restaurant_share=D("496.00"), platform_keeps=D("102.20"), currency="INR",
                                       status=PayoutStatus.FAILED.value, last_error="nope")
        self.db.add(self.payout)
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        self.addCleanup(app.dependency_overrides.clear)
        self.http = TestClient(app)

    def as_user(self, user) -> None:
        app.dependency_overrides[get_current_user] = lambda: user

    def test_an_owner_sees_their_share_and_not_the_platforms(self) -> None:
        self.as_user(self.owner)
        body = self.http.get(f"{PREFIX}/payouts").json()
        self.assertEqual(body["rows"][0]["restaurant_share"], "496.00")
        self.assertIsNone(body["rows"][0]["platform_keeps"])

    def test_an_owner_cannot_name_another_restaurant(self) -> None:
        self.as_user(self.owner)
        self.assertEqual(self.http.get(f"{PREFIX}/payouts?restaurant_id={uuid.uuid4()}").status_code, 403)
        self.assertEqual(self.http.get(f"{PREFIX}/payouts/account?restaurant_id={uuid.uuid4()}").status_code, 403)

    def test_an_owner_cannot_retry_or_edit(self) -> None:
        self.as_user(self.owner)
        self.assertEqual(self.http.post(f"{PREFIX}/payouts/{self.payout.id}/retry").status_code, 403)
        self.assertIn(self.http.put(f"{PREFIX}/payouts/account", json={}).status_code, (403, 422))

    def test_an_admin_sees_both_halves_and_a_summary(self) -> None:
        self.as_user(self.admin)
        body = self.http.get(f"{PREFIX}/payouts?restaurant_id={self.restaurant.id}").json()
        self.assertEqual(body["rows"][0]["platform_keeps"], "102.20")
        self.assertEqual(body["summary"]["problems"]["count"], 1)
        self.assertFalse(body["payouts_enabled"])

    def test_an_admin_must_name_a_restaurant_for_its_account(self) -> None:
        self.as_user(self.admin)
        self.assertEqual(self.http.get(f"{PREFIX}/payouts/account").status_code, 400)


if __name__ == "__main__":
    unittest.main()
