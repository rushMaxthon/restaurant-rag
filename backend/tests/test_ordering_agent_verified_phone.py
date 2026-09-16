"""Provisioning an account from a number a channel has verified."""

from __future__ import annotations

import unittest
import uuid

from app.main import app  # noqa: F401 - imported first to settle import order
from app.models.enums import UserRole
from app.models.user import User
from app.services.ordering_agent.verified_phone import (
    PhoneNotVerified,
    customer_for_verified_phone,
)


class FakeDb:
    """Holds users in a list and answers the one query this service makes."""

    def __init__(self, users=None) -> None:
        self.users = list(users or [])
        self.added: list[User] = []

    def scalar(self, statement):
        # Matches on the statement's own bound values rather than on the SQL
        # text, so a service that filtered on the wrong column would find
        # nobody here — which is the point of checking at all.
        wanted = set(statement.compile().params.values())
        for user in self.users:
            if {user.phone_number, user.role, user.app_client_id} <= wanted:
                return user
        return None

    def add(self, obj):
        self.added.append(obj)
        self.users.append(obj)

    def flush(self):
        for user in self.added:
            if user.id is None:
                user.id = uuid.uuid4()


def make_customer(phone: str, app_client_id=None) -> User:
    return User(
        id=uuid.uuid4(), full_name="Returning Customer", email="old@example.com",
        phone_number=phone, hashed_password="x", role=UserRole.CUSTOMER,
        app_client_id=app_client_id, is_active=True,
    )


class VerifiedPhoneTests(unittest.TestCase):
    APP = uuid.UUID("11111111-1111-1111-1111-111111111111")

    def test_an_unverified_number_is_refused(self) -> None:
        # The whole premise. A number typed into a web chat proves nothing.
        with self.assertRaises(PhoneNotVerified):
            customer_for_verified_phone(
                FakeDb(), phone_number="+919876543210", app_client_id=self.APP,
                verified=False, full_name="Hitesh", email="h@example.com",
            )

    def test_nonsense_is_refused_even_when_called_verified(self) -> None:
        with self.assertRaises(PhoneNotVerified):
            customer_for_verified_phone(
                FakeDb(), phone_number="hello", app_client_id=self.APP,
                verified=True, full_name="Hitesh", email="h@example.com",
            )

    def test_a_returning_customer_is_recognised_not_duplicated(self) -> None:
        # Otherwise every order from the same number would be a new person
        # with no history and no saved address.
        existing = make_customer("+919876543210", self.APP)
        db = FakeDb([existing])
        user = customer_for_verified_phone(
            db, phone_number="+91 98765 43210", app_client_id=self.APP,
            verified=True, full_name="Someone Else", email="new@example.com",
        )
        self.assertIs(user, existing)
        self.assertEqual(db.added, [])
        self.assertEqual(user.email, "old@example.com", "the account is not rewritten")

    def test_a_new_number_becomes_a_customer(self) -> None:
        db = FakeDb()
        user = customer_for_verified_phone(
            db, phone_number="+919876543210", app_client_id=self.APP,
            verified=True, full_name="Hitesh", email="H@Example.COM",
        )
        self.assertEqual(len(db.added), 1)
        self.assertEqual(user.role, UserRole.CUSTOMER)
        self.assertEqual(user.app_client_id, self.APP)
        self.assertEqual(user.email, "h@example.com", "stored lowercase, as everywhere else")
        self.assertTrue(user.is_verified, "the number is the verification")
        self.assertTrue(user.hashed_password, "the column is not null; the value is unguessable")

    def test_the_same_number_on_a_different_app_is_a_different_person(self) -> None:
        # The house rule: identity is scoped by app client, and this must not
        # be the one place that forgets it.
        existing = make_customer("+919876543210", self.APP)
        db = FakeDb([existing])
        user = customer_for_verified_phone(
            db, phone_number="+919876543210", app_client_id=uuid.uuid4(),
            verified=True, full_name="Hitesh", email="h@example.com",
        )
        self.assertIsNot(user, existing)
        self.assertEqual(len(db.added), 1)


if __name__ == "__main__":
    unittest.main()
