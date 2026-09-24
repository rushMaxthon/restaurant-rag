/**
 * The numbers along the top of the board.
 *
 * Every one is counted from the tickets already on screen — nothing here asks
 * the server for a statistic it does not publish, and nothing is estimated.
 * A kitchen metric that disagrees with the column under it is worse than no
 * metric at all, so they are derived from exactly the same rows.
 */

import type { KitchenOrder, OrderStatus } from './api'
import { urgencyOf, waitingMinutes } from './board'

export interface BoardMetrics {
  newCount: number
  acceptedCount: number
  cookingCount: number
  readyCount: number
  /** Tickets past their column's threshold — the number worth reacting to. */
  overdue: number
  /**
   * Median minutes a live ticket has been waiting, or null when the board is
   * empty.
   *
   * MEDIAN, not mean: one ticket stuck at 90 minutes drags an average far
   * enough to describe a kitchen that is not the one anybody is standing in.
   *
   * And "waiting", not "prep time": this counts from `placed_at`, which is
   * when the customer ordered, not from when a cook picked the ticket up. The
   * backend records no start-of-cooking instant, so a genuine prep time is not
   * something this app can know — and labelling this one as prep time would be
   * a claim about kitchen performance built on the wrong clock.
   */
  medianWait: number | null
}

function median(values: number[]): number | null {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0
    ? Math.round(((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2)
    : (sorted[middle] ?? 0)
}

export function boardMetrics(
  columns: { status: OrderStatus; orders: KitchenOrder[] }[],
  now: Date = new Date(),
): BoardMetrics {
  const at = (status: OrderStatus) =>
    columns.find((column) => column.status === status)?.orders ?? []

  const everything = columns.flatMap((column) => column.orders)

  return {
    newCount: at('PLACED').length,
    acceptedCount: at('ACCEPTED').length,
    cookingCount: at('PREPARING').length,
    readyCount: at('OUT_FOR_DELIVERY').length,
    overdue: everything.filter((order) => urgencyOf(order, now) === 'late').length,
    medianWait: median(everything.map((order) => waitingMinutes(order, now))),
  }
}

/**
 * The badge a ticket wears, or none.
 *
 * Deliberately derived from how long it has waited rather than read off a
 * field: this backend has no priority column, and inventing one would put a
 * word on screen that nothing behind it can justify. What a kitchen actually
 * means by "urgent" is "this one has been sitting too long", which is exactly
 * what `urgencyOf` already answers.
 */
export function priorityLabel(order: KitchenOrder, now: Date = new Date()): string | null {
  switch (urgencyOf(order, now)) {
    case 'late':
      return 'URGENT'
    case 'due':
      return 'HIGH'
    default:
      return null
  }
}

/** Filters the toolbar offers. Only ones this data can honestly answer. */
export type BoardFilter =
  | 'ALL'
  | 'PLACED'
  | 'ACCEPTED'
  | 'PREPARING'
  | 'OUT_FOR_DELIVERY'
  | 'DELIVERY'
  | 'PICKUP'
  | 'PRIORITY'

/**
 * Whether a ticket survives the toolbar.
 *
 * The search half matches the order code the way a person reads it aloud —
 * with or without the leading `#`, in any case — because the number on a
 * customer's receipt is the one thing somebody will be holding when they ring
 * the kitchen.
 */
export function matchesFilter(
  order: KitchenOrder,
  filter: BoardFilter,
  search: string,
  now: Date = new Date(),
): boolean {
  const query = search.trim().replace(/^#/, '').toLowerCase()
  if (query && !order.id.toLowerCase().startsWith(query)) {
    return false
  }

  switch (filter) {
    case 'ALL':
      return true
    case 'DELIVERY':
      return order.fulfillment_type === 'DELIVERY'
    case 'PICKUP':
      return order.fulfillment_type === 'PICKUP'
    case 'PRIORITY':
      return urgencyOf(order, now) !== 'calm'
    default:
      return order.status === filter
  }
}
