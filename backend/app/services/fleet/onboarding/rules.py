"""What a rider's application is checked against. Pure, so it can be tested
without a database and mirrored in the app (`rider/src/utils/onboarding.ts`).

The phone checks first so a rider hears "that IFSC is wrong" before sending
anything; this copy is the one that counts.
"""

from __future__ import annotations

import re
from datetime import date

from app.models.enums import ApplicationItemKind as K
from app.models.enums import VehicleType

# Standard plates (GJ05AB1234, GJ51234) and the Bharat series (22BH1234AA).
_PLATE = re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}$")
_BH_PLATE = re.compile(r"^\d{2}BH\d{4}[A-Z]{1,2}$")
_PAN = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
# The fifth character of an IFSC is always zero, reserved by the RBI.
_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_PINCODE = re.compile(r"^[1-9]\d{5}$")
_ACCOUNT = re.compile(r"^\d{9,18}$")
_UPI = re.compile(r"^[a-z0-9.\-_]{2,256}@[a-z]{2,64}$")

PHOTO_KINDS = frozenset(
    {K.SELFIE, K.RC, K.AADHAAR_FRONT, K.AADHAAR_BACK, K.PAN, K.LICENCE_FRONT, K.LICENCE_BACK, K.BANK_PROOF}
)

#: Which form step each item belongs to, so the app can open the right one
#: when the rider taps "Fix" on a flagged item.
SECTION_OF: dict[K, str] = {
    K.PERSONAL: "personal",
    K.SELFIE: "personal",
    K.VEHICLE_DETAILS: "vehicle",
    K.RC: "vehicle",
    K.AADHAAR_FRONT: "documents",
    K.AADHAAR_BACK: "documents",
    K.PAN: "documents",
    K.LICENCE_FRONT: "documents",
    K.LICENCE_BACK: "documents",
    K.BANK_DETAILS: "bank",
    K.BANK_PROOF: "bank",
}


def needs_rc(vehicle: VehicleType | None) -> bool:
    """A registered vehicle. A bicycle and a low-speed e-scooter have no RC."""

    return vehicle in (VehicleType.BIKE, VehicleType.SCOOTER)


def needs_licence(vehicle: VehicleType | None) -> bool:
    return vehicle in (VehicleType.BIKE, VehicleType.SCOOTER)


def required_items(vehicle: VehicleType | None) -> list[K]:
    """Everything an application must carry before it can be submitted.

    The bank proof photo depends on whether an account number was given (a
    UPI ID needs none), so `applications.required_for` adds it, not this.
    """

    items = [K.PERSONAL, K.SELFIE, K.AADHAAR_FRONT, K.AADHAAR_BACK, K.PAN, K.BANK_DETAILS]
    if needs_rc(vehicle):
        items += [K.VEHICLE_DETAILS, K.RC]
    if needs_licence(vehicle):
        items += [K.LICENCE_FRONT, K.LICENCE_BACK]
    return items


def _squash(raw: str | None) -> str:
    return re.sub(r"[\s\-]", "", (raw or "")).upper()


def clean_plate(raw: str | None) -> str | None:
    plate = _squash(raw)
    return plate if _PLATE.match(plate) or _BH_PLATE.match(plate) else None


def valid_pan(raw: str | None) -> str | None:
    pan = _squash(raw)
    return pan if _PAN.match(pan) else None


def valid_ifsc(raw: str | None) -> str | None:
    ifsc = _squash(raw)
    return ifsc if _IFSC.match(ifsc) else None


def valid_pincode(raw: str | None) -> str | None:
    pin = _squash(raw)
    return pin if _PINCODE.match(pin) else None


def valid_account(raw: str | None, again: str | None) -> str | None:
    """Typed twice because a wrong digit pays a stranger and is not undone."""

    first, second = _squash(raw), _squash(again)
    return first if _ACCOUNT.match(first) and first == second else None


def valid_upi(raw: str | None) -> str | None:
    upi = (raw or "").strip().lower()
    return upi if _UPI.match(upi) else None


def is_adult(dob: date, today: date) -> bool:
    """18 on or before today. Born on 29 February: the birthday is 1 March."""

    try:
        eighteenth = dob.replace(year=dob.year + 18)
    except ValueError:
        eighteenth = date(dob.year + 18, 3, 1)
    return today >= eighteenth


def licence_valid(expiry: date, today: date) -> bool:
    return expiry > today
