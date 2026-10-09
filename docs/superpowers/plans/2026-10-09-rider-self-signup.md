# Rider Self Sign-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A rider signs up in the app, submits details, vehicle, documents and bank; an admin accepts or flags each item; flagged items go back with reasons; approval lets the rider work.

**Architecture:** The application is the rider account in a pending state (`riders.onboarding`). A new backend package `app/services/fleet/onboarding/` holds pure rules, phone codes, Supabase Storage and the state machine; routes live in `api/rider_signup.py` (public + rider) and `api/admin_rider_applications.py`. The admin panel gets an Applications tab and a review page; the rider app gets sign-up screens, a 4-step wizard and an application status screen, gated in navigation by `/rider/me.onboarding`.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic + unittest (backend); React 19 + Vite + vitest, no new deps (admin); React Native 0.87 + jest + `react-native-image-picker` (rider).

**Spec:** `docs/superpowers/specs/2026-10-09-rider-self-signup-design.md`

## Global Constraints

- **Change from the user (2026-10-09):** the sign-up code is a **static code for now, everywhere**, behind `RIDER_SIGNUP_OTP_MODE` = `static` (default) | `whatsapp`. Static accepts `otp_debug_code` (`123456`) and sends nothing. WhatsApp mode is built but used only when the user supplies the Meta template.
- Backend tests are `unittest`, built on `tests/fleet_harness.py` (`FleetDB`, `client_for`, `postgres_available`).
- Migration `0090_rider_onboarding`, `down_revision = "0089_own_fleet"`; RLS enabled on every new table **in the migration**; new enum values added in `op.get_context().autocommit_block()`.
- Every new model mirrored in `__table_args__`, because tests build from `create_all`.
- Existing and admin-created riders are `APPROVED` (column default), so nothing changes for them.
- Aadhaar: last 4 only. PAN, licence number, bank account: `services/secrets.py` `encrypt_secret`; responses carry last 4 only.
- `frontend-admin`: **no new dependencies**; hand-written CSS in the existing token system; both themes; phone width.
- Rider app: one new dep `react-native-image-picker`; every string in `i18n/strings/onboarding.ts` with en/hi/gu (`Translations<typeof en>`); utils use `translate` from `@/i18n/translate`, components `useI18n()`.
- Comments explain *why*, matching the repo's density.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01JFJkFSMqqK5aVpJZytBUDN`.

## Review Focus

1. A PENDING rider calling `/rider/status {online:true}`, `/rider/orders/{id}/claim` or appearing in `_candidates` - must be refused/excluded server-side (Task 5 tests).
2. A rider editing an ACCEPTED item after send-back, or anything while SUBMITTED - 409 (Task 4 tests).
3. An upload that is a renamed PDF/HTML with `.jpg`, or over 5 MB - 415/413 by magic bytes (Task 3 tests).
4. Two admins: approve after the other sent back - 409 `state_changed` (Task 4 test).
5. Sign-up with a phone that already belongs to a rider/staff - 409 and the app says "sign in instead" (Task 6 test, Task 10 screen).

---

## File Structure

Backend
- Modify `app/models/enums.py`: `RiderOnboarding`, `ApplicationStatus`, `ApplicationItemKind`, `ItemStatus`, `ApplicationAction`, `VehicleType.EV_SCOOTER`.
- Modify `app/models/rider.py`: `Rider.onboarding`.
- Create `app/models/rider_application.py`: `RiderApplication`, `RiderApplicationItem`, `RiderApplicationEvent`, `PhoneVerification`.
- Modify `app/models/__init__.py`: import the new models.
- Create `alembic/versions/0090_rider_onboarding.py`.
- Modify `app/config/settings.py`: `rider_signup_otp_mode`, `whatsapp_otp_template`, `supabase_url`, `supabase_service_key`, `rider_docs_bucket`.
- Create `app/services/fleet/onboarding/__init__.py`, `rules.py`, `phone.py`, `storage.py`, `applications.py`.
- Modify `app/services/fleet/riders.py` (`set_status` gate), `offers.py` (`_candidates`, `_why_not_free`, `open_orders`).
- Create `app/schemas/rider_onboarding.py`.
- Create `app/api/rider_signup.py`, `app/api/admin_rider_applications.py`; register in `app/api/__init__.py`.
- Modify `app/api/rider.py` `me_response` + `app/schemas/rider.py` `RiderMe`.
- Modify `app/services/fleet/notify.py`: `application_decided`.
- Tests: `tests/test_rider_onboarding_rules.py`, `tests/test_rider_onboarding.py`, `tests/test_rider_onboarding_api.py`.

Admin
- Modify `src/services/api.ts`, `src/types/index.ts` (types).
- Create `src/services/riderApplications.ts` (+ `.test.ts`): decision rules, labels.
- Create `src/components/riders/ApplicationsTab.tsx`, `src/pages/RiderApplicationPage.tsx`.
- Modify `src/pages/RidersPage.tsx` (tab), `src/routes.tsx` (route), `src/legacy.css` (styles, `rapp-` prefix).

