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


class OtpRequest(BaseModel):
    """Ask for a code to be sent to a phone number."""

    phone_number: str = Field(min_length=6, max_length=20)


class OtpRequestResponse(BaseModel):
    """What the client needs to draw the second step of the form."""

    #: Always true when the route returns at all; a failure is an error status,
    #: not `sent: false`. Present so the shape still reads as an answer.
    sent: bool = True
    #: Whether this number already belongs to an account on this app. The
    #: client asks a first-time caller for their name on the next screen, which
    #: is the only point in this flow where a name can be collected.
    #:
    #: It does tell an unauthenticated caller whether a number is registered.
    #: That is the same thing every food app in this market does — the second
    #: screen says "create your account" or "welcome back" — and the whole
    #: route is refused outside a local environment today. Worth revisiting
    #: with the real sender, together with rate limiting.
    is_new_account: bool
    #: The code to type, when the deployment is using the fixed one. Null
    #: anywhere a real code would have been sent, so this can never become the
    #: way a production client learns a secret.
    debug_code: str | None = None


class OtpVerify(BaseModel):
    """Exchange a phone number and a code for a session."""

    phone_number: str = Field(min_length=6, max_length=20)
    code: str = Field(min_length=4, max_length=8)
    #: Only read when the number has no account yet; ignored otherwise, so a
    #: returning customer cannot have their name rewritten by a sign-in form.
    full_name: str | None = Field(default=None, max_length=255)


class UserResponse(BaseModel):
    """An account as stored, for reading back.

    Not `UserBase`: its rules (a two-letter name, an email that validates,
    an eight-digit phone) are for what somebody types at sign-up. A customer
    who signed in by phone OTP had no name yet, and inheriting them turned
    `GET /admin/users` into a 500 for every admin - which a browser reports
    as a CORS error. What is stored is shown as it is.
    """

    model_config = ConfigDict(from_attributes=True)

    full_name: str = ""
    email: str = ""
    phone_number: str | None = None
    default_address: str | None = None
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
    # The restaurant this account is bound to: an OWNER's own, or the one a
    # KITCHEN account is assigned to. Null for an ADMIN, who has none, and for
    # a CUSTOMER, who is not staff.
    restaurant_id: uuid.UUID | None = None
    # The single branch a KITCHEN account is pinned to, and null for every
    # other role — including a kitchen account assigned to a restaurant rather
    # than to one of its branches. The order board reads it to decide whether
    # to offer a branch picker at all.
    restaurant_location_id: uuid.UUID | None = None
    # The app this account belongs to; null for platform staff. Clients can
    # persist it alongside the token to detect a rebuilt/re-branded app.
    app_client_id: uuid.UUID | None = None
    app_key: str | None = None
    user: UserResponse


class LogoutAllResponse(BaseModel):
    """Result of invalidating every session for the calling account."""

    detail: str = "All sessions have been signed out"
    token_version: int
