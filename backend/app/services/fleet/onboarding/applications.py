"""A rider's application: what they fill in, what an admin decides, and who may edit what when.

States (`rider_applications.status`):

    DRAFT --submit--> SUBMITTED --approve--> APPROVED
                         |  ^
            send back    v  | resubmit
                      CHANGES_NEEDED
    SUBMITTED / CHANGES_NEEDED --reject--> REJECTED (final; an admin may reopen)

Each reviewable thing is its own item with its own status and reason, so an
admin sends back only the blurry licence and the rider fixes only that:

- DRAFT: everything is editable.
- SUBMITTED: nothing is (the admin is looking at it).
- CHANGES_NEEDED: only items marked NEEDS_CHANGE; an accepted item stays
  accepted and locked, so a resubmission cannot quietly swap a checked
  document for an unchecked one.

Every transition locks the application row, writes an event, commits once,
and only then tells anybody: a push for a decision that rolled back would
send a rider off to wait for an approval that never happened.

The rules here are the rules; the app and the admin screen only reflect them.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import (
    ApplicationAction,
    ApplicationItemKind,
    ApplicationStatus,
    ItemStatus,
    RiderOnboarding,
    VehicleType,
)
from app.models.rider import Rider
from app.models.rider_application import RiderApplication, RiderApplicationEvent, RiderApplicationItem
from app.models.user import User
from app.services.fleet.onboarding import rules, storage
from app.services.fleet.onboarding.rules import PHOTO_KINDS, SECTION_OF
from app.services.secrets import SecretsUnavailable, decrypt_secret, encrypt_secret, secrets_available

logger = logging.getLogger(__name__)

K = ApplicationItemKind
Section = Literal["personal", "vehicle", "documents", "bank"]
SECTIONS: tuple[Section, ...] = ("personal", "vehicle", "documents", "bank")

__all__ = [
    "PHOTO_KINDS",
    "SECTION_OF",
    "SECTIONS",
    "approve",
    "editable",
    "missing_items",
    "reject",
    "reopen",
    "required_for",
    "review_item",
    "save_photo",
    "save_section",
    "send_back",
    "start",
    "submit",
]

#: The typed-in field a document item also needs, beside its photo: a PAN
#: photo with no PAN number is not a complete PAN.
_DATA_OF: dict[K, tuple[str, ...]] = {
    K.VEHICLE_DETAILS: ("vehicle_type",),
    K.AADHAAR_FRONT: ("aadhaar_last4",),
    K.PAN: ("pan_last4",),
    K.LICENCE_FRONT: ("licence_last4", "licence_expiry"),
}

#: The documents step carries fields for three items; each field may change
#: only while its own item may.
_DOCUMENT_FIELD_ITEM: dict[str, K] = {
    "aadhaar_last4": K.AADHAAR_FRONT,
    "pan": K.PAN,
    "licence_number": K.LICENCE_FRONT,
    "licence_expiry": K.LICENCE_FRONT,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _invalid(field: str, error: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"field": field, "error": error})


# --- reading -----------------------------------------------------------------


def items_of(db: Session, rider_user_id: uuid.UUID) -> dict[K, RiderApplicationItem]:
    rows = db.scalars(select(RiderApplicationItem).where(RiderApplicationItem.rider_user_id == rider_user_id))
    return {row.kind: row for row in rows}


def required_for(app: RiderApplication) -> list[K]:
    items = rules.required_items(app.vehicle_type)
    # A bank account is checked against a cheque or passbook; a UPI ID alone
    # has nothing to photograph.
    if app.bank_account_last4:
        items.append(K.BANK_PROOF)
    return items


def _has_data(app: RiderApplication, kind: K) -> bool:
    return all(bool(getattr(app, field)) for field in _DATA_OF.get(kind, ()))


def missing_items(app: RiderApplication, items: dict[K, RiderApplicationItem]) -> list[K]:
    missing = []
    for kind in required_for(app):
        item = items.get(kind)
        if item is None or item.status == ItemStatus.MISSING or not _has_data(app, kind):
            missing.append(kind)
    return missing


def editable(app: RiderApplication, item: RiderApplicationItem | None) -> bool:
    """While sent back: what was flagged, and anything required that is still
    missing - a fix can make a new item required (a bank account given where
    there was only UPI needs its cheque), and a rider who could not give it
    would be stuck with no way to resubmit."""

    if app.status == ApplicationStatus.DRAFT:
        return True
    if app.status == ApplicationStatus.CHANGES_NEEDED:
        return item is not None and item.status in (ItemStatus.NEEDS_CHANGE, ItemStatus.MISSING)
    return False


# --- writing helpers -----------------------------------------------------------


def _lock(db: Session, rider_user_id: uuid.UUID) -> RiderApplication:
    app = db.get(RiderApplication, rider_user_id, with_for_update=True, populate_existing=True)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return app


def _event(
    db: Session, app: RiderApplication, action: ApplicationAction, actor: User | None,
    kind: K | None = None, note: str = "",
) -> None:
    db.add(
        RiderApplicationEvent(
            rider_user_id=app.rider_user_id,
            actor_user_id=actor.id if actor is not None else None,
            action=action,
            item_kind=kind,
            note=note,
            at=_now(),
        )
    )


def _touch(app: RiderApplication, item: RiderApplicationItem) -> None:
    """A change to an item: it is now waiting for review, whatever it was."""

    item.status = ItemStatus.PENDING
    item.reason = ""
    item.reviewed_at = None
    item.reviewed_by_user_id = None


def _seal(value: str, field: str) -> str:
    try:
        return encrypt_secret(value)
    except SecretsUnavailable:
        # Refused rather than stored in the clear: the same rule as payment
        # accounts. An operator sees it on Platform watch before a rider does.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no_secrets") from None


def _previous_account(app: RiderApplication) -> str:
    """The account saved before, compared in full: two accounts can share the
    last four digits. Unreadable (key changed) counts as different."""

    if not app.bank_account_encrypted:
        return ""
    try:
        return decrypt_secret(app.bank_account_encrypted)
    except Exception:  # noqa: BLE001 - treated as a different account
        return ""


def _date(raw: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise _invalid(field, "bad_date") from None


def _text(data: dict[str, Any], field: str, low: int, high: int) -> str:
    value = " ".join(str(data.get(field) or "").split())
    if not low <= len(value) <= high:
        raise _invalid(field, "required" if not value else "bad_length")
    return value


# --- the rider's side ------------------------------------------------------------


def start(db: Session, user: User) -> RiderApplication:
    """A DRAFT application with every item MISSING. Called by sign-up."""

    app = RiderApplication(rider_user_id=user.id, status=ApplicationStatus.DRAFT, full_name=user.full_name)
    db.add(app)
    db.flush()
    for kind in K:
        db.add(RiderApplicationItem(rider_user_id=user.id, kind=kind, status=ItemStatus.MISSING))
    db.flush()
    return app


def save_section(
    db: Session, user: User, section: Section, data: dict[str, Any], today: date | None = None
) -> RiderApplication:
    today = today or date.today()
    app = _lock(db, user.id)
    items = items_of(db, user.id)

    if section == "personal":
        item = items[K.PERSONAL]
        if not editable(app, item):
            raise HTTPException(status.HTTP_409_CONFLICT, "not_editable")
        dob = _date(data.get("date_of_birth"), "date_of_birth")
        if not rules.is_adult(dob, today):
            raise _invalid("date_of_birth", "too_young")
        pincode = rules.valid_pincode(data.get("pincode"))
        if pincode is None:
            raise _invalid("pincode", "bad_pincode")
        from app.services.fleet.riders import canonical_phone

        emergency = canonical_phone(str(data.get("emergency_phone") or ""))
        if not emergency or len(emergency) != 13:
            raise _invalid("emergency_phone", "bad_phone")
        app.full_name = _text(data, "full_name", 2, 120)
        app.date_of_birth = dob
        app.city = _text(data, "city", 2, 80)
        app.address_line = _text(data, "address_line", 5, 240)
        app.pincode = pincode
        app.emergency_name = _text(data, "emergency_name", 2, 120)
        app.emergency_phone = emergency
        _touch(app, item)

    elif section == "vehicle":
        item = items[K.VEHICLE_DETAILS]
        if not editable(app, item):
            raise HTTPException(status.HTTP_409_CONFLICT, "not_editable")
        try:
            vehicle = VehicleType(str(data.get("vehicle_type") or ""))
        except ValueError:
            raise _invalid("vehicle_type", "required") from None
        plate = ""
        if rules.needs_rc(vehicle):
            plate = rules.clean_plate(data.get("vehicle_number")) or ""
            if not plate:
                raise _invalid("vehicle_number", "bad_plate")
        app.vehicle_type = vehicle
        app.vehicle_number = plate
        _touch(app, item)

    elif section == "documents":
        changed: set[K] = set()

        def may(field: str) -> bool:
            kind = _DOCUMENT_FIELD_ITEM[field]
            return field in data and editable(app, items[kind])

        if not any(may(field) for field in _DOCUMENT_FIELD_ITEM):
            raise HTTPException(status.HTTP_409_CONFLICT, "not_editable")
        if may("aadhaar_last4"):
            last4 = str(data.get("aadhaar_last4") or "").strip()
            if not (len(last4) == 4 and last4.isdigit()):
                raise _invalid("aadhaar_last4", "bad_aadhaar_last4")
            app.aadhaar_last4 = last4
            changed.add(K.AADHAAR_FRONT)
        if may("pan"):
            pan = rules.valid_pan(data.get("pan"))
            if pan is None:
                raise _invalid("pan", "bad_pan")
            app.pan_encrypted, app.pan_last4 = _seal(pan, "pan"), pan[-4:]
            changed.add(K.PAN)
        if rules.needs_licence(app.vehicle_type) and (may("licence_number") or may("licence_expiry")):
            number = "".join(str(data.get("licence_number") or "").upper().split()).replace("-", "")
            if not (6 <= len(number) <= 20 and number.isalnum()):
                raise _invalid("licence_number", "bad_licence")
            expiry = _date(data.get("licence_expiry"), "licence_expiry")
            if not rules.licence_valid(expiry, today):
                raise _invalid("licence_expiry", "licence_expired")
            app.licence_number_encrypted, app.licence_last4 = _seal(number, "licence_number"), number[-4:]
            app.licence_expiry = expiry
            changed.add(K.LICENCE_FRONT)
        # A corrected number is news to the reviewer only if the item was
        # flagged; in a draft the photo decides whether it is there yet.
        if app.status == ApplicationStatus.CHANGES_NEEDED:
            for kind in changed:
                _touch(app, items[kind])

    elif section == "bank":
        item = items[K.BANK_DETAILS]
        if not editable(app, item):
            raise HTTPException(status.HTTP_409_CONFLICT, "not_editable")
        holder = _text(data, "bank_holder", 2, 120)
        raw_account = str(data.get("account_number") or "").strip()
        raw_upi = str(data.get("upi_id") or "").strip()
        if not raw_account and not raw_upi:
            raise _invalid("account_number", "bank_required")
        account = ifsc = upi = ""
        if raw_account:
            account = rules.valid_account(raw_account, data.get("account_number_again")) or ""
            if not account:
                raise _invalid("account_number_again", "account_mismatch")
            ifsc = rules.valid_ifsc(data.get("ifsc")) or ""
            if not ifsc:
                raise _invalid("ifsc", "bad_ifsc")
        if raw_upi:
            upi = rules.valid_upi(raw_upi) or ""
            if not upi:
                raise _invalid("upi_id", "bad_upi")
        # A cheque proves the account it shows. A different account (or none)
        # makes the old photo prove nothing, accepted or not: back to missing.
        if not account or account != _previous_account(app):
            proof = items[K.BANK_PROOF]
            if proof.status != ItemStatus.MISSING:
                proof.status, proof.reason = ItemStatus.MISSING, ""
                proof.reviewed_at = proof.reviewed_by_user_id = None
        app.bank_holder = holder
        app.bank_account_encrypted = _seal(account, "account_number") if account else ""
        app.bank_account_last4 = account[-4:]
        app.ifsc = ifsc
        app.upi_id = upi
        _touch(app, item)
    else:  # pragma: no cover - the route only accepts the four
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown section")

    db.commit()
    return app


def save_photo(db: Session, user: User, kind: K, data: bytes) -> RiderApplicationItem:
    if kind not in PHOTO_KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a photo")
    if len(data) > get_settings().rider_doc_max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "too_large")
    content_type = storage.sniff_image(data)
    if content_type is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "not_an_image")

    # Checked before the upload (no point sending a photo that will be
    # refused), then again under the lock after it: the upload is a slow
    # network call and must not hold the application row while it runs.
    app = db.get(RiderApplication, user.id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    if not editable(app, items_of(db, user.id)[kind]):
        raise HTTPException(status.HTTP_409_CONFLICT, "not_editable")
    db.rollback()

    path = f"riders/{user.id}/{kind.value.lower()}-{uuid.uuid4().hex}.{storage.EXTENSION[content_type]}"
    try:
        storage.upload(path, data, content_type)
    except storage.StorageUnavailable as error:
        logger.warning("Rider document upload failed: %s", error)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "storage_not_configured") from None

    app = _lock(db, user.id)
    item = items_of(db, user.id)[kind]
    if not editable(app, item):
        # Submitted from another phone while this one was uploading.
        db.rollback()
        storage.delete(path)
        raise HTTPException(status.HTTP_409_CONFLICT, "not_editable")

    old = item.storage_path
    item.storage_path, item.content_type, item.size_bytes = path, content_type, len(data)
    _touch(app, item)
    db.commit()
    if old:
        storage.delete(old)
    return item


def submit(db: Session, user: User) -> RiderApplication:
    app = _lock(db, user.id)
    items = items_of(db, user.id)
    if app.status not in (ApplicationStatus.DRAFT, ApplicationStatus.CHANGES_NEEDED):
        raise HTTPException(status.HTTP_409_CONFLICT, "state_changed")
    missing = missing_items(app, items)
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"missing": [k.value for k in missing]})
    flagged = [k for k in required_for(app) if items[k].status == ItemStatus.NEEDS_CHANGE]
    if flagged:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"flagged": [k.value for k in flagged]})
    first = app.status == ApplicationStatus.DRAFT
    app.status = ApplicationStatus.SUBMITTED
    app.submitted_at = _now()
    _event(db, app, ApplicationAction.SUBMITTED if first else ApplicationAction.RESUBMITTED, user)
    db.commit()
    _announce(app.rider_user_id)
    return app


# --- the admin's side --------------------------------------------------------------


def review_item(
    db: Session, admin: User, rider_user_id: uuid.UUID, kind: K, *, accept: bool, reason: str = ""
) -> RiderApplicationItem:
    app = _lock(db, rider_user_id)
    if app.status != ApplicationStatus.SUBMITTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "state_changed")
    if kind not in required_for(app):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "not_required")
    reason = " ".join((reason or "").split())[:300]
    if not accept and not reason:
        raise _invalid("reason", "required")
    item = items_of(db, rider_user_id)[kind]
    item.status = ItemStatus.ACCEPTED if accept else ItemStatus.NEEDS_CHANGE
    item.reason = "" if accept else reason
    item.reviewed_by_user_id, item.reviewed_at = admin.id, _now()
    _event(db, app, ApplicationAction.ITEM_ACCEPTED if accept else ApplicationAction.ITEM_FLAGGED, admin, kind, reason)
    db.commit()
    return item


def send_back(db: Session, admin: User, rider_user_id: uuid.UUID) -> RiderApplication:
    app = _lock(db, rider_user_id)
    if app.status != ApplicationStatus.SUBMITTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "state_changed")
    items = items_of(db, rider_user_id)
    if not any(items[k].status == ItemStatus.NEEDS_CHANGE for k in required_for(app)):
        raise HTTPException(status.HTTP_409_CONFLICT, "nothing_flagged")
    app.status = ApplicationStatus.CHANGES_NEEDED
    app.decided_at, app.decided_by_user_id = _now(), admin.id
    _event(db, app, ApplicationAction.SENT_BACK, admin)
    db.commit()
    _announce(rider_user_id, ApplicationStatus.CHANGES_NEEDED)
    return app


def approve(db: Session, admin: User, rider_user_id: uuid.UUID) -> RiderApplication:
    app = _lock(db, rider_user_id)
    if app.status != ApplicationStatus.SUBMITTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "state_changed")
    items = items_of(db, rider_user_id)
    if any(items[k].status != ItemStatus.ACCEPTED for k in required_for(app)):
        raise HTTPException(status.HTTP_409_CONFLICT, "not_all_accepted")
    app.status = ApplicationStatus.APPROVED
    app.decided_at, app.decided_by_user_id = _now(), admin.id
    rider = db.get(Rider, rider_user_id)
    user = db.get(User, rider_user_id)
    # The application is what was checked, so it becomes what the fleet uses:
    # the name on the ID, the vehicle on the RC, the city they work in.
    rider.onboarding = RiderOnboarding.APPROVED
    rider.vehicle_type = app.vehicle_type or rider.vehicle_type
    rider.vehicle_number = app.vehicle_number
    rider.city = app.city
    user.full_name = app.full_name or user.full_name
    from app.services.fleet import referral

    # A referred rider's clock starts now; every approved rider gets a code.
    referral.on_approved(db, rider_user_id)
    _event(db, app, ApplicationAction.APPROVED, admin)
    db.commit()
    _announce(rider_user_id, ApplicationStatus.APPROVED)
    return app


def reject(db: Session, admin: User, rider_user_id: uuid.UUID, reason: str) -> RiderApplication:
    reason = " ".join((reason or "").split())[:500]
    if not reason:
        raise _invalid("reason", "required")
    app = _lock(db, rider_user_id)
    if app.status not in (ApplicationStatus.SUBMITTED, ApplicationStatus.CHANGES_NEEDED):
        raise HTTPException(status.HTTP_409_CONFLICT, "state_changed")
    app.status = ApplicationStatus.REJECTED
    app.final_reason = reason
    app.decided_at, app.decided_by_user_id = _now(), admin.id
    db.get(Rider, rider_user_id).onboarding = RiderOnboarding.REJECTED
    _event(db, app, ApplicationAction.REJECTED, admin, note=reason)
    db.commit()
    _announce(rider_user_id, ApplicationStatus.REJECTED)
    return app


def reopen(db: Session, admin: User, rider_user_id: uuid.UUID) -> RiderApplication:
    """Undo a permanent rejection that was a mistake.

    Back to CHANGES_NEEDED with nothing flagged: the rider can resubmit it as
    it stands, and the admin reviews it again - flagging whatever was wrong
    then, like any other submission.
    """

    app = _lock(db, rider_user_id)
    if app.status != ApplicationStatus.REJECTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "state_changed")
    app.status = ApplicationStatus.CHANGES_NEEDED
    app.final_reason = ""
    db.get(Rider, rider_user_id).onboarding = RiderOnboarding.PENDING
    _event(db, app, ApplicationAction.REOPENED, admin)
    db.commit()
    _announce(rider_user_id, ApplicationStatus.CHANGES_NEEDED)
    return app


def _announce(rider_user_id: uuid.UUID, decided: ApplicationStatus | None = None) -> None:
    """After commit only. The admin queue hears every change; the rider hears decisions."""

    from app.services.fleet import notify

    notify.riders_changed(rider_user_id, force=True)
    if decided is not None:
        notify.application_decided(rider_user_id, decided.value)
