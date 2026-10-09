"""What the rider app and the admin panel see of a rider's application.

Sensitive numbers leave the server as their last four digits only - PAN,
licence, bank account - and Aadhaar was never stored as more than that.
Photos reach an admin as links that expire in five minutes, and never reach
the rider at all (they have the photo on their phone already).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import ApplicationAction, ApplicationItemKind, ApplicationStatus, ItemStatus, VehicleType


class SignupCodeRequest(BaseModel):
    phone_number: str = Field(min_length=6, max_length=20)


class SignupCodeResponse(BaseModel):
    sent: bool
    retry_after: int
    #: The static code, while sign-up runs without a real sender.
    debug_code: str | None = None


class SignupCheckRequest(BaseModel):
    phone_number: str = Field(min_length=6, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class SignupRequest(BaseModel):
    phone_number: str = Field(min_length=6, max_length=20)
    code: str = Field(min_length=4, max_length=8)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=120)


class ItemView(BaseModel):
    kind: ApplicationItemKind
    status: ItemStatus
    reason: str
    section: str
    required: bool
    has_photo: bool
    #: Whether the rider may change it right now (draft, or flagged).
    editable: bool


class PersonalSection(BaseModel):
    full_name: str
    date_of_birth: date | None
    city: str
    address_line: str
    pincode: str
    emergency_name: str
    emergency_phone: str


class VehicleSection(BaseModel):
    vehicle_type: VehicleType | None
    vehicle_number: str


class DocumentsSection(BaseModel):
    aadhaar_last4: str
    pan_last4: str
    licence_last4: str
    licence_expiry: date | None


class BankSection(BaseModel):
    bank_holder: str
    bank_account_last4: str
    ifsc: str
    upi_id: str


class Sections(BaseModel):
    personal: PersonalSection
    vehicle: VehicleSection
    documents: DocumentsSection
    bank: BankSection


class ApplicationView(BaseModel):
    rider_user_id: uuid.UUID
    status: ApplicationStatus
    sections: Sections
    items: list[ItemView]
    required: list[ApplicationItemKind]
    missing: list[ApplicationItemKind]
    final_reason: str
    submitted_at: datetime | None
    decided_at: datetime | None


class EventView(BaseModel):
    at: datetime
    action: ApplicationAction
    item_kind: ApplicationItemKind | None
    note: str
    actor_name: str | None


class AdminApplicationView(ApplicationView):
    phone_number: str | None
    #: Signed links, valid five minutes. Empty when storage is not configured.
    photos: dict[ApplicationItemKind, str]
    photos_error: str | None = None
    #: Uploaded, but the file could not be found in storage. Shown per photo.
    missing_photos: list[ApplicationItemKind] = []
    events: list[EventView]


class ApplicationSummary(BaseModel):
    rider_user_id: uuid.UUID
    full_name: str
    phone_number: str | None
    city: str
    vehicle_type: VehicleType | None
    status: ApplicationStatus
    submitted_at: datetime | None
    updated_at: datetime
    flagged: int


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
