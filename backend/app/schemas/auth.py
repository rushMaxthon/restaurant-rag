from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.enums import UserRole


class UserBase(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    default_address: str | None = None


class UserRegister(UserBase):
    """Public registration always creates a CUSTOMER.

    The role used to be taken from the request body, which let anyone
    self-register as ADMIN. Staff accounts are created through admin-only
    endpoints instead. Clients already send `role: "CUSTOMER"`; the extra field
    is simply ignored.
    """

    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr | None = None
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_identifier(self) -> "UserLogin":
        if not self.email and not self.phone_number:
            raise ValueError("Either email or phone number is required")
        return self


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime


class TokenPayload(BaseModel):
    """Claims carried by an access token.

    `app_client_id` and `token_version` are optional here on purpose: a token
    issued before per-app identity existed simply lacks them, and that must be
    detectable as "legacy" rather than surfacing as an indistinguishable
    validation error.
    """

    sub: str
    role: UserRole
    exp: int
    iat: int | None = None
    app_client_id: uuid.UUID | None = None
    token_version: int | None = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    restaurant_id: uuid.UUID | None = None
    # The app this account belongs to; null for platform staff. Clients can
    # persist it alongside the token to detect a rebuilt/re-branded app.
    app_client_id: uuid.UUID | None = None
    app_key: str | None = None
    user: UserResponse


class LogoutAllResponse(BaseModel):
    """Result of invalidating every session for the calling account."""

    detail: str = "All sessions have been signed out"
    token_version: int
