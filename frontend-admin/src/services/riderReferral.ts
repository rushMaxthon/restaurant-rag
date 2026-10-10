/**
 * The Referrals tab's rules, out of the component so they can be tested.
 * The server owns them (`fleet/referral.py validate_config`); these repeat
 * them so a mistake shows beside the field instead of as a 422 after Save.
 *
 * v2 (2026-10-10): the programme pays in steps, Swiggy-style - e.g. ₹100 +
 * ₹50 at 10 deliveries, ₹400 + ₹150 more at 30.
 */

import type { ReferralSettings, ReferralStatus } from '../types/app';

export const MAX_STEPS = 5;

export interface StepDraft {
  deliveries: string;
  referrer_amount: string;
  joiner_amount: string;
}

export interface ReferralDraft {
  enabled: boolean;
  leaderboard_enabled: boolean;
  days_allowed: string;
  steps: StepDraft[];
}

export function draftFrom(s: ReferralSettings): ReferralDraft {
  return {
    enabled: s.enabled,
    leaderboard_enabled: s.leaderboard_enabled,
    days_allowed: String(s.days_allowed),
    steps: s.steps.map((step) => ({
      deliveries: String(step.deliveries),
      referrer_amount: String(Number(step.referrer_amount)),
      joiner_amount: String(Number(step.joiner_amount)),
    })),
  };
}

export function settingsFrom(d: ReferralDraft): ReferralSettings {
  return {
    enabled: d.enabled,
    leaderboard_enabled: d.leaderboard_enabled,
    days_allowed: Number(d.days_allowed),
    steps: d.steps.map((step) => ({
      deliveries: Number(step.deliveries),
      referrer_amount: step.referrer_amount.trim(),
      joiner_amount: step.joiner_amount.trim(),
    })),
  };
}

const num = (v: string): number | null => (v.trim() === '' || !Number.isFinite(Number(v)) ? null : Number(v));
const money = (v: number | null) => v !== null && v >= 0 && v <= 10000;

export function referralSettingsError(d: ReferralDraft): string | null {
  if (d.steps.length < 1 || d.steps.length > MAX_STEPS) return `Add between 1 and ${MAX_STEPS} steps.`;
  let previous = 0;
  let paysSomething = false;
  for (const step of d.steps) {
    const n = num(step.deliveries);
    if (n === null || !Number.isInteger(n) || n < 1 || n > 500) {
      return 'Deliveries needed must be a whole number from 1 to 500.';
    }
    if (n <= previous) return 'Each step must need more deliveries than the one before it.';
    previous = n;
    const a = num(step.referrer_amount);
    const b = num(step.joiner_amount);
    if (!money(a) || !money(b)) return 'Bonus amounts must be between ₹0 and ₹10,000.';
    if ((a ?? 0) > 0 || (b ?? 0) > 0) paysSomething = true;
  }
  if (!paysSomething) return 'A referral must pay somebody something.';
  const days = num(d.days_allowed);
  if (days === null || !Number.isInteger(days) || days < 1 || days > 365) {
    return 'Days allowed must be a whole number from 1 to 365.';
  }
  return null;
}

export function referralExample(d: ReferralDraft): string {
  const parts = d.steps.map((step, i) =>
    i === 0
      ? `${step.deliveries} deliveries: ₹${step.referrer_amount} to the referrer + ₹${step.joiner_amount} to the new rider`
      : `${step.deliveries} deliveries: ₹${step.referrer_amount} + ₹${step.joiner_amount}`,
  );
  return `${parts.join('; ')} - all within ${d.days_allowed} days of approval.`;
}

export function progressLabel(
  row: {
    status: ReferralStatus;
    delivered: number;
    required: number;
    deadline: string | null;
    steps_total: number;
    steps_earned: number;
  },
  now: Date = new Date(),
): string {
  if (row.status === 'WAITING') return 'Waiting for approval';
  const done = `${Math.min(row.delivered, row.required)}/${row.required} deliveries`;
  if (row.status !== 'IN_PROGRESS' || !row.deadline) return done;
  const days = Math.max(0, Math.ceil((new Date(row.deadline).getTime() - now.getTime()) / 86_400_000));
  const steps = row.steps_total > 1 ? ` · step ${row.steps_earned} of ${row.steps_total}` : '';
  return `${done}${steps} · ${days} days left`;
}

export const STATUS_LABEL: Record<ReferralStatus, string> = {
  WAITING: 'Waiting',
  IN_PROGRESS: 'In progress',
  EARNED: 'Earned',
  EXPIRED: 'Expired',
  CANCELLED: 'Cancelled',
};
