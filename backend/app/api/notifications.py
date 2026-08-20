from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.schemas.notifications import (
    AdminNotificationSendRequest,
    AdminNotificationSendResponse,
    DeviceTokenRegisterRequest,
    DeviceTokenRegisterResponse,
    NotificationHistoryResponse,
)
from app.services.auth import get_current_user, require_admin
from app.services.notifications import (
    build_notification_history_response,
    list_notification_history,
    send_admin_notification,
    upsert_device_token,
)

router = APIRouter(tags=["Notifications"])


@router.post(
    "/notifications/device-tokens",
    response_model=DeviceTokenRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_device_token(
    payload: DeviceTokenRegisterRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> DeviceTokenRegisterResponse:
    token_record = upsert_device_token(
        db,
        current_user=current_user,
        payload=payload,
    )
    return DeviceTokenRegisterResponse.model_validate(token_record)


@router.post(
    "/admin/notifications/send",
    response_model=AdminNotificationSendResponse,
)
def send_notification(
    payload: AdminNotificationSendRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> AdminNotificationSendResponse:
    result = send_admin_notification(
        db,
        current_user=current_user,
        payload=payload,
    )
    return AdminNotificationSendResponse(
        history=build_notification_history_response(result.history),
        target_user_count=result.target_user_count,
        sent_count=result.sent_count,
        success_count=result.success_count,
        failure_count=result.failure_count,
    )


@router.get(
    "/admin/notifications/history",
    response_model=list[NotificationHistoryResponse],
)
def get_notification_history(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> list[NotificationHistoryResponse]:
    return list_notification_history(db)
