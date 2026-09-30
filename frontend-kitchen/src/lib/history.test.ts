/**
 * The order history's rules, checked without a browser.
 *
 * Mostly about the edges a cook would hit first: what "today" means on a
 * tablet that is not in UTC, how a code read off a receipt is searched, and
 * whether the page arrows ever offer a page that is not there.
 */

import { describe, expect, it } from 'vitest'

import {
  HISTORY_PAGE_SIZE,
  completedLabel,
  itemCount,
  localDayKey,
  pageSummary,
  searchTerm,
  settledPaymentLabel,
  startOfToday,
} from './history'

describe("today's window", () => {
  it('starts at local midnight, not UTC midnight', () => {
    const afternoon = new Date(2026, 8, 30, 15, 45, 12)
    const start = new Date(startOfToday(afternoon))
    expect(start.getFullYear()).toBe(2026)
    expect(start.getMonth()).toBe(8)
    expect(start.getDate()).toBe(30)
    expect([start.getHours(), start.getMinutes(), start.getSeconds()]).toEqual([0, 0, 0])
  })

  it('rolls over at midnight so a screen left open moves to the new day', () => {
    expect(localDayKey(new Date(2026, 8, 30, 23, 59))).not.toBe(
      localDayKey(new Date(2026, 9, 1, 0, 1)),
    )
    expect(localDayKey(new Date(2026, 8, 30, 0, 1))).toBe(localDayKey(new Date(2026, 8, 30, 23, 59)))
  })
})

describe('searching by order number', () => {
  it('accepts the code the way it is printed and read aloud', () => {
    expect(searchTerm('#3F2A1B2C')).toBe('3F2A1B2C')
    expect(searchTerm('  3f2a  ')).toBe('3f2a')
    expect(searchTerm('# 3F2A')).toBe('3F2A')
  })

  it('treats a blank box as no search at all', () => {
    // A lone "#" would otherwise search for "" and match everything, while the
    // header claimed a search was running.
    expect(searchTerm('')).toBeNull()
    expect(searchTerm('   ')).toBeNull()
    expect(searchTerm('#')).toBeNull()
  })
})

describe('paging', () => {
  it('describes the first page', () => {
    expect(pageSummary(0, HISTORY_PAGE_SIZE, 63)).toEqual({
      from: 1,
      to: 20,
      total: 63,
      hasPrevious: false,
      hasNext: true,
    })
  })

  it('describes a short last page and offers nothing past it', () => {
    expect(pageSummary(3, 3, 63)).toEqual({
      from: 61,
      to: 63,
      total: 63,
      hasPrevious: true,
      hasNext: false,
    })
  })

  it('offers no next page when the total fits exactly', () => {
    expect(pageSummary(0, 20, 20).hasNext).toBe(false)
  })

  it('says nothing when there is nothing', () => {
    expect(pageSummary(0, 0, 0)).toEqual({
      from: 0,
      to: 0,
      total: 0,
      hasPrevious: false,
      hasNext: false,
    })
  })
})

describe('reading a finished order', () => {
  const now = new Date(2026, 8, 30, 18, 0)

  it('shows only the time for today', () => {
    const label = completedLabel(new Date(2026, 8, 30, 14, 32).toISOString(), now)
    const timeOnly = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(
      new Date(2026, 8, 30, 14, 32),
    )
    expect(label).toBe(timeOnly)
  })

  it('adds the date for an older order, so a search result is not read as this afternoon', () => {
    const label = completedLabel(new Date(2026, 8, 22, 14, 32).toISOString(), now)
    const timeOnly = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(
      new Date(2026, 8, 22, 14, 32),
    )
    expect(label).not.toBe(timeOnly)
    expect(label.endsWith(timeOnly)).toBe(true)
  })

  it('says when no completion time was recorded instead of printing nothing', () => {
    // A delivered order older than event tracking has no DELIVERED event.
    expect(completedLabel(null, now)).toBe('Time not recorded')
    expect(completedLabel('not a date', now)).toBe('Time not recorded')
  })

  it('does not tell anyone to collect cash on an order that already went out', () => {
    expect(settledPaymentLabel('COD')).toBe('Cash on delivery')
    expect(settledPaymentLabel('PAID')).toBe('Paid online')
    expect(settledPaymentLabel('REFUNDED')).toBe('Refunded')
  })

  it('counts dishes by quantity', () => {
    expect(itemCount([{ quantity: 2 }, { quantity: 1 }])).toBe('3 items')
    expect(itemCount([{ quantity: 1 }])).toBe('1 item')
  })
})
