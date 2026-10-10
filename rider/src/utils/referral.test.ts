import {
  daysLeft,
  normaliseCode,
  progressFraction,
  shareMessage,
} from './referral';

describe('referral helpers', () => {
  const now = new Date('2026-10-10T00:00:00Z');

  it('counts whole days left, never below zero', () => {
    expect(daysLeft('2026-10-28T00:00:00Z', now)).toBe(18);
    expect(daysLeft('2026-10-10T05:00:00Z', now)).toBe(1);
    expect(daysLeft('2026-10-01T00:00:00Z', now)).toBe(0);
    expect(daysLeft(null, now)).toBeNull();
  });

  it('fills the bar by deliveries, capped at full', () => {
    expect(progressFraction({ delivered: 5, required: 20 })).toBe(0.25);
    expect(progressFraction({ delivered: 25, required: 20 })).toBe(1);
    expect(progressFraction({ delivered: 0, required: 0 })).toBe(0);
  });

  it('cleans what the rider typed the way the server does', () => {
    expect(normaliseCode('  priya 4821 ')).toBe('PRIYA4821');
  });

  it('builds the share message from the terms', () => {
    const t = (key: string, vars?: Record<string, string | number>) =>
      `${key}:${JSON.stringify(vars)}`;
    expect(
      shareMessage(
        'PRIYA4821',
        { joiner_amount: '200.00', deliveries_required: 20, days_allowed: 30 },
        t,
      ),
    ).toBe(
      'referral.shareMessage:{"code":"PRIYA4821","amount":"₹200","n":20,"days":30}',
    );
  });
});
