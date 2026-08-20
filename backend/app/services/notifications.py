from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import islice
from typing import Iterable
import uuid

import firebase_admin
from firebase_admin import credentials, messaging
from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.user_device_token import UserDeviceToken
from app.models.user import User
from app.models.enums import (
    OrderScheduleType,
    PaymentMethod,
    PushNotificationAudience as PushNotificationAudienceModel,
    PushNotificationCampaignStatus,
    PushNotificationDeliveryType,
    UserRole,
)
from app.models.order import Order
from app.schemas.notifications import (
    AdminNotificationSendRequest,
    DeviceTokenRegisterRequest,
    NotificationDeepLinkType,
    NotificationAudience,
    NotificationHistoryResponse,
    NotificationType,
)

settings = get_settings()
logger = logging.getLogger(__name__)


class NotificationDeliveryError(RuntimeError):
    pass


@dataclass
class NotificationDispatchResult:
    history: PushNotificationCampaign
    target_user_count: int
    sent_count: int
    success_count: int
    failure_count: int


def _chunked(values: Iterable[str], size: int) -> Iterable[list[str]]:
    iterator = iter(values)
    while True:
        batch = list(islice(iterator, size))
        if not batch:
            break
        yield batch


def _should_deactivate_token(exception: Exception | None) -> bool:
    if exception is None:
        return False

    code = getattr(exception, "code", "") or ""
    if code in {
        "messaging/registration-token-not-registered",
        "messaging/invalid-registration-token",
        "messaging/mismatched-credential",
    }:
        return True

    return "SenderId mismatch" in str(exception)


def _build_history_response_payload(history: PushNotificationCampaign) -> dict[str, object | None]:
    payload = history.data_payload or {}
    notification_type = payload.get("notification_type") or payload.get("type")
    deep_link_type = payload.get("deep_link_type")
    order_id = payload.get("order_id")
    normalized_notification_type = (
        NotificationType.ORDER_PLACED
        if notification_type in {"ORDER_PLACED", "order_placed"}
        else NotificationType.GENERAL
    )
    normalized_deep_link_type = (
        NotificationDeepLinkType.ORDER_DETAILS
        if deep_link_type == NotificationDeepLinkType.ORDER_DETAILS.value
        else None
    )
    return {
        "notification_type": normalized_notification_type,
        "deep_link_type": normalized_deep_link_type,
        "order_id": uuid.UUID(order_id) if isinstance(order_id, str) and order_id else None,
        "category": payload.get("category") if isinstance(payload.get("category"), str) else None,
    }


