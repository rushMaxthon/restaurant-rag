from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DevicePlatform(StrEnum):
    ANDROID = "ANDROID"
    IOS = "IOS"


class NotificationAudience(StrEnum):
    ALL_USERS = "ALL_USERS"
    CUSTOMERS = "CUSTOMERS"
    OWNERS = "OWNERS"
    ADMINS = "ADMINS"
    SPECIFIC_USER = "SPECIFIC_USER"


class NotificationType(StrEnum):
    GENERAL = "GENERAL"
    ORDER_PLACED = "ORDER_PLACED"


class NotificationDeepLinkType(StrEnum):
    ORDER_DETAILS = "order_details"


class DeviceTokenRegisterRequest(BaseModel):
    installation_id: str = Field(min_length=8, max_length=120)
    fcm_token: str = Field(min_length=32)
    platform: DevicePlatform


class DeviceTokenRegisterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    installation_id: str
    fcm_token: str
    platform: DevicePlatform
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdminNotificationSendRequest(BaseModel):
    audience: NotificationAudience
    notification_type: NotificationType = NotificationType.GENERAL
    title: str = Field(min_length=2, max_length=160)
    message: str = Field(min_length=2, max_length=2000)
    category: str | None = Field(default=None, max_length=80)
    target_user_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_targeting(self) -> "AdminNotificationSendRequest":
        if self.audience == NotificationAudience.SPECIFIC_USER and not self.target_user_id:
            raise ValueError("target_user_id is required when audience is SPECIFIC_USER")
        if self.audience != NotificationAudience.SPECIFIC_USER and self.target_user_id is not None:
            raise ValueError("target_user_id is only allowed when audience is SPECIFIC_USER")
        return self


class NotificationHistoryResponse(BaseModel):
    id: uuid.UUID
    audience: NotificationAudience
    notification_type: NotificationType
    title: str
    message: str
    category: str | None
    deep_link_type: NotificationDeepLinkType | None = None
    order_id: uuid.UUID | None = None
    target_user_id: uuid.UUID | None
    target_user_name: str | None = None
    target_user_email: str | None = None
    target_user_count: int
    sent_count: int
    success_count: int
    failure_count: int
    failure_reason: str | None
    created_by_user_id: uuid.UUID | None
    created_by_name: str | None = None
    created_by_email: str | None = None
    created_at: datetime
    updated_at: datetime


class AdminNotificationSendResponse(BaseModel):
    history: NotificationHistoryResponse
    target_user_count: int
    sent_count: int
    success_count: int
    failure_count: int
