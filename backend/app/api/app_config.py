from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import APP_BUNDLE_ID_HEADER, APP_PLATFORM_HEADER
from app.config.database import get_db
from app.schemas.app_config import AppConfigResponse
from app.services.app_clients import (
    build_app_config_response,
    parse_app_client_platform,
    resolve_app_client_by_bundle_id,
)

router = APIRouter(prefix="/app-config", tags=["App Config"])
logger = logging.getLogger(__name__)


@router.get("", response_model=AppConfigResponse)
def get_app_config(
    db: Annotated[Session, Depends(get_db)],
    x_app_bundle_id: Annotated[str | None, Header(alias=APP_BUNDLE_ID_HEADER)] = None,
    x_app_platform: Annotated[str | None, Header(alias=APP_PLATFORM_HEADER)] = None,
    bundle_id: Annotated[str | None, Query(max_length=255)] = None,
    platform: Annotated[str | None, Query(max_length=16)] = None,
) -> AppConfigResponse:
    """Resolve a mobile build's bundle ID to its app configuration.

    Public on purpose: the app calls this at startup, before any login, to learn
    which brand it is and whether it runs in marketplace or single-restaurant
    mode. The `X-App-Bundle-Id` header is the path the app uses; the `bundle_id`
    query parameter is a convenience for testing and takes effect only when the
    header is absent.

    `X-App-Platform` (`IOS` / `ANDROID`) is optional. When supplied the bundle
    ID is matched for that platform specifically, which matters because a bundle
    ID may be registered to different app clients per platform. An unrecognised
    value is ignored rather than rejected.
    """

    resolved_bundle_id = x_app_bundle_id or bundle_id
    if not resolved_bundle_id or not resolved_bundle_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide the app bundle ID via the X-App-Bundle-Id header or the bundle_id query parameter",
        )

    resolved_platform = parse_app_client_platform(x_app_platform or platform)
    app_client = resolve_app_client_by_bundle_id(
        db,
        bundle_id=resolved_bundle_id,
        platform=resolved_platform,
    )
    logger.info(
        "App config resolved bundle_id=%s platform=%s app_key=%s app_mode=%s restaurant_id=%s",
        resolved_bundle_id.strip(),
        resolved_platform.value if resolved_platform else "any",
        app_client.key,
        app_client.app_mode.value,
        app_client.restaurant_id,
    )
    return build_app_config_response(app_client, bundle_id=resolved_bundle_id)
