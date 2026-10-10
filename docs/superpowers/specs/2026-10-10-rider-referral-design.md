# Rider referral programme - design

Date: 2026-10-10. Status: approved in conversation, awaiting written review.

## Goal

Riders bring in riders. A rider shares a referral code; a new rider signs up
with it; when the new rider has actually worked - N successful deliveries
within X days of approval - BOTH earn money, paid with their next payout.
Modelled on Swiggy's delivery-partner referral. Every amount and threshold is
set by the platform admin and can change later without breaking promises
already made.

## Decisions (from the owner)

| Question | Decision |
|---|---|
| When is the reward earned | When the new rider completes N delivered trips within X days of approval |
| Who earns | Both: the referrer (A) and the new rider (B); either amount may be 0 |
| How it is paid | Automatically into the next payout, shown as "Referral bonus" under To be paid |
| Defaults | A = Rs 500, B = Rs 200, N = 20, X = 30 days, programme on |

## Rules

1. **Codes.** Every APPROVED rider has one code: their first name's letters
   (A-Z only, up to 6, uppercased; "RIDER" when there are none) plus 4 random
   digits, e.g. `PRIYA4821`. Unique; compared case-insensitively and with
   spaces stripped. Created on approval, and lazily the first time an older
   (already approved or admin-made) rider opens Refer & earn.
2. **Entering a code.** Optional field on the sign-up account step
   (`POST /rider/signup` gains `referral_code`). A rider who skipped it may add
   one with `POST /rider/referral/code` any time until their application is
   APPROVED. One referrer per rider, ever - a code once accepted is not
   changeable by the rider.
3. **Refused** (422 with a code the app translates):
   `referral_unknown` (no such code), `referral_self` (own code),
   `referral_inactive` (the referrer is deactivated or not APPROVED),
   `referral_taken` (this rider already has a referrer),
   `referral_closed` (already approved, or the programme is off).
   At sign-up a bad code fails the whole request before the account is made,
   so the rider can fix it and resubmit - nothing half-created.
4. **Terms are frozen on the referral row** when the code is accepted:
   `referrer_amount`, `joiner_amount`, `deliveries_required`,
   `days_allowed`. Admin changes later apply only to new referrals.
5. **The clock** starts at approval: `deadline = approved_at + days_allowed`.
   Before approval the referral is `WAITING`.
6. **Qualifying.** Counted: the referred rider's trips with
   `end_reason = DELIVERED` and `ended_at` between approval and the deadline.
   Not counted: cancelled trips, customer-unavailable trips, anything outside
   the window. Checked when a trip ends DELIVERED (in `trips._finish`'s path,
   after the pay is set); reaching N marks the referral `EARNED` and writes two
   bonus rows (zero amounts are not written). Idempotent: a referral that is
   already EARNED is never paid again.
7. **Expiry.** A referral still `IN_PROGRESS` past its deadline reads as
   `EXPIRED`, and is saved as such the first time anyone reads it (no beat
   task). A delivery after the deadline does not count.
8. **Cancellation.** An admin may cancel a referral in WAITING or IN_PROGRESS
   (with a reason), or an EARNED one whose bonuses are not yet in a payout -
   then those unpaid bonus rows are deleted. A paid bonus is never touched.
9. **Programme off** (`enabled = false`): no new codes are accepted and no
   referral moves to EARNED; existing earned-but-unpaid bonuses still pay.

## Data

Migration `0091_rider_referrals` (RLS enabled in the migration, like 0070+):

- `riders.referral_code` - `varchar(16)`, unique, nullable.
- `rider_referrals`
  - `referred_user_id` uuid PK, FK riders(user_id) - one referrer per rider
  - `referrer_user_id` uuid FK riders(user_id), indexed
  - `code` varchar(16) - as entered
  - `referrer_amount`, `joiner_amount` numeric(10,2)
  - `deliveries_required` int, `days_allowed` int
  - `status` enum `rider_referral_status`: WAITING, IN_PROGRESS, EARNED,
    EXPIRED, CANCELLED
  - `approved_at`, `deadline`, `earned_at`, `cancelled_at` timestamptz null
  - `cancel_reason` text null, `cancelled_by_user_id` uuid null
  - timestamps; CHECK referred <> referrer
