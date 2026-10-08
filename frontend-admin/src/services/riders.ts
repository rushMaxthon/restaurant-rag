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

import type { RiderPay, RiderVehicle } from '../types/app';

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

export function payFormError(pay: RiderPay): string | null {
  const parts = [amount(pay.base), amount(pay.per_km), amount(pay.minimum)];
  if (parts.some((part) => part === null)) return 'Every pay field needs a number.';
  if (parts.some((part) => (part as number) < 0 || (part as number) > 1000)) return 'Pay amounts must be between ₹0 and ₹1,000.';
  if (parts.every((part) => part === 0)) return 'A trip must pay the rider something.';
  return null;
}

/** What a trip of `km` pays at these rates - the same sum the server makes. */
export function payExample(pay: RiderPay, km: number): number | null {
  const base = amount(pay.base);
  const perKm = amount(pay.per_km);
  const minimum = amount(pay.minimum);
  if (base === null || perKm === null || minimum === null) return null;
  return Math.round(Math.max(minimum, base + perKm * km) * 100) / 100;
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