def _stringify_payload(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _get_firebase_app():
    credentials_path = os.path.abspath(settings.fcm_credentials_path)

    if not os.path.exists(credentials_path):
        raise NotificationDeliveryError(
            f"Firebase Admin credentials file is missing at {credentials_path}"
        )

    try:
        return firebase_admin.get_app()
    except ValueError:
        certificate = credentials.Certificate(credentials_path)
        options = {"projectId": settings.fcm_project_id} if settings.fcm_project_id else None
        return firebase_admin.initialize_app(certificate, options=options)


def upsert_device_token(
    db: Session,
    *,
    current_user: User,
    payload: DeviceTokenRegisterRequest,
) -> UserDeviceToken:
    normalized_token = payload.fcm_token.strip()
    installation_id = payload.installation_id.strip()

    token_record = db.scalar(
        select(UserDeviceToken).where(
            UserDeviceToken.user_id == current_user.id,
            UserDeviceToken.installation_id == installation_id,
        )
    )

    if token_record is None:
        token_record = db.scalar(
            select(UserDeviceToken).where(UserDeviceToken.fcm_token == normalized_token)
        )

    if token_record is None:
        token_record = UserDeviceToken(
            user_id=current_user.id,
            installation_id=installation_id,
            fcm_token=normalized_token,
            platform=payload.platform.value,
            device_name=None,
            app_version=None,
            is_active=True,
        )
    else:
        token_record.user_id = current_user.id
        token_record.installation_id = installation_id
        token_record.fcm_token = normalized_token
        token_record.platform = payload.platform.value
        token_record.is_active = True

    db.add(token_record)
    db.commit()
    db.refresh(token_record)
    logger.info(
        "Registered FCM token user_id=%s platform=%s installation_id=%s",
        current_user.id,
        token_record.platform,
        token_record.installation_id,
    )
    return token_record


def list_notification_history(db: Session, *, limit: int = 20) -> list[NotificationHistoryResponse]:
    rows = db.scalars(
        select(PushNotificationCampaign)
        .options(
            joinedload(PushNotificationCampaign.specific_user),
            joinedload(PushNotificationCampaign.created_by_user),
        )
        .order_by(PushNotificationCampaign.created_at.desc())
        .limit(limit)
    ).all()

    return [_history_response(history) for history in rows]


def _build_audience_query(payload: AdminNotificationSendRequest) -> Select[tuple[User]]:
    query = select(User).where(
        User.is_active.is_(True),
        User.is_verified.is_(True),
    )

    if payload.audience == NotificationAudience.CUSTOMERS:
        query = query.where(User.role == UserRole.CUSTOMER)
    elif payload.audience == NotificationAudience.OWNERS:
        query = query.where(User.role == UserRole.OWNER)
    elif payload.audience == NotificationAudience.ADMINS:
        query = query.where(User.role == UserRole.ADMIN)
    elif payload.audience == NotificationAudience.SPECIFIC_USER:
        query = query.where(User.id == payload.target_user_id)

    return query.order_by(User.created_at.desc())


def _history_response(history: PushNotificationCampaign) -> NotificationHistoryResponse:
    creator = history.created_by_user
    target_user = history.specific_user
    payload = _build_history_response_payload(history)
    return NotificationHistoryResponse(
        id=history.id,
        audience=NotificationAudience(history.audience.value),
        notification_type=payload["notification_type"],
        title=history.title,
        message=history.message,
        category=payload["category"],
        deep_link_type=payload["deep_link_type"],
        order_id=payload["order_id"],
        target_user_id=history.specific_user_id,
        target_user_name=target_user.full_name if target_user else None,
        target_user_email=target_user.email if target_user else None,
        target_user_count=history.estimated_recipient_count or 0,
        sent_count=history.sent_count or 0,
        success_count=history.delivered_count or 0,
        failure_count=history.failed_count or 0,
        failure_reason=history.last_error,
        created_by_user_id=history.created_by_user_id,
        created_by_name=creator.full_name if creator else None,
        created_by_email=creator.email if creator else None,
        created_at=history.created_at,
        updated_at=history.updated_at,
    )


def send_admin_notification(
    db: Session,
    *,
    current_user: User,
    payload: AdminNotificationSendRequest,
) -> NotificationDispatchResult:
    logger.info(
        "Admin notification request received admin_user_id=%s audience=%s title=%s",
        current_user.id,
        payload.audience.value,
        payload.title,
    )

    target_users = db.scalars(_build_audience_query(payload)).all()
    target_user_ids = [user.id for user in target_users]

    if not target_users:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No matching users found for the selected audience",
        )

    logger.info(
        "Notification payload resolved audience=%s target_users=%s",
        payload.audience.value,
        len(target_users),
    )

    device_tokens = db.scalars(
        select(UserDeviceToken)
        .where(
            UserDeviceToken.user_id.in_(target_user_ids),
            UserDeviceToken.is_active.is_(True),
        )
        .order_by(UserDeviceToken.updated_at.desc())
    ).all()

    token_values = list(dict.fromkeys(token.fcm_token for token in device_tokens))
    logger.info(
        "Notification target device lookup audience=%s tokens=%s",
        payload.audience.value,
        len(token_values),
    )

    history = PushNotificationCampaign(
        created_by_user_id=current_user.id,
        specific_user_id=payload.target_user_id,
        audience=PushNotificationAudienceModel(payload.audience.value),
        delivery_type=PushNotificationDeliveryType.INSTANT,
        status=PushNotificationCampaignStatus.DRAFT,
        template_key=None,
        title=payload.title.strip(),
        message=payload.message.strip(),
        image_url=None,
        deep_link=None,
        timezone="Asia/Kolkata",
        scheduled_for=None,
        dispatched_at=None,
        estimated_recipient_count=len(target_users),
        data_payload={
            "notification_type": (
                "order_placed"
                if payload.notification_type == NotificationType.ORDER_PLACED
                else "general"
            ),
            "category": payload.category.strip() if payload.category else None,
            "audience": payload.audience.value,
        },
    )
    return _dispatch_push_campaign(
        db,
        history=history,
        device_tokens=device_tokens,
        target_user_count=len(target_users),
    )

