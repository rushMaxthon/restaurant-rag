# Rider self sign-up and verification

Date: 2026-10-09. Status: approved in conversation, awaiting spec review.

## Goal

A rider can sign up in the rider app on their own, give their details,
vehicle, documents and bank account, and submit. The application appears in
the admin panel, where the platform team accepts or flags each item. Flagged
items go back to the rider with a reason; the rider fixes only those and
resubmits. An approved rider works exactly like a rider created by an admin
today. The experience should feel like Swiggy's onboarding: guided, clear,
and pleasant on a cheap Android phone.

Success: a stranger with a phone and their documents can go from "Become a
rider" to taking an order with no help except the admin's review, and the
admin can review an application in under two minutes.

## Decisions taken

| Question | Decision |
|---|---|
| Shape | **The application is the rider account, in a pending state.** One identity from sign-up to work; no second login system. |
| Storage for document photos | **Supabase Storage**, one private bucket, server key on the backend only. |
| Phone check at sign-up | **WhatsApp OTP** through the existing Business number and an approved AUTHENTICATION template; locally the existing debug code. |
| Bank details | **Collected at sign-up**, encrypted, with a cheque/passbook photo. |
| Admin-created riders | Unchanged, and count as approved. |

## States

`rider_applications.status`:

```
DRAFT --submit--> SUBMITTED --approve--> APPROVED
                     |  ^
        send back    v  | resubmit
                  CHANGES_NEEDED
SUBMITTED / CHANGES_NEEDED --reject--> REJECTED   (final)
```

- DRAFT: being filled in; every step saves on its own.
- SUBMITTED: in the admin queue. The rider cannot edit.
- CHANGES_NEEDED: at least one item is flagged with a reason. The rider can
  change flagged items only; everything already accepted stays locked.
- APPROVED: the rider may work. Terminal for the application.
- REJECTED: final, with a reason. No resubmission. (An admin can reopen it to
  CHANGES_NEEDED if it was a mistake.)

A rider row (`riders`) gains `onboarding` = `PENDING` | `APPROVED` |
`REJECTED`. Every existing rider and every admin-created rider is `APPROVED`
(the migration backfills; `create_rider` sets it). Only `APPROVED` riders may
work, enforced on the server:

- `set_status(ONLINE)` refuses with `rider_not_approved`.
- `offers.advance` never picks a rider who is not approved.
- `offers.claim` (the Orders board) refuses with `rider_not_approved`.
- `open_orders` returns an empty list for them.
- Location pings are accepted but unused (harmless).

## What is collected

Four steps, each its own screen and its own save.

1. **About you**: full name (as on Aadhaar), date of birth (18 or older on
   the day of submission), city (from the platform's fleet cities, free text
   fallback), current address (one line plus PIN code), emergency contact
   name and phone, and a **selfie** taken with the front camera (no gallery
   for the selfie).
2. **Vehicle**: type (`BIKE`, `SCOOTER`, `EV_SCOOTER`, `CYCLE`). For anything
   but `CYCLE`: registration number (Indian plate format, normalised to
   upper case without spaces) and an **RC photo**. `EV_SCOOTER` means a
   low-speed e-scooter that needs no licence or RC; a registered electric
   scooter is `SCOOTER`.
3. **Documents**:
   - Aadhaar: **last 4 digits only** plus front and back photos. The full
     number is never asked for or stored.
   - PAN: number (validated `AAAAA9999A`), encrypted, plus a photo.
   - Driving licence (BIKE and SCOOTER only): number, expiry date (must be in
     the future), front and back photos.
4. **Bank**: account holder name, account number (typed twice, must match,
   9-18 digits), IFSC (validated `AAAA0XXXXXX`), or a UPI ID instead of the
   account (one of the two is required), plus a **cheque or passbook photo**
   when an account number is given.

Dates are typed as DD/MM/YYYY in three boxes; no date picker library.

## Data model

Migration `0090_rider_onboarding` (RLS enabled on every new table, in the
migration itself):

- `riders.onboarding` enum `rider_onboarding` (`PENDING`, `APPROVED`,
  `REJECTED`), NOT NULL, default `APPROVED` so the backfill is the default.
- `VehicleType` gains `EV_SCOOTER`.
- `rider_applications` (1:1 with the rider, PK `rider_user_id`):
  status, full_name, date_of_birth, city, address_line, pincode,
  emergency_name, emergency_phone, vehicle_type, vehicle_number,
  aadhaar_last4, pan_encrypted, pan_last4, licence_number_encrypted,
  licence_last4, licence_expiry, bank_holder, bank_account_encrypted,
  bank_account_last4, ifsc, upi_id, submitted_at, decided_at,
  decided_by_user_id, final_reason, created_at, updated_at.
