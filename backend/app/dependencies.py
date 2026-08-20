"""Shared request-level dependencies.

Deliberately lives at the top level of `app` rather than inside `app.api`.
`app/api/__init__.py` imports every router, and those routers import
`app.services.auth`, which needs `get_app_scope` from here. Reaching it through
the `app.api` package therefore created an import cycle that crashed any process
importing `app.services` before `app.api` — which is exactly what a Celery
worker does, so no background task could start.

`app.api.deps` re-exports everything below, so existing imports keep working.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.enums import AppClientStatus
from app.services.app_clients import AppScope, resolve_app_scope, resolve_identity_app_client_id

APP_BUNDLE_ID_HEADER = "X-App-Bundle-Id"
APP_PLATFORM_HEADER = "X-App-Platform"


def get_app_scope(
    db: Annotated[Session, Depends(get_db)],
    x_app_bundle_id: Annotated[str | None, Header(alias=APP_BUNDLE_ID_HEADER)] = None,
    x_app_platform: Annotated[str | None, Header(alias=APP_PLATFORM_HEADER)] = None,
) -> AppScope:
    """Resolve which restaurants the calling app may see.

    Branded mobile builds identify themselves with `X-App-Bundle-Id` (and
    optionally `X-App-Platform`). Callers that send neither — the customer web
    app, the admin panel, curl — resolve to the unscoped marketplace scope, so
    adding this dependency to an endpoint changes nothing for them.

    An unknown bundle ID degrades to the unscoped scope rather than breaking
    the request. A suspended or offboarded app, however, is refused outright:
    `/app-config` already rejects it at startup, so letting a warm app keep
    working from a cached config would make suspension ineffective.
    """

    scope = resolve_app_scope(
        db,
        bundle_id=x_app_bundle_id,
        platform_value=x_app_platform,
    )

    if scope.status is not None and scope.status != AppClientStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This app is {scope.status.value.lower()} and cannot be used",
        )

    return scope


AppScopeDep = Annotated[AppScope, Depends(get_app_scope)]


def ensure_restaurant_readable(app_scope: AppScope, restaurant_id: uuid.UUID | None) -> None:
    """Reject a read for a restaurant outside the calling app's scope.

    Raises 404 rather than 403 so a single-restaurant app cannot be used to
    probe which restaurant IDs exist on the platform.
    """

    if app_scope.allows_restaurant(restaurant_id):
        return

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Not found",
    )


def ensure_restaurant_writable(app_scope: AppScope, restaurant_id: uuid.UUID | None) -> None:
    """Reject a write for a restaurant outside the calling app's scope.

    Writes answer 403: the caller already knows the restaurant it named, so
    there is nothing to hide, and an explicit refusal is easier to debug.
    """

    if app_scope.allows_restaurant(restaurant_id):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This app cannot access data for another restaurant",
    )


def get_identity_app_client_id(
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
) -> uuid.UUID:
    """The app client that owns user accounts for this request.

    Requests without a resolvable bundle id (customer web) fall back to the
    default marketplace client rather than to "no scope", so every customer
    account belongs to exactly one app.
    """

    return resolve_identity_app_client_id(db, app_scope)


IdentityAppClientDep = Annotated[uuid.UUID, Depends(get_identity_app_client_id)]
