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
function headerLabel(day: string, now: Date): string {
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
        label: headerLabel(day, now),
        total: 0,
        count: 0,
      };
      rows.push(current);
    }
    current.total =
      Math.round((current.total + Number(trip.earning || 0)) * 100) / 100;
    current.count += 1;
    rows.push({ kind: 'trip', key: trip.id, trip });
  }
  return rows;
}
