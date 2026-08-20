/** Presentation rules shared by every panel on the AI Manager screen.
 *
 * These mirror the backend's own rules so the same movement cannot be described
 * two different ways on one screen. Where a number is decided, the backend
 * decides it; what is decided here is only how it reads.
 */

/** Mirrors `insights_misleading_percent_change` in the backend settings.
 *
 * Above this, a percentage says more about how quiet the earlier period was
 * than about the business: a week with one order followed by a normal week
 * reads as "up 2859.6%". */
export const MISLEADING_PERCENT_CHANGE = 300;

/** Whether a percentage change would mislead more than it informs. */
export function percentIsMisleading(
  previous: number | null | undefined,
  percentChange: number | null | undefined,
): boolean {
  if (percentChange === null || percentChange === undefined) {
    return false;
  }
  if (previous !== null && previous !== undefined && Math.abs(previous) < 1e-9) {
    return true;
  }
  return Math.abs(percentChange) >= MISLEADING_PERCENT_CHANGE;
}

export interface PeriodOption {
  days: number;
  label: string;
  /** How an owner would say it in a sentence, for the "covers" line. */
  phrase: string;
}

/** The windows the screen offers. One list, so every panel agrees. */
export const PERIOD_OPTIONS: PeriodOption[] = [
  { days: 7, label: '7 days', phrase: 'the last 7 days' },
  { days: 30, label: '30 days', phrase: 'the last 30 days' },
  { days: 90, label: '3 months', phrase: 'the last 3 months' },
];

export const DEFAULT_PERIOD_DAYS = 90;

/** Whether an insight's own period overlaps the window on screen.
 *
 * Findings are produced by runs with their own windows, so a feed filtered to
 * exact equality would usually be empty. Overlap is the honest test, and
 * anything outside it is shown separately rather than silently mixed in. */
export function overlapsPeriod(
  insightStart: string,
  insightEnd: string,
  windowStart: string,
  windowEnd: string,
): boolean {
  return insightStart <= windowEnd && insightEnd >= windowStart;
}