Rider app
- `package.json`: `react-native-image-picker`; `android/app/src/main/AndroidManifest.xml`: CAMERA permission.
- Modify `src/services/http.ts` (`upload`), `src/services/rider.ts` (signup + application API), `src/types/api.ts`.
- Create `src/utils/onboarding.ts` (+ `.test.ts`): validators, required items, resume step.
- Create `src/i18n/strings/onboarding.ts`; register in `strings/index.ts`.
- Modify `src/store/SessionProvider.tsx` (`signInWithToken`).
- Create screens `src/screens/signup/{SignupPhoneScreen,SignupCodeScreen,SignupAccountScreen}.tsx`, `src/screens/onboarding/{OnboardingHomeScreen,ApplicationStepScreen,ApplicationReviewScreen}.tsx`, components `src/components/onboarding/{PhotoSlot,StepProgressBar,DateInput,StatusBanner,ItemRow}.tsx`.
- Modify `src/navigation/RootNavigator.tsx`, `src/navigation/types.ts`, `src/screens/auth/LoginScreen.tsx`.

---

### Task 1: Data model and migration

**Files:** Modify `app/models/enums.py`, `app/models/rider.py`, `app/models/__init__.py`; Create `app/models/rider_application.py`, `alembic/versions/0090_rider_onboarding.py`; Test `tests/test_rider_onboarding.py` (first test).

**Interfaces — Produces:**
- `RiderOnboarding(StrEnum)`: `PENDING`, `APPROVED`, `REJECTED`
- `ApplicationStatus`: `DRAFT`, `SUBMITTED`, `CHANGES_NEEDED`, `APPROVED`, `REJECTED`
- `ApplicationItemKind`: `PERSONAL`, `VEHICLE_DETAILS`, `BANK_DETAILS`, `SELFIE`, `RC`, `AADHAAR_FRONT`, `AADHAAR_BACK`, `PAN`, `LICENCE_FRONT`, `LICENCE_BACK`, `BANK_PROOF`
- `ItemStatus`: `MISSING`, `PENDING`, `ACCEPTED`, `NEEDS_CHANGE`
- `ApplicationAction`: `SUBMITTED`, `RESUBMITTED`, `ITEM_ACCEPTED`, `ITEM_FLAGGED`, `SENT_BACK`, `APPROVED`, `REJECTED`, `REOPENED`
- `VehicleType.EV_SCOOTER`
- Models `RiderApplication(rider_user_id PK)`, `RiderApplicationItem(id, rider_user_id, kind, status, reason, storage_path, content_type, size_bytes, reviewed_by_user_id, reviewed_at)` unique `(rider_user_id, kind)`, `RiderApplicationEvent`, `PhoneVerification`.

- [ ] **Step 1: Failing test** — `tests/test_rider_onboarding.py`:

```python
"""Rider self sign-up: the application, its items, and who may work.

The application IS the rider account in a pending state, so these tests
create riders the way sign-up does and check every state change, the edit
rules per state, and the server-side gates that keep a pending rider off
the road whatever the app shows.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available, reset_overrides  # noqa: E402

from app.models.enums import RiderOnboarding  # noqa: E402
from app.models.rider import Rider  # noqa: E402


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class OnboardingModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_onboarding_test")

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def test_a_rider_made_the_old_way_is_approved(self) -> None:
        with self.fdb.session() as db:
            user = self.fdb.make_rider(db)
            db.commit()
            self.assertEqual(db.get(Rider, user.id).onboarding, RiderOnboarding.APPROVED)
```

- [ ] **Step 2:** `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_rider_onboarding -v` → FAIL (`cannot import name 'RiderOnboarding'`).
- [ ] **Step 3: Implement** enums (StrEnum, as the file does), `Rider.onboarding = mapped_column(_enum(RiderOnboarding, "rider_onboarding"), nullable=False, default=RiderOnboarding.APPROVED, server_default="APPROVED")`, and `app/models/rider_application.py`:

```python
class RiderApplication(TimestampMixin, Base):
    __tablename__ = "rider_applications"
    rider_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[ApplicationStatus] = mapped_column(_enum(ApplicationStatus, "rider_application_status"), nullable=False, default=ApplicationStatus.DRAFT, server_default="DRAFT")
    full_name: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    city: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    address_line: Mapped[str] = mapped_column(String(240), nullable=False, default="", server_default="")
    pincode: Mapped[str] = mapped_column(String(6), nullable=False, default="", server_default="")
    emergency_name: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    emergency_phone: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    vehicle_type: Mapped[VehicleType | None] = mapped_column(_enum(VehicleType, "rider_vehicle_type"), nullable=True)
    vehicle_number: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    aadhaar_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    pan_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    pan_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    licence_number_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    licence_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    licence_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    bank_holder: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    bank_account_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    bank_account_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    ifsc: Mapped[str] = mapped_column(String(11), nullable=False, default="", server_default="")
    upi_id: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    final_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    __table_args__ = (Index("ix_rider_applications_status", "status", "submitted_at"),)
```

