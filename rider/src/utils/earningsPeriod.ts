import { rupees } from './format';

/** The Earnings screen's period switch: what the server is asked for, and how the hero is labelled. */

export type PeriodKey = 'today' | 'week' | 'month';

export type Period = {
  key: PeriodKey;
  label: string;
  heroLabel: string;
  days: number;
};

export const PERIODS: readonly Period[] = [
  { key: 'today', label: 'Today', heroLabel: 'TODAY', days: 1 },
  { key: 'week', label: '7 days', heroLabel: 'LAST 7 DAYS', days: 7 },
  { key: 'month', label: '30 days', heroLabel: 'LAST 30 DAYS', days: 30 },
];

export function periodFor(key: PeriodKey): Period {
  return PERIODS.find(p => p.key === key) ?? PERIODS[1]!;
}

/** One bar is not a chart. */
export function showsChart(key: PeriodKey): boolean {
  return periodFor(key).days > 1;
}

/**
 * The one line under the hero total. The average is whole rupees: it is a
 * feel for the period, and the exact amounts are on every delivery.
 */
export function heroLine(trips: number, total: string | number): string {
  if (trips <= 0) return 'No deliveries yet';
  if (trips === 1) return '1 delivery';
  return `${trips} deliveries · ${rupees(Math.round(Number(total) / trips))} each`;
}
