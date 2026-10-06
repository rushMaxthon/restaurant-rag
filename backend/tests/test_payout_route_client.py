"""The calls that move a restaurant's share, and that open its linked account.

Every request body is asserted exactly, because these are the calls that move
money: an amount in rupees where paise were meant is a hundredfold error, and
`on_hold` missing means the restaurant is paid for food nobody has delivered.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.enums import PayoutAccountStatus  # noqa: E402
from app.services.payments.razorpay_provider import V2_API_BASE, RazorpayProvider  # noqa: E402
from app.services.payouts.route_client import ACCOUNT_STATUS_FOR_ACTIVATION, RouteClient  # noqa: E402

TRANSFER = {"id": "trf_1", "status": "pending", "on_hold": True, "settlement_status": "on_hold",
            "recipient_settlement_id": None}


class RouteClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = RazorpayProvider(key_id="rzp_test_x", key_secret="s", is_platform=True)
        self.client = RouteClient(self.provider)

    def _run(self, reply, call):
        with mock.patch.object(self.provider, "_request", return_value=reply) as request:
            result = call()
        return result, request.call_args

    def test_a_transfer_is_made_from_the_payment_in_paise_and_on_hold(self) -> None:
        order_id = uuid.uuid4()
        state, call = self._run({"items": [TRANSFER]}, lambda: self.client.create_transfer(
            payment_id="pay_9", account_id="acc_1", amount=Decimal("496.55"), currency="INR",
            order_id=order_id, on_hold=True))
        self.assertEqual(call.args, ("POST", "/payments/pay_9/transfers"))
        self.assertEqual(call.kwargs["json"], {"transfers": [{
            "account": "acc_1", "amount": 49655, "currency": "INR", "on_hold": 1,
            "notes": {"order_id": str(order_id)},
        }]})
        self.assertEqual((state.transfer_id, state.on_hold), ("trf_1", True))

    def test_a_delivered_order_is_transferred_without_a_hold(self) -> None:
        _, call = self._run({"items": [dict(TRANSFER, on_hold=False)]}, lambda: self.client.create_transfer(
            payment_id="pay_9", account_id="acc_1", amount=Decimal("1"), currency="INR",
            order_id=uuid.uuid4(), on_hold=False))
        self.assertEqual(call.kwargs["json"]["transfers"][0]["on_hold"], 0)

    def test_release_lifts_the_hold(self) -> None:
        state, call = self._run(dict(TRANSFER, on_hold=False), lambda: self.client.release("trf_1"))
        self.assertEqual(call.args, ("PATCH", "/transfers/trf_1"))
        self.assertEqual(call.kwargs["json"], {"on_hold": 0})
        self.assertFalse(state.on_hold)

    def test_reverse_takes_the_whole_transfer_back(self) -> None:
        _, call = self._run({"id": "rvrsl_1"}, lambda: self.client.reverse("trf_1"))
        self.assertEqual(call.args, ("POST", "/transfers/trf_1/reversals"))

    def test_a_settled_transfer_carries_its_settlement(self) -> None:
        state, _ = self._run(dict(TRANSFER, status="processed", on_hold=False, settlement_status="settled",
                                  recipient_settlement_id="setl_7"), lambda: self.client.fetch_transfer("trf_1"))
        self.assertEqual((state.settlement_status, state.settlement_id), ("settled", "setl_7"))

    def test_opening_a_linked_account_uses_v2(self) -> None:
        account = SimpleNamespace(
            restaurant_id=uuid.uuid4(), email="a@b.in", phone="9876543210", legal_business_name="Darshan Foods",
            business_type="proprietorship", contact_name="Darshan", pan="ABCDE1234F", street="1 Road",
            city="Surat", state="Gujarat", postal_code="395007")
        account_id, call = self._run({"id": "acc_1"}, lambda: self.client.create_account(account))
        self.assertEqual(call.args, ("POST", "/accounts"))
        self.assertEqual(call.kwargs["base"], V2_API_BASE)
        body = call.kwargs["json"]
        self.assertEqual(body["type"], "route")
        self.assertEqual(body["reference_id"], str(account.restaurant_id)[:20])
        self.assertEqual(body["legal_info"], {"pan": "ABCDE1234F"})
        self.assertEqual(body["profile"]["addresses"]["registered"]["postal_code"], "395007")
        self.assertEqual(account_id, "acc_1")

    def test_the_bank_account_goes_on_the_route_product(self) -> None:
        state, call = self._run({"id": "acc_prd_1", "activation_status": "under_review", "requirements": []},
                                lambda: self.client.submit_bank("acc_1", "acc_prd_1", account_number="123456789",
                                                                ifsc="HDFC0000001", beneficiary_name="Darshan Foods"))
        self.assertEqual(call.args, ("PATCH", "/accounts/acc_1/products/acc_prd_1"))
        self.assertEqual(call.kwargs["json"], {"settlements": {"account_number": "123456789",
                                                               "ifsc_code": "HDFC0000001",
                                                               "beneficiary_name": "Darshan Foods"},
                                               "tnc_accepted": True})
        self.assertEqual(state.activation_status, "under_review")

    def test_requirements_are_kept_as_razorpay_said_them(self) -> None:
        state, _ = self._run({"id": "acc_prd_1", "activation_status": "needs_clarification",
                              "requirements": [{"field_reference": "settlements.ifsc_code",
                                                "reason_code": "field_missing"}]},
                             lambda: self.client.fetch_product("acc_1", "acc_prd_1"))
        self.assertEqual(state.requirements, ["settlements.ifsc_code: field_missing"])

    def test_every_activation_status_has_a_meaning_here(self) -> None:
        self.assertEqual(ACCOUNT_STATUS_FOR_ACTIVATION["activated"], PayoutAccountStatus.ACTIVE)
        self.assertEqual(ACCOUNT_STATUS_FOR_ACTIVATION["needs_clarification"],
                         PayoutAccountStatus.NEEDS_CLARIFICATION)


    def test_an_earlier_transfer_for_this_order_is_found_by_its_note(self) -> None:
        order_id = uuid.uuid4()
        other = dict(TRANSFER, id="trf_other", notes={"order_id": str(uuid.uuid4())})
        mine = dict(TRANSFER, id="trf_mine", notes={"order_id": str(order_id)})
        state, call = self._run({"items": [other, mine]},
                                lambda: self.client.find_transfer(payment_id="pay_9", order_id=order_id))
        self.assertEqual(call.args, ("GET", "/payments/pay_9/transfers"))
        self.assertEqual(state.transfer_id, "trf_mine")
        none, _ = self._run({"items": [other]},
                            lambda: self.client.find_transfer(payment_id="pay_9", order_id=order_id))
        self.assertIsNone(none)


if __name__ == "__main__":
    unittest.main()