`RiderApplicationItem` (uuid pk `id`, FK `rider_user_id` → `rider_applications.rider_user_id` CASCADE, `kind` enum `rider_application_item_kind`, `status` enum `rider_application_item_status` default `MISSING`, `reason` Text, `storage_path` String(255) null, `content_type` String(40), `size_bytes` Integer, `reviewed_by_user_id`, `reviewed_at`, timestamps; `UniqueConstraint("rider_user_id", "kind", name="uq_rider_application_items_kind")`). `RiderApplicationEvent` (uuid pk, `rider_user_id` FK CASCADE, `at` DateTime default now, `actor_user_id` FK users SET NULL, `action` enum `rider_application_action`, `item_kind` nullable same enum, `note` Text; index on `(rider_user_id, at)`). `PhoneVerification` (uuid pk, `phone` String(20), `purpose` String(20), `code_hash` String(64), `expires_at`, `attempts` Integer default 0, `verified_at` null, `created_at`; index `(phone, purpose, created_at)`).

Migration: in `autocommit_block()` `ALTER TYPE rider_vehicle_type ADD VALUE IF NOT EXISTS 'EV_SCOOTER'`; create the five enum types; `riders.onboarding` with `server_default='APPROVED'`; the four tables; `ENABLE ROW LEVEL SECURITY` on each; downgrade drops tables, column and types (the enum value stays: Postgres cannot drop one, say so in a comment).

- [ ] **Step 4:** rerun → PASS. Also `./.venv/Scripts/python.exe -m compileall -q app alembic`.
- [ ] **Step 5: Commit** `feat(fleet): rider onboarding data model and migration 0090`.

### Task 2: Pure rules (validation and required items)

**Files:** Create `app/services/fleet/onboarding/__init__.py` (empty docstring), `rules.py`; Test `tests/test_rider_onboarding_rules.py` (plain `unittest.TestCase`, no DB).

**Interfaces — Produces:**
- `required_items(vehicle: VehicleType | None) -> list[ApplicationItemKind]`
- `PHOTO_KINDS: frozenset[ApplicationItemKind]`, `SECTION_OF: dict[ApplicationItemKind, str]` (`SELFIE→personal`, `RC→vehicle`, `AADHAAR_*`/`PAN`/`LICENCE_*→documents`, `BANK_PROOF→bank`, `PERSONAL→personal`, `VEHICLE_DETAILS→vehicle`, `BANK_DETAILS→bank`)
- `clean_plate(raw) -> str | None`, `valid_pan(raw) -> str | None`, `valid_ifsc(raw) -> str | None`, `valid_account(a, b) -> str | None`, `valid_pincode(raw) -> str | None`, `is_adult(dob: date, today: date) -> bool`, `licence_valid(expiry: date, today: date) -> bool`, `valid_upi(raw) -> str | None`, `needs_licence(vehicle) -> bool`, `needs_rc(vehicle) -> bool`.

- [ ] **Step 1: Failing tests:**

```python
class RequiredItems(unittest.TestCase):
    def test_a_motorbike_needs_licence_and_rc(self):
        items = required_items(VehicleType.BIKE)
        for kind in ("RC", "LICENCE_FRONT", "LICENCE_BACK", "VEHICLE_DETAILS"):
            self.assertIn(ApplicationItemKind(kind), items)

    def test_a_bicycle_needs_neither(self):
        items = required_items(VehicleType.CYCLE)
        for kind in ("RC", "LICENCE_FRONT", "LICENCE_BACK", "VEHICLE_DETAILS"):
            self.assertNotIn(ApplicationItemKind(kind), items)

    def test_a_low_speed_ev_needs_neither(self):
        self.assertNotIn(ApplicationItemKind.RC, required_items(VehicleType.EV_SCOOTER))
        self.assertNotIn(ApplicationItemKind.LICENCE_FRONT, required_items(VehicleType.EV_SCOOTER))

    def test_everyone_needs_identity_and_bank(self):
        for vehicle in VehicleType:
            items = required_items(vehicle)
            for kind in ("PERSONAL", "SELFIE", "AADHAAR_FRONT", "AADHAAR_BACK", "PAN", "BANK_DETAILS"):
                self.assertIn(ApplicationItemKind(kind), items)

class Validators(unittest.TestCase):
    def test_plates_are_normalised(self):
        self.assertEqual(clean_plate(" gj 05 ab 1234 "), "GJ05AB1234")
        self.assertIsNone(clean_plate("hello"))

    def test_pan_ifsc_pincode(self):
        self.assertEqual(valid_pan("abcde1234f"), "ABCDE1234F")
        self.assertIsNone(valid_pan("ABCDE12345"))
        self.assertEqual(valid_ifsc("sbin0001234"), "SBIN0001234")
        self.assertIsNone(valid_ifsc("SBIN1001234"))
        self.assertEqual(valid_pincode("395009"), "395009")
        self.assertIsNone(valid_pincode("095009"))

    def test_account_numbers_must_match(self):
        self.assertEqual(valid_account("123456789012", "123456789012"), "123456789012")
        self.assertIsNone(valid_account("123456789012", "123456789013"))
        self.assertIsNone(valid_account("12345", "12345"))

    def test_eighteen_on_the_day(self):
        today = date(2026, 10, 9)
        self.assertTrue(is_adult(date(2008, 10, 9), today))
        self.assertFalse(is_adult(date(2008, 10, 10), today))

    def test_an_expired_licence(self):
        self.assertFalse(licence_valid(date(2026, 10, 8), date(2026, 10, 9)))
        self.assertTrue(licence_valid(date(2026, 10, 10), date(2026, 10, 9)))

    def test_upi(self):
        self.assertEqual(valid_upi("Ravi.k@okaxis"), "ravi.k@okaxis")
        self.assertIsNone(valid_upi("ravi"))
```

