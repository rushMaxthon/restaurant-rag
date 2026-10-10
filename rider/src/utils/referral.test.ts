import {
  daysLeft,
  normaliseCode,
  progressFraction,
  shareMessage,
  showsJoiningCard,
  stepMarkers,
  nextStep,
  tabOf,
  whatsappUrl,
} from './referral';
import type { ReferralProgress } from '@/types/api';

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

describe('showsJoiningCard', () => {
  const base = {
    delivered: 3,
    required: 20,
    deadline: null,
    amount: '200.00',
    name: 'Priya',
    steps: [],
  };
  const card = (
    status: ReferralProgress['status'],
    earned: string,
    paid: string,
  ): ReferralProgress => ({
    ...base,
    status,
    earned_amount: earned,
    paid_amount: paid,
    paid: Number(earned) > 0 && earned === paid,
  });
  it('shows while working towards it, and once earned until it is paid', () => {
    expect(showsJoiningCard(card('IN_PROGRESS', '0.00', '0.00'))).toBe(true);
    expect(showsJoiningCard(card('EARNED', '200.00', '0.00'))).toBe(true);
  });
  it('goes away once paid - "comes with your next payout" would be false', () => {
    expect(showsJoiningCard(card('EARNED', '200.00', '200.00'))).toBe(false);
  });
  it('shows nothing for waiting, expired-with-nothing, or no referral', () => {
    expect(showsJoiningCard(card('WAITING', '0.00', '0.00'))).toBe(false);
    expect(showsJoiningCard(card('EXPIRED', '0.00', '0.00'))).toBe(false);
    expect(showsJoiningCard(null)).toBe(false);
  });
});

describe('v2 helpers', () => {
  const progress = (
    over: Partial<ReferralProgress> = {},
  ): ReferralProgress => ({
    name: 'Ravi K.',
    status: 'IN_PROGRESS',
    delivered: 12,
    required: 30,
    deadline: null,
    amount: '500.00',
    paid: false,
    earned_amount: '100.00',
    paid_amount: '0.00',
    steps: [
      { deliveries: 10, amount: '100.00', earned: true, paid: false },
      { deliveries: 30, amount: '400.00', earned: false, paid: false },
    ],
    ...over,
  });

  it('builds the WhatsApp link with the message encoded', () => {
    expect(whatsappUrl('Join me & earn ₹50')).toBe(
      `whatsapp://send?text=${encodeURIComponent('Join me & earn ₹50')}`,
    );
  });

  it('sorts statuses into the three tabs', () => {
    expect(
      ['WAITING', 'IN_PROGRESS', 'EARNED', 'EXPIRED', 'CANCELLED'].map(s =>
        tabOf(s as never),
      ),
    ).toEqual(['active', 'active', 'earned', 'expired', 'expired']);
  });

  it('places a marker for each step along the bar', () => {
    expect(stepMarkers(progress().steps, 30)).toEqual([1 / 3, 1]);
  });

  it('names the next step to reach, or none', () => {
    expect(nextStep(progress())?.deliveries).toBe(30);
    expect(
      nextStep(
        progress({
          steps: progress().steps.map(s => ({ ...s, earned: true })),
        }),
      ),
    ).toBeNull();
  });

  it('keeps the joining card while money is earned but not yet paid', () => {
    expect(
      showsJoiningCard(
        progress({
          status: 'EXPIRED',
          earned_amount: '50.00',
          paid_amount: '0.00',
        }),
      ),
    ).toBe(true);
    expect(
      showsJoiningCard(
        progress({
          status: 'EXPIRED',
          earned_amount: '50.00',
          paid_amount: '50.00',
        }),
      ),
    ).toBe(false);
  });
});