- `rider_bonuses`
  - `id` uuid PK, `rider_user_id` uuid FK riders, indexed
  - `kind` enum `rider_bonus_kind`: REFERRAL_REFERRER, REFERRAL_JOINER
  - `amount` numeric(10,2) > 0
  - `referral_id` uuid FK rider_referrals(referred_user_id)
  - `payout_id` uuid FK rider_payouts null - set when paid
  - `earned_at` timestamptz; timestamps
  - UNIQUE (referral_id, kind) - the money guard: one of each, ever
- `platform_settings` key `rider_referral`: `{enabled, referrer_amount,
  joiner_amount, deliveries_required, days_allowed}`, read/validated like
  `fleet/config.py` (defaults in code; ranges: amounts 0-10000, N 1-500,
  X 1-365).

## Money path

- `payouts.unpaid_summary`, `rider_earnings` (`unpaid`) and `pay_rider` add
  unpaid bonus rows to unpaid trips. `pay_rider` locks bonus rows
  `FOR UPDATE` alongside trips and sets their `payout_id`; the payout amount
  includes them. `trips` count on the payout stays trips only.
- `rider_earnings` gains `bonuses` (list for the period: amount, kind,
  earned_at) and the day series counts a bonus on the day it was earned, so
  the Earnings chart and totals include it.
- A rider with only a bonus unpaid appears in Payouts and can be paid.

## API

Rider (`/rider`, RIDER role):
- `POST /rider/signup` - optional `referral_code`.
- `GET /rider/referral` - `{code, enabled, terms: {referrer_amount,
  joiner_amount, deliveries_required, days_allowed}, earned_total,
  referrals: [{name (first name + last initial), status, delivered,
  required, deadline, amount}], joined_with: {status, delivered, required,
  deadline, amount} | null}`. Creates the code if the rider is APPROVED and
  has none. A PENDING rider gets `code: null` and only `joined_with`.
- `POST /rider/referral/code` `{code}` - add a referrer before approval.

Admin (`/admin/riders`, ADMIN only; OWNER 403):
- `GET /admin/riders/referrals?status=` - rows with both names, code, terms,
  progress, status, bonus paid/unpaid.
- `GET|PUT /admin/riders/settings/referral` - the settings.
- `POST /admin/riders/referrals/{referred_user_id}/cancel` `{reason}`.

## Admin panel

Riders -> new **Referrals** tab (`frontend-admin`, no new dependencies):
settings card (on/off, two amounts, deliveries, days, with a one-line example)
and the list (filter by status; Cancel through `ConfirmDialog`, reason
required). Payouts tab shows bonus amounts inside each rider's total.
Form rules in `services/riderReferral.ts` with vitest tests.

## Rider app

- **Profile -> Refer & earn** (new `ReferralScreen`): the code in large type,
  Share (React Native `Share` - no new dependency) with a ready message in
  the app language, a Copy button, three-line "how it works" from the terms,
  total earned, and the list of referrals with a progress bar
  ("12/20 deliveries - 18 days left"), status pill.
- **Joining bonus card** on Home and Earnings while the rider's own referral
  is IN_PROGRESS (and a one-time "earned" state once).
- **Sign-up account step**: "Referral code (optional)" field. **Application
  home**: "Have a referral code?" row until approved.
- Earnings shows "Referral bonus" rows.
- Strings in a new `i18n/strings/referral.ts`, en/hi/gu; error codes mapped
  in `services/http.ts` `messageFor`.
- Pure helpers (`utils/referral.ts`: progress label, days left, share text)
  with jest tests.

## Testing

Backend unittest (`tests/test_fleet_referral.py`): code format and
uniqueness; each refusal code; sign-up with a bad code makes no account;
frozen terms survive a settings change; WAITING -> IN_PROGRESS on approval;
EARNED exactly at N (not N-1), counting only DELIVERED trips inside the
window; nothing after the deadline and the row saved EXPIRED on read; both
bonuses written once even if the check runs twice; zero amount writes no row;
programme off blocks codes and earning; bonuses land in exactly one payout
and in `unpaid`; cancel deletes unpaid bonuses and refuses after payout;
owner gets 403. Admin vitest for the form rules; rider jest for the helpers.

## Out of scope

Device/phone-similarity fraud detection (admin Cancel covers it for now),
leaderboards, tiered/milestone rewards, customers referring riders,
push notifications for "your referral earned" (can follow; the screen shows
it).