- [ ] **Step 2:** run → FAIL (module missing).
- [ ] **Step 3: Implement** with regexes: plate `^[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}$` (after removing spaces/hyphens, upper) and the BH series `^\d{2}BH\d{4}[A-Z]{1,2}$`; PAN `^[A-Z]{5}\d{4}[A-Z]$`; IFSC `^[A-Z]{4}0[A-Z0-9]{6}$`; pincode `^[1-9]\d{5}$`; account `^\d{9,18}$` and equal; UPI `^[a-z0-9.\-_]{2,256}@[a-z]{2,64}$` (lowercased). `is_adult`: `today >= dob.replace(year=dob.year + 18)` (29 Feb → 1 Mar). `required_items`: `PERSONAL, SELFIE, AADHAAR_FRONT, AADHAAR_BACK, PAN, BANK_DETAILS` always; `+ VEHICLE_DETAILS, RC` when `needs_rc` (BIKE, SCOOTER); `+ LICENCE_FRONT, LICENCE_BACK` when `needs_licence` (BIKE, SCOOTER). `BANK_PROOF` is required only when an account number is given, so it is added by `applications.required_for(app)` (Task 4), not here.
- [ ] **Step 4:** PASS. **Step 5:** commit `feat(fleet): onboarding validation rules`.

### Task 3: Phone codes and document storage

**Files:** Create `onboarding/phone.py`, `onboarding/storage.py`; Modify `app/config/settings.py`; Test in `tests/test_rider_onboarding.py` (class `PhoneCodeTests`, DB) and `tests/test_rider_onboarding_rules.py` (class `ImageChecks`, no DB).

**Interfaces — Produces:**
- `phone.request_code(db, phone: str, now=None) -> RequestResult(sent: bool, debug_code: str | None, retry_after: int)`; raises `HTTPException(429, "code_too_soon")`, `503 "no_sender"`.
- `phone.verify_code(db, phone, code, now=None) -> None`; raises `400 "code_wrong"` (attempts++), `400 "code_expired"`, `429 "code_locked"` (5 wrong).
- `storage.sniff_image(data: bytes) -> str | None` (`image/jpeg`, `image/png`, `image/webp`).
- `storage.upload(path: str, data: bytes, content_type: str) -> None`, `storage.delete(path) -> None`, `storage.signed_url(path, seconds=300) -> str`, `storage.configured() -> bool`; raise `StorageUnavailable`.

Settings (with why-comments): `rider_signup_otp_mode: str = "static"`, `whatsapp_otp_template: str = ""`, `supabase_url: str = ""`, `supabase_service_key: str = ""`, `rider_docs_bucket: str = "rider-documents"`, `rider_doc_max_bytes: int = 5_000_000`.

- [ ] **Step 1: Failing tests:**

```python
class ImageChecks(unittest.TestCase):
    def test_types_come_from_the_bytes_not_the_name(self):
        self.assertEqual(sniff_image(b"\xff\xd8\xff\xe0rest"), "image/jpeg")
        self.assertEqual(sniff_image(b"\x89PNG\r\n\x1a\nrest"), "image/png")
        self.assertEqual(sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertIsNone(sniff_image(b"%PDF-1.7"))
        self.assertIsNone(sniff_image(b"<html>"))
```

