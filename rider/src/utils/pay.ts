/**
 * The admin's rate card (backend `fleet/config.RiderPay`), read for the rider.
 *
 * A delivery pays the slab its distance falls in plus the incentive; past the
 * last slab the team prices the trip by hand, so the server sends no amount
 * (null) - shown as words, never as ₹0.
 */

import { rupees } from './format';

export type RiderPay = {
  slabs: { up_to_km: number; amount: string }[];
  /** Added for every successful delivery. */
  incentive: string;
  /** A ride to the restaurant for an order then cancelled. */
  minimum: string;
};

export type RateRow = { from: number; to: number; amount: number };

export function rateCard(pay: RiderPay): {
  rows: RateRow[];
  incentive: number;
  lastKm: number;
  lowest: number;
  highest: number;
} {
  const rows = pay.slabs.map((slab, i) => ({
    from: i === 0 ? 0 : pay.slabs[i - 1]?.up_to_km ?? 0,
    to: slab.up_to_km,
    amount: Number(slab.amount),
  }));
  const amounts = rows.map(row => row.amount);
  return {
    rows,
    incentive: Number(pay.incentive),
    lastKm: rows[rows.length - 1]?.to ?? 0,
    lowest: amounts.length ? Math.min(...amounts) : 0,
    highest: amounts.length ? Math.max(...amounts) : 0,
  };
}

/** Rupees, or `later` for a trip past the rate card that has no price yet. */
export function earningLabel(
  value: string | number | null | undefined,
  later: string,
): string {
  return value == null ? later : rupees(value);
}
