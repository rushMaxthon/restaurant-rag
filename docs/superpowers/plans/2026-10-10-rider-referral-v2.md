# Rider Referral v2 (Swiggy-style) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Milestone rewards, referral push notifications, a WhatsApp-first Refer & earn screen with tabs, totals, leaderboard and FAQ, and an admin steps editor.

**Architecture:** Steps live in the settings and are frozen per referral (JSONB); bonus rows carry a step index under `UNIQUE(referral_id, kind, step)`. `referral.on_delivered` pays every reached step. Pushes are queued on `session.info` and sent by a class-level `after_commit` listener in a fresh session. The view grows totals, per-step progress and a leaderboard; the app and admin render them.

**Tech Stack:** FastAPI/SQLAlchemy/Alembic/Postgres (unittest), React admin (vitest, no new deps), React Native rider app (jest, no new deps).

**Spec:** `docs/superpowers/specs/2026-10-10-rider-referral-v2-design.md` (on top of v1's).

## Global Constraints

- Steps: 1-5, `deliveries` strictly increasing 1-500, amounts 0-10000, not all zero; days 1-365.
- Default `[{10,100,50},{30,400,150}]`, 30 days, enabled, leaderboard on.
- v1 settings shape reads as one step; v1 referral rows backfill to one step.
- Pushes only after commit, never raising; type `rider_referral`, events `joined|approved|earned`.
- Leaderboard month = calendar month in Asia/Kolkata; counts first-step bonuses (REFERRAL_REFERRER, step 0).
- No new dependencies. en/hi/gu strings. Commit trailer as in v1. Never commit `rider/metro.log`.

## Review Focus

1. A delivery that crosses TWO steps at once (e.g. step deliveries 1 and 2 with an admin-confirmed backlog) pays both steps, once each - test `test_two_steps_at_once`.
2. A rolled-back transaction sends no referral push - test `test_push_not_sent_after_rollback`.
3. Legacy v1 settings row still loads as one step, and v1 tests keep passing - test `test_v1_settings_read_as_one_step`.
4. Leaderboard ignores last month and other kinds/steps - test `test_leaderboard_this_month_first_steps_only`.
5. Expired referral keeps step-0 bonus unpaid-and-payable - test `test_expiry_keeps_earned_steps`.

---

### Task 1: Steps - settings, data, earning

**Files:** `backend/app/services/fleet/referral.py`, `backend/app/models/rider_referral.py`, `backend/alembic/versions/0092_referral_steps.py`, `backend/tests/test_fleet_referral_steps.py`

**Interfaces - Produces:** `ReferralStep(deliveries:int, referrer_amount:Decimal, joiner_amount:Decimal)`; `ReferralConfig.steps: tuple[ReferralStep,...]`, `.leaderboard_enabled: bool`, properties `referrer_amount`, `joiner_amount`, `deliveries_required` (totals/last); `RiderReferral.steps: list[dict]`; `RiderBonus.step: int`; `referral.steps_of(ref) -> list[ReferralStep]`; `on_delivered(...) -> list[tuple[RiderBonusKind, int, Decimal]]` (newly written bonuses; truthy when any) - v1 callers that test truthiness keep working.

- [ ] Write failing tests (new file, same harness/setUp as `test_fleet_referral.py`, rate limit patched):

```python
    def test_default_is_two_steps(self):
        cfg = referral.load_config(db)
        self.assertEqual([(s.deliveries, s.referrer_amount, s.joiner_amount) for s in cfg.steps],
                         [(10, Decimal("100.00"), Decimal("50.00")), (30, Decimal("400.00"), Decimal("150.00"))])
        self.assertTrue(cfg.leaderboard_enabled)

    def test_v1_settings_read_as_one_step(self):  # save_config({"referrer_amount":"300","joiner_amount":"100","deliveries_required":5})
        # -> steps == [(5, 300, 100)]

    def test_steps_refuse_nonsense(self):  # [], 6 steps, not increasing, deliveries 0/501, negative, all zero -> HTTPException

    def test_partial_then_final(self):  # steps [(1,100,50),(3,400,150)]: 1 delivery -> step-0 bonuses, IN_PROGRESS;
        # 3 deliveries -> step-1 bonuses, EARNED; totals 500/200

    def test_two_steps_at_once(self):  # steps [(1,..),(2,..)], 2 deliveries then one on_delivered -> 4 rows, EARNED

    def test_each_step_paid_once(self):  # repeat on_delivered -> still 4 rows

    def test_expiry_keeps_earned_steps(self):  # step 0 reached, deadline passes -> EXPIRED, step-0 rows remain, payable
```

- [ ] Run → FAIL (no `steps`).
- [ ] Implement:
  - `ReferralStep` dataclass; `ReferralConfig(enabled, leaderboard_enabled, days_allowed, steps)` with the three derived properties; `validate_config` accepts `steps` list, or the v1 shape (→ one step); `config_value` writes `{enabled, leaderboard_enabled, days_allowed, steps:[...], referrer_amount, joiner_amount, deliveries_required}` (totals kept for older readers).
  - Model: `RiderReferral.steps = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))`; `RiderBonus.step = mapped_column(Integer, nullable=False, default=0, server_default="0")`; unique constraint `uq_rider_bonuses_referral_kind_step (referral_id, kind, step)` replaces the v1 one.
  - `accept_code` stores `steps=[{"deliveries":…, "referrer_amount": str(…), "joiner_amount": str(…)}]` plus the totals in the v1 columns.
  - `steps_of(ref)`: parse `ref.steps`; empty → one step from the v1 columns.
  - `on_delivered`: count once; for each step index `i` with `count >= deliveries`, `_pay(..., kind, amount, step=i)` for both sides (savepoint per row, IntegrityError = already paid); EARNED when the last step is reached; return the list of rows written.
  - Migration `0092_referral_steps`: add both columns, backfill `steps` with `jsonb_build_array(jsonb_build_object('deliveries', deliveries_required, 'referrer_amount', referrer_amount::text, 'joiner_amount', joiner_amount::text))` where `steps = '[]'`, drop the v1 unique, create the new one; downgrade reverses.
- [ ] Run new + v1 referral tests → OK (update v1's default-values test to the two-step default - Ruling).
- [ ] Commit `feat(fleet): referral milestone steps`.

### Task 2: Referral pushes after commit

**Files:** `backend/app/services/fleet/notify.py`, `backend/app/services/fleet/referral.py`, `backend/app/api/rider_signup.py`, `backend/app/api/rider.py`, `backend/app/services/fleet/onboarding/applications.py`, tests in `test_fleet_referral_steps.py`

**Produces:** `notify.queue_referral_push(db, rider_user_id, event, **fields)`; listeners `_send_referral_pushes` (after_commit) / `_drop_referral_pushes` (after_soft_rollback).

- [ ] Failing tests: patch `notify._push`; accept a code + commit → one `joined` push to the referrer with the referred rider's short name; `on_approved` + commit → `approved` push (deliveries of step 0, days); a step earned + commit → `earned` push to each side with amount > 0; `test_push_not_sent_after_rollback` → queue, rollback, commit another change → no push.
- [ ] Implement: `queue_referral_push` appends `(rider_id, data)` to `db.info["referral_pushes"]`; `@event.listens_for(Session, "after_commit")` pops the list and sends each with `_push` in `SessionLocal()` (try/except, log); `after_soft_rollback` clears it when `previous_transaction` is the outermost (mirror `realtime/outbox.py`). Call sites: `accept_code` (joined), `on_approved` (approved), `on_delivered` (earned, per written row).
- [ ] Run → OK. Commit `feat(fleet): referral pushes - joined, approved, step earned - after commit`.

### Task 3: View - totals, per-step progress, leaderboard

**Files:** `backend/app/services/fleet/referral.py`, `backend/app/schemas/rider.py`, `backend/app/api/admin_riders.py`, tests.

- [ ] Failing tests: `rider_view` has `pending_total`, `paid_total`, `terms.steps`; progress `steps` with `earned`/`paid` flags and `earned_amount`/`paid_amount`; `test_leaderboard_this_month_first_steps_only` (bonus last month ignored; step 1 ignored; joiner kind ignored; ranks; `me`); leaderboard null when disabled; admin row `steps_total`/`steps_earned`; settings API round-trips `steps` and `leaderboard_enabled`.
- [ ] Implement: `_progress` per-step rows from `steps_of` + bonus rows for that side; leaderboard query grouped by `rider_user_id` over REFERRER step-0 bonuses with `earned_at` in the IST month, ordered by count desc, min(earned_at) asc, limit 10, plus my rank via the same grouped subquery; schemas `ReferralStepIn/Out`, settings model with `steps` (min 1, max 5) and `leaderboard_enabled`; AdminReferralRow new fields.
- [ ] Run all referral tests + `discover -p "test_fleet*"`. Commit `feat(fleet): referral view - totals, step progress, monthly leaderboard`.

### Task 4: Admin steps editor

**Files:** `frontend-admin/src/services/riderReferral.ts` (+test), `src/types/app.ts`, `src/components/riders/ReferralsTab.tsx`.

- [ ] Failing vitest: `referralSettingsError` for steps (none, >5, not increasing, bad numbers, all zero); `referralExample` lists steps ("10 deliveries: ₹100 + ₹50; 30 deliveries: ₹400 + ₹150 - within 30 days"); `progressLabel` adds "· step 1 of 2".
- [ ] Implement: draft `steps: {deliveries, referrer_amount, joiner_amount}[]` strings; editor rows with add/remove (max 5, min 1) using the `delivery-slab` markup from Pay & dispatch; leaderboard checkbox; list column shows steps earned.
- [ ] `npx vitest run`, `npm run build`. Commit `feat(admin): referral steps editor and leaderboard switch`.

### Task 5: Rider app - screen, card, pushes

**Files:** `rider/src/utils/referral.ts` (+test), `rider/src/utils/push.ts` (+test), `rider/src/services/push.ts`, `rider/src/components/PushRouter.tsx`, `rider/src/screens/profile/ReferralScreen.tsx`, `rider/src/components/JoiningBonusCard.tsx`, `rider/src/types/api.ts`, `rider/src/i18n/strings/referral.ts`, `rider/android/app/src/main/AndroidManifest.xml`.

- [ ] Failing jest: `whatsappUrl(message)` = `whatsapp://send?text=<encoded>`; `tabOf(status)` → 'active'|'earned'|'expired'; `stepMarkers(steps, required)` → fractions; `nextStep(progress)` → first unearned step or null; `showsJoiningCard` (IN_PROGRESS, or earned_amount > paid_amount); `parsePush({type:'rider_referral', event:'earned', amount:'100'})` → `{kind:'referral', event:'earned', ...}`.
- [ ] Implement helpers; push: `showReferral(push)` (updates channel, title/body per event from strings), router: `kind === 'referral'` → `navigationRef.navigate('Referral')` when that route exists. Screen: WhatsApp button (`Linking.openURL(whatsappUrl(msg)).catch(() => Share.share({message}))`), More options, totals row, `Segmented` tabs, step markers on the bar, leaderboard card (highlight `me`), FAQ (5 Q/A, `Pressable` fold). Manifest `<queries>`: `<intent><action android:name="android.intent.action.VIEW"/><data android:scheme="whatsapp"/></intent>`. Strings en/hi/gu for every new key.
- [ ] `npx jest`, `tsc --noEmit`, `eslint src` (0 errors). Commit `feat(rider): Swiggy-style Refer & earn - WhatsApp invite, tabs, steps, leaderboard, FAQ, pushes`.

### Task 6: Migrate dev DB, docs, verify

- [ ] `alembic upgrade head` on rr_rider_dev (assert target first), round trip down/up; restart 8001.
- [ ] Full backend suite; admin vitest + build; rider jest + tsc + eslint.
- [ ] CLAUDE.md fleet bullet updated for steps/pushes/leaderboard; worklog entry. Commit `docs: referral v2`.