```python
@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class PhoneCodeTests(unittest.TestCase):
    # setUpClass/tearDownClass as OnboardingModelTests, db "restaurant_rag_onboarding_phone_test"
    def test_static_mode_accepts_the_fixed_code_and_sends_nothing(self):
        with self.fdb.session() as db:
            result = phone.request_code(db, "+919812300001")
            self.assertFalse(result.sent)
            phone.verify_code(db, "+919812300001", get_settings().otp_debug_code)

    def test_a_second_request_inside_a_minute_is_refused(self):
        with self.fdb.session() as db:
            phone.request_code(db, "+919812300002")
            with self.assertRaises(HTTPException) as caught:
                phone.request_code(db, "+919812300002")
            self.assertEqual(caught.exception.detail, "code_too_soon")

    def test_five_wrong_codes_lock_it(self):
        with self.fdb.session() as db:
            phone.request_code(db, "+919812300003")
            for _ in range(5):
                with self.assertRaises(HTTPException):
                    phone.verify_code(db, "+919812300003", "000000")
            with self.assertRaises(HTTPException) as caught:
                phone.verify_code(db, "+919812300003", get_settings().otp_debug_code)
            self.assertEqual(caught.exception.detail, "code_locked")

    def test_an_expired_code(self):
        with self.fdb.session() as db:
            now = datetime.now(UTC)
            phone.request_code(db, "+919812300004", now=now)
            with self.assertRaises(HTTPException) as caught:
                phone.verify_code(db, "+919812300004", get_settings().otp_debug_code, now=now + timedelta(minutes=11))
            self.assertEqual(caught.exception.detail, "code_expired")
```

- [ ] **Step 2:** FAIL. **Step 3: Implement.** `phone.py`: one live row per phone+purpose (newest); static mode stores the HMAC of `otp_debug_code` so verification is one path for both modes; whatsapp mode generates `f"{secrets.randbelow(10**6):06d}"`, sends via `services/whatsapp.send_template(phone, template, [code])` (add a small `send_template` beside `send_text` there), and `503 no_sender` if the template setting is empty. HMAC key: `settings.jwt_secret_key`. Limits: 60 s between requests, 5 per hour per phone (count rows in the last hour). `storage.py`: `httpx.Client(timeout=15)`, headers `Authorization: Bearer {key}`, `apikey: {key}`; upload `POST {url}/storage/v1/object/{bucket}/{path}` with `x-upsert: false`; on a 404 "Bucket not found" create it once with `POST {url}/storage/v1/bucket` `{"id": bucket, "name": bucket, "public": false}` and retry; signed URL `POST {url}/storage/v1/object/sign/{bucket}/{path}` `{"expiresIn": seconds}` → `{url}/storage/v1{signedURL}`; delete `DELETE {url}/storage/v1/object/{bucket}` `{"prefixes": [path]}`.
- [ ] **Step 4:** PASS (+ a storage test with `httpx.MockTransport` asserting the bucket is created on first 404 and the upload retried). **Step 5:** commit `feat(fleet): sign-up codes (static for now) and private document storage`.

### Task 4: The application state machine

**Files:** Create `onboarding/applications.py`; Test `tests/test_rider_onboarding.py` (class `ApplicationFlowTests`, storage patched).

**Interfaces — Consumes:** Task 1 models, Task 2 rules, Task 3 storage.
**Produces:**
- `start(db, user) -> RiderApplication` (creates DRAFT + MISSING rows for every kind)
- `required_for(app) -> list[ApplicationItemKind]` (`rules.required_items(app.vehicle_type)` + `BANK_PROOF` if `bank_account_last4`)
- `save_section(db, user, section: Literal["personal","vehicle","documents","bank"], data: dict, today: date | None = None) -> RiderApplication`
- `save_photo(db, user, kind, data: bytes) -> RiderApplicationItem`
- `submit(db, user) -> RiderApplication`
- `review_item(db, admin, rider_id, kind, accept: bool, reason: str = "")`
- `send_back(db, admin, rider_id)`, `approve(db, admin, rider_id)`, `reject(db, admin, rider_id, reason)`, `reopen(db, admin, rider_id)`
- `missing_items(app) -> list[ApplicationItemKind]`, `editable(app, kind) -> bool`

Rules: every write locks `rider_applications` row `with_for_update()`; edits allowed when `DRAFT`, or `CHANGES_NEEDED` and that item `NEEDS_CHANGE`, else `409 "not_editable"`; saving a section sets its section item (and for photos the photo item) to `PENDING` when the app is `CHANGES_NEEDED`, else stays `PENDING` after first save in DRAFT; `submit` from DRAFT requires `missing_items == []` (`422 {"missing": [...]}`) → SUBMITTED, event SUBMITTED; from CHANGES_NEEDED requires no `NEEDS_CHANGE` among required → SUBMITTED, event RESUBMITTED; `send_back` requires SUBMITTED and ≥1 `NEEDS_CHANGE` → CHANGES_NEEDED; `approve` requires SUBMITTED and every required `ACCEPTED` → APPROVED, `riders.onboarding = APPROVED`, `users.full_name = app.full_name`, `riders.vehicle_type/number/city` copied; `reject` from SUBMITTED/CHANGES_NEEDED → REJECTED, `riders.onboarding = REJECTED`, `final_reason`; `reopen` from REJECTED → CHANGES_NEEDED, onboarding PENDING. Wrong state → `409 "state_changed"`. Every transition writes `RiderApplicationEvent` and calls `notify.application_decided` after commit for send_back/approve/reject.

