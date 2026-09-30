/**
 * The board's rules, checked without a browser.
 *
 * These exist because the alternative way to find out that a scheduled order
 * shows as two hours late, or that the first poll plays a sound for every
 * ticket at once, is to be standing in a kitchen during a rush.
 */

import { describe, expect, it } from 'vitest'

import {
  LIVE_WINDOW_HOURS,
  advanceLabel,
  formatWait,
  hiddenCount,
  idsOf,
  inServiceOrder,
  liveWindowStart,
  lineModifiers,
  newlyArrived,
  nextStatus,
  orderCode,
  urgencyOf,
  waitingMinutes,
} from './board'
import type { KitchenOrder } from './api'

const NOW = new Date('2026-09-22T12:00:00.000Z')

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

describe('the linear flow', () => {
  it('offers exactly one next step', () => {
    expect(nextStatus('PLACED')).toBe('ACCEPTED')
    expect(nextStatus('OUT_FOR_DELIVERY')).toBe('DELIVERED')
  })

  it('offers nothing once an order is settled', () => {
    // The server refuses these too; the button simply must not be there.
    expect(nextStatus('DELIVERED')).toBeNull()
    expect(nextStatus('CANCELLED')).toBeNull()
    expect(nextStatus('PAYMENT_PENDING')).toBeNull()
  })
})

describe('what the button says', () => {
  it('never tells a pickup order it is out for delivery', () => {
    // One backend flow serves both, so the status name alone would lie here.
    expect(advanceLabel(order({ status: 'PREPARING', fulfillment_type: 'PICKUP' }))).toBe(
      'Ready for pickup',
    )
    expect(advanceLabel(order({ status: 'PREPARING', fulfillment_type: 'DELIVERY' }))).toBe(
      'Hand to rider',
    )
  })

  it('says nothing for an order that cannot move', () => {
    expect(advanceLabel(order({ status: 'DELIVERED' }))).toBeNull()
  })
})

describe('how long a ticket has waited', () => {
  it('counts from when an ASAP order was placed', () => {
    const placed = new Date(NOW.getTime() - 12 * 60000).toISOString()
    expect(waitingMinutes(order({ placed_at: placed }), NOW)).toBe(12)
  })

  it('counts a scheduled order from when it was booked for, not placed', () => {
    // Placed at 9am for 12:30. At noon it has not waited three hours; it has
    // not started waiting at all.
    const waited = waitingMinutes(
      order({
        schedule_type: 'SCHEDULED',
        placed_at: new Date(NOW.getTime() - 3 * 3600_000).toISOString(),
        scheduled_at: new Date(NOW.getTime() + 30 * 60000).toISOString(),
      }),
      NOW,
    )
    expect(waited).toBe(0)
  })

  it('never goes negative', () => {
    const future = new Date(NOW.getTime() + 60 * 60000).toISOString()
    expect(waitingMinutes(order({ placed_at: future }), NOW)).toBe(0)
  })
})

describe('urgency', () => {
  const minutesAgo = (n: number) => new Date(NOW.getTime() - n * 60000).toISOString()

  it('is calm when a ticket has just landed', () => {
    expect(urgencyOf(order({ placed_at: minutesAgo(0) }), NOW)).toBe('calm')
  })

  it('warns before it is actually late', () => {
    // PLACED is late at 5; 3 is past 60% of that and worth a nudge.
    expect(urgencyOf(order({ placed_at: minutesAgo(3) }), NOW)).toBe('due')
  })

  it('is late once the column threshold passes', () => {
    expect(urgencyOf(order({ placed_at: minutesAgo(6) }), NOW)).toBe('late')
  })

  it('gives a cooking order more time than a new one', () => {
    const at12 = minutesAgo(12)
    expect(urgencyOf(order({ status: 'PLACED', placed_at: at12 }), NOW)).toBe('late')
    expect(urgencyOf(order({ status: 'PREPARING', placed_at: at12 }), NOW)).toBe('calm')
  })

  it('stays calm for a status with no threshold', () => {
    expect(urgencyOf(order({ status: 'DELIVERED', placed_at: minutesAgo(600) }), NOW)).toBe('calm')
  })
})

