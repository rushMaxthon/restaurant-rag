import { describe, expect, it } from 'vitest';

import {
  draftFrom,
  progressLabel,
  referralExample,
  referralSettingsError,
  settingsFrom,
  type ReferralDraft,
} from './riderReferral';

const draft = (): ReferralDraft => ({
  enabled: true,
  leaderboard_enabled: true,
  days_allowed: '30',
  steps: [
    { deliveries: '10', referrer_amount: '100', joiner_amount: '50' },
    { deliveries: '30', referrer_amount: '400', joiner_amount: '150' },
  ],
});

describe('referral settings form (steps)', () => {
  it('accepts the two-step default', () => {
    expect(referralSettingsError(draft())).toBeNull();
  });
  it('needs 1 to 5 steps', () => {
    expect(referralSettingsError({ ...draft(), steps: [] })).toBeTruthy();
    const six = Array.from({ length: 6 }, (_, i) => ({ deliveries: String(i + 1), referrer_amount: '10', joiner_amount: '0' }));
    expect(referralSettingsError({ ...draft(), steps: six })).toBeTruthy();
  });
  it('needs each step to ask for more deliveries than the last', () => {
    const d = draft();
    d.steps[1].deliveries = '10';
    expect(referralSettingsError(d)).toMatch(/more deliveries/);
  });
  it('refuses bad numbers and a programme that pays nothing', () => {
    const bad = draft();
    bad.steps[0].referrer_amount = '-1';
    expect(referralSettingsError(bad)).toBeTruthy();
    const zero = draft();
    zero.steps = [{ deliveries: '5', referrer_amount: '0', joiner_amount: '0' }];
    expect(referralSettingsError(zero)).toMatch(/pay/);
    expect(referralSettingsError({ ...draft(), days_allowed: '366' })).toBeTruthy();
  });
  it('says the deal in one line', () => {
    expect(referralExample(draft())).toBe(
      '10 deliveries: ₹100 to the referrer + ₹50 to the new rider; 30 deliveries: ₹400 + ₹150 - all within 30 days of approval.',
    );
  });
  it('round-trips the server shape', () => {
    const wire = settingsFrom(draft());
    expect(wire.steps[0]).toEqual({ deliveries: 10, referrer_amount: '100', joiner_amount: '50' });
    expect(draftFrom(wire)).toEqual(draft());
  });
});

describe('progressLabel', () => {
  const now = new Date('2026-10-10T00:00:00Z');
  it('reads progress, steps and what is left', () => {
    expect(
      progressLabel(
        { status: 'IN_PROGRESS', delivered: 12, required: 30, deadline: '2026-10-28T00:00:00Z', steps_total: 2, steps_earned: 1 },
        now,
      ),
    ).toBe('12/30 deliveries · step 1 of 2 · 18 days left');
    expect(progressLabel({ status: 'WAITING', delivered: 0, required: 30, deadline: null, steps_total: 2, steps_earned: 0 }, now)).toBe(
      'Waiting for approval',
    );
    expect(progressLabel({ status: 'EARNED', delivered: 30, required: 30, deadline: null, steps_total: 1, steps_earned: 1 }, now)).toBe(
      '30/30 deliveries',
    );
  });
});
