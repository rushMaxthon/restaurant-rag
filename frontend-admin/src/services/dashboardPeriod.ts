/**
 * Which stretch of time the dashboard is reading, for the platform admin and
 * the owner alike.
 *
 * The dashboard offered "last 7 days" and "last 30 days" and nothing else, so
 * "how did yesterday go?" or "what did we take in September?" had no answer
 * on the screen meant to answer it. Pure, so every rule here - what a period
 * starts and ends on, what it is compared against, how its chart is cut - is
 * tested without rendering a page.
 *
 * Two rules worth knowing:
 *
 * - A period still under way (today, this month, this year) is compared with
 *   the SAME elapsed stretch of the one before. Half of October against all
 *   of September would read as a collapse every month.
 * - Times are the browser's own, which for this platform is the kitchen's.
 */

export type PeriodKind =
  | "today"
  | "yesterday"
  | "last7"
  | "last30"
  | "thisMonth"
  | "lastMonth"
  | "month"
  | "year"
  | "custom";

export interface DashboardPeriod {
  kind: PeriodKind;
  /** "YYYY-MM", for `month`. */
  month?: string;
  /** For `year`. */
  year?: number;
  /** "YYYY-MM-DD", both days included, for `custom`. */
  from?: string;
  to?: string;
}

export interface PeriodRange {
  start: Date;
  /** Exclusive. Never later than now. */
  end: Date;
  previousStart: Date;
  previousEnd: Date;
  /** "Today", "September 2026", "2025". */
  label: string;
  /** "vs yesterday", "vs September 2026". */
  comparison: string;
  /** How the chart is cut. */
  bucket: "hour" | "day" | "month";
}

export interface PeriodBucket {
  start: Date;
  end: Date;
  label: string;
  meta: string;
}

export const PERIOD_OPTIONS: Array<{ kind: PeriodKind; label: string }> = [
  { kind: "today", label: "Today" },
  { kind: "yesterday", label: "Yesterday" },
  { kind: "last7", label: "Last 7 days" },
  { kind: "last30", label: "Last 30 days" },
  { kind: "thisMonth", label: "This month" },
  { kind: "lastMonth", label: "Last month" },
  { kind: "month", label: "Pick a month…" },
  { kind: "year", label: "Pick a year…" },
  { kind: "custom", label: "Custom dates…" },
];

const KINDS = new Set<PeriodKind>(PERIOD_OPTIONS.map((option) => option.kind));

export const DEFAULT_PERIOD: DashboardPeriod = { kind: "last7" };

const monthName = new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" });
const dayName = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });

function midnight(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days, date.getHours(), date.getMinutes());
}

function addMonths(date: Date, months: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + months, 1);
}

function parseDay(value: string | undefined): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? "");
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function parseMonth(value: string | undefined): Date | null {
  const match = /^(\d{4})-(\d{2})$/.exec(value ?? "");
  if (!match) return null;
  const month = Number(match[2]);
  return month >= 1 && month <= 12 ? new Date(Number(match[1]), month - 1, 1) : null;
}

/**
 * A period that may still be running: cut at now, and compared with the same
 * elapsed stretch of the period before it.
 */
function bounded(
  start: Date,
  naturalEnd: Date,
  previousStart: Date,
  now: Date,
  rest: Pick<PeriodRange, "label" | "comparison" | "bucket">,
): PeriodRange {
  // Every previous period here ends where this one starts.
  if (naturalEnd <= now) {
    return { start, end: naturalEnd, previousStart, previousEnd: start, ...rest };
  }
  // Still under way: the same elapsed stretch of the previous one, so a 31-day
  // month is never compared with the first 30 days of the month before it.
  const elapsed = now.getTime() - start.getTime();
  const previousEnd = new Date(Math.min(previousStart.getTime() + elapsed, start.getTime()));
  return { start, end: now, previousStart, previousEnd, ...rest };
}

function lastDays(days: number, now: Date, label: string): PeriodRange {
  const start = addDays(midnight(now), -(days - 1));
  return bounded(start, addDays(midnight(now), 1), addDays(start, -days), now, {
    label,
    comparison: `vs the ${days} days before`,
    bucket: "day",
  });
}

