"""A restaurant's Razorpay linked account: whether it can be paid, and how it
is opened. Only the platform admin opens or edits one (`api/payouts.py`)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.enums import PayoutAccountStatus
from app.models.restaurant_payout import RestaurantPayoutAccount
from app.services.payments.base import PaymentProviderError
from app.services.payouts.route_client import ACCOUNT_STATUS_FOR_ACTIVATION
from app.services.secrets import decrypt_secret, encrypt_secret


def get_account(db: Session, restaurant_id: uuid.UUID) -> RestaurantPayoutAccount | None:
    return db.get(RestaurantPayoutAccount, restaurant_id)


def payout_account_active(db: Session, restaurant_id: uuid.UUID | None) -> bool:
    if restaurant_id is None:
        return False
    account = get_account(db, restaurant_id)
    return bool(account and account.razorpay_account_id and account.status == PayoutAccountStatus.ACTIVE.value)


#: Statuses in which the admin may still change what Razorpay will be sent.
_EDITABLE = {PayoutAccountStatus.DRAFT.value, PayoutAccountStatus.NEEDS_CLARIFICATION.value}


def save_draft(db, restaurant_id, data, actor_id) -> RestaurantPayoutAccount:
    account = get_account(db, restaurant_id)
    if account is None:
        account = RestaurantPayoutAccount(restaurant_id=restaurant_id)
        db.add(account)
    elif account.status not in _EDITABLE:
        raise ValueError(
            "This account is with Razorpay already; it can be changed only if Razorpay asks for a correction."
        )
    for name in ("legal_business_name", "business_type", "pan", "contact_name", "email", "phone",
                 "street", "city", "state", "postal_code", "ifsc", "beneficiary_name"):
        setattr(account, name, getattr(data, name))
    account.bank_account_number_encrypted = encrypt_secret(data.bank_account_number)
    account.bank_account_last4 = data.bank_account_number[-4:]
    account.updated_by_user_id = actor_id
    db.commit()
    return account


def _apply_product(account, product) -> bool:
    """Write Razorpay's word onto the row; True when it just became ACTIVE."""

    status = ACCOUNT_STATUS_FOR_ACTIVATION.get(product.activation_status)
    if product.product_id:
        account.product_id = product.product_id
    account.requirements = list(product.requirements)
    if status is None:
        return False
    became_active = status == PayoutAccountStatus.ACTIVE and account.status != status.value
    account.status = status.value
    return became_active


def _flush_after_commit(db, restaurant_id) -> None:
    from app.services.payouts.webhooks import after_commit_task

    after_commit_task(db, "app.tasks.payouts.flush_waiting_task", restaurant_id=str(restaurant_id))


def submit(db, restaurant_id, client) -> RestaurantPayoutAccount:
    """Open (or correct) the linked account with Razorpay. Each step once.

    Every id is written to the row as soon as Razorpay returns it, so a
    failure halfway resumes from where it stopped rather than opening a
    second account for the same restaurant.
    """

    account = get_account(db, restaurant_id)
    if account is None or not account.bank_account_number_encrypted:
        raise ValueError("Save the restaurant's details and bank account first.")
    try:
        if not account.razorpay_account_id:
            account.razorpay_account_id = client.create_account(account)
            db.commit()
        if not account.stakeholder_id:
            account.stakeholder_id = client.create_stakeholder(account.razorpay_account_id, account)
            db.commit()
        if not account.product_id:
            _apply_product(account, client.request_route(account.razorpay_account_id))
            db.commit()
        product = client.submit_bank(
            account.razorpay_account_id, account.product_id,
            account_number=decrypt_secret(account.bank_account_number_encrypted),
            ifsc=account.ifsc, beneficiary_name=account.beneficiary_name,
        )
    except PaymentProviderError as error:
        account.last_error = str(error)
        db.commit()
        raise
    account.last_error = None
    if _apply_product(account, product):
        _flush_after_commit(db, restaurant_id)
    db.commit()
    return account


def refresh_status(db, restaurant_id, client) -> RestaurantPayoutAccount:
    account = get_account(db, restaurant_id)
    if account is None or not account.razorpay_account_id or not account.product_id:
        raise ValueError("This restaurant's account has not been sent to Razorpay yet.")
    if _apply_product(account, client.fetch_product(account.razorpay_account_id, account.product_id)):
        _flush_after_commit(db, restaurant_id)
    db.commit()
    return account


def describe(account) -> dict:
    """What a screen may know. Never the bank account number."""

    return {
        "restaurant_id": account.restaurant_id, "status": account.status,
        "razorpay_account_id": account.razorpay_account_id,
        "legal_business_name": account.legal_business_name, "business_type": account.business_type,
        "pan": account.pan, "contact_name": account.contact_name, "email": account.email,
        "phone": account.phone, "street": account.street, "city": account.city, "state": account.state,
        "postal_code": account.postal_code, "bank_account_last4": account.bank_account_last4,
        "ifsc": account.ifsc, "beneficiary_name": account.beneficiary_name,
        "requirements": list(account.requirements or []), "last_error": account.last_error,
        "updated_at": account.updated_at,
    }
