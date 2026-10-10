/**
 * Refer & earn, the parts with no screen (backend `fleet/referral.py`).
 */

import type {
  ReferralProgress,
  ReferralStatus,
  ReferralStepProgress,
} from '@/types/api';

import { rupees } from './format';

export function daysLeft(
  deadline: string | null,
  now: Date = new Date(),
): number | null {
  if (!deadline) return null;
  return Math.max(
    0,
    Math.ceil((new Date(deadline).getTime() - now.getTime()) / 86_400_000),
  );
}

export function progressFraction(p: {
  delivered: number;
  required: number;
}): number {
  if (p.required <= 0) return 0;
  return Math.min(1, p.delivered / p.required);
}

/** As the server stores it: uppercase, no spaces. */
export function normaliseCode(code: string): string {
  return code.replace(/\s+/g, '').toUpperCase();
}

type Translate = (
  key: string,
  vars?: Record<string, string | number>,
) => string;

export function shareMessage(
  code: string,
  terms: {
    joiner_amount: string;
    deliveries_required: number;
    days_allowed: number;
  },
  t: Translate,
): string {
  return t('referral.shareMessage', {
    code,
    amount: rupees(terms.joiner_amount),
    n: terms.deliveries_required,
    days: terms.days_allowed,
  });
}

/**
 * The joining-bonus card: while the rider works towards it, and afterwards
 * for as long as an earned step is not yet paid - then "it comes with your
 * next payout" would be false.
 */
export function showsJoiningCard(p: ReferralProgress | null): boolean {
  if (!p) return false;
  if (p.status === 'IN_PROGRESS') return true;
  const earned = Number(p.earned_amount);
  if (Number.isFinite(earned)) return earned > Number(p.paid_amount ?? 0);
  return p.status === 'EARNED' && !p.paid;
}

/** Opens WhatsApp with the message typed in; the caller falls back to Share. */
export function whatsappUrl(message: string): string {
  return `whatsapp://send?text=${encodeURIComponent(message)}`;
}

export type ReferralTab = 'active' | 'earned' | 'expired';

export function tabOf(status: ReferralStatus): ReferralTab {
  if (status === 'EARNED') return 'earned';
  if (status === 'EXPIRED' || status === 'CANCELLED') return 'expired';
  return 'active';
}

/** Where each step sits along the progress bar, as a fraction of the last. */
export function stepMarkers(
  steps: { deliveries: number }[],
  required: number,
): number[] {
  if (required <= 0) return [];
  return steps.map(s => Math.min(1, s.deliveries / required));
}

/** The first step not yet earned, or null when every step is. */
export function nextStep(p: ReferralProgress): ReferralStepProgress | null {
  return p.steps?.find(s => !s.earned) ?? null;
}

export type JoiningCard =
  | { mode: 'progress'; deliveries: number; amount: string }
  | { mode: 'earned'; pending: number };

/**
 * What the joining-bonus card says: the next step while the clock runs;
 * otherwise only money earned and not yet paid - an expired referral must
 * never show a progress bar for a step that can no longer be reached.
 */
export function joiningCardState(
  p: ReferralProgress | null,
): JoiningCard | null {
  if (!p || !showsJoiningCard(p)) return null;
  const next = nextStep(p);
  if (p.status === 'IN_PROGRESS' && next) {
    return {
      mode: 'progress',
      deliveries: next.deliveries,
      amount: next.amount,
    };
  }
  const pending =
    Math.round((Number(p.earned_amount) - Number(p.paid_amount || 0)) * 100) /
    100;
  return pending > 0 ? { mode: 'earned', pending } : null;
}