- [ ] **Step 1: Failing tests** (each a method; helper `_complete(db, user)` fills every section and photo with valid data, storage patched with `mock.patch("app.services.fleet.onboarding.storage.upload")`):

```python
def test_submit_needs_every_required_item(self): ...      # 422 with missing kinds listed
def test_a_complete_draft_submits(self): ...              # status SUBMITTED, event SUBMITTED
def test_nothing_is_editable_while_under_review(self): ... # save_section → 409 not_editable
def test_send_back_needs_a_flag(self): ...                 # 409 when nothing flagged
def test_only_flagged_items_reopen(self): ...             # after flag PAN + send back: PAN editable, PERSONAL not (409)
def test_resubmit_after_fixing(self): ...                  # fix PAN → PENDING; submit → SUBMITTED, event RESUBMITTED
def test_approve_needs_everything_accepted(self): ...      # 409 until all accepted; then APPROVED, rider APPROVED, vehicle copied
def test_two_admins(self): ...                             # send_back then approve → 409 state_changed
def test_reject_is_final_until_reopened(self): ...          # submit after reject → 409; reopen → CHANGES_NEEDED
def test_secrets_are_stored_encrypted(self): ...            # pan_encrypted != PAN, pan_last4 == last 4
def test_a_bicycle_needs_no_rc(self): ...                   # complete without RC/licence → submits
def test_a_too_young_rider(self): ...                        # personal dob 17y → 422 "too_young"
```

- [ ] **Step 2:** FAIL. **Step 3:** implement as specified (validation errors as `HTTPException(422, {"field": name, "error": code})`, codes: `too_young`, `bad_plate`, `bad_pan`, `bad_ifsc`, `account_mismatch`, `bad_pincode`, `licence_expired`, `bad_upi`, `bank_required` (neither account nor UPI), `bad_aadhaar_last4`, `no_secrets` 503 when `secrets_available()` is false; photo: `413 "too_large"`, `415 "not_an_image"`). Old object deleted after commit when a photo is replaced.
- [ ] **Step 4:** PASS. **Step 5:** commit `feat(fleet): rider application state machine`.

### Task 5: Pending riders cannot work

**Files:** Modify `app/services/fleet/riders.py` (`set_status`), `offers.py` (`_candidates`, `_why_not_free`, `open_orders`); Test `tests/test_rider_onboarding.py` (class `WorkGateTests`).

- [ ] **Step 1: Failing tests:**

```python
def test_a_pending_rider_cannot_go_online(self):
    # rider row onboarding=PENDING → riders.set_status(db, user, True) raises 403 "rider_not_approved"
def test_a_pending_rider_is_never_offered(self):
    # ONLINE + fresh location but PENDING → offers._candidates(...) excludes them
def test_a_pending_rider_cannot_claim(self):
    # offers.claim → 409 "rider_not_approved"
def test_a_pending_rider_sees_no_board(self):
    # offers.open_orders → []
```

- [ ] **Step 2:** FAIL. **Step 3:** `set_status`: if `online and rider.onboarding != RiderOnboarding.APPROVED: raise HTTPException(403, "rider_not_approved")`. `_candidates`: add `Rider.onboarding == RiderOnboarding.APPROVED` to the WHERE. `_why_not_free`: return `"rider_not_approved"` first when not approved. `open_orders`: return `[]` when not approved. Comments: why each gate exists (the app hides, the server enforces).
- [ ] **Step 4:** PASS, plus `tests.test_fleet_*` still green. **Step 5:** commit `feat(fleet): only approved riders go online, get offers or claim`.

### Task 6: Routes and schemas

**Files:** Create `app/schemas/rider_onboarding.py`, `app/api/rider_signup.py`, `app/api/admin_rider_applications.py`; Modify `app/api/__init__.py`, `app/api/rider.py` (`me_response`), `app/schemas/rider.py` (`RiderMe.onboarding: RiderOnboarding`, `RiderMe.application_status: ApplicationStatus | None`); Test `tests/test_rider_onboarding_api.py`.