describe('spotting a new ticket', () => {
  it('reports only what was not there before', () => {
    const previous = idsOf([order({ id: 'one' })])
    const arrived = newlyArrived(previous, [order({ id: 'one' }), order({ id: 'two' })])
    expect(arrived).toEqual(['two'])
  })

  it('reports everything against an empty set', () => {
    // Which is why the caller must not sound the alarm on the first poll: on a
    // board opened mid-service every ticket would be "new" at once.
    const arrived = newlyArrived(new Set(), [order({ id: 'one' }), order({ id: 'two' })])
    expect(arrived).toEqual(['one', 'two'])
  })
})

describe('reading a ticket', () => {
  it('shares the customer receipt code', () => {
    expect(orderCode(order({ id: 'abcdef12-3456-7890-abcd-ef1234567890' }))).toBe('#ABCDEF12')
  })

  // Every fixture below uses the keys `OrderItemResponse` actually sends. The
  // previous ones used `selected_size_name` / `selected_options`, which the API
  // has never sent — so these tests passed while every real ticket printed the
  // bare dish name with no size and no options at all.
  //
  // This is the shape `ResolvedCustomizationOption.to_snapshot()` writes.
  const snapshot = (overrides: Record<string, unknown>) => ({
    group_id: 'g-toppings',
    group_title: 'Toppings',
    selection_type: 'MULTI',
    option_id: 'o1',
    option_name: 'Olives',
    extra_price: '1.00',
    quantity: 1,
    is_countable: true,
    portion: 'WHOLE',
    ...overrides,
  })

  it('reads the size and options from the fields the API sends', () => {
    expect(
      lineModifiers({
        size_name_snapshot: 'Large',
        selected_options_snapshot: [
          snapshot({ group_id: 'g-crust', group_title: 'Crust', option_name: 'Thin' }),
          snapshot({ option_name: 'Olives' }),
        ],
      }),
    ).toEqual([
      { label: 'Size', half: null, text: 'Large' },
      { label: 'Crust', half: null, text: 'Thin' },
      { label: 'Toppings', half: null, text: 'Olives' },
    ])
  })

  it('gives each half of a split group its own row', () => {
    // "Pepperoni" alone is the difference between a correct pizza and a remake,
    // and so is putting it on the wrong side.
    expect(
      lineModifiers({
        size_name_snapshot: null,
        selected_options_snapshot: [
          snapshot({ option_name: 'Pepperoni', portion: 'LEFT' }),
          snapshot({ option_name: 'Mushroom', portion: 'RIGHT' }),
          snapshot({ option_name: 'Jalapeño', portion: 'LEFT' }),
        ],
      }),
    ).toEqual([
      { label: 'Toppings', half: 'LEFT', text: 'Pepperoni · Jalapeño' },
      { label: 'Toppings', half: 'RIGHT', text: 'Mushroom' },
    ])
  })

  it('prints how many of an option, but not "×1"', () => {
    expect(
      lineModifiers({
        selected_options_snapshot: [
          snapshot({ option_name: 'Extra cheese', quantity: 2 }),
          snapshot({ option_name: 'Basil', quantity: 1 }),
        ],
      }),
    ).toEqual([{ label: 'Toppings', half: null, text: 'Extra cheese ×2 · Basil' }])
  })

  it('carries a quantity onto a half as well', () => {
    expect(
      lineModifiers({
        selected_options_snapshot: [snapshot({ option_name: 'Pepperoni', quantity: 3, portion: 'RIGHT' })],
      }),
    ).toEqual([{ label: 'Toppings', half: 'RIGHT', text: 'Pepperoni ×3' }])
  })

  it('keeps groups in the order the customer built them', () => {
    const rows = lineModifiers({
      selected_options_snapshot: [
        snapshot({ group_id: 'g-sauce', group_title: 'Sauce', option_name: 'Garlic' }),
        snapshot({ option_name: 'Olives' }),
        snapshot({ group_id: 'g-sauce', group_title: 'Sauce', option_name: 'Chilli' }),
      ],
    })
    expect(rows.map((row) => `${row.label}: ${row.text}`)).toEqual([
      'Sauce: Garlic · Chilli',
      'Toppings: Olives',
    ])
  })

  it('never drops an option, even from a group that breaks the split rule', () => {
    // Checkout refuses whole + halves in one group; if a row ever carries both,
    // the ticket shows all of it rather than guessing which part to trust.
    expect(
      lineModifiers({
        selected_options_snapshot: [
          snapshot({ option_name: 'Olives', portion: 'WHOLE' }),
          snapshot({ option_name: 'Pepperoni', portion: 'LEFT' }),
        ],
      }),
    ).toEqual([
      { label: 'Toppings', half: null, text: 'Olives' },
      { label: 'Toppings', half: 'LEFT', text: 'Pepperoni' },
    ])
  })

  it('still prints options from old snapshots missing newer keys', () => {
    // Rows written before `portion` and `group_title` existed come back too.
    expect(
      lineModifiers({
        selected_options_snapshot: [{ option_name: 'No onion' }, { option_name: 'Extra sauce' }],
      }),
    ).toEqual([{ label: null, half: null, text: 'No onion · Extra sauce' }])
  })

  it('says nothing when a dish is exactly as listed', () => {
    expect(lineModifiers({ size_name_snapshot: null, selected_options_snapshot: [] })).toEqual([])
    expect(lineModifiers({})).toEqual([])
  })
})


