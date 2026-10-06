"""Razorpay Route and linked-account calls, on the platform's own account.

Built on `RazorpayProvider._request` so the error handling is the one already
proven on checkout: a 4xx is our request being wrong and is not retried, a
5xx or a network failure is. Amounts go through `_to_minor_units`, the one
place rupees become paise.

Linked accounts use Razorpay's v2 Accounts API (`/v2/accounts`, then a
stakeholder, then the `route` product, then the settlement bank account on
the product). Transfers use v1. The v2 bodies follow Razorpay's published
Route onboarding docs; the first test-mode run is where a field name is
confirmed (see `backend/docs/payouts.md`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.models.enums import PayoutAccountStatus
from app.services.payments.razorpay_provider import V2_API_BASE, RazorpayProvider, _to_minor_units

#: Razorpay's `activation_status` on the route product, in this app's words.
ACCOUNT_STATUS_FOR_ACTIVATION: dict[str, PayoutAccountStatus] = {
    "requested": PayoutAccountStatus.SUBMITTED,
    "under_review": PayoutAccountStatus.UNDER_REVIEW,
    "needs_clarification": PayoutAccountStatus.NEEDS_CLARIFICATION,
    "activated": PayoutAccountStatus.ACTIVE,
    "suspended": PayoutAccountStatus.SUSPENDED,
}


@dataclass(frozen=True)
class TransferState:
    transfer_id: str
    status: str
    on_hold: bool
    settlement_status: str
    settlement_id: str
    error: str = ""


@dataclass(frozen=True)
class ProductState:
    product_id: str
    activation_status: str
    requirements: list[str] = field(default_factory=list)


def _transfer(body: dict[str, Any]) -> TransferState:
    error = body.get("error") or {}
    return TransferState(
        transfer_id=str(body.get("id") or ""),
        status=str(body.get("status") or ""),
        on_hold=bool(body.get("on_hold")),
        settlement_status=str(body.get("settlement_status") or ""),
        settlement_id=str(body.get("recipient_settlement_id") or ""),
        error=str(error.get("description") or "") if isinstance(error, dict) else "",
    )


def _product(body: dict[str, Any]) -> ProductState:
    needs = []
    for item in body.get("requirements") or []:
        if isinstance(item, dict):
            needs.append(f"{item.get('field_reference', '')}: {item.get('reason_code', '')}".strip(": "))
    return ProductState(
        product_id=str(body.get("id") or ""),
        activation_status=str(body.get("activation_status") or ""),
        requirements=needs,
    )


class RouteClient:
    def __init__(self, provider: RazorpayProvider) -> None:
        self._provider = provider

    # --- transfers -------------------------------------------------------

    def create_transfer(self, *, payment_id: str, account_id: str, amount: Decimal, currency: str,
                        order_id: uuid.UUID, on_hold: bool) -> TransferState:
        body = self._provider._request("POST", f"/payments/{payment_id}/transfers", json={"transfers": [{
            "account": account_id,
            "amount": _to_minor_units(amount),
            "currency": (currency or "INR").upper(),
            "on_hold": 1 if on_hold else 0,
            "notes": {"order_id": str(order_id)},
        }]})
        items = body.get("items") or []
        return _transfer(items[0] if items else body)

    def find_transfer(self, *, payment_id: str, order_id: uuid.UUID) -> TransferState | None:
        """A transfer already made from this payment for this order, if any.

        Asked before every transfer, because a create that timed out may
        still have been accepted: re-sending it would pay the restaurant
        twice (or, past half the payment, be refused while the first one
        stands). Matched on the `order_id` note `create_transfer` writes.
        """

        body = self._provider._request("GET", f"/payments/{payment_id}/transfers")
        for item in body.get("items") or []:
            if str((item.get("notes") or {}).get("order_id") or "") == str(order_id):
                return _transfer(item)
        return None

    def release(self, transfer_id: str) -> TransferState:
        return _transfer(self._provider._request("PATCH", f"/transfers/{transfer_id}", json={"on_hold": 0}))

    def reverse(self, transfer_id: str) -> None:
        # No amount: the whole transfer comes back to the platform's balance.
        self._provider._request("POST", f"/transfers/{transfer_id}/reversals", json={})

    def fetch_transfer(self, transfer_id: str) -> TransferState:
        return _transfer(self._provider._request("GET", f"/transfers/{transfer_id}"))

    # --- linked accounts ------------------------------------------------

    def create_account(self, account: Any) -> str:
        body = self._provider._request("POST", "/accounts", base=V2_API_BASE, json={
            "email": account.email,
            "phone": account.phone,
            "type": "route",
            # Razorpay caps reference_id at 20 characters.
            "reference_id": str(account.restaurant_id)[:20],
            "legal_business_name": account.legal_business_name,
            "business_type": account.business_type,
            "contact_name": account.contact_name,
            "profile": {
                "category": "food",
                "subcategory": "restaurant",
                "addresses": {"registered": {
                    "street1": account.street, "street2": account.street, "city": account.city,
                    "state": account.state, "postal_code": account.postal_code, "country": "IN",
                }},
            },
            "legal_info": {"pan": account.pan},
        })
        return str(body.get("id") or "")

    def create_stakeholder(self, account_id: str, account: Any) -> str:
        body = self._provider._request("POST", f"/accounts/{account_id}/stakeholders", base=V2_API_BASE,
                                       json={"name": account.contact_name, "email": account.email})
        return str(body.get("id") or "")

    def request_route(self, account_id: str) -> ProductState:
        return _product(self._provider._request("POST", f"/accounts/{account_id}/products", base=V2_API_BASE,
                                                json={"product_name": "route", "tnc_accepted": True}))

    def submit_bank(self, account_id: str, product_id: str, *, account_number: str, ifsc: str,
                    beneficiary_name: str) -> ProductState:
        return _product(self._provider._request(
            "PATCH", f"/accounts/{account_id}/products/{product_id}", base=V2_API_BASE,
            json={"settlements": {"account_number": account_number, "ifsc_code": ifsc,
                                  "beneficiary_name": beneficiary_name},
                  "tnc_accepted": True},
        ))

    def fetch_product(self, account_id: str, product_id: str) -> ProductState:
        return _product(self._provider._request("GET", f"/accounts/{account_id}/products/{product_id}",
                                                base=V2_API_BASE))
