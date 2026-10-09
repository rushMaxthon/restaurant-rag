"""Turning an application into what the rider app and the admin panel see.

One builder for both, so the two cannot disagree about what a rider has
given or what is still missing; the admin view only adds what an admin
alone may see (the phone, the photos, the history).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rider_application import RiderApplication, RiderApplicationEvent
from app.models.user import User
from app.schemas.rider_onboarding import (
    AdminApplicationView,
    ApplicationView,
    BankSection,
    DocumentsSection,
    EventView,
    ItemView,
    PersonalSection,
    Sections,
    VehicleSection,
)
from app.services.fleet.onboarding import applications, storage
from app.services.fleet.onboarding.rules import PHOTO_KINDS, SECTION_OF


def _base(db: Session, app: RiderApplication) -> dict:
    items = applications.items_of(db, app.rider_user_id)
    required = applications.required_for(app)
    return {
        "rider_user_id": app.rider_user_id,
        "status": app.status,
        "sections": Sections(
            personal=PersonalSection(
                full_name=app.full_name,
                date_of_birth=app.date_of_birth,
                city=app.city,
                address_line=app.address_line,
                pincode=app.pincode,
                emergency_name=app.emergency_name,
                emergency_phone=app.emergency_phone,
            ),
            vehicle=VehicleSection(vehicle_type=app.vehicle_type, vehicle_number=app.vehicle_number),
            documents=DocumentsSection(
                aadhaar_last4=app.aadhaar_last4,
                pan_last4=app.pan_last4,
                licence_last4=app.licence_last4,
                licence_expiry=app.licence_expiry,
            ),
            bank=BankSection(
                bank_holder=app.bank_holder,
                bank_account_last4=app.bank_account_last4,
                ifsc=app.ifsc,
                upi_id=app.upi_id,
            ),
        ),
        "items": [
            ItemView(
                kind=kind,
                status=item.status,
                reason=item.reason,
                section=SECTION_OF[kind],
                required=kind in required,
                has_photo=bool(item.storage_path),
                editable=applications.editable(app, item),
            )
            for kind, item in items.items()
        ],
        "required": required,
        "missing": applications.missing_items(app, items),
        "final_reason": app.final_reason,
        "submitted_at": app.submitted_at,
        "decided_at": app.decided_at,
    }


def application_view(db: Session, app: RiderApplication) -> ApplicationView:
    return ApplicationView(**_base(db, app))


def admin_application_view(db: Session, app: RiderApplication) -> AdminApplicationView:
    base = _base(db, app)
    user = db.get(User, app.rider_user_id)
    photos: dict = {}
    error = None
    missing: list = []
    if storage.configured():
        # Signed one by one: a single file gone from the bucket costs that
        # photo, not every document on the page (one broken link used to
        # blank the whole review).
        for kind, item in applications.items_of(db, app.rider_user_id).items():
            if kind in PHOTO_KINDS and item.storage_path:
                try:
                    photos[kind] = storage.signed_url(item.storage_path)
                except storage.StorageUnavailable:
                    missing.append(kind)
    else:
        error = "storage_not_configured"
    names = {}
    events = db.scalars(
        select(RiderApplicationEvent)
        .where(RiderApplicationEvent.rider_user_id == app.rider_user_id)
        .order_by(RiderApplicationEvent.at)
    ).all()
    for actor_id in {e.actor_user_id for e in events if e.actor_user_id}:
        actor = db.get(User, actor_id)
        names[actor_id] = actor.full_name if actor else None
    return AdminApplicationView(
        **base,
        phone_number=user.phone_number if user else None,
        photos=photos,
        photos_error=error,
        missing_photos=missing if storage.configured() else [],
        events=[
            EventView(
                at=e.at,
                action=e.action,
                item_kind=e.item_kind,
                note=e.note,
                actor_name=names.get(e.actor_user_id),
            )
            for e in events
        ],
    )

