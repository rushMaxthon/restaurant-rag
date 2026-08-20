"""Tenancy scope for the AI Restaurant Manager metrics layer.

Every metric query in this package takes an `InsightsScope`. The scope is
resolved once, from the authenticated user, and carries an already-verified
restaurant id. Metric builders never accept a raw client-supplied restaurant id,
so a request cannot widen its own blast radius by passing a different uuid.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.auth import resolve_owner_restaurant_id


@dataclass(frozen=True, slots=True)
class InsightsScope:
    """A verified restaurant (and optional branch) an insights request may read.

    Frozen so a scope cannot be mutated after the permission check that produced
    it.
    """

    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None = None

    def cache_fragment(self) -> str:
        location = self.restaurant_location_id or "all"
        return f"{self.restaurant_id}:{location}"


def resolve_insights_scope(
    db: Session,
    *,
    current_user: User,
    restaurant_id: uuid.UUID | None = None,
    restaurant_location_id: uuid.UUID | None = None,
) -> InsightsScope:
    """Resolve and authorize the restaurant/branch an insights request may read.

    Owners are pinned to their own restaurant and may not name another one, even
    by accident. Admins must name a restaurant explicitly, because there is no
    sensible cross-tenant diagnosis.
    """

    if current_user.role == UserRole.OWNER:
        owned_restaurant_id = resolve_owner_restaurant_id(db, current_user)
        if restaurant_id is not None and restaurant_id != owned_restaurant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Owners can only access insights for their own restaurant",
            )
        resolved_restaurant_id = owned_restaurant_id
    elif current_user.role == UserRole.ADMIN:
        if restaurant_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="restaurant_id is required for admin insights requests",
            )
        exists = db.scalar(select(Restaurant.id).where(Restaurant.id == restaurant_id))
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Restaurant not found",
            )
        resolved_restaurant_id = restaurant_id
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access restaurant insights",
        )

    if restaurant_location_id is not None:
        owns_location = db.scalar(
            select(RestaurantLocation.id).where(
                RestaurantLocation.id == restaurant_location_id,
                RestaurantLocation.restaurant_id == resolved_restaurant_id,
            )
        )
        if owns_location is None:
            # Deliberately 404 rather than 403: confirming that a branch exists
            # but belongs to someone else is itself a cross-tenant disclosure.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Restaurant location not found for this restaurant",
            )

    return InsightsScope(
        restaurant_id=resolved_restaurant_id,
        restaurant_location_id=restaurant_location_id,
    )


__all__ = ["InsightsScope", "resolve_insights_scope"]