Routes (exact):
- `POST /rider/signup/code` body `{phone_number}` → `{sent, retry_after, debug_code}` (debug_code only in static mode on a local environment). `per_ip("rider-signup-code", limit=10, window_seconds=3600)`.
- `POST /rider/signup` body `{phone_number, code, password (min 8), full_name (2-120)}` → `AuthResponse` (201). 409 `phone_in_use` if any non-customer user has the phone. Creates `users` (RIDER, active), `riders` (`onboarding=PENDING`, vehicle `BIKE` placeholder, OFFLINE), `start()`. `per_ip("rider-signup", limit=10, window_seconds=3600)`.
- `GET /rider/application` → `ApplicationView {status, vehicle_type, sections: {personal, vehicle, documents, bank} (with last-4 fields only), items: [{kind, status, reason, has_photo}], required: [kinds], missing: [kinds], final_reason, submitted_at}`.
- `PUT /rider/application/{section}` → `ApplicationView`.
- `POST /rider/application/items/{kind}` multipart `file` → `ApplicationView` (read at most `rider_doc_max_bytes + 1`).
- `POST /rider/application/submit` → `ApplicationView`.
- Admin (`require_admin`): `GET /admin/rider-applications?status=&q=&city=` → `[ApplicationSummary {rider_user_id, full_name, phone_number, city, vehicle_type, status, submitted_at, flagged}]` ordered by `submitted_at` asc (nulls last); `GET /admin/rider-applications/{id}` → `AdminApplicationView` (ApplicationView + phone, `photos: {kind: signed_url}`, `events`); `POST .../items/{kind}/accept`, `POST .../items/{kind}/flag {reason}`, `POST .../send-back`, `POST .../approve`, `POST .../reject {reason}`, `POST .../reopen` → `AdminApplicationView`.

- [ ] **Step 1: Failing API tests** (client via `client_for(fdb, None)` for public, `client_for(fdb, user)` otherwise; storage patched):

```python
def test_sign_up_end_to_end(self):
    # code → signup → token; GET /rider/me shows onboarding PENDING, application_status DRAFT
def test_sign_up_with_a_taken_phone(self):         # 409 phone_in_use
def test_a_wrong_code_does_not_create_an_account(self)
def test_responses_never_carry_full_numbers(self):  # PAN/account absent from JSON text
def test_upload_rejects_a_renamed_pdf(self):        # 415
def test_upload_rejects_a_huge_file(self):          # 413
def test_admin_review_flow(self):                    # flag → send-back → rider fixes → resubmit → accept all → approve; /rider/status online now 200
def test_a_rider_cannot_read_the_admin_routes(self): # 403
```

- [ ] **Step 2:** FAIL. **Step 3:** implement; register routers. **Step 4:** PASS + `python -m compileall -q app`. **Step 5:** commit `feat(fleet): sign-up and application routes, admin review routes`.

### Task 7: Notifications

**Files:** Modify `app/services/fleet/notify.py`, `rider/src/services/push.ts` is Task 11. Test in `tests/test_rider_onboarding.py` (`ApplicationFlowTests.test_decisions_are_announced`).

- [ ] Steps: failing test asserting `notify.application_decided` called with `(rider_id, "APPROVED"|"CHANGES_NEEDED"|"REJECTED")` and `notify.riders_changed(force=True)` on submit/resubmit/decisions; implement `application_decided` as a data-only FCM `{type: "application", status}` through the existing rider push sender, swallowing errors like the other hints; PASS; commit `feat(fleet): tell the rider when their application is decided`.

### Task 8: Admin panel — data layer and rules

**Files:** Modify `frontend-admin/src/types/index.ts`, `src/services/api.ts`; Create `src/services/riderApplications.ts`, `src/services/riderApplications.test.ts`.

**Produces:** types `RiderApplicationSummary`, `RiderApplicationDetail`, `ApplicationItem`, `ApplicationStatus`, `ItemKind`; api methods `listRiderApplications(token, {status, q, city})`, `getRiderApplication(token, id)`, `acceptApplicationItem`, `flagApplicationItem(token, id, kind, reason)`, `sendBackApplication`, `approveApplication`, `rejectApplication(token, id, reason)`, `reopenApplication`; rules `decisionState(detail) -> {canApprove: boolean, approveReason: string|null, canSendBack: boolean, sendBackReason: string|null}`, `ITEM_LABELS: Record<ItemKind,string>`, `REASONS: string[]`, `waitingLabel(submittedAt, now) -> string`, `photoPairs(items) -> [front, back][]`.

- [ ] Failing vitest: approve disabled with "2 items not accepted yet" while any required item is not ACCEPTED; send back disabled with "Flag at least one item" when none flagged; `waitingLabel` "3 h", "2 days"; implement; PASS (`npm run test -- riderApplications`); commit.

### Task 9: Admin panel — Applications tab and review page

**Files:** Create `src/components/riders/ApplicationsTab.tsx`, `src/pages/RiderApplicationPage.tsx`; Modify `src/pages/RidersPage.tsx` (tab first with badge when count>0), `src/routes.tsx` (`/riders/applications/:id`, ADMIN_ONLY, no nav entry), `src/legacy.css` (`rapp-` classes using existing tokens only).

