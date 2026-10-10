# Rider referral v2 - Swiggy-style - design

Date: 2026-10-10. Status: approved in conversation ("yes go ahead").
Builds on `2026-10-10-rider-referral-design.md` (v1, shipped). Everything v1
says still holds unless this document changes it.

## Goal

Make Refer & earn feel like Swiggy's delivery-partner referral: rewards in
steps, notifications at every stage, a one-tap WhatsApp invite, status tabs,
a monthly leaderboard, and an FAQ - all numbers still set by the admin.

## 1. Milestone rewards

- The programme is a list of **1-5 steps**, each `{deliveries, referrer_amount,
  joiner_amount}`, `deliveries` strictly increasing (1-500), amounts 0-10000,
  not every amount zero; plus `days_allowed` (1-365), `enabled`, and
  `leaderboard_enabled`.
- **Default:** `[{10, 100, 50}, {30, 400, 150}]`, 30 days, enabled, leaderboard on.
- A settings row in the v1 shape (`referrer_amount, joiner_amount,
  deliveries_required`) reads as ONE step - nothing saved before breaks.
- The steps are frozen on the referral (`rider_referrals.steps`, JSONB) when
  the code is accepted. v1 columns stay, now meaning the totals
  (`referrer_amount`, `joiner_amount` = sums; `deliveries_required` = the
  last step's deliveries).
- `on_delivered`: every step whose `deliveries` is reached and not yet paid
  writes its bonus rows (`rider_bonuses.step` = index); reaching the LAST
  step marks the referral `EARNED`. In between it stays `IN_PROGRESS`.
- Expiry: past the deadline the referral is `EXPIRED`; steps already earned
  stay earned and paid; later steps are lost.
- Money guard becomes `UNIQUE (referral_id, kind, step)`.
- Cancel: unchanged - deletes unpaid bonus rows, refused if any is paid.

## 2. Notifications

Data-only FCM (`type: rider_referral`, `event`, `name`, `amount`,
`deliveries`, `days`), drawn by the app in its language on the updates
channel; a tap opens Refer & earn. Sent only AFTER the commit that caused
them (queued on `session.info`, class-level `after_commit`, dropped on
rollback - the `realtime/outbox.py` pattern), in a fresh session, never
raising.

| Event | To | When |
|---|---|---|
| `joined` | referrer | a code is accepted (sign-up or added later) |
| `approved` | referrer | the referred rider is approved (clock starts) |
| `earned` | each side with a non-zero amount | a step is reached |

## 3. Refer & earn screen

- Code card: **Invite on WhatsApp** (opens WhatsApp with the message; falls
  back to the share sheet when WhatsApp is missing) and **More options**
  (share sheet). Android manifest gains a `<queries>` entry for the
  `whatsapp` scheme.
- Totals: **Earned / Pending / Paid** (`earned_total`, `pending_total` =
  unpaid bonus rows, `paid_total`) - this rider's referral money, both sides.
- Tabs: **In progress** (WAITING, IN_PROGRESS) / **Earned** / **Expired**
  (EXPIRED, CANCELLED). Each card: name, status, a bar with a marker per
  step, "12/30 deliveries - 18 days left", this side's amounts per step with
  a tick on earned ones.
- **Leaderboard** (when on): this month's top 10 (calendar month,
  Asia/Kolkata) by number of referrals that reached their FIRST step this
  month; first name + last initial; ties by who got there first; plus "Your
  rank" when the rider is placed.
- **FAQ**: 5 foldable questions in en/hi/gu, numbers filled from the live
  terms.
- Joining-bonus card: shows the next step to reach; hides when every earned
  step is paid and no step is left.

## 4. Admin

Riders -> Referrals: a steps editor (add/remove up to 5; deliveries,
referrer Rs, new rider Rs), days, programme on, leaderboard on; the list
shows "steps earned k of n". Form rules mirrored in
`services/riderReferral.ts`.

## API changes

- `ReferralSettings`: `{enabled, leaderboard_enabled, days_allowed, steps:
  [{deliveries, referrer_amount, joiner_amount}]}`.
- `RiderReferralView.terms` gains `steps`; v1 total fields kept.
  View gains `pending_total`, `paid_total`, `leaderboard: {month, top:
  [{rank, name, count, me}], my_rank, my_count} | null`.
- `ReferralProgress` gains `steps: [{deliveries, amount, earned, paid}]`,
  `earned_amount`, `paid_amount` (this side); `paid` stays (= every earned
  step paid and none left).
- `AdminReferralRow` gains `steps_total`, `steps_earned`.

## Migration 0092_referral_steps

`rider_referrals.steps` JSONB NOT NULL default `'[]'`, backfilled to one
step from the v1 columns; `rider_bonuses.step` INTEGER NOT NULL default 0;
drop `uq_rider_bonuses_referral_kind`, add `uq_rider_bonuses_referral_kind_step`.

## Testing

Backend: steps validation and legacy shape; partial earning keeps
IN_PROGRESS with step-0 bonuses; final step -> EARNED; each step paid once
under a repeat call; expiry keeps earned steps; pushes queued and sent only
after commit, none after rollback; leaderboard counts first steps this month
only, ranks, ties, `me`, off when disabled. Admin vitest: steps form rules.
Rider jest: step markers / next-step helper, WhatsApp URL builder, tab
filter, push parsing of `rider_referral`.

## Out of scope

Install/deep links that pre-fill the code (no hosted domain), contacts
picker, cash-in-wallet redemption, per-city programmes.
