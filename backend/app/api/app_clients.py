"""The operator's view of every tenant on the platform.

Everything else that reads `app_clients` is answering a question about one of
them — which brand is this storefront, which app is this phone. This router
answers the question the platform operator asks: who is on here, what state
are they in, and take that one off the air.

ADMIN only, without exception. An owner has exactly one restaurant and reaches
it through `/restaurants`; a listing of every tenant is the one screen where
a scoping mistake would show one restaurant another's business.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config.database import get_db
from app.models.app_client import AppClient
from app.models.enums import AppClientDomainKind, AppClientStatus, UserRole
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.app_clients import TenantStatusUpdate, TenantSummaryResponse
from app.services.auth import require_admin

router = APIRouter(prefix="/app-clients", tags=["App Clients"])
logger = logging.getLogger(__name__)


def _counts_by_app_client(db: Session) -> dict[uuid.UUID, dict[str, int]]:
    """Four grouped queries rather than four per tenant.

    The naive version — count locations, items, orders and customers inside
    the loop — is 4N round trips against a pooled connection that is already
    the slowest hop in this deployment. At six tenants nobody would notice; at
    two hundred this is the whole response time.

    Orders and menu items hang off the *location*, not the restaurant, so both
    join through `restaurant_locations`. Getting that wrong would report zero
    for every tenant, which reads as "no business yet" rather than as a bug.
    """

    counts: dict[uuid.UUID, dict[str, int]] = {}

    def _record(key: str, rows: list[tuple[uuid.UUID | None, int]]) -> None:
        for app_client_id, value in rows:
            if app_client_id is None:
                continue
            counts.setdefault(app_client_id, {})[key] = int(value)

    location_rows = db.execute(
        select(AppClient.id, func.count(RestaurantLocation.id))
        .join(RestaurantLocation, RestaurantLocation.restaurant_id == AppClient.restaurant_id)
        .group_by(AppClient.id)
    ).all()
    _record("location_count", list(location_rows))

    menu_rows = db.execute(
        select(AppClient.id, func.count(MenuItem.id))
        .join(RestaurantLocation, RestaurantLocation.restaurant_id == AppClient.restaurant_id)
        .join(MenuItem, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .group_by(AppClient.id)
    ).all()
    _record("menu_item_count", list(menu_rows))

    order_rows = db.execute(
        select(AppClient.id, func.count(Order.id))
        .join(RestaurantLocation, RestaurantLocation.restaurant_id == AppClient.restaurant_id)
        .join(Order, Order.restaurant_location_id == RestaurantLocation.id)
        .group_by(AppClient.id)
    ).all()
    _record("order_count", list(order_rows))

    # Customers are scoped by `app_client_id` directly — that is the whole
    # point of per-app identity — so this one needs no restaurant join.
    customer_rows = db.execute(
        select(User.app_client_id, func.count(User.id))
        .where(User.role == UserRole.CUSTOMER, User.app_client_id.is_not(None))
        .group_by(User.app_client_id)
    ).all()
    _record("customer_count", list(customer_rows))

    return counts


def _summarize(
    app_client: AppClient,
    *,
    counts: dict[str, int],
    changed_by: str | None,
) -> TenantSummaryResponse:
    restaurant = app_client.restaurant

    platform_host = next(
        (
            domain.host
            for domain in app_client.domains
            if domain.kind == AppClientDomainKind.PLATFORM_SUBDOMAIN and domain.is_active
        ),
        None,
    )
    custom_hosts = sum(
        1
        for domain in app_client.domains
        if domain.kind == AppClientDomainKind.CUSTOM and domain.is_active
    )

    return TenantSummaryResponse(
        id=app_client.id,
        app_key=app_client.key,
        display_name=app_client.display_name,
        app_mode=app_client.app_mode,
        status=app_client.status,
        restaurant_id=app_client.restaurant_id,
        restaurant_name=restaurant.name if restaurant else None,
        restaurant_slug=restaurant.slug if restaurant else None,
        cuisine_type=restaurant.cuisine_type if restaurant else None,
        city=restaurant.city if restaurant else None,
        is_approved=restaurant.is_approved if restaurant else None,
        primary_host=platform_host,
        custom_host_count=custom_hosts,
        brand_primary_color=app_client.brand_primary_color,
        status_note=app_client.status_note,
        status_changed_at=app_client.status_changed_at,
        status_changed_by=changed_by,
        location_count=counts.get("location_count", 0),
        menu_item_count=counts.get("menu_item_count", 0),
        order_count=counts.get("order_count", 0),
        customer_count=counts.get("customer_count", 0),
        created_at=app_client.created_at,
        updated_at=app_client.updated_at,
    )


def _changed_by_names(db: Session, app_clients: list[AppClient]) -> dict[uuid.UUID, str]:
    """Display names for the admins who last changed a status, in one query."""

    user_ids = {
        app_client.status_changed_by_user_id
        for app_client in app_clients
        if app_client.status_changed_by_user_id is not None
    }
    if not user_ids:
        return {}

    rows = db.execute(
        select(User.id, User.full_name, User.email).where(User.id.in_(user_ids))
    ).all()
    return {row[0]: (row[1] or row[2]) for row in rows}


def _name_of(names: dict[uuid.UUID, str], user_id: uuid.UUID | None) -> str | None:
    return names.get(user_id) if user_id is not None else None


@router.get("", response_model=list[TenantSummaryResponse])
def list_tenants(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
) -> list[TenantSummaryResponse]:
    """Every tenant, by name.

    Unfiltered and unpaginated, like the other admin listings here: search and
    paging happen in the browser, and the tenant switcher needs the whole set
    anyway. If this platform ever carries enough tenants for that to hurt, the
    switcher is what changes shape first, not this.
    """

    app_clients = list(
        db.scalars(
            select(AppClient)
            .options(selectinload(AppClient.restaurant), selectinload(AppClient.domains))
            .order_by(AppClient.display_name.asc())
        ).all()
    )

    counts = _counts_by_app_client(db)
    changed_by = _changed_by_names(db, app_clients)

    return [
        _summarize(
            app_client,
            counts=counts.get(app_client.id, {}),
            changed_by=_name_of(changed_by, app_client.status_changed_by_user_id),
        )
        for app_client in app_clients
    ]


@router.patch("/{app_client_id}/status", response_model=TenantSummaryResponse)
def update_tenant_status(
    app_client_id: uuid.UUID,
    payload: TenantStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> TenantSummaryResponse:
    """Suspend, offboard or reactivate a tenant.

    This is the only writer of `app_clients.status`, and it is the sharpest
    control in the console: anything other than ACTIVE makes every storefront
    and app request for that tenant fail at `_assert_client_usable`, which is
    exactly the intent and exactly why it is worth being slow about.

    Two guards, both about not being able to do this by accident:

    - Taking a tenant off the air requires a note. Restoring one does not,
      because a restored storefront explains itself by working again.
    - OFFBOARDED is terminal. It is the state for a restaurant that has left
      the platform, and reviving one should mean somebody looked at what they
      still have here rather than clicking a toggle back.
    """

    app_client = db.get(AppClient, app_client_id)
    if app_client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    note = (payload.note or "").strip() or None

    if payload.status != AppClientStatus.ACTIVE and note is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Say why this tenant is being taken off the air",
        )

    if (
        app_client.status == AppClientStatus.OFFBOARDED
        and payload.status != AppClientStatus.OFFBOARDED
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An offboarded tenant cannot be reactivated from here",
        )

    if app_client.status == payload.status and note is None:
        # Nothing to record. Returning the row unchanged keeps the UI honest
        # about what happened rather than stamping a new timestamp on a no-op.
        counts = _counts_by_app_client(db).get(app_client.id, {})
        return _summarize(
            app_client,
            counts=counts,
            changed_by=_name_of(
                _changed_by_names(db, [app_client]),
                app_client.status_changed_by_user_id,
            ),
        )

    previous = app_client.status
    app_client.status = payload.status
    app_client.status_note = note
    app_client.status_changed_at = datetime.now(timezone.utc)
    app_client.status_changed_by_user_id = current_user.id

    db.add(app_client)
    db.commit()
    db.refresh(app_client)

    logger.warning(
        "Tenant lifecycle change app_client_id=%s key=%s %s -> %s by=%s",
        app_client.id,
        app_client.key,
        previous.value,
        app_client.status.value,
        current_user.id,
    )

    counts = _counts_by_app_client(db).get(app_client.id, {})
    return _summarize(
        app_client,
        counts=counts,
        changed_by=current_user.full_name or current_user.email,
    )
