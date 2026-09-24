/**
 * The summary bar and the toolbar.
 *
 * These are here because a kitchen metric that disagrees with the column
 * beneath it destroys trust in the whole board, and because the search box is
 * the control somebody reaches for while holding a phone with a customer on
 * the other end.
 */

import { describe, expect, it } from 'vitest'

import { boardMetrics, matchesFilter, priorityLabel } from './metrics'
import type { KitchenOrder, OrderStatus } from './api'

const NOW = new Date('2026-09-23T12:00:00.000Z')
const minutesAgo = (n: number) => new Date(NOW.getTime() - n * 60000).toISOString()

function order(overrides: Partial<KitchenOrder> = {}): KitchenOrder {
  return {
    id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    status: 'PLACED',
    payment_status: 'PAID',
    fulfillment_type: 'DELIVERY',
    schedule_type: 'ASAP',
    scheduled_at: null,
    placed_at: NOW.toISOString(),
    total_amount: '500.00',
    currency: 'INR',
    special_instructions: null,
    contact_name: null,
    contact_phone: null,
    delivery_address: null,
    restaurant_id: 'r',
    restaurant_location_id: 'l',
    restaurant_location: null,
    customer: null,
    items: [],
    ...overrides,
  }
}

function columns(map: Partial<Record<OrderStatus, KitchenOrder[]>>) {
  return (['PLACED', 'ACCEPTED', 'PREPARING', 'OUT_FOR_DELIVERY'] as OrderStatus[]).map(
    (status) => ({ status, orders: map[status] ?? [] }),
  )
}

describe('the summary bar', () => {
  it('counts each column', () => {
    const metrics = boardMetrics(
      columns({
        PLACED: [order(), order()],
        PREPARING: [order({ status: 'PREPARING' })],
      }),
      NOW,
    )
    expect(metrics.newCount).toBe(2)
    expect(metrics.acceptedCount).toBe(0)
    expect(metrics.cookingCount).toBe(1)
    expect(metrics.readyCount).toBe(0)
  })

  it('counts overdue across every column, not just New', () => {
    // A ticket stuck in Cooking is the one a kitchen most needs to see.
    const metrics = boardMetrics(
      columns({
        PLACED: [order({ placed_at: minutesAgo(9) })],
        PREPARING: [order({ status: 'PREPARING', placed_at: minutesAgo(40) })],
        ACCEPTED: [order({ status: 'ACCEPTED', placed_at: minutesAgo(1) })],
      }),
      NOW,
    )
    expect(metrics.overdue).toBe(2)
  })

  it('reports the median wait, not the mean', () => {
    // One forgotten ticket at 90 minutes would drag a mean to 32 and describe
    // a kitchen nobody is standing in.
    const metrics = boardMetrics(
      columns({
        PLACED: [
          order({ placed_at: minutesAgo(2) }),
          order({ placed_at: minutesAgo(4) }),
          order({ placed_at: minutesAgo(90) }),
        ],
      }),
      NOW,
    )
    expect(metrics.medianWait).toBe(4)
  })

  it('has no wait to report on an empty board', () => {
    // Null, so the tile can say "—" rather than a confident zero.
    expect(boardMetrics(columns({}), NOW).medianWait).toBeNull()
  })
})

describe('the priority badge', () => {
  it('says nothing about a fresh ticket', () => {
    expect(priorityLabel(order({ placed_at: minutesAgo(0) }), NOW)).toBeNull()
  })

  it('escalates as the ticket ages', () => {
    expect(priorityLabel(order({ placed_at: minutesAgo(3) }), NOW)).toBe('HIGH')
    expect(priorityLabel(order({ placed_at: minutesAgo(9) }), NOW)).toBe('URGENT')
  })

  it('gives a cooking ticket the longer patience its column has', () => {
    const at12 = minutesAgo(12)
    expect(priorityLabel(order({ status: 'PLACED', placed_at: at12 }), NOW)).toBe('URGENT')
    expect(priorityLabel(order({ status: 'PREPARING', placed_at: at12 }), NOW)).toBeNull()
  })
})

describe('the toolbar', () => {
  it('keeps everything under All', () => {
    expect(matchesFilter(order(), 'ALL', '', NOW)).toBe(true)
  })

  it('filters by fulfilment', () => {
    expect(matchesFilter(order({ fulfillment_type: 'PICKUP' }), 'PICKUP', '', NOW)).toBe(true)
    expect(matchesFilter(order({ fulfillment_type: 'DELIVERY' }), 'PICKUP', '', NOW)).toBe(false)
  })

  it('filters by column', () => {
    expect(matchesFilter(order({ status: 'PREPARING' }), 'PREPARING', '', NOW)).toBe(true)
    expect(matchesFilter(order({ status: 'PLACED' }), 'PREPARING', '', NOW)).toBe(false)
  })

  it('shows only tickets that are actually pressing under Priority', () => {
    expect(matchesFilter(order({ placed_at: minutesAgo(9) }), 'PRIORITY', '', NOW)).toBe(true)
    expect(matchesFilter(order({ placed_at: minutesAgo(0) }), 'PRIORITY', '', NOW)).toBe(false)
  })

  it('finds an order however the code is typed', () => {
    // Somebody reading a receipt down the phone says "8C9BDD85"; somebody
    // pasting it includes the hash. Both have to work.
    const row = order({ id: '8c9bdd85-1111-2222-3333-444444444444' })
    for (const typed of ['8c9bdd85', '8C9BDD85', '#8C9BDD85', '8c9b']) {
      expect(matchesFilter(row, 'ALL', typed, NOW)).toBe(true)
    }
    expect(matchesFilter(row, 'ALL', '9999', NOW)).toBe(false)
  })

  it('applies the search and the filter together', () => {
    const row = order({ id: '8c9bdd85-1111-2222-3333-444444444444', fulfillment_type: 'DELIVERY' })
    expect(matchesFilter(row, 'PICKUP', '8c9b', NOW)).toBe(false)
  })
})
