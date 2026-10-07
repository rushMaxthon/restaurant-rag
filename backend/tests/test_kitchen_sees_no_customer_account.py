"""A kitchen tablet gets what it cooks from, not the customer's account.

Found in the 2026-10-07 security review: every order sent to a KITCHEN
account carried the customer's account email and phone, the gateway's
payment reference and any refund error. Neither kitchen app reads them, and a
board is a shared tablet on a wall - its token could harvest every
customer's email and phone in its branch. The order's own contact name and
phone, which the board does show, stay.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.enums import UserRole  # noqa: E402
from app.schemas.order import OrderCustomerSummary, OrderResponse  # noqa: E402


def _order() -> OrderResponse:
    response = OrderResponse.model_construct(
        id=uuid.uuid4(),
        customer=OrderCustomerSummary(
            id=uuid.uuid4(), full_name="Asha", email="asha@example.com", phone_number="+919800000001"
        ),
        payment_reference="pay_ABC123",
        refund_error="Razorpay said no",
        contact_name="Asha",
        contact_phone="+919800000001",
        total_amount=Decimal("100"),
        created_at=datetime.now(UTC),
    )
    return response


class WhatEachViewerGets(unittest.TestCase):
    def test_the_kitchen_gets_no_account_details(self) -> None:
        seen = _order().for_viewer(SimpleNamespace(role=UserRole.KITCHEN))
        self.assertIsNone(seen.customer.email)
        self.assertIsNone(seen.customer.phone_number)
        self.assertIsNone(seen.payment_reference)
        self.assertIsNone(seen.refund_error)

    def test_the_kitchen_keeps_who_to_call_about_this_order(self) -> None:
        seen = _order().for_viewer(SimpleNamespace(role=UserRole.KITCHEN))
        self.assertEqual(seen.customer.full_name, "Asha")
        self.assertEqual(seen.contact_name, "Asha")
        self.assertEqual(seen.contact_phone, "+919800000001")

    def test_owners_admins_and_the_customer_are_unchanged(self) -> None:
        for role in (UserRole.OWNER, UserRole.ADMIN, UserRole.CUSTOMER):
            seen = _order().for_viewer(SimpleNamespace(role=role))
            self.assertEqual(seen.customer.email, "asha@example.com")
            self.assertEqual(seen.payment_reference, "pay_ABC123")


if __name__ == "__main__":
    unittest.main()
