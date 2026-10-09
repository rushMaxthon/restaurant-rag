/**
 * The rules behind reviewing a rider's application, kept out of the page so
 * they can be tested without rendering it.
 *
 * Every rule here is also enforced by the server (`fleet/onboarding/
 * applications.py`): this file only decides what to grey out and what to say
 * beside it. A disabled button says why, so each `can*` comes with a reason.
 */

import type { StatusPillTone } from '../components/statusPillUtils';
import type {
  ApplicationEvent,
  ApplicationItem,
  ApplicationItemStatus,
  ApplicationStatus,
  ItemKind,
  RiderApplicationDetail,
} from '../types/app';

export const ITEM_LABELS: Record<ItemKind, string> = {
  PERSONAL: 'Personal details',
  VEHICLE_DETAILS: 'Vehicle details',
  BANK_DETAILS: 'Bank details',
  SELFIE: 'Selfie',
  RC: 'RC (registration)',
  AADHAAR_FRONT: 'Aadhaar front',
  AADHAAR_BACK: 'Aadhaar back',
  PAN: 'PAN card',
  LICENCE_FRONT: 'Driving licence front',
  LICENCE_BACK: 'Driving licence back',
  BANK_PROOF: 'Cheque / passbook',
};

/** One tap for the reasons that cover most flags; anything else is typed. */
export const REASONS: string[] = [
  'Photo is blurry or cut off',
  "Name doesn't match",
  'Document has expired',
  'Wrong document',
  "Details don't match the photo",
];

/**
 * Tones are chosen here rather than left to `StatusPill`'s text matching:
 * SUBMITTED reads "info" there (a payout account), but in this queue it is the
 * one state that is waiting on an admin, so it takes the attention colour.
 */
export const STATUS_META: Record<ApplicationStatus, { label: string; tone: StatusPillTone }> = {
  DRAFT: { label: 'Draft', tone: 'muted' },
  SUBMITTED: { label: 'Submitted', tone: 'warning' },
  CHANGES_NEEDED: { label: 'Changes needed', tone: 'info' },
  APPROVED: { label: 'Approved', tone: 'success' },
  REJECTED: { label: 'Rejected', tone: 'danger' },
};

export const ITEM_STATUS_META: Record<ApplicationItemStatus, { label: string; tone: StatusPillTone }> = {
  MISSING: { label: 'Not uploaded', tone: 'muted' },
  PENDING: { label: 'To review', tone: 'neutral' },
  ACCEPTED: { label: 'Accepted', tone: 'success' },
  NEEDS_CHANGE: { label: 'Needs change', tone: 'danger' },
};

/** Why nothing can be decided right now, for any state but SUBMITTED. */
const NOT_REVIEWABLE: Record<Exclude<ApplicationStatus, 'SUBMITTED'>, string> = {
  DRAFT: 'The rider has not submitted yet',
  CHANGES_NEEDED: 'Waiting for the rider to resubmit',
  APPROVED: 'Already approved',
  REJECTED: 'Rejected - reopen it to review again',
};

/**
 * The server answers `not_required` for an item the application does not
 * need (an RC left over after switching to a bicycle), so those are never
 * offered for review and never count against approval.
 */
export function reviewItems(items: ApplicationItem[]): ApplicationItem[] {
  return items.filter((item) => item.required);
}

export interface DecisionState {
  canReview: boolean;
  canApprove: boolean;
  approveReason: string | null;
  canSendBack: boolean;
  sendBackReason: string | null;
  canReject: boolean;
  canReopen: boolean;
}

export function decisionState(detail: RiderApplicationDetail): DecisionState {
  const items = reviewItems(detail.items);
  const canReview = detail.status === 'SUBMITTED';
  const stateReason = detail.status === 'SUBMITTED' ? null : NOT_REVIEWABLE[detail.status];

  const notAccepted = items.filter((item) => item.status !== 'ACCEPTED').length;
  const flagged = items.filter((item) => item.status === 'NEEDS_CHANGE').length;

  const approveReason =
    stateReason ?? (notAccepted > 0 ? `${notAccepted} ${notAccepted === 1 ? 'item' : 'items'} not accepted yet` : null);
  const sendBackReason = stateReason ?? (flagged === 0 ? 'Flag at least one item' : null);

  return {
    canReview,
    canApprove: approveReason === null,
    approveReason,
    canSendBack: sendBackReason === null,
    sendBackReason,
    // A rider sitting on "changes needed" for a week can still be turned
    // down without waiting for them to resubmit; the server allows both.
    canReject: detail.status === 'SUBMITTED' || detail.status === 'CHANGES_NEEDED',
    canReopen: detail.status === 'REJECTED',
  };
}

