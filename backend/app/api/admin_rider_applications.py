"""Reviewing riders who signed up in the app. ADMIN only, like the rest of the fleet.

The queue is oldest-submitted first: a rider who applied yesterday is waiting
longer than one who applied an hour ago. Every decision goes through
`onboarding.applications`, which locks the row, so two admins on the same
application get one decision and a 409 `state_changed`, not two.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.enums import ApplicationItemKind, ApplicationStatus, ItemStatus
from app.models.rider_application import RiderApplication, RiderApplicationItem
from app.models.user import User
from app.schemas.rider_onboarding import AdminApplicationView, ApplicationSummary, ReasonBody
from app.services.auth import require_admin
from app.services.fleet.onboarding import applications
from app.services.fleet.onboarding.views import admin_application_view

router = APIRouter(prefix="/admin/rider-applications", tags=["admin-rider-applications"])
Admin = Annotated[User, Depends(require_admin)]
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[ApplicationSummary])
def queue(
    admin: Admin,
    db: Db,
    status_filter: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
    q: str = "",
    city: str = "",
) -> list[ApplicationSummary]:
    flagged = (
        select(func.count())
        .select_from(RiderApplicationItem)
        .where(
            RiderApplicationItem.rider_user_id == RiderApplication.rider_user_id,
            RiderApplicationItem.status == ItemStatus.NEEDS_CHANGE,
        )
        .scalar_subquery()
    )
    query = select(RiderApplication, User, flagged).join(User, User.id == RiderApplication.rider_user_id)
    if status_filter is not None:
        query = query.where(RiderApplication.status == status_filter)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(RiderApplication.full_name.ilike(like), User.phone_number.ilike(like)))
    if city.strip():
        query = query.where(RiderApplication.city.ilike(city.strip()))
    query = query.order_by(RiderApplication.submitted_at.asc().nulls_last(), RiderApplication.updated_at.desc()).limit(500)
    return [
        ApplicationSummary(
            rider_user_id=app.rider_user_id,
            full_name=app.full_name or user.full_name,
            phone_number=user.phone_number,
            city=app.city,
            vehicle_type=app.vehicle_type,
            status=app.status,
            submitted_at=app.submitted_at,
            updated_at=app.updated_at,
            flagged=count or 0,
        )
        for app, user, count in db.execute(query).all()
    ]


def _view(db: Session, rider_user_id: uuid.UUID) -> AdminApplicationView:
    app = db.get(RiderApplication, rider_user_id, populate_existing=True)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return admin_application_view(db, app)


@router.get("/{rider_user_id}", response_model=AdminApplicationView)
def detail(rider_user_id: uuid.UUID, admin: Admin, db: Db) -> AdminApplicationView:
    return _view(db, rider_user_id)


@router.post("/{rider_user_id}/items/{kind}/accept", response_model=AdminApplicationView)
def accept_item(rider_user_id: uuid.UUID, kind: ApplicationItemKind, admin: Admin, db: Db) -> AdminApplicationView:
    applications.review_item(db, admin, rider_user_id, kind, accept=True)
    return _view(db, rider_user_id)


@router.post("/{rider_user_id}/items/{kind}/flag", response_model=AdminApplicationView)
def flag_item(
    rider_user_id: uuid.UUID, kind: ApplicationItemKind, body: ReasonBody, admin: Admin, db: Db
) -> AdminApplicationView:
    applications.review_item(db, admin, rider_user_id, kind, accept=False, reason=body.reason)
    return _view(db, rider_user_id)


@router.post("/{rider_user_id}/send-back", response_model=AdminApplicationView)
def send_back(rider_user_id: uuid.UUID, admin: Admin, db: Db) -> AdminApplicationView:
    applications.send_back(db, admin, rider_user_id)
    return _view(db, rider_user_id)


@router.post("/{rider_user_id}/approve", response_model=AdminApplicationView)
def approve(rider_user_id: uuid.UUID, admin: Admin, db: Db) -> AdminApplicationView:
    applications.approve(db, admin, rider_user_id)
    return _view(db, rider_user_id)


@router.post("/{rider_user_id}/reject", response_model=AdminApplicationView)
def reject(rider_user_id: uuid.UUID, body: ReasonBody, admin: Admin, db: Db) -> AdminApplicationView:
    applications.reject(db, admin, rider_user_id, body.reason)
    return _view(db, rider_user_id)


@router.post("/{rider_user_id}/reopen", response_model=AdminApplicationView)
def reopen(rider_user_id: uuid.UUID, admin: Admin, db: Db) -> AdminApplicationView:
    applications.reopen(db, admin, rider_user_id)
    return _view(db, rider_user_id)