UI (per spec): queue = `PageIntro`-less tab body with segmented status filter, search, city select, `ResponsiveTable` rows (name+phone, vehicle, city, `StatusPill`, waiting, flagged count) → row click navigates. Review page = header (back, name, phone, status pill), two-column grid (`grid-template-columns: minmax(0,1fr) minmax(0,1.3fr)`, single column under 900px): left cards Details / Vehicle / Bank (last 4) / History; right document cards with image (click → zoom modal with rotate buttons, CSS `transform: rotate()`), front/back side by side, per-card Accept / Needs change (reason chips + text in a small `Modal`); sticky decision bar with Approve / Send back / Reject (ConfirmDialog with reason). Live refresh with `useRidersChanged`.

- [ ] `npm run build` and `npm run test` green; manual check in browser both themes and 390 px; commit `feat(admin): rider applications queue and review`.

### Task 10: Rider app — rules, API and sign-up

**Files:** `rider/package.json` (+ `react-native-image-picker`), AndroidManifest CAMERA; Create `src/utils/onboarding.ts` + `.test.ts`, `src/i18n/strings/onboarding.ts` (register), `src/screens/signup/*.tsx`; Modify `src/services/http.ts` (`upload(path, {uri, type, name}, token)` with FormData, same error mapping), `src/services/rider.ts`, `src/types/api.ts`, `src/store/SessionProvider.tsx` (`signInWithToken(result)` shared with `signIn`), `src/screens/auth/LoginScreen.tsx` ("New here? Become a rider").

- [ ] Failing jest for `utils/onboarding.ts`: the same validators as Task 2 (same cases), `requiredItems(vehicle)` mirror, `firstIncompleteStep(view) -> 'personal'|'vehicle'|'documents'|'bank'|'review'`, `stepsFor(vehicle)` (no vehicle step for CYCLE/EV_SCOOTER beyond the type picker). Implement; PASS.
- [ ] Screens: phone (10 digits, +91 prefix chip) → code (6 boxes, paste/auto-advance, resend after 60 s, shows "Test code 123456" when the API returns `debug_code`) → account (name, password + confirm) → `signInWithToken`. Errors from the API mapped to translated sentences (`phone_in_use` → "This number already has an account. Sign in instead." with a Sign in button).
- [ ] `npx tsc --noEmit`, `npx jest`, `npx eslint src` green; commit `feat(rider): sign up with a phone code`.

### Task 11: Rider app — wizard and status screen

**Files:** Create `src/screens/onboarding/{OnboardingHomeScreen,ApplicationStepScreen,ApplicationReviewScreen}.tsx`, `src/components/onboarding/{PhotoSlot,StepProgressBar,DateInput,StatusBanner,ItemRow}.tsx`; Modify `src/navigation/RootNavigator.tsx` (signed-in: `me.onboarding !== 'APPROVED'` → onboarding stack; ShiftKeeper/RiderProvider polling only when approved), `src/navigation/types.ts`, `src/services/push.ts` (handle `type: application` → refresh `me` and application).

UI (per spec): `StepProgressBar` (4 segments, current label "Step 2 of 4 · Vehicle"); `ApplicationStepScreen` renders one section form (TextField, chips for vehicle type, `DateInput` DD/MM/YYYY), photo slots via `PhotoSlot` (frame guide overlay, `launchCamera` / `launchImageLibrary` with `{mediaType:'photo', maxWidth:1600, maxHeight:1600, quality:0.8}`; selfie uses `cameraType:'front'` and camera only; shows upload progress, Retry on failure), sticky Next/Back footer; validation inline in red with translated messages; disabled/flag state from the server (`editable`). `ApplicationReviewScreen` = section cards with Edit + Submit. `OnboardingHomeScreen` = `StatusBanner` (tone per status, "usually within 24 hours"), progress, `ItemRow` list (flagged in red with reason + Fix), Resubmit, Call support, Sign out; pull to refresh.

- [ ] jest still green (pure helpers already tested in Task 10); tsc, eslint green; emulator walkthrough: sign up → fill → submit → (admin flags PAN) → fix → resubmit → (admin approves) → app switches to Home and Go online works. Light + dark, Hindi spot check. Commit `feat(rider): application wizard and status`.

### Task 12: Docs, final verification, review

- [ ] CLAUDE.md fleet bullet (sign-up, states, gates, static code setting, Supabase settings, traps found); worklog entry; `docs/superpowers/specs/...` unchanged.
- [ ] Full suites: backend `tests.test_rider_onboarding*` + `tests.test_fleet_*`, compileall; admin `npm run test` + `npm run build`; rider jest/tsc/eslint.
- [ ] Whole-branch review by a fresh reviewer; fix Critical/Important with tests.
- [ ] Commit `docs: rider self sign-up`.
