"""An owner may correct a customer's name, not the number they sign in with.

Found in the 2026-10-07 security review. `PATCH /admin/users/{id}/details`
let an owner rewrite a customer's phone, and the phone is a login: password
sign-in accepts it, and phone sign-in matches on it. An owner who set a
customer's number to their own could sign in as that customer once an SMS
sender exists, and would receive their marketing texts meanwhile. Decided
with the platform owner: owners cannot change it; the customer can, and so
can the platform admin.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api import admin  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.schemas.admin import AdminUserUpdate  # noqa: E402


def _customer():
    return SimpleNamespace(
        id=uuid.uuid4(), full_name="Asha", phone_number="+919800000001", default_address="Old"
    )


def _save(caller_role, update: AdminUserUpdate, customer):
    db = mock.MagicMock()
    db.scalar.return_value = customer
    with mock.patch.object(admin, "_get_manageable_user", return_value=customer), mock.patch.object(
        admin, "_serialize_admin_user", side_effect=lambda user: user
    ):
        return admin.update_user_details(customer.id, update, db, SimpleNamespace(role=caller_role))


class WhoMayChangeIt(unittest.TestCase):
    def test_an_owner_is_refused_and_nothing_is_written(self) -> None:
        customer = _customer()
        update = AdminUserUpdate(full_name="Asha K", phone_number="+919811111111", default_address="New")
        with self.assertRaises(HTTPException) as raised:
            _save(UserRole.OWNER, update, customer)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(customer.phone_number, "+919800000001")
        self.assertEqual(customer.full_name, "Asha")

    def test_an_owner_may_still_fix_the_name_and_address(self) -> None:
        customer = _customer()
        update = AdminUserUpdate(full_name="Asha K", phone_number="+919800000001", default_address="New")
        _save(UserRole.OWNER, update, customer)
        self.assertEqual(customer.full_name, "Asha K")
        self.assertEqual(customer.default_address, "New")

    def test_the_admin_may_change_it(self) -> None:
        customer = _customer()
        update = AdminUserUpdate(full_name="Asha", phone_number="+919811111111", default_address="Old")
        _save(UserRole.ADMIN, update, customer)
        self.assertEqual(customer.phone_number, "+919811111111")


if __name__ == "__main__":
    unittest.main()
