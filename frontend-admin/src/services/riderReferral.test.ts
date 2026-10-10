import { describe, expect, it } from 'vitest';

import { progressLabel, referralExample, referralSettingsError, type ReferralDraft } from './riderReferral';

const draft = (): ReferralDraft => ({
  enabled: true,
  referrer_amount: '500',
  joiner_amount: '200',
  deliveries_required: '20',
  days_allowed: '30',
});

describe('referral settings form', () => {
  it('accepts the defaults', () => {
    expect(referralSettingsError(draft())).toBeNull();
  });
  it('refuses out-of-range numbers', () => {
    expect(referralSettingsError({ ...draft(), referrer_amount: '-1' })).toBeTruthy();
    expect(referralSettingsError({ ...draft(), joiner_amount: 'abc' })).toBeTruthy();
    expect(referralSettingsError({ ...draft(), deliveries_required: '0' })).toBeTruthy();
    expect(referralSettingsError({ ...draft(), days_allowed: '366' })).toBeTruthy();
    expect(referralSettingsError({ ...draft(), deliveries_required: '2.5' })).toBeTruthy();
  });
  it('says the deal in one line', () => {
    expect(referralExample(draft())).toBe(
      'A new rider who makes 20 deliveries within 30 days of approval earns their referrer ₹500 and themselves ₹200.',
    );
  });
});

describe('progressLabel', () => {
  it('reads progress and what is left', () => {
    const now = new Date('2026-10-10T00:00:00Z');
    expect(
      progressLabel({ status: 'IN_PROGRESS', delivered: 12, required: 20, deadline: '2026-10-28T00:00:00Z' }, now),
    ).toBe('12/20 deliveries · 18 days left');
    expect(progressLabel({ status: 'WAITING', delivered: 0, required: 20, deadline: null }, now)).toBe(
      'Waiting for approval',
    );
    expect(progressLabel({ status: 'EARNED', delivered: 20, required: 20, deadline: null }, now)).toBe('20/20 deliveries');
  });
});
