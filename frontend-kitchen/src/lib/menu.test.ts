import { describe, expect, it } from 'vitest'

import type { KitchenMenuItem } from './api'
import {
  backInStockNeedsCount,
  changedCount,
  matchesMenuFilter,
  menuSummary,
  parseCount,
  sectionsOf,
  stockLabel,
  stockState,
} from './menu'

function dish(overrides: Partial<KitchenMenuItem> = {}): KitchenMenuItem {
  return {
    id: Math.random().toString(36).slice(2),
    name: 'Green Curry',
    category: 'Mains',
    is_veg: true,
    restaurant_location_id: 'l-1',
    branch_name: 'Downtown',
    is_available: true,
    out_of_stock: false,
    stock_quantity: null,
    stock_daily_quantity: null,
    is_on_sale: true,
    sizes: [],
    updated_at: '1',
    ...overrides,
  }
}

describe('stockState', () => {
  it('puts the owner’s switch above everything the kitchen can do', () => {
    expect(stockState(dish({ is_available: false, out_of_stock: true }))).toBe('hidden')
  })

  it('tells marked out, counted to zero and not counted apart', () => {
    expect(stockState(dish({ out_of_stock: true }))).toBe('out')
    expect(stockState(dish({ stock_quantity: 0 }))).toBe('sold_out')
    expect(stockState(dish({ stock_quantity: null }))).toBe('unlimited')
    expect(stockLabel(dish({ stock_quantity: 3 }))).toBe('3 left')
    expect(stockState(dish({ stock_quantity: 3 }))).toBe('low')
  })
})

describe('typing a count', () => {
  it('reads empty as not counted, never as zero', () => {
    expect(parseCount('')).toBeNull()
    expect(parseCount('0')).toBe(0)
  })

  it('refuses fractions, negatives and words', () => {
    expect(() => parseCount('1.5')).toThrow()
    expect(() => parseCount('-2')).toThrow()
    expect(() => parseCount('ten')).toThrow()
  })

  it('sends only a box that changed', () => {
    expect(changedCount('10', 10)).toEqual({ changed: false })
    expect(changedCount('', 7)).toEqual({ changed: true, value: null })
  })

  it('asks for a count before putting a zero-count dish back', () => {
    expect(backInStockNeedsCount(dish({ out_of_stock: true, stock_quantity: 0 }))).toBe(true)
    expect(backInStockNeedsCount(dish({ out_of_stock: true }))).toBe(false)
  })
})

describe('filters, sections and summary', () => {
  const list = [
    dish({ name: 'Curry', stock_quantity: 2 }),
    dish({ name: 'Soup', is_available: false }),
    dish({ name: 'Pizza', category: 'Pizza', sizes: [{ id: 's', name: 'Large', stock_quantity: 0, stock_daily_quantity: null }] }),
    dish({ name: 'Rice', out_of_stock: true, branch_name: 'Airport' }),
  ]

  it('filters by state, a sold-out size included', () => {
    const names = (filter: Parameters<typeof matchesMenuFilter>[1]) =>
      list.filter((d) => matchesMenuFilter(d, filter, '')).map((d) => d.name)
    expect(names('OUT')).toEqual(['Pizza', 'Rice'])
    expect(names('HIDDEN')).toEqual(['Soup'])
    expect(list.filter((d) => matchesMenuFilter(d, 'ALL', 'piz')).map((d) => d.name)).toEqual(['Pizza'])
  })

  it('groups by category, and by branch across branches', () => {
    expect(sectionsOf(list, false).map((s) => s.title)).toEqual(['Mains', 'Pizza'])
    expect(sectionsOf(list, true).map((s) => s.title)).toContain('Airport · Mains')
  })

  it('counts what needs attention', () => {
    expect(menuSummary(list)).toEqual({ out: 1, low: 1, hidden: 1 })
  })
})