/** How long a submission has waited: the queue's oldest-first is easier to read with this beside it. */
export function waitingLabel(submittedAt: string | null, now: Date = new Date()): string {
  if (!submittedAt) return '—';
  const minutes = Math.max(0, (now.getTime() - new Date(submittedAt).getTime()) / 60_000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${Math.floor(minutes)} min`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h`;
  const days = Math.floor(minutes / (24 * 60));
  return `${days} ${days === 1 ? 'day' : 'days'}`;
}

/** The server only ever sends the last four; this makes that obvious on the page. */
export function masked(last4: string): string {
  return last4 ? `•••• ${last4}` : '—';
}

/** Display order of the document cards, with the two-sided ones paired. */
const PHOTO_GROUPS: ItemKind[][] = [
  ['SELFIE'],
  ['AADHAAR_FRONT', 'AADHAAR_BACK'],
  ['PAN'],
  ['LICENCE_FRONT', 'LICENCE_BACK'],
  ['RC'],
  ['BANK_PROOF'],
];

export const GROUP_TITLES: Record<string, string> = {
  SELFIE: 'Selfie',
  AADHAAR_FRONT: 'Aadhaar card',
  PAN: 'PAN card',
  LICENCE_FRONT: 'Driving licence',
  RC: 'RC (registration)',
  BANK_PROOF: 'Cheque / passbook',
};

/**
 * Document cards, front beside back. A front and a back are judged together
 * (does the address on the back belong to the name on the front?), so they
 * share a card rather than sitting apart in a list.
 */
export function photoPairs(items: ApplicationItem[]): ApplicationItem[][] {
  const byKind = new Map(reviewItems(items).map((item) => [item.kind, item]));
  return PHOTO_GROUPS.map((group) => group.map((kind) => byKind.get(kind)).filter((i): i is ApplicationItem => !!i)).filter(
    (group) => group.length > 0,
  );
}

const ACTION_LABELS: Record<ApplicationEvent['action'], string> = {
  SUBMITTED: 'Submitted',
  RESUBMITTED: 'Resubmitted',
  ITEM_ACCEPTED: 'Accepted',
  ITEM_FLAGGED: 'Flagged',
  SENT_BACK: 'Sent back for changes',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  REOPENED: 'Reopened',
};

export function eventLabel(event: ApplicationEvent): string {
  const action = ACTION_LABELS[event.action] ?? event.action;
  return event.item_kind ? `${action} ${ITEM_LABELS[event.item_kind]}` : action;
}

/** The codes `applications.py` answers with, as sentences an admin can act on. */
const ERROR_MESSAGES: Record<string, string> = {
  state_changed: 'Someone else just reviewed this - reloaded.',
  nothing_flagged: 'Flag at least one item before sending it back.',
  not_all_accepted: 'Accept every item before approving.',
  not_required: 'This application does not need that item.',
};

export function applicationErrorMessage(message: string): string {
  return ERROR_MESSAGES[message] ?? message;
}

type Photos = RiderApplicationDetail['photos'];

const pathOf = (url: string) => url.split('?')[0];

/**
 * A new set of signed links, keeping the old link wherever it points at the
 * same file. Every fetch signs afresh, so taking them all would re-download
 * every photo on each live hint - and a rider's location pings arrive as the
 * same hint. The four-minute refresh passes `keep = false` to renew them
 * before the five-minute expiry.
 */
export function mergePhotos(previous: Photos, next: Photos, keep = true): Photos {
  if (!keep) return next;
  const out: Photos = {};
  for (const [kind, url] of Object.entries(next) as [ItemKind, string][]) {
    const old = previous[kind];
    out[kind] = old && pathOf(old) === pathOf(url) ? old : url;
  }
  return out;
}

/** Whole years on `now`, for the "26 years" beside a date of birth. */
export function ageOn(dateOfBirth: string | null, now: Date = new Date()): number | null {
  if (!dateOfBirth) return null;
  const [year, month, day] = dateOfBirth.split('-').map(Number);
  if (!year || !month || !day) return null;
  let age = now.getFullYear() - year;
  const beforeBirthday = now.getMonth() + 1 < month || (now.getMonth() + 1 === month && now.getDate() < day);
  if (beforeBirthday) age -= 1;
  return age;
}
