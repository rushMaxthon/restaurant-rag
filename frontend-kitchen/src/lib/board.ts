/**
 * The board's rules, with no React and no network in them.
 *
 * All of this used to be the kind of thing that lives inside a component and
 * can only be checked by watching a kitchen screen during a rush. The three
 * decisions here are worth pinning: which column an order belongs in, which
 * tickets are new since the last poll, and when one is late.
 */

import type { KitchenOrder, OrderStatus } from './api'

/**
 * The linear flow, mirroring `ORDER_STATUS_FLOW` in
 * `backend/app/services/orders.py`.
 *
 * The server refuses anything that is not the single legal next status, so
 * this is not a second opinion — it is what lets the button say the right verb
 * before the customer's food is anywhere near it.
 */
const FLOW: Partial<Record<OrderStatus, OrderStatus>> = {
  PLACED: 'ACCEPTED',
  ACCEPTED: 'PREPARING',
  PREPARING: 'OUT_FOR_DELIVERY',
  OUT_FOR_DELIVERY: 'DELIVERED',
}

export function nextStatus(status: OrderStatus): OrderStatus | null {
  return FLOW[status] ?? null
}

/**
 * What the button says, worded for the person pressing it.
 *
 * A pickup order passes through OUT_FOR_DELIVERY too, because the backend runs
 * one flow for both — so naming the status would tell a cook packing a
 * collection order that it is "out for delivery".
 */
export function advanceLabel(order: Pick<KitchenOrder, 'status' | 'fulfillment_type'>): string | null {
  const isDelivery = order.fulfillment_type === 'DELIVERY'
  switch (order.status) {
    case 'PLACED':
      return 'Accept'
    case 'ACCEPTED':
      return 'Start cooking'
    case 'PREPARING':
      return isDelivery ? 'Hand to rider' : 'Ready for pickup'
    case 'OUT_FOR_DELIVERY':
      return isDelivery ? 'Delivered' : 'Collected'
    default:
      return null
  }
}

/**
 * The columns a kitchen actually works in, in the order the work happens.
 *
 * `blurb` is the second line of the column's EMPTY state, so each one is
 * written as reassurance rather than as a definition — an empty rail during
 * service should read as "you are on top of it", not as a screen that failed
 * to load.
 */
/**
 * How far back the live queue reaches, measured on when an order is DUE.
 *
 * A kitchen board is a view of the current service, not of everything that was
 * ever ordered and never worked. Without a bound it grows forever: this branch
 * had 206 tickets in "New", 178 of them more than a week old, and because the
 * board asks for a fixed-size page of them oldest-first, orders placed after
 * the hundredth simply never appeared. The window is what stops that
 * recurring — the page limit then bounds a queue that is already small.
 *
 * 24 hours covers an overnight pass and a ticket that ran late, without
 * carrying yesterday's abandoned work onto today's rail. Nothing is deleted or
 * cancelled by this: orders outside the window stay exactly as they are and
 * stay visible to the owner, they are just not this service's work.
 */
export const LIVE_WINDOW_HOURS = 24

/** The `due_from` the board asks for, as the API's ISO-8601 instant. */
export function liveWindowStart(now: Date = new Date()): string {
  return new Date(now.getTime() - LIVE_WINDOW_HOURS * 60 * 60 * 1000).toISOString()
}

/**
 * The page the server returned, in the order a kitchen works it.
 *
 * The request asks for `placed_at:desc` and this puts it back to oldest-first,
 * which is what the rail has always shown and what FIFO means at a pass. The
 * round trip is not pointless: sort direction decides which end of an
 * over-long queue survives the page limit. Ascending drops the NEWEST, which
 * is precisely how a just-placed order became invisible. Descending drops the
 * oldest instead, so the ticket a customer is waiting on right now is in the
 * payload whatever the queue length — and `hiddenCount` below makes sure the
 * dropped ones are reported rather than silently missing.
 */
export function inServiceOrder<T>(rows: readonly T[]): T[] {
  return [...rows].reverse()
}

/**
 * How many orders match the column but did not fit in the page.
 *
 * Reported to the cook rather than swallowed. A board that shows 200 of 260
 * and says nothing is the original bug wearing a different number.
 */
export function hiddenCount(total: number, shown: number): number {
  return Math.max(0, total - shown)
}

export const BOARD_COLUMNS: { status: OrderStatus; title: string; blurb: string }[] = [
  { status: 'PLACED', title: 'New', blurb: 'You’re all caught up' },
  { status: 'ACCEPTED', title: 'Accepted', blurb: 'Nothing waiting to start' },
  { status: 'PREPARING', title: 'Cooking', blurb: 'The pass is clear' },
  { status: 'OUT_FOR_DELIVERY', title: 'Ready', blurb: 'Nothing waiting to go out' },
]

