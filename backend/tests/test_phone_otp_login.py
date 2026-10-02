"""Signing in with a phone number and a one-time code.

Two things are being guarded here, and the second matters more than the first.

**That an existing customer gets their own account back.** Phone numbers in
this database were written by several paths over the years and are not in one
shape — `(982) 000-0011`, `+19059039992` and `9192127000` are all really in
there. A sign-in that compared the stored string literally would decide a
returning customer was new, make them a second account, and show them an empty
order history. That is the worst outcome this flow has, and it is silent.

**That a fixed code cannot escape a developer's machine.** The only code this
can check today is one written in a config file, which is a password every
account on the platform shares. The flag alone is not a guard — it is one
`.env` line from being wrong — so `otp_availability` also requires a local
environment, and refuses outright rather than falling back to accepting it.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # imported first to settle import order
from app.api.deps import get_identity_app_client_id
from app.config import get_settings
from app.config.database import get_db
from app.models.app_client import AppClient
from app.models.base import Base
from app.models.enums import AppMode, UserRole
from app.models.user import User
from app.services import otp as otp_service
from app.services.auth import hash_password
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

TEST_DB_NAME = os.environ.get("OTP_TEST_DB", "restaurant_rag_otp_test")


def live_settings():
    """The settings object the code under test will actually read.

    NOT a module-level snapshot. `get_settings()` is `lru_cache`'d, and other
    modules in this suite clear that cache — so a snapshot taken at import
    time stops being the instance `services/otp.py` consults, and these tests
    passed alone and failed in a full run. Asking again each time makes them
    order-independent.
    """

    return get_settings()


def _admin_url() -> str:
    return (
        f"postgresql+psycopg://{live_settings().postgres_user}:{live_settings().postgres_password}"
        f"@{live_settings().postgres_server}:{live_settings().postgres_port}/postgres"
    )


def _test_url() -> str:
    return (
        f"postgresql+psycopg://{live_settings().postgres_user}:{live_settings().postgres_password}"
        f"@{live_settings().postgres_server}:{live_settings().postgres_port}/{TEST_DB_NAME}"
    )


def postgres_available() -> bool:
    engine = None
    try:
        engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with engine.connect():
            return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if engine is not None:
            engine.dispose()


class TheFixedCodeCannotLeaveALaptopTests(unittest.TestCase):
    """No database needed: these are the rules that decide whether to answer."""

    def setUp(self) -> None:
        self._environment = live_settings().environment
        self._enabled = live_settings().enable_phone_otp_login
        self._code = live_settings().otp_debug_code

    def tearDown(self) -> None:
        live_settings().environment = self._environment
        live_settings().enable_phone_otp_login = self._enabled
        live_settings().otp_debug_code = self._code

    def test_off_by_default_means_no_flow_at_all(self) -> None:
        live_settings().enable_phone_otp_login = False
        live_settings().environment = "development"
        self.assertEqual(otp_service.otp_availability().reason, "disabled")
        self.assertFalse(otp_service.code_is_valid("123456"))

    def test_on_and_local_accepts_the_fixed_code(self) -> None:
        live_settings().enable_phone_otp_login = True
        live_settings().environment = "development"
        live_settings().otp_debug_code = "123456"
        availability = otp_service.otp_availability()
        self.assertTrue(availability.available)
        self.assertTrue(availability.debug)
        self.assertTrue(otp_service.code_is_valid("123456"))
        self.assertTrue(otp_service.code_is_valid(" 123456 "))
        self.assertFalse(otp_service.code_is_valid("123457"))

    def test_on_in_production_refuses_rather_than_accepting_it(self) -> None:
        # The whole point. A flag is one `.env` line from being wrong, and the
        # failure here is not a degraded service — it is anybody signing in as
        # anybody.
        live_settings().enable_phone_otp_login = True
        live_settings().otp_debug_code = "123456"
        for environment in ("production", "staging", "prod"):
            with self.subTest(environment=environment):
                live_settings().environment = environment
                availability = otp_service.otp_availability()
                self.assertFalse(availability.available)
                self.assertEqual(availability.reason, "no_sender")
                self.assertFalse(otp_service.code_is_valid("123456"))

    def test_a_blank_configured_code_accepts_nothing(self) -> None:
        live_settings().enable_phone_otp_login = True
        live_settings().environment = "development"
        live_settings().otp_debug_code = ""
        self.assertFalse(otp_service.code_is_valid(""))
        self.assertFalse(otp_service.code_is_valid("   "))


class SubscriberKeyTests(unittest.TestCase):
    def test_every_shape_in_the_column_reduces_to_the_same_subscriber(self) -> None:
        for written in ("(982) 000-0011", "9820000011", "+919820000011", "982-000-0011"):
            with self.subTest(written=written):
                self.assertEqual(otp_service.subscriber_key(written), "9820000011")

    def test_nothing_in_means_nothing_out(self) -> None:
        for empty in (None, "", "   ", "no digits here"):
            with self.subTest(empty=empty):
                self.assertEqual(otp_service.subscriber_key(empty), "")


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class PhoneSignInTests(unittest.TestCase):
    engine = None
    session_factory = None

    @classmethod
    def setUpClass(cls) -> None:
        admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin_engine.dispose()

        cls.engine = create_engine(_test_url())
        with cls.engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
        Base.metadata.create_all(cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, expire_on_commit=False)

        with cls.session_factory() as session:
            client = AppClient(
                key="otp-test",
                display_name="OTP Test App",
                app_mode=AppMode.MARKETPLACE,
            )
            session.add(client)
            session.commit()
            cls.app_client_id = client.id

            # The messy stored shape, on purpose: this is what the column
            # really holds for the customer seeded long before this flow.
            session.add(
                User(
                    full_name="Returning Customer",
                    email="returning@example.com",
                    phone_number="(982) 000-0011",
                    hashed_password=hash_password("password123"),
                    role=UserRole.CUSTOMER,
                    app_client_id=client.id,
                    is_active=True,
                    is_verified=True,
                )
            )
            session.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.engine is not None:
            cls.engine.dispose()
        admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin_engine.dispose()

    def setUp(self) -> None:
        self._environment = live_settings().environment
        self._enabled = live_settings().enable_phone_otp_login
        live_settings().environment = "development"
        live_settings().enable_phone_otp_login = True
        live_settings().otp_debug_code = "123456"

        def override_db():
            with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_identity_app_client_id] = lambda: self.app_client_id
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        live_settings().environment = self._environment
        live_settings().enable_phone_otp_login = self._enabled

    def test_a_number_already_in_the_column_is_not_a_new_account(self) -> None:
        # Typed plainly; stored as "(982) 000-0011".
        reply = self.client.post("/api/auth/otp/request", json={"phone_number": "9820000011"})
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertFalse(reply.json()["is_new_account"])

    def test_signing_in_returns_the_existing_account_not_a_second_one(self) -> None:
        before = self._customer_count()
        reply = self.client.post(
            "/api/auth/otp/verify",
            json={"phone_number": "+91 98200 00011", "code": "123456"},
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(self._customer_count(), before)

    def test_a_new_number_creates_one_account_with_the_name_given(self) -> None:
        reply = self.client.post(
            "/api/auth/otp/verify",
            json={"phone_number": "9000000123", "code": "123456", "full_name": "  Asha  "},
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        with self.session_factory() as session:
            user = session.scalar(select(User).where(User.phone_number == "9000000123"))
        self.assertIsNotNone(user)
        self.assertEqual(user.full_name, "Asha")
        # Synthesised, under the domain RFC 2606 reserves so it can never
        # belong to anybody.
        self.assertTrue(user.email.endswith("@phone.example.com"))
        self.assertTrue(user.is_verified)

    def test_signing_in_twice_does_not_make_a_second_account(self) -> None:
        body = {"phone_number": "9000000456", "code": "123456", "full_name": "Ravi"}
        self.assertEqual(self.client.post("/api/auth/otp/verify", json=body).status_code, 200)
        before = self._customer_count()
        self.assertEqual(self.client.post("/api/auth/otp/verify", json=body).status_code, 200)
        self.assertEqual(self._customer_count(), before)

    def test_a_returning_customers_name_is_never_rewritten_by_the_form(self) -> None:
        self.client.post(
            "/api/auth/otp/verify",
            json={"phone_number": "9820000011", "code": "123456", "full_name": "Somebody Else"},
        )
        with self.session_factory() as session:
            user = session.scalar(select(User).where(User.email == "returning@example.com"))
        self.assertEqual(user.full_name, "Returning Customer")

    def test_a_wrong_code_is_refused(self) -> None:
        reply = self.client.post(
            "/api/auth/otp/verify",
            json={"phone_number": "9000000789", "code": "000000"},
        )
        self.assertEqual(reply.status_code, 401)
        self.assertIsNone(self._customer_by_phone("9000000789"))

    def test_the_whole_flow_is_gone_when_the_flag_is_off(self) -> None:
        live_settings().enable_phone_otp_login = False
        for path in ("/api/auth/otp/request", "/api/auth/otp/verify"):
            with self.subTest(path=path):
                reply = self.client.post(
                    path, json={"phone_number": "9820000011", "code": "123456"}
                )
                self.assertEqual(reply.status_code, 404)

    def test_in_production_it_refuses_instead_of_signing_anybody_in(self) -> None:
        live_settings().environment = "production"
        reply = self.client.post(
            "/api/auth/otp/verify",
            json={"phone_number": "9820000011", "code": "123456"},
        )
        self.assertEqual(reply.status_code, 503)

    def _customer_count(self) -> int:
        with self.session_factory() as session:
            return len(
                session.scalars(
                    select(User).where(
                        User.role == UserRole.CUSTOMER,
                        User.app_client_id == self.app_client_id,
                    )
                ).all()
            )

    def _customer_by_phone(self, phone: str) -> User | None:
        with self.session_factory() as session:
            return session.scalar(select(User).where(User.phone_number == phone))


if __name__ == "__main__":
    unittest.main()