def _dispatch_push_campaign(
    db: Session,
    *,
    history: PushNotificationCampaign,
    device_tokens: list[UserDeviceToken],
    target_user_count: int,
) -> NotificationDispatchResult:
    token_values = list(dict.fromkeys(token.fcm_token for token in device_tokens))

    db.add(history)
    db.flush()

    if not token_values:
        history.status = PushNotificationCampaignStatus.FAILED
        history.last_error = "No active device tokens found for the selected audience"
        db.add(history)
        db.commit()
        db.refresh(history)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=history.last_error,
        )

    try:
        firebase_app = _get_firebase_app()
        logger.info(
            "Firebase send attempt notification_id=%s tokens=%s",
            history.id,
            len(token_values),
        )
        history.status = PushNotificationCampaignStatus.SENDING
        db.add(history)
        db.flush()

        success_count = 0
        failure_count = 0
        invalid_tokens: set[str] = set()
        failure_reasons: dict[str, int] = {}
        payload_data = history.data_payload or {}

        data = {
            "notification_type": _stringify_payload(
                payload_data.get("notification_type"),
            ) or "general",
            "category": _stringify_payload(payload_data.get("category")) or "GENERAL",
            "audience": history.audience.value,
            "notification_id": str(history.id),
            "order_id": _stringify_payload(payload_data.get("order_id")) or "",
        }

        for batch in _chunked(token_values, 500):
            response = messaging.send_each_for_multicast(
                messaging.MulticastMessage(
                    tokens=batch,
                    notification=messaging.Notification(
                        title=history.title,
                        body=history.message,
                    ),
                    data=data,
                ),
                app=firebase_app,
            )
            success_count += response.success_count
            failure_count += response.failure_count

            for token_value, send_response in zip(batch, response.responses, strict=False):
                if send_response.success:
                    continue
                exception = send_response.exception
                logger.warning(
                    "Firebase send failure notification_id=%s token=%s error=%s",
                    history.id,
                    token_value,
                    exception,
                )
                reason = str(exception) if exception is not None else "Unknown Firebase send failure"
                failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
                if _should_deactivate_token(exception):
                    invalid_tokens.add(token_value)

        if invalid_tokens:
            for token_record in device_tokens:
                if token_record.fcm_token in invalid_tokens:
                    token_record.is_active = False
                    db.add(token_record)

        history.sent_count = len(token_values)
        history.delivered_count = success_count
        history.failed_count = failure_count
        history.dispatched_at = datetime.now(timezone.utc)
        history.status = (
            PushNotificationCampaignStatus.SENT
            if success_count > 0
            else PushNotificationCampaignStatus.FAILED
        )
        if failure_count == 0:
            history.last_error = None
        else:
            summarized_reasons = ", ".join(
                f"{reason} ({count})"
                for reason, count in sorted(
                    failure_reasons.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:3]
            )
            history.last_error = (
                f"Partial delivery failure: {summarized_reasons}"
                if success_count > 0
                else f"All notification deliveries failed: {summarized_reasons}"
            )
        db.add(history)
        db.commit()
        db.refresh(history)
        logger.info(
            "Firebase response notification_id=%s sent=%s success=%s failure=%s",
            history.id,
            history.sent_count,
            history.delivered_count,
            history.failed_count,
        )
        return NotificationDispatchResult(
            history=history,
            target_user_count=target_user_count,
            sent_count=history.sent_count,
            success_count=history.delivered_count,
            failure_count=history.failed_count,
        )
    except HTTPException:
        raise
    except NotificationDeliveryError as error:
        history.status = PushNotificationCampaignStatus.FAILED
        history.last_error = str(error)
        db.add(history)
        db.commit()
        db.refresh(history)
        logger.exception("Notification delivery blocked notification_id=%s", history.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except Exception as error:
        history.status = PushNotificationCampaignStatus.FAILED
        history.last_error = str(error)
        db.add(history)
        db.commit()
        db.refresh(history)
        logger.exception("Notification send failed notification_id=%s", history.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Firebase send failed. Check backend logs for the exact reason.",
        ) from error


def build_notification_history_response(
    history: PushNotificationCampaign,
) -> NotificationHistoryResponse:
    return _history_response(history)


def send_order_placed_notification(
    db: Session,
    *,
    customer: User,
    order: Order,
) -> NotificationDispatchResult | None:
    if order.payment_method == PaymentMethod.COD:
        return None
    if str(order.payment_status) not in {"PAID", "PaymentStatus.PAID"}:
        return None

    device_tokens = db.scalars(
        select(UserDeviceToken)
        .where(
            UserDeviceToken.user_id == customer.id,
            UserDeviceToken.is_active.is_(True),
        )
        .order_by(UserDeviceToken.updated_at.desc())
    ).all()

    history = PushNotificationCampaign(
        created_by_user_id=None,
        specific_user_id=customer.id,
        audience=PushNotificationAudienceModel.SPECIFIC_USER,
        delivery_type=PushNotificationDeliveryType.INSTANT,
        status=PushNotificationCampaignStatus.DRAFT,
        template_key="order_placed",
        title="✅ Order Placed Successfully",
        message="Your payment was successful and your order has been placed.",
        image_url=None,
        deep_link=None,
        timezone="Asia/Kolkata",
        scheduled_for=None,
        dispatched_at=None,
        estimated_recipient_count=1,
        data_payload={
            "notification_type": "order_placed",
            "category": "ORDER_UPDATE",
            "audience": NotificationAudience.SPECIFIC_USER.value,
            "order_id": str(order.id),
            "schedule_type": order.schedule_type.value
            if isinstance(order.schedule_type, OrderScheduleType)
            else str(order.schedule_type),
        },
    )

    return _dispatch_push_campaign(
        db,
        history=history,
        device_tokens=device_tokens,
        target_user_count=1,
    )