describe('saying a waiting time out loud', () => {
  it('stays in minutes for the range a cook works in', () => {
    // "1h 04m" is worse than "64m" at 64 minutes, so the switch is at an hour.
    expect(formatWait(0)).toBe('now')
    expect(formatWait(7)).toBe('7m')
    expect(formatWait(59)).toBe('59m')
  })

  it('switches to hours past the hour', () => {
    expect(formatWait(60)).toBe('1h')
    expect(formatWait(83)).toBe('1h 23m')
    expect(formatWait(23 * 60 + 5)).toBe('23h 5m')
  })

  it('switches to days rather than printing a five-figure minute count', () => {
    // A forgotten ticket rendered as "132388m" on the real board — both
    // unreadable and somehow less alarming than the truth.
    expect(formatWait(25 * 60)).toBe('1d 1h')
    expect(formatWait(132388)).toBe('91d')
  })
})

/**
 * The live window, and the two rules that keep a long queue honest.
 *
 * All three exist because of one incident: a branch accumulated 206 PLACED
 * orders, the board asked for the oldest 100 of them, and every order placed
 * after the hundredth was invisible to the kitchen while showing normally to
 * the owner. Nothing failed and nothing was logged — the board simply showed
 * a page and called it the queue.
 */
describe('the live window', () => {
  it('reaches back a day, so an overnight pass is still this service', () => {
    expect(LIVE_WINDOW_HOURS).toBe(24)
  })

  it('is measured from now, so a board left on for a week keeps up', () => {
    const now = new Date('2026-09-23T18:00:00.000Z')
    expect(liveWindowStart(now)).toBe('2026-09-22T18:00:00.000Z')
  })
})

describe('inServiceOrder', () => {
  it('puts a newest-first page back into the order a kitchen cooks it', () => {
    // What the server returns for `placed_at:desc`.
    const page = ['newest', 'middle', 'oldest']
    expect(inServiceOrder(page)).toEqual(['oldest', 'middle', 'newest'])
  })

  it('does not mutate the array react-query is caching', () => {
    const page = ['a', 'b']
    inServiceOrder(page)
    expect(page).toEqual(['a', 'b'])
  })

  it('survives the empty column', () => {
    expect(inServiceOrder([])).toEqual([])
  })
})

describe('hiddenCount', () => {
  it('is zero when the page carried the whole queue', () => {
    expect(hiddenCount(12, 12)).toBe(0)
  })

  it('counts what the page could not carry', () => {
    expect(hiddenCount(260, 200)).toBe(60)
  })

  it('never goes negative when the total lags the page', () => {
    // The count and the rows are two reads of a table that is still moving,
    // so the total can arrive smaller than the page. "-3 tickets" on a wall
    // is worse than saying nothing.
    expect(hiddenCount(2, 5)).toBe(0)
  })
})