- `rider_application_items` (one row per reviewable item):
  `(rider_user_id, kind)` unique, where kind is `SELFIE`, `RC`,
  `AADHAAR_FRONT`, `AADHAAR_BACK`, `PAN`, `LICENCE_FRONT`, `LICENCE_BACK`,
  `BANK_PROOF`, plus the non-photo sections `PERSONAL`, `VEHICLE_DETAILS`,
  `BANK_DETAILS`. Columns: storage_path (null for sections), content_type,
  size_bytes, status (`PENDING`, `ACCEPTED`, `NEEDS_CHANGE`), reason,
  reviewed_by_user_id, reviewed_at, updated_at.
- `rider_application_events`: id, rider_user_id, at, actor_user_id, action
  (`SUBMITTED`, `ITEM_ACCEPTED`, `ITEM_FLAGGED`, `SENT_BACK`, `RESUBMITTED`,
  `APPROVED`, `REJECTED`, `REOPENED`), item kind, note. The audit trail.
- `phone_verifications`: id, phone (canonical), purpose (`RIDER_SIGNUP`),
  code_hash (HMAC), expires_at (10 min), attempts (max 5), verified_at,
  created_at. One live row per phone and purpose.

Which items are required follows the vehicle type, in one function
(`required_items(vehicle_type)`) that the API, the admin screen and the app
all read through the API, so they cannot disagree.

## Backend

New module `app/services/fleet/onboarding/`:

- `storage.py`: Supabase Storage over its REST API with `httpx` (no new
  dependency). Settings `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
  `RIDER_DOCS_BUCKET` (default `rider-documents`). Upload, delete, and a
  signed URL valid 300 s. Paths are
  `riders/{user_id}/{kind}-{uuid}.{ext}`: a re-upload is a new object, the
  old one deleted after commit. Without the settings, uploads answer 503
  `storage_not_configured` and the admin screen says so; nothing falls back
  to local disk (Render's disk is ephemeral).
- `phone.py`: request and verify codes. Code: 6 random digits, HMAC'd with the
  JWT secret before storage. Rate limits: 1 request per phone per 60 s, 5 per
  hour, plus the existing per-IP limiter. Sender: WhatsApp template
  `rider_signup_code` (name in settings, `WHATSAPP_OTP_TEMPLATE`); on a local
  environment the code `otp_debug_code` is accepted and nothing is sent.
  Anywhere else with no template configured, it answers 503 `no_sender`.
- `applications.py`: the state machine, `required_items`, validation,
  `submit`, `review_item`, `send_back`, `approve`, `reject`, `reopen`. Every
  transition locks the application row, writes an event, and commits once.
- Notifications: approval and send-back push the rider (the existing rider
  FCM path, data-only) and send a `riders_changed` hint to admins.

Routes:

- Public (rate-limited): `POST /rider/signup/code` {phone},
  `POST /rider/signup` {phone, code, password, full_name} creates the user
  (role RIDER, inactive for work, `riders.onboarding = PENDING`) and a DRAFT
  application, and returns a normal access token, so the rider is signed in.
  A phone that already belongs to any staff account is refused (409).
- Rider (`require_rider`, allowed while PENDING):
  `GET /rider/application` (application, items with status and reason,
  required items), `PUT /rider/application/{section}` (personal, vehicle,
  documents, bank), `POST /rider/application/items/{kind}` (multipart photo,
  JPEG/PNG/WebP, max 5 MB, magic bytes checked, not just the extension),
  `POST /rider/application/submit`.
- Admin (`require_admin`): `GET /admin/rider-applications?status=&q=&city=`,
  `GET /admin/rider-applications/{id}` (with signed photo URLs),
  `POST .../items/{kind}/accept`, `POST .../items/{kind}/flag` {reason},
  `POST .../send-back`, `POST .../approve`, `POST .../reject` {reason},
  `POST .../reopen`.
- `/rider/me` gains `onboarding` and `application_status`.

Edit rules on the server, not only in the app: a rider may change an item or
section only while DRAFT, or while CHANGES_NEEDED and that item is
`NEEDS_CHANGE`. Changing a flagged item sets it back to `PENDING`. Resubmit
requires every required item present and none still `NEEDS_CHANGE`. Approve
requires every required item `ACCEPTED`.

Secrets: PAN, licence and account numbers through `services/secrets.py`
(Fernet). Responses carry only the last 4. Without `SECRETS_ENCRYPTION_KEY`
the bank and document steps cannot be saved (503), same rule as payment
accounts.

## Admin panel

`RidersPage` gains an **Applications** tab (first when anything is waiting,
with a count badge). No new dependencies (house rule).

- Queue: segmented filter (Submitted, Changes needed, Approved, Rejected,
  Draft), search, city filter; rows show name, phone, vehicle, city, waiting
  time, items flagged. Oldest submitted first. Live via `useRidersChanged`.
- Review page (`/riders/applications/:id`): two columns on desktop, stacked
  on a phone. Left: details, vehicle, bank (last 4), history. Right: one
  card per photo with zoom and rotate (CSS transform), front and back side by
  side, and Accept / Needs change per item and per section. "Needs change"
  opens a reason picker: Blurry or cut off, Name doesn't match, Expired,
  Wrong document, Details don't match the photo, or a typed reason.
- Decision bar: Approve (disabled with the reason while any item is not
  accepted), Send back for changes (needs at least one flag), Reject
  permanently (reason + confirm).
- Built from the panel's existing components and tokens (`PageIntro`,
  `StatusPill`, `ResponsiveTable`, `Modal`, `ConfirmDialog`), so it looks like
  the rest of the panel in both themes.

## Rider app

New signed-out screens and one gated signed-in screen. New dependency:
`react-native-image-picker` (camera and gallery; it also resizes, so photos
leave the phone at up to 1600 px, JPEG quality 0.8, typically under 1 MB).
Native rebuild required.

- Login: "New here? Become a rider".
- Sign-up: phone, then the 6-digit code (paste and auto-advance), then name
  and password. Lands signed in on the application.
- Application wizard: a progress bar across 4 steps, Back/Next, each step
  validated locally with the same rules as the server and saved on Next.
  Photo slots show a frame guide, a preview with Retake / Use photo, and
  upload progress; a failed upload keeps the photo and offers Retry.
- Review and submit: every section as a card with Edit.
- Application status screen (`OnboardingHome`): what a PENDING rider sees
  instead of the tabs. Status banner (Draft, Under review "usually within 24
  hours", Changes needed, Not approved), the list of items with their state,
  each flagged item in red with the admin's reason and **Fix**, and
  **Resubmit** when ready. Pull to refresh; a push on approval or send-back
  refreshes it. Help: call support.
- Navigation: `SignedIn` decides on `/rider/me.onboarding`: `APPROVED`
  shows today's app (and the first-time intro); anything else shows the
  onboarding stack. Shift keeper, location and offer polling do not start
  until approved.
- All text in English, Hindi and Gujarati (`i18n/strings/onboarding.ts`).

## Errors and edge cases

- An app killed mid-wizard resumes at the first incomplete step (from the
  server, not local storage).
- A photo upload that fails on a bad network keeps the photo on the device
  until it is sent; Next waits for pending uploads.
- A second device signing in during review sees the same status.
- Two admins reviewing at once: item actions are idempotent; approve/send
  back check the state under a row lock and answer 409 `state_changed` if
  someone else decided first.
- Deactivating an applicant (`is_active = false`) works as for any rider.
- A rider who already has an account cannot sign up again with that phone;
  they are told to sign in.

## Testing

- Backend `unittest` (`tests/test_rider_onboarding.py`): every transition and
  its refusals, edit rules per state, required items per vehicle type, OTP
  expiry/attempts/rate limit, upload type/size/magic-byte checks (storage
  faked at the HTTP seam), secrets never in responses, and the work gates
  (online, offers, claim, open orders) for a PENDING rider.
- Rider jest: step validation rules (DOB 18+, plate, PAN, IFSC, account
  match, licence expiry), `required_items` mirror, resume step.
- Admin vitest: queue filters and the decision bar's enable rules.
- Manual: emulator sign-up to approval to going online; admin review in both
  themes and at phone width.

## Out of scope

Automatic document checks (OCR, DigiLocker, face match), background-check
vendors, training videos or quizzes, rider T-shirt/bag orders, and a web
sign-up page. The data model leaves room for each.

## What the user must do

- Add `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` to `backend/.env` and Render
  (the bucket is created by the backend on first use, private).
- Create and get approval for a WhatsApp AUTHENTICATION template, then set
  `WHATSAPP_OTP_TEMPLATE`. Until then, sign-up works locally only.
- Run migration `0090_rider_onboarding` on Supabase.
