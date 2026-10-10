/**
 * Refer & earn, the parts with no screen (backend `fleet/referral.py`).
 */

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
