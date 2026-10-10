/**
 * The Riders page's form rules, kept out of the page so they can be tested
 * without rendering a form.
 *
 * The backend owns every one of them (`services/fleet/riders.py`,
 * `services/fleet/config.py`): it stores the number as +91XXXXXXXXXX, refuses
 * a password under eight characters and a pay rate that pays nothing. These
 * repeat them only so a mistake shows beside the field instead of as a 422
 * after Save.
 */

import type { FleetBranch, RiderPay, RiderVehicle } from '../types/app';

export const MIN_PASSWORD = 8;

export interface RiderDraft {
  full_name: string;
  phone: string;
  password: string;
  vehicle_type: RiderVehicle;
  vehicle_number: string;
  city: string;
  notes: string;
}

export type RiderFormErrors = Partial<Record<keyof RiderDraft, string>>;

export function emptyRiderDraft(): RiderDraft {
  return { full_name: '', phone: '', password: '', vehicle_type: 'BIKE', vehicle_number: '', city: '', notes: '' };
}

/** The last ten digits of whatever was typed: "+91 98765-43210" -> "9876543210". */
export function tenDigits(value: string): string {
  return value.replace(/\D/g, '').slice(-10);
}

export function riderFormErrors(draft: RiderDraft, mode: 'create' | 'edit'): RiderFormErrors {
  const errors: RiderFormErrors = {};
  if (!draft.full_name.trim()) errors.full_name = 'Enter the rider’s name.';
  if (tenDigits(draft.phone).length !== 10) errors.phone = 'Enter a 10-digit mobile number.';
  if (mode === 'create' && draft.password.length < MIN_PASSWORD) {
    errors.password = `At least ${MIN_PASSWORD} characters.`;
  }
  if (mode === 'edit' && draft.password && draft.password.length < MIN_PASSWORD) {
    errors.password = `At least ${MIN_PASSWORD} characters, or leave it empty to keep the current one.`;
  }
  return errors;
}

function amount(value: string): number | null {
  if (value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** The rate card as the form edits it: every field a string, so a half-typed number stays put. */
export interface PayDraft {
  slabs: Array<{ up_to_km: string; amount: string }>;
  incentive: string;
  minimum: string;
}

export function payDraftFrom(pay: RiderPay): PayDraft {
  return {
    slabs: pay.slabs.map((slab) => ({ up_to_km: String(slab.up_to_km), amount: String(Number(slab.amount)) })),
    incentive: String(Number(pay.incentive)),
    minimum: String(Number(pay.minimum)),
  };
}

export function payFromDraft(draft: PayDraft): RiderPay {
  return {
    slabs: draft.slabs.map((slab) => ({ up_to_km: Number(slab.up_to_km), amount: slab.amount.trim() })),
    incentive: draft.incentive.trim(),
    minimum: draft.minimum.trim(),
  };
}

const inRange = (value: number) => value >= 0 && value <= 1000;

/** The server's rules (`fleet/config.validate_pay`), so a mistake shows before Save. */
export function payFormError(draft: PayDraft): string | null {
  if (draft.slabs.length === 0) return 'Add at least one distance slab.';
  if (draft.slabs.length > 40) return 'At most 40 distance slabs.';
  let previous: { km: number; pay: number } | null = null;
  for (const slab of draft.slabs) {
    const km = amount(slab.up_to_km);
    const pay = amount(slab.amount);
    if (km === null || pay === null) return 'Every slab needs a distance and an amount.';
    if (km <= 0 || km > 50) return 'A slab’s distance must be between 0 and 50 km.';
    if (!inRange(pay)) return 'Pay amounts must be between ₹0 and ₹1,000.';
    if (previous && km <= previous.km) return 'Each slab must go further than the one before it.';
    if (previous && pay < previous.pay) return 'A longer slab cannot pay less than a shorter one.';
    previous = { km, pay };
  }
  const incentive = amount(draft.incentive);
  const minimum = amount(draft.minimum);
  if (incentive === null || minimum === null) return 'The incentive and the cancelled-ride pay need a number.';
  if (!inRange(incentive) || !inRange(minimum)) return 'Pay amounts must be between ₹0 and ₹1,000.';
  if (incentive === 0 && draft.slabs.every((slab) => amount(slab.amount) === 0)) {
    return 'A delivery must pay the rider something.';
  }
  return null;
}

/**
 * What a delivered trip of `km` pays - the same sum the server makes
 * (`fleet/earnings.earning_for`): km to one decimal, the top of a slab
 * belongs to it, plus the incentive. Past the last slab: 'manual'.
 */
export function payExample(draft: PayDraft, km: number): number | 'manual' | null {
  if (payFormError(draft)) return null;
  const rounded = Math.round(Math.max(km, 0) * 10) / 10;
  const incentive = Number(draft.incentive);
  for (const slab of draft.slabs) {
    if (rounded <= Number(slab.up_to_km)) return Math.round((Number(slab.amount) + incentive) * 100) / 100;
  }
  return 'manual';
}

export function lastSeenLabel(iso: string | null, now: Date = new Date()): string {
  if (!iso) return 'Never';
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86_400)} d ago`;
}

export const VEHICLE_LABEL: Record<RiderVehicle, string> = {
  BIKE: 'Motorbike',
  SCOOTER: 'Scooter',
  // A low-speed e-scooter needs no licence or RC, which is why sign-up offers
  // it as its own type and asks for neither.
  EV_SCOOTER: 'E-scooter (low-speed)',
  CYCLE: 'Bicycle',
};

/**
 * Why the server refused to move an order to this rider, in words. The codes
 * are a contract with `offers.reassign`; one order, one rider (2026-10-08).
 */
const REASSIGN_ERRORS: Record<string, string> = {
  rider_has_it: 'Another rider has this order and is still active. It can only move if they go silent before pickup.',
  food_picked_up: 'The rider has already picked up the food, so it stays with them.',
  rider_offline: 'That rider has just gone offline.',
  rider_busy: 'That rider is already answering another order.',
  courier_has_it: 'A Pidge rider has this order. Cancel it there first.',
  delivery_finished: 'This order is already finished.',
};

export function reassignErrorMessage(detail: unknown, fallback = 'Please try again.'): string {
  return (typeof detail === 'string' && REASSIGN_ERRORS[detail]) || fallback;
}

/** Add or remove one branch; sorted so saving the same set twice is not "changed". */
export function toggleBranch(ids: string[], id: string): string[] {
  const next = ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];
  return next.sort();
}

/**
 * What the allowlist means, in words. Empty is EVERY branch (the backend's
 * rule in `fleet/config.py`), which is the opposite of what an empty list of
 * checkboxes looks like - so the screen has to say it.
 */
export function branchScopeLabel(ids: string[], branches: FleetBranch[]): string {
  if (ids.length === 0) return 'Every branch';
  const named = branches.filter((b) => ids.includes(b.id)).length;
  return `${named} of ${branches.length} ${branches.length === 1 ? 'branch' : 'branches'}`;
}
