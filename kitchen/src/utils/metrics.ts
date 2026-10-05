import type { BoardFilter } from '@/data/boardFilters';
import type { KitchenOrder } from '@/types/app';
import { urgencyOf, waitingMinutes } from '@utils/board';

// The numbers above the board, counted from exactly the tickets on screen.
// Nothing is fetched or estimated: a metric that disagrees with the column
// under it is worse than no metric.
export interface BoardMetrics {
  overdue: number;
  // MEDIAN minutes waited across live tickets, null when the board is empty.
  // Median, because one ticket stuck at 90 minutes drags a mean into
  // describing a kitchen nobody is standing in. And "wait", not "prep time":
  // it counts from when the customer ordered, because the backend records no
  // start-of-cooking instant.
  medianWait: number | null;
  total: number;
}

const median = (values: number[]): number | null => {
  if (values.length === 0) {
    return null;
  }
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? Math.round((sorted[middle - 1] + sorted[middle]) / 2)
    : sorted[middle];
};

export const boardMetrics = (
  orders: readonly KitchenOrder[],
  now: Date = new Date(),
): BoardMetrics => ({
  overdue: orders.filter(order => urgencyOf(order, now) === 'late').length,
  medianWait: median(orders.map(order => waitingMinutes(order, now))),
  total: orders.length,
});

// The badge a ticket wears. Derived from how long it has waited because the
// backend has no priority column, and a word on screen with nothing behind
// it is worse than none.
export const priorityLabel = (order: KitchenOrder, now: Date = new Date()): string | null => {
  switch (urgencyOf(order, now)) {
    case 'late':
      return 'URGENT';
    case 'due':
      return 'SOON';
    default:
      return null;
  }
};

// Whether a ticket survives the filter and search. The search matches the
// order code as a person reads it aloud — with or without '#', any case —
// because the receipt is what a customer is holding when they ring.
export const matchesFilter = (
  order: KitchenOrder,
  filter: BoardFilter,
  search: string,
  now: Date = new Date(),
): boolean => {
  const query = search.trim().replace(/^#/, '').toLowerCase();
  if (query && !order.id.toLowerCase().startsWith(query)) {
    return false;
  }
  switch (filter) {
    case 'DELIVERY':
      return order.fulfillment_type === 'DELIVERY';
    case 'PICKUP':
      return order.fulfillment_type === 'PICKUP';
    case 'PRIORITY':
      return urgencyOf(order, now) !== 'calm';
    default:
      return true;
  }
};