/**
 * How long this ticket has been waiting, in whole minutes.
 *
 * Measured from `placed_at` for an ASAP order. A SCHEDULED order has not
 * started waiting until the time it was booked for, so counting from when it
 * was placed would show a lunch order booked at 9am as two hours late before
 * anyone was supposed to touch it.
 */
export function waitingMinutes(order: KitchenOrder, now: Date = new Date()): number {
  const from =
    order.schedule_type === 'SCHEDULED' && order.scheduled_at
      ? new Date(order.scheduled_at)
      : new Date(order.placed_at)
  if (Number.isNaN(from.getTime())) return 0
  const elapsed = Math.floor((now.getTime() - from.getTime()) / 60000)
  // A scheduled order due later is not waiting at all; negative minutes would
  // render as "-38m ago", which reads as a bug rather than as "not yet".
  return elapsed > 0 ? elapsed : 0
}

/**
 * A waiting time as a kitchen would say it out loud.
 *
 * `waitingMinutes` counts in minutes because that is the unit every threshold
 * is written in, but rendering the raw number breaks down on exactly the
 * tickets that matter most. A forgotten order showed as "132388m" on this
 * board — ninety-two days, printed as a five-figure minute count, which is
 * both unreadable and somehow less alarming than "92d".
 *
 * Under an hour stays in minutes, because that is the range a cook is
 * actually working in and "1h 04m" is worse there than "64m" would be at
 * 64 minutes.
 */
export function formatWait(minutes: number): string {
  if (minutes <= 0) return 'now'
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    const rest = minutes % 60
    return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`
  }
  const days = Math.floor(hours / 24)
  return days < 7 ? `${days}d ${hours % 24}h` : `${days}d`
}

/** Thresholds in minutes, per column. Later stages get less patience. */
const OVERDUE_AFTER: Partial<Record<OrderStatus, number>> = {
  PLACED: 5,
  ACCEPTED: 10,
  PREPARING: 25,
  OUT_FOR_DELIVERY: 45,
}

export type Urgency = 'calm' | 'due' | 'late'

/**
 * How loudly a ticket should ask to be looked at.
 *
 * Three states rather than a boolean, because a board where everything is
 * either white or red has no way to say "this one next" — which is the
 * question a cook is actually asking when they glance at it.
 */
export function urgencyOf(order: KitchenOrder, now: Date = new Date()): Urgency {
  const limit = OVERDUE_AFTER[order.status]
  if (limit === undefined) return 'calm'
  const waited = waitingMinutes(order, now)
  if (waited >= limit) return 'late'
  if (waited >= limit * 0.6) return 'due'
  return 'calm'
}

/**
 * Which tickets appeared since the last poll.
 *
 * Returned rather than acted on so the caller decides what a new ticket is
 * worth — a sound, a flash, or nothing at all on the very first load, when
 * every ticket is "new" and a kitchen does not want a fanfare for a board it
 * just opened.
 */
export function newlyArrived(previousIds: ReadonlySet<string>, current: KitchenOrder[]): string[] {
  return current.filter((order) => !previousIds.has(order.id)).map((order) => order.id)
}

/** A stable id set for the next comparison. */
export function idsOf(orders: KitchenOrder[]): Set<string> {
  return new Set(orders.map((order) => order.id))
}

/**
 * The short code a kitchen calls an order by.
 *
 * The same first eight characters the customer app prints on their receipt
 * (`orderCode` in `frontend-customer/src/lib/bangkok-data.ts`), so a customer
 * reading a number aloud on the phone and the ticket on the rail agree.
 */
export function orderCode(order: Pick<KitchenOrder, 'id'>): string {
  return `#${order.id.slice(0, 8).toUpperCase()}`
}

/**
 * The one line under a dish that says how it differs from the menu default.
 *
 * Half-and-half is spelled out rather than flattened: "Pepperoni (left)" is
 * the difference between a correct pizza and a remake.
 */
export function lineDetail(line: {
  selected_size_name?: string | null
  selected_options?: { option_name: string; portion?: string | null }[] | null
}): string | null {
  const parts: string[] = []
  if (line.selected_size_name) parts.push(line.selected_size_name)
  for (const option of line.selected_options ?? []) {
    const portion = option.portion && option.portion !== 'WHOLE' ? option.portion.toLowerCase() : null
    parts.push(portion ? `${option.option_name} (${portion})` : option.option_name)
  }
  return parts.length ? parts.join(' · ') : null
}
