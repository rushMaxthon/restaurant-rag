"""The Users list is paged and filtered on the server.

`GET /admin/users` returned every account in one response - for an owner,
every customer of their app; for the admin, everyone - and the page filtered
and paged in the browser (2026-10-07 security review: one stolen token, one
request, the whole user table). It now takes `search`, `role`, `status`,
`limit` (default 50, at most 200) and `offset`, and says the full count in
`X-Total-Count`, the same contract as `GET /orders`. The tiles that count
accounts per role come from `GET /admin/users/stats`, so they still describe
everybody, not one page.

Scope is unchanged: an owner sees only their own app's customers, whatever
they filter on.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.config.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.app_client import AppClient  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import AppMode, UserRole  # noqa: E402
from app.models.restaurant import Restaurant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import get_current_user  # noqa: E402

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_admin_users_paging_test"


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


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class PagedUsers(unittest.TestCase):
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

        db = cls.session_factory()
        cls.admin = User(email="admin@t.local", full_name="Platform Admin", hashed_password="x", role=UserRole.ADMIN)
        cls.owner = User(email="owner@t.local", full_name="Owner One", hashed_password="x", role=UserRole.OWNER)
        db.add_all([cls.admin, cls.owner])
        db.flush()
        restaurant = Restaurant(
            owner_id=cls.owner.id, name="R", slug="r-paging", cuisine_type="Bakery", address_line_1="1 St",
            city="Surat", state="Gujarat", postal_code="395004", is_approved=True, is_active=True,
        )
        db.add(restaurant)
        db.flush()
        cls.app_client = AppClient(
            key="r-paging", display_name="R app", app_mode=AppMode.SINGLE_RESTAURANT, restaurant_id=restaurant.id
        )
        other_app = AppClient(key="other-app", display_name="Other", app_mode=AppMode.MARKETPLACE)
        db.add_all([cls.app_client, other_app])
        db.flush()
        # 7 customers of the owner's app (2 inactive, one called Asha), 3 elsewhere.
        for index in range(7):
            db.add(User(
                email=f"c{index}@t.local", full_name="Asha Patel" if index == 0 else f"Customer {index}",
                hashed_password="x", role=UserRole.CUSTOMER, app_client_id=cls.app_client.id,
                phone_number=f"+91980000{index:04d}", is_active=index not in (5, 6),
            ))
        for index in range(3):
            db.add(User(
                email=f"other{index}@t.local", full_name=f"Elsewhere {index}", hashed_password="x",
                role=UserRole.CUSTOMER, app_client_id=other_app.id,
            ))
        db.commit()
        db.close()

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        if cls.engine is not None:
            cls.engine.dispose()
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin.dispose()

    def _as(self, user: User) -> TestClient:
        def _db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: user
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def test_a_page_and_the_total(self) -> None:
        response = self._as(self.admin).get("/api/admin/users?limit=4&offset=0")
        self.assertEqual(len(response.json()), 4)
        self.assertEqual(response.headers["X-Total-Count"], "12")

    def test_no_limit_means_fifty_not_everyone(self) -> None:
        from app.api import admin as admin_api

        self.assertEqual(admin_api.USERS_DEFAULT_LIMIT, 50)
        self.assertEqual(self._as(self.admin).get("/api/admin/users?limit=500").status_code, 422)

    def test_search_by_name_email_or_phone(self) -> None:
        client = self._as(self.admin)
        self.assertEqual([u["full_name"] for u in client.get("/api/admin/users?search=asha").json()], ["Asha Patel"])
        self.assertEqual(len(client.get("/api/admin/users?search=c3%40t.local").json()), 1)
        self.assertEqual(len(client.get("/api/admin/users?search=9800000002").json()), 1)

    def test_a_percent_sign_is_not_a_wildcard(self) -> None:
        self.assertEqual(self._as(self.admin).get("/api/admin/users?search=%25").json(), [])

    def test_role_and_status_filters(self) -> None:
        client = self._as(self.admin)
        owners = client.get("/api/admin/users?role=OWNER")
        self.assertEqual(owners.headers["X-Total-Count"], "1")
        inactive = client.get("/api/admin/users?status=INACTIVE")
        self.assertEqual(inactive.headers["X-Total-Count"], "2")

    def test_an_owner_sees_only_their_apps_customers(self) -> None:
        response = self._as(self.owner).get("/api/admin/users?limit=200")
        self.assertEqual(response.headers["X-Total-Count"], "7")
        self.assertTrue(all(u["role"] == "CUSTOMER" for u in response.json()))
        self.assertEqual(self._as(self.owner).get("/api/admin/users?search=elsewhere").json(), [])

    def test_the_tiles_count_everyone_not_one_page(self) -> None:
        stats = self._as(self.admin).get("/api/admin/users/stats").json()
        self.assertEqual(stats["all"], {"total": 12, "active": 10})
        self.assertEqual(stats["CUSTOMER"], {"total": 10, "active": 8})
        self.assertEqual(stats["ADMIN"], {"total": 1, "active": 1})

    def test_an_owners_tiles_are_their_customers(self) -> None:
        stats = self._as(self.owner).get("/api/admin/users/stats").json()
        self.assertEqual(stats["all"], {"total": 7, "active": 5})

    def test_a_cook_or_customer_cannot_list_users(self) -> None:
        cook = User(id=uuid.uuid4(), email="k@t.local", full_name="K", hashed_password="x", role=UserRole.KITCHEN)
        self.assertEqual(self._as(cook).get("/api/admin/users").status_code, 403)
        self.assertEqual(self._as(cook).get("/api/admin/users/stats").status_code, 403)


if __name__ == "__main__":
    unittest.main()