export function resolvePeriod(period: DashboardPeriod, now: Date = new Date()): PeriodRange {
  const today = midnight(now);
  switch (period.kind) {
    case "today":
      return bounded(today, addDays(today, 1), addDays(today, -1), now, {
        label: "Today",
        comparison: "vs yesterday",
        bucket: "hour",
      });
    case "yesterday": {
      const start = addDays(today, -1);
      return bounded(start, today, addDays(start, -1), now, {
        label: "Yesterday",
        comparison: "vs the day before",
        bucket: "hour",
      });
    }
    case "last7":
      return lastDays(7, now, "Last 7 days");
    case "last30":
      return lastDays(30, now, "Last 30 days");
    case "thisMonth":
    case "lastMonth":
    case "month": {
      const start =
        period.kind === "thisMonth"
          ? new Date(now.getFullYear(), now.getMonth(), 1)
          : period.kind === "lastMonth"
            ? addMonths(new Date(now.getFullYear(), now.getMonth(), 1), -1)
            : parseMonth(period.month);
      if (!start) return lastDays(7, now, "Last 7 days");
      const previousStart = addMonths(start, -1);
      return bounded(start, addMonths(start, 1), previousStart, now, {
        label: monthName.format(start),
        comparison: `vs ${monthName.format(previousStart)}`,
        bucket: "day",
      });
    }
    case "year": {
      const year = Number(period.year);
      if (!Number.isInteger(year) || year < 2000 || year > 3000) return lastDays(7, now, "Last 7 days");
      return bounded(new Date(year, 0, 1), new Date(year + 1, 0, 1), new Date(year - 1, 0, 1), now, {
        label: String(year),
        comparison: `vs ${year - 1}`,
        bucket: "month",
      });
    }
    case "custom": {
      const a = parseDay(period.from);
      const b = parseDay(period.to);
      if (!a || !b) return lastDays(7, now, "Last 7 days");
      const [first, last] = a <= b ? [a, b] : [b, a];
      const start = first;
      const naturalEnd = addDays(last, 1);
      const length = Math.round((naturalEnd.getTime() - start.getTime()) / 86_400_000);
      const label = length === 1 ? dayName.format(first) : `${dayName.format(first)} – ${dayName.format(last)}`;
      return bounded(start, naturalEnd, addDays(start, -length), now, {
        label,
        comparison: `vs the ${length === 1 ? "day" : `${length} days`} before`,
        bucket: length === 1 ? "hour" : length > 92 ? "month" : "day",
      });
    }
    default:
      return lastDays(7, now, "Last 7 days");
  }
}

const hourLabel = new Intl.DateTimeFormat("en-IN", { hour: "numeric" });
const dayLabel = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
const dayMeta = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short" });
const monthLabel = new Intl.DateTimeFormat("en-IN", { month: "short" });

/** The chart's columns: hours of a day, days of up to a quarter, months beyond. */
export function periodBuckets(range: PeriodRange): PeriodBucket[] {
  const buckets: PeriodBucket[] = [];
  let cursor = new Date(range.start);
  while (cursor < range.end && buckets.length < 400) {
    let next: Date;
    let label: string;
    let meta: string;
    if (range.bucket === "hour") {
      next = new Date(cursor.getTime() + 3_600_000);
      label = hourLabel.format(cursor);
      meta = `${dayMeta.format(cursor)}, ${label}`;
    } else if (range.bucket === "day") {
      next = addDays(midnight(cursor), 1);
      label = dayLabel.format(cursor);
      meta = dayMeta.format(cursor);
    } else {
      next = addMonths(new Date(cursor.getFullYear(), cursor.getMonth(), 1), 1);
      label = monthLabel.format(cursor);
      meta = monthName.format(cursor);
    }
    buckets.push({ start: cursor, end: next, label, meta });
    cursor = next;
  }
  return buckets;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function isoDay(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function isoMonth(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}`;
}

/**
 * The period a newly picked kind opens on, so a choice is never half-made:
 * "Pick a month" lands on last month, "Pick a year" on this one, and custom
 * dates on the last seven days, each ready to change.
 */
export function periodFor(kind: PeriodKind, now: Date = new Date()): DashboardPeriod {
  if (kind === "month") return { kind, month: isoMonth(new Date(now.getFullYear(), now.getMonth() - 1, 1)) };
  if (kind === "year") return { kind, year: now.getFullYear() };
  if (kind === "custom") {
    const from = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6);
    return { kind, from: isoDay(from), to: isoDay(now) };
  }
  return { kind };
}

/** Whether an order counts as a sale: the same rule as the server's revenue. */
export function isSale(order: { status: string }): boolean {
  return order.status !== "PAYMENT_PENDING" && order.status !== "CANCELLED";
}

export function inRange(value: string, start: Date, end: Date): boolean {
  const at = new Date(value).getTime();
  return at >= start.getTime() && at < end.getTime();
}

/** A saved period, or null when what was saved is not one. */
export function parsePeriod(raw: string | null): DashboardPeriod | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<DashboardPeriod>;
    if (!value || typeof value !== "object" || !KINDS.has(value.kind as PeriodKind)) return null;
    const period: DashboardPeriod = { kind: value.kind as PeriodKind };
    if (typeof value.month === "string") period.month = value.month;
    if (typeof value.year === "number") period.year = value.year;
    if (typeof value.from === "string") period.from = value.from;
    if (typeof value.to === "string") period.to = value.to;
    return period;
  } catch {
    return null;
  }
}
