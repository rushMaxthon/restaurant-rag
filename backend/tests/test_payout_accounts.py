"""Opening a restaurant's linked account: validation, encryption, and the
four Razorpay calls, each made once."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_payout_ledger import LedgerDatabase, postgres_available  # noqa: E402

from app.models.enums import PayoutAccountStatus  # noqa: E402
from app.schemas.payout import PayoutAccountInput  # noqa: E402
from app.services.payouts import accounts  # noqa: E402
from app.services.payouts.route_client import ProductState  # noqa: E402

GOOD = dict(legal_business_name="Darshan Foods", business_type="proprietorship", pan="ABCDE1234F",
            contact_name="Darshan Patel", email="d@x.in", phone="9876543210", street="1 Ring Road",
            city="Surat", state="Gujarat", postal_code="395007", bank_account_number="123456789012",
            ifsc="HDFC0000123", beneficiary_name="Darshan Foods")


class InputTests(unittest.TestCase):
    def test_a_bad_pan_ifsc_pin_or_account_number_is_refused(self) -> None:
        for field, value in (("pan", "ABC123"), ("ifsc", "HDFC123"), ("postal_code", "39"),
                             ("bank_account_number", "12ab")):
            with self.assertRaises(ValueError, msg=field):
                PayoutAccountInput(**dict(GOOD, **{field: value}))

    def test_a_lowercase_pan_is_the_same_pan(self) -> None:
        self.assertEqual(PayoutAccountInput(**dict(GOOD, pan="abcde1234f")).pan, "ABCDE1234F")


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class AccountTests(LedgerDatabase):
    def test_a_draft_keeps_only_the_last_four_in_the_clear(self) -> None:
        row = accounts.save_draft(self.db, self.restaurant.id, PayoutAccountInput(**GOOD), self.owner.id)
        self.assertEqual(row.bank_account_last4, "9012")
        self.assertNotIn("123456789012", row.bank_account_number_encrypted)
        self.assertNotIn("bank_account_number", accounts.describe(row))

    def test_an_active_account_cannot_be_edited(self) -> None:
        account = self.make_active_account()
        with self.assertRaises(ValueError):
            accounts.save_draft(self.db, account.restaurant_id, PayoutAccountInput(**GOOD), self.owner.id)

    def test_submitting_makes_each_call_once(self) -> None:
        accounts.save_draft(self.db, self.restaurant.id, PayoutAccountInput(**GOOD), self.owner.id)
        client = mock.Mock()
        client.create_account.return_value = "acc_1"
        client.create_stakeholder.return_value = "sth_1"
        client.request_route.return_value = ProductState("acc_prd_1", "requested", [])
        client.submit_bank.return_value = ProductState("acc_prd_1", "needs_clarification", ["ifsc: field_missing"])
        row = accounts.submit(self.db, self.restaurant.id, client)
        self.assertEqual((row.razorpay_account_id, row.product_id, row.status),
                         ("acc_1", "acc_prd_1", PayoutAccountStatus.NEEDS_CLARIFICATION.value))
        client.submit_bank.assert_called_once_with("acc_1", "acc_prd_1", account_number="123456789012",
                                                   ifsc="HDFC0000123", beneficiary_name="Darshan Foods")
        # Submitting again after a correction does not open a second account.
        accounts.submit(self.db, self.restaurant.id, client)
        client.create_account.assert_called_once()
        client.request_route.assert_called_once()

    def test_a_refusal_is_kept_on_the_row(self) -> None:
        from app.services.payments.base import PaymentProviderError
        accounts.save_draft(self.db, self.restaurant.id, PayoutAccountInput(**GOOD), self.owner.id)
        client = mock.Mock()
        client.create_account.side_effect = PaymentProviderError("Razorpay refused this request: invalid PAN",
                                                                 retryable=False)
        with self.assertRaises(PaymentProviderError):
            accounts.submit(self.db, self.restaurant.id, client)
        self.db.expire_all()
        self.assertIn("invalid PAN", accounts.get_account(self.db, self.restaurant.id).last_error)

    def test_refresh_that_finds_it_active_flushes_the_waiting(self) -> None:
        account = self.make_active_account()
        account.status = PayoutAccountStatus.UNDER_REVIEW.value
        self.db.commit()
        client = mock.Mock()
        client.fetch_product.return_value = ProductState("acc_prd_1", "activated", [])
        accounts.refresh_status(self.db, self.restaurant.id, client)
        self.assertIn("app.tasks.payouts.flush_waiting_task", [c.args[0] for c in self.sent.call_args_list])


if __name__ == "__main__":
    unittest.main()
