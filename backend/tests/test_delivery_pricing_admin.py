"""The platform admin edits the delivery slabs, and every restaurant follows.

Asked for on 2026-10-07: "give me options in the admin panel for delivery
range and their price ... it will apply for all and this is visible for only
super admin". So:

- one `platform_settings` row, key "delivery_pricing", holding the slabs, the
  furthest the platform delivers and the GST on delivery;
- no row means the settings defaults (Rs 68 / 78 / 100, 10 km, 18%), so
  shipping this changes nobody's price;
- only an ADMIN may read or write it. An owner never sees it: next to what a
  courier charges it is the platform's delivery margin;
- a list that would leave a gap, go backwards or charge nothing past the last
  slab is refused rather than saved, because a saved mistake is a price every
  customer pays at once.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.restaurant import Restaurant  # noqa: E402
from app.models.restaurant_location import RestaurantLocation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.delivery_pricing import DeliveryPricingUpdate  # noqa: E402
from app.services import order_charges  # noqa: E402
from app.services.auth import get_current_user  # noqa: E402
from app.services.delivery import slabs  # noqa: E402

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_delivery_pricing_test"


def _url(database: str) -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/{database}"
    )


def postgres_available() -> bool:
    engine = None
    try:
        engine = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with engine.connect():
            return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if engine is not None:
            engine.dispose()


def _update(**over) -> DeliveryPricingUpdate:
    body = {
        "slabs": [
            {"up_to_km": 3, "fee": "60"},
            {"up_to_km": 6, "fee": "80"},
            {"up_to_km": None, "fee": "110"},
        ],
        "max_distance_km": 12,
        "gst_percent": 18,
    }
    body.update(over)
    return DeliveryPricingUpdate(**body)


class WhoMayOpenIt(unittest.TestCase):
    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def _as(self, role: UserRole, method: str = "get") -> int:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(), role=role, is_active=True, restaurant_id=None
        )
        client = TestClient(app)
        if method == "get":
            return client.get("/api/admin/delivery-pricing").status_code
        return client.put("/api/admin/delivery-pricing", json=_update().model_dump(mode="json")).status_code

    def test_an_owner_cannot_read_it(self) -> None:
        self.assertEqual(self._as(UserRole.OWNER), 403)

    def test_an_owner_cannot_change_it(self) -> None:
        self.assertEqual(self._as(UserRole.OWNER, "put"), 403)

    def test_a_cook_or_customer_cannot_either(self) -> None:
        self.assertEqual(self._as(UserRole.KITCHEN), 403)
        self.assertEqual(self._as(UserRole.CUSTOMER), 403)


class WhatIsAValidList(unittest.TestCase):
    def _refused(self, **over) -> str:
        with self.assertRaises(HTTPException) as raised:
            slabs.validate_update(_update(**over))
        self.assertEqual(raised.exception.status_code, 422)
        return str(raised.exception.detail)

    def test_the_example_is_valid(self) -> None:
        pricing = slabs.validate_update(_update())
        self.assertEqual(pricing.slabs[-1], (None, Decimal("110.00")))

    def test_the_last_slab_must_be_open_ended(self) -> None:
        detail = self._refused(slabs=[{"up_to_km": 2, "fee": "68"}, {"up_to_km": 5, "fee": "78"}])
        self.assertIn("last", detail.lower())

    def test_only_the_last_slab_may_be_open_ended(self) -> None:
        self._refused(slabs=[{"up_to_km": None, "fee": "68"}, {"up_to_km": None, "fee": "78"}])

    def test_distances_must_go_up(self) -> None:
        self._refused(
            slabs=[{"up_to_km": 5, "fee": "78"}, {"up_to_km": 2, "fee": "68"}, {"up_to_km": None, "fee": "100"}]
        )

    def test_a_negative_fee_is_refused(self) -> None:
        self._refused(slabs=[{"up_to_km": 2, "fee": "-1"}, {"up_to_km": None, "fee": "100"}])

    def test_a_slab_past_the_delivery_limit_is_refused(self) -> None:
        # A price for a distance nobody is delivered to is a mistake waiting.
        self._refused(max_distance_km=4)

    def test_the_gst_rate_is_bounded(self) -> None:
        self._refused(gst_percent=40)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class SavedOnceAppliesEverywhere(unittest.TestCase):
    engine = None

    @classmethod
    def setUpClass(cls) -> None:
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin.dispose()
        cls.engine = create_engine(_url(TEST_DB_NAME))
        with cls.engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
        Base.metadata.create_all(cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.engine is not None:
            cls.engine.dispose()
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin.dispose()

    def setUp(self) -> None:
        self.db = self.session_factory()
        self.db.execute(text("DELETE FROM platform_settings"))
        self.db.commit()
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self.addCleanup(self.db.close)

    def _admin(self) -> User:
        user = User(
            email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
            full_name="Admin",
            hashed_password="x",
            role=UserRole.ADMIN,
        )
        self.db.add(user)
        self.db.commit()
        return user

    def test_with_no_row_the_agreed_defaults_stand(self) -> None:
        pricing = slabs.load_pricing(self.db)
        self.assertEqual(slabs.fee_for_distance(1500, pricing), Decimal("68.00"))
        self.assertEqual(pricing.max_distance_km, 10.0)
        self.assertEqual(pricing.gst_percent, Decimal("18"))
        self.assertFalse(pricing.saved)

    def test_a_saved_list_is_what_the_next_load_returns(self) -> None:
        admin = self._admin()
        slabs.save_pricing(self.db, admin, _update())
        pricing = slabs.load_pricing(self.db)
        self.assertTrue(pricing.saved)
        self.assertEqual(slabs.fee_for_distance(2500, pricing), Decimal("60.00"))
        self.assertEqual(slabs.fee_for_distance(5000, pricing), Decimal("80.00"))
        self.assertEqual(slabs.fee_for_distance(9000, pricing), Decimal("110.00"))
        self.assertEqual(pricing.max_distance_km, 12.0)
        self.assertEqual(pricing.updated_by, admin.id)

    def test_saving_twice_keeps_one_row(self) -> None:
        admin = self._admin()
        slabs.save_pricing(self.db, admin, _update())
        slabs.save_pricing(self.db, admin, _update(gst_percent=5))
        count = self.db.execute(text("SELECT count(*) FROM platform_settings")).scalar_one()
        self.assertEqual(count, 1)
        self.assertEqual(slabs.load_pricing(self.db).gst_percent, Decimal("5"))

    def test_the_saved_gst_goes_on_every_bill(self) -> None:
        admin = self._admin()
        slabs.save_pricing(self.db, admin, _update(gst_percent=5))
        owner = User(
            email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
            full_name="Owner",
            hashed_password="x",
            role=UserRole.OWNER,
        )
        self.db.add(owner)
        self.db.flush()
        restaurant = Restaurant(
            owner_id=owner.id, name="Slab Test", slug=f"slab-{uuid.uuid4().hex[:8]}",
            cuisine_type="Bakery", address_line_1="1 St", city="Surat", state="Gujarat",
            postal_code="395004", is_approved=True, is_active=True,
        )
        self.db.add(restaurant)
        self.db.flush()
        location = RestaurantLocation(
            restaurant_id=restaurant.id, branch_name="Main", address_line_1="1 St",
            city="Surat", state="Gujarat", postal_code="395004",
            delivery_tax_percent=Decimal("0"), is_open=True,
        )
        self.db.add(location)
        self.db.commit()
        charges = order_charges.for_location(
            location, subtotal=Decimal("100"), delivery_fee=Decimal("60"), discount_amount=Decimal("0")
        )
        self.assertEqual(charges.delivery_tax, Decimal("3.00"))

    def test_the_admin_route_round_trips(self) -> None:
        admin = self._admin()
        from app.config.database import get_db

        def _db():
            yield self.db

        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_db] = _db
        self.addCleanup(app.dependency_overrides.clear)
        client = TestClient(app)

        before = client.get("/api/admin/delivery-pricing").json()
        self.assertEqual([row["fee"] for row in before["slabs"]], ["68.00", "78.00", "100.00"])
        self.assertFalse(before["saved"])

        saved = client.put("/api/admin/delivery-pricing", json=_update().model_dump(mode="json"))
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["max_distance_km"], 12.0)
        self.assertTrue(saved.json()["saved"])

        refused = client.put(
            "/api/admin/delivery-pricing",
            json=_update(slabs=[{"up_to_km": 2, "fee": "68"}]).model_dump(mode="json"),
        )
        self.assertEqual(refused.status_code, 422)
        # The refused list did not overwrite the saved one.
        self.assertEqual(client.get("/api/admin/delivery-pricing").json()["max_distance_km"], 12.0)


if __name__ == "__main__":
    unittest.main()
