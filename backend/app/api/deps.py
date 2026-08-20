"""Backwards-compatible re-export of the shared request dependencies.

The implementations moved to `app.dependencies` to break an import cycle: this
module lives inside the `app.api` package, whose `__init__` imports every
router, so anything importing from here pulled the whole API in. See
`app/dependencies.py` for the full explanation.

Import from `app.dependencies` in new code.
"""

from __future__ import annotations

from app.dependencies import (
    APP_BUNDLE_ID_HEADER,
    APP_PLATFORM_HEADER,
    AppScope,
    AppScopeDep,
    IdentityAppClientDep,
    ensure_restaurant_readable,
    ensure_restaurant_writable,
    get_app_scope,
    get_identity_app_client_id,
)

__all__ = [
    "APP_BUNDLE_ID_HEADER",
    "APP_PLATFORM_HEADER",
    "AppScope",
    "AppScopeDep",
    "IdentityAppClientDep",
    "ensure_restaurant_readable",
    "ensure_restaurant_writable",
    "get_app_scope",
    "get_identity_app_client_id",
]
