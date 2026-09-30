/**
 * The order history's rules, with no React and no network in them.
 *
 * Kept apart from `board.ts` because the questions are different: the board
 * asks "what is live right now", history asks "what already went out". Both
 * are scoped by the server the same way; only the window differs.
 */

/** One screen of finished orders. Small enough to scan, big enough for a lunch rush's worth. */
export const HISTORY_PAGE_SIZE = 20

/**
 * Local midnight on the tablet, as the API's ISO-8601 instant.
 *
 * "Today" is the kitchen's day, not UTC's: a board in Bangalore asking from
 * UTC midnight would show yesterday evening's service until 05:30.
 */
export function startOfToday(now: Date = new Date()): string {
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  return midnight.toISOString()
}

/**
 * Which local day it is, for the query key.
 *
 * In the key so the history rolls over at midnight on a screen left open —
 * the midnight instant itself is computed per fetch, like the board's window.
 */
export function localDayKey(now: Date = new Date()): string {
  return `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`
}

/**
 * What the search box sends, or null for "no search".
 *
 * An order code is read aloud with its `#` and printed in capitals; the
 * server matches the id case-insensitively, so only the `#` has to go.
 */
export function searchTerm(raw: string): string | null {
  const term = raw.trim().replace(/^#/, '').trim()
  return term === '' ? null : term
}

export interface PageSummary {
  /** 1-based, for display; 0 when there is nothing. */
  from: number
  to: number
  total: number
  hasPrevious: boolean
  hasNext: boolean
}

/** "21–40 of 63", and whether each arrow does anything. */
export function pageSummary(page: number, shown: number, total: number, size = HISTORY_PAGE_SIZE): PageSummary {
  const from = shown === 0 ? 0 : page * size + 1
  const to = shown === 0 ? 0 : page * size + shown
  return {
    from,
    to,
    total,
    hasPrevious: page > 0,
    hasNext: to < total,
  }
}

/**
 * The payment line on a FINISHED order.
 *
 * Not the live ticket's wording: "Collect cash" is an instruction for the
 * handover, and on an order that already went out it reads as if the money
 * is still owed.
 */
export function settledPaymentLabel(status: string): string {
  switch (status.toUpperCase()) {
    case 'COD':
      return 'Cash on delivery'
    case 'PAID':
      return 'Paid online'
    case 'REFUNDED':
      return 'Refunded'
    default:
      return 'Unpaid'
  }
}

function sameLocalDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

/**
 * When something happened, as short as it can honestly be.
 *
 * Time only for today, because that is the default list and a date on every
 * row would be noise. A date as well for anything older — a search reaches
 * all history, and "14:32" on last Tuesday's order would read as this
 * afternoon. A missing instant says so rather than printing nothing: a
 * delivered order older than event tracking has no completion time.
 */
export function completedLabel(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return 'Time not recorded'
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return 'Time not recorded'
  const time = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(at)
  if (sameLocalDay(at, now)) return time
  const date = new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  }).format(at)
  return `${date}, ${time}`
}

/** "3 items" — every dish counted by quantity, because that is what was cooked. */
export function itemCount(items: { quantity: number }[]): string {
  const count = items.reduce((sum, line) => sum + line.quantity, 0)
  return `${count} ${count === 1 ? 'item' : 'items'}`
}
