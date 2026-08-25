/**
 * Status badge logic, kept out of `StatusPill.tsx` so that file exports a
 * component and nothing else - which is what React Fast Refresh requires to
 * hot-swap it without remounting the tree.
 */
import type { OrderStatus } from '../types/app';

export type StatusPillTone =
  | 'success'
  | 'warning'
  | 'info'
  | 'primary'
  | 'danger'
  | 'neutral'
  | 'muted';


export function resolveStatusPillTone(status: string | OrderStatus): StatusPillTone {
  const normalized = status.toUpperCase();

  // Payment states resolve first. Falling through to the generic chain below
  // would render an unpaid or cancelled order as a plain grey pill, visually
  // identical to a live one.
  if (normalized === 'PAYMENT_PENDING') {
    return 'warning';
  }
  if (normalized === 'CANCELLED' || normalized === 'FAILED') {
    return 'danger';
  }
  if (normalized === 'PAID' || normalized === 'COD') {
    return 'success';
  }
  if (normalized === 'REFUNDED') {
    return 'info';
  }
  // Live, but not yet acted on. Kept out of `muted`, which is for dormant
  // states: as `muted` this was pixel-identical to ARCHIVED and EXPIRED, so a
  // brand new order read as a dead one.
  if (normalized === 'PLACED') {
    return 'neutral';
  }
  // ENABLED / DISABLED are rendered as a pair on the location screens. DISABLED
  // was already `danger`; ENABLED fell through to `muted`, so the "on" half of
  // the pair read as the most inert thing on the page.
  if (normalized === 'ENABLED') {
    return 'success';
  }
  // The dashboard's AI-health indicator is `failures > 0 ? AMBER : CLEAR`. Both
  // fell through to `muted`, so the two opposite outcomes rendered identically
  // and the indicator said nothing at all.
  if (normalized === 'AMBER') {
    return 'warning';
  }
  if (normalized === 'CLEAR') {
    return 'success';
  }

  return normalized === 'DELIVERED' ||
    normalized === 'APPROVED' ||
    normalized === 'OPEN' ||
    normalized === 'ACTIVE' ||
    normalized === 'LIVE' ||
    normalized === 'PUBLISHED' ||
    normalized === 'SUCCESS' ||
    normalized === 'AVAILABLE'
    ? 'success'
    : normalized === 'OUT_FOR_DELIVERY'
      ? 'info'
      : normalized === 'PREPARING' ||
          normalized === 'PENDING' ||
          normalized === 'NEW' ||
          normalized === 'DRAFT' ||
          normalized === 'PAUSED' ||
          normalized === 'BESTSELLER' ||
          normalized === 'BEST SELLER' ||
          normalized.startsWith('5 STAR') ||
          normalized.startsWith('4 STAR')
        ? 'warning'
        : normalized === 'ACCEPTED' || normalized === 'ADMIN'
          ? 'primary'
          : normalized === 'CLOSED' ||
              normalized === 'INACTIVE' ||
              normalized === 'ARCHIVED' ||
              normalized === 'HIDDEN'
            ? 'muted'
            : normalized === 'DISABLED'
              ? 'danger'
              : normalized === 'EXPIRED'
                ? 'muted'
                : normalized === 'FAILURE'
                  ? 'danger'
                  : normalized.endsWith('MS')
                    ? 'info'
                    : 'muted';
}

/**
 * Turns a raw status into its display label.
 *
 * Enum values arrive as SCREAMING_SNAKE_CASE and used to be rendered as-is,
 * leaning on CSS `text-transform: capitalize` to tidy them. That never worked:
 * `capitalize` only upper-cases the first letter of each word and leaves the
 * rest alone, so "OUT_FOR_DELIVERY" rendered as "OUT FOR DELIVERY" - a wall of
 * caps, and much of why these chips were so wide.
 *
 * Sentence case is shorter and easier to scan. Labels that are already
 * mixed-case were written for display by their caller ("3 orders", "Planned"),
 * so they pass through untouched.
 */
/**
 * Words that must survive sentence-casing intact. Without this, COD - cash on
 * delivery, and a payment status shown on every order - renders as "Cod".
 */
const PRESERVED_ACRONYMS = new Set(['COD', 'OTP', 'AI', 'SMS', 'VIP', 'POS']);

export function formatStatusLabel(status: string): string {
  const spaced = status.replaceAll('_', ' ').trim();
  if (spaced !== spaced.toUpperCase()) {
    return spaced;
  }
  const words = spaced.split(' ');
  return words
    .map((word, index) => {
      if (PRESERVED_ACRONYMS.has(word)) {
        return word;
      }
      const lowered = word.toLowerCase();
      return index === 0 ? lowered.charAt(0).toUpperCase() + lowered.slice(1) : lowered;
    })
    .join(' ');
}
