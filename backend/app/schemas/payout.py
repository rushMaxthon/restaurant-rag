"""Payouts and linked accounts on the wire. See `api/payouts.py`."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator

_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
BUSINESS_TYPES = {"proprietorship", "partnership", "private_limited", "public_limited", "llp", "individual"}


class PayoutAccountInput(BaseModel):
    """What the admin types to open a restaurant's linked account.

    Checked here in the shape Razorpay checks it, so a typo is caught on this
    screen rather than coming back from Razorpay a day later as
    NEEDS_CLARIFICATION.
    """

    legal_business_name: str
    business_type: str = "proprietorship"
    pan: str
    contact_name: str
    email: str
    phone: str
    street: str
    city: str
    state: str
    postal_code: str
    bank_account_number: str
    ifsc: str
    beneficiary_name: str

    @field_validator("pan", "ifsc", mode="before")
    @classmethod
    def _upper(cls, value: str) -> str:
        return str(value or "").strip().upper()

    @field_validator("pan")
    @classmethod
    def _pan(cls, value: str) -> str:
        if not _PAN.match(value):
            raise ValueError("A PAN is five letters, four digits and a letter, like ABCDE1234F.")
        return value

    @field_validator("ifsc")
    @classmethod
    def _ifsc(cls, value: str) -> str:
        if not _IFSC.match(value):
            raise ValueError("An IFSC is four letters, a zero, then six letters or digits, like HDFC0001234.")
        return value

    @field_validator("postal_code")
    @classmethod
    def _postal(cls, value: str) -> str:
        value = str(value or "").strip()
        if not re.fullmatch(r"[1-9][0-9]{5}", value):
            raise ValueError("A PIN code is six digits.")
        return value

    @field_validator("bank_account_number")
    @classmethod
    def _account(cls, value: str) -> str:
        value = re.sub(r"\s", "", str(value or ""))
        if not re.fullmatch(r"[0-9]{9,18}", value):
            raise ValueError("A bank account number is 9 to 18 digits.")
        return value

    @field_validator("business_type")
    @classmethod
    def _type(cls, value: str) -> str:
        if value not in BUSINESS_TYPES:
            raise ValueError(f"Business type must be one of: {', '.join(sorted(BUSINESS_TYPES))}.")
        return value

    @field_validator("legal_business_name", "contact_name", "email", "phone", "street", "city", "state",
                     "beneficiary_name")
    @classmethod
    def _required(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("This is required.")
        return value


class PayoutAccountResponse(BaseModel):
    restaurant_id: uuid.UUID
    status: str
    razorpay_account_id: str
    legal_business_name: str
    business_type: str
    pan: str
    contact_name: str
    email: str
    phone: str
    street: str
    city: str
    state: str
    postal_code: str
    bank_account_last4: str
    ifsc: str
    beneficiary_name: str
    requirements: list[str]
    last_error: str | None
    updated_at: datetime | None


class PayoutRow(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    order_placed_at: datetime | None
    restaurant_id: uuid.UUID
    restaurant_name: str
    restaurant_share: Decimal
    #: None for an owner: with the share and the total, it would give away
    #: the commission.
    platform_keeps: Decimal | None
    currency: str
    status: str
    transfer_id: str
    last_error: str | None
    released_at: datetime | None
    settled_at: datetime | None


class PayoutBucket(BaseModel):
    count: int
    amount: Decimal


class PayoutSummary(BaseModel):
    held: PayoutBucket
    released: PayoutBucket
    settled: PayoutBucket
    waiting: PayoutBucket
    problems: PayoutBucket
    not_applicable: PayoutBucket


class PayoutListResponse(BaseModel):
    currency: str
    payouts_enabled: bool
    summary: PayoutSummary
    rows: list[PayoutRow]
