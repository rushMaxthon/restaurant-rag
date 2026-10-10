/**
 * The Referrals tab's rules, out of the component so they can be tested.
 * The server owns them (`fleet/referral.py validate_config`); these repeat
 * them so a mistake shows beside the field instead of as a 422 after Save.
 */

import type { ReferralSettings, ReferralStatus } from '../types/app';

export interface ReferralDraft {
  enabled: boolean;
  referrer_amount: string;
  joiner_amount: string;
  deliveries_required: string;
  days_allowed: string;
}

export function draftFrom(s: ReferralSettings): ReferralDraft {
  return {
    enabled: s.enabled,
    referrer_amount: String(Number(s.referrer_amount)),
    joiner_amount: String(Number(s.joiner_amount)),
    deliveries_required: String(s.deliveries_required),
    days_allowed: String(s.days_allowed),
  };
}

export function settingsFrom(d: ReferralDraft): ReferralSettings {
  return {
    enabled: d.enabled,
    referrer_amount: d.referrer_amount.trim(),
    joiner_amount: d.joiner_amount.trim(),
    deliveries_required: Number(d.deliveries_required),
    days_allowed: Number(d.days_allowed),
  };
}

const num = (v: string): number | null => (v.trim() === '' || !Number.isFinite(Number(v)) ? null : Number(v));

export function referralSettingsError(d: ReferralDraft): string | null {
  const a = num(d.referrer_amount);
  const b = num(d.joiner_amount);
  if (a === null || b === null || a < 0 || b < 0 || a > 10000 || b > 10000) {
    return 'Bonus amounts must be between ₹0 and ₹10,000.';
  }
  const n = num(d.deliveries_required);
  if (n === null || !Number.isInteger(n) || n < 1 || n > 500) {
    return 'Deliveries needed must be a whole number from 1 to 500.';
  }
  const days = num(d.days_allowed);
  if (days === null || !Number.isInteger(days) || days < 1 || days > 365) {
    return 'Days allowed must be a whole number from 1 to 365.';
  }
  return null;
}

export function referralExample(d: ReferralDraft): string {
  return `A new rider who makes ${d.deliveries_required} deliveries within ${d.days_allowed} days of approval earns their referrer ₹${d.referrer_amount} and themselves ₹${d.joiner_amount}.`;
}

export function progressLabel(
  row: { status: ReferralStatus; delivered: number; required: number; deadline: string | null },
  now: Date = new Date(),
): string {
  if (row.status === 'WAITING') return 'Waiting for approval';
  const done = `${Math.min(row.delivered, row.required)}/${row.required} deliveries`;
  if (row.status !== 'IN_PROGRESS' || !row.deadline) return done;
  const days = Math.max(0, Math.ceil((new Date(row.deadline).getTime() - now.getTime()) / 86_400_000));
  return `${done} · ${days} days left`;
}

export const STATUS_LABEL: Record<ReferralStatus, string> = {
  WAITING: 'Waiting',
  IN_PROGRESS: 'In progress',
  EARNED: 'Earned',
  EXPIRED: 'Expired',
  CANCELLED: 'Cancelled',
};
