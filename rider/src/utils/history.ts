import type { Trip } from '@/types/api';
import { dayLabel, weekday } from './format';

export type HistoryRow =
  | { kind: 'day'; key: string; label: string; total: number; count: number }
  | { kind: 'trip'; key: string; trip: Trip };

function localDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(
    2,
    '0',
  )}-${String(d.getDate()).padStart(2, '0')}`;
}

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

/** "Today", "Yesterday", else "Mon, 5 Oct" - a bare weekday repeats every week. */
export function dateLabel(day: string, now: Date = new Date()): string {
  const label = dayLabel(day, now);
  if (label === 'Today' || label === 'Yesterday') return label;
  const [, m, d] = day.split('-').map(Number);
  return `${weekday(day)}, ${d} ${MONTHS[(m ?? 1) - 1]}`;
}

/**
 * Finished trips (newest first) with a header before each local day carrying
 * that day's count and total - the way a rider reads their history: "what
 * did I make on Tuesday?".
 */
export function groupByDay(
  trips: Trip[],
  now: Date = new Date(),
): HistoryRow[] {
  const rows: HistoryRow[] = [];
  let current: Extract<HistoryRow, { kind: 'day' }> | null = null;
  for (const trip of trips) {
    const day = localDate(trip.ended_at ?? trip.accepted_at);
    if (!current || current.key !== `day-${day}`) {
      current = {
        kind: 'day',
        key: `day-${day}`,
        label: dateLabel(day, now),
        total: 0,
        count: 0,
      };
      rows.push(current);
    }
    current.total =
      Math.round((current.total + Number(trip.earning || 0)) * 100) / 100;
    // Paid deliveries, the same count the earnings summary and Home show; a
    // trip cancelled before pickup is listed but pays nothing.
    if (Number(trip.earning || 0) > 0) current.count += 1;
    rows.push({ kind: 'trip', key: trip.id, trip });
  }
  return rows;
}

/** The rows FlashList pins while scrolling: every day heading. */
export function dayHeaderIndices(rows: readonly HistoryRow[]): number[] {
  return rows.flatMap((row, i) => (row.kind === 'day' ? [i] : []));
}

/**
 * The first page fetched again on coming back to History, on top of what was
 * already loaded: new trips appear, and the rider keeps the older pages they
 * scrolled to instead of being dropped back to the first twenty.
 */
export function mergeNewest(loaded: readonly Trip[], firstPage: readonly Trip[]): Trip[] {
  const fresh = new Set(firstPage.map(t => t.id));
  return [...firstPage, ...loaded.filter(t => !fresh.has(t.id))];
}
