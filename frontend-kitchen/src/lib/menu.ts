/**
 * The menu-stock rules, with no React and no network in them.
 *
 * The same rules as the native kitchen app (`kitchen/src/utils/menuStock.ts`)
 * and, where they overlap, the owner's panel (`frontend-admin/src/services/
 * menuStock.ts`) — above all that an EMPTY count is "not counted", which is a
 * different fact from zero: zero is sold out, empty is unlimited. Change one
 * and the others must follow, or the same dish reads differently on two
 * screens in the same kitchen.
 */

import type { KitchenMenuItem, KitchenMenuSize } from './api'

/** At or under this, a counted dish is flagged as running low. */
export const LOW_STOCK_AT = 3

export type StockState = 'hidden' | 'out' | 'sold_out' | 'low' | 'counted' | 'unlimited'

/**
 * What a dish's row says, most urgent first. "Hidden" outranks everything:
 * the owner switched it off, so nothing the kitchen does puts it on sale.
 */
export function stockState(
  dish: Pick<KitchenMenuItem, 'is_available' | 'out_of_stock' | 'stock_quantity'>,
): StockState {
  if (!dish.is_available) return 'hidden'
  if (dish.out_of_stock) return 'out'
  if (dish.stock_quantity === null) return 'unlimited'
  if (dish.stock_quantity === 0) return 'sold_out'
  return dish.stock_quantity <= LOW_STOCK_AT ? 'low' : 'counted'
}

export function stockLabel(dish: KitchenMenuItem): string {
  switch (stockState(dish)) {
    case 'hidden':
      return 'Hidden by owner'
    case 'out':
      return 'Out of stock'
    case 'sold_out':
      return 'Sold out (0 left)'
    case 'low':
    case 'counted':
      return `${dish.stock_quantity} left`
    case 'unlimited':
      return 'In stock'
  }
}

export function sizeLabel(size: KitchenMenuSize): string {
  if (size.stock_quantity === null) return 'uses dish count'
  return size.stock_quantity === 0 ? 'sold out' : `${size.stock_quantity} left`
}

/**
 * A count typed into a box. Empty is "not counted" (null), never zero —
 * clearing the box must not take a dish off sale. Digits only.
 */
export function parseCount(typed: string): number | null {
  const value = typed.trim()
  if (value === '') return null
  if (!/^\d+$/.test(value)) {
    throw new Error('Enter a whole number, or leave it empty to stop counting.')
  }
  const count = Number.parseInt(value, 10)
  if (count > 1_000_000) throw new Error('That number is too large.')
  return count
}

export function countText(value: number | null): string {
  return value === null ? '' : String(value)
}

/**
 * Only a box that was changed is sent. A count moves with every order, so an
 * editor opened at 10 and saved after three sold must not write 10 back.
 */
export function changedCount(
  typed: string,
  loaded: number | null,
): { changed: false } | { changed: true; value: number | null } {
  const value = parseCount(typed)
  return value === loaded ? { changed: false } : { changed: true, value }
}

/** "Back in stock" at a count of zero would still be sold out: ask for a count. */
export function backInStockNeedsCount(dish: KitchenMenuItem): boolean {
  return dish.out_of_stock && dish.stock_quantity === 0
}

export type MenuFilter = 'ALL' | 'OUT' | 'LOW' | 'COUNTED' | 'HIDDEN'

export const MENU_FILTERS: { key: MenuFilter; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'OUT', label: 'Out of stock' },
  { key: 'LOW', label: 'Running low' },
  { key: 'COUNTED', label: 'Counted' },
  { key: 'HIDDEN', label: 'Hidden' },
]

export function matchesMenuFilter(dish: KitchenMenuItem, filter: MenuFilter, search: string): boolean {
  const query = search.trim().toLowerCase()
  if (query && !dish.name.toLowerCase().includes(query) && !dish.category.toLowerCase().includes(query)) {
    return false
  }
  const state = stockState(dish)
  switch (filter) {
    case 'OUT':
      return state === 'out' || state === 'sold_out' || dish.sizes.some((size) => size.stock_quantity === 0)
    case 'LOW':
      return state === 'low'
    case 'COUNTED':
      return dish.stock_quantity !== null || dish.sizes.some((size) => size.stock_quantity !== null)
    case 'HIDDEN':
      return state === 'hidden'
    default:
      return true
  }
}

export type MenuSection = { title: string; dishes: KitchenMenuItem[] }

/** Category sections in server order, prefixed by branch when the list spans several. */
export function sectionsOf(dishes: readonly KitchenMenuItem[], showBranch: boolean): MenuSection[] {
  const sections = new Map<string, KitchenMenuItem[]>()
  for (const dish of dishes) {
    const title = showBranch ? `${dish.branch_name} · ${dish.category}` : dish.category
    const list = sections.get(title)
    if (list) list.push(dish)
    else sections.set(title, [dish])
  }
  return [...sections].map(([title, list]) => ({ title, dishes: list }))
}

export function menuSummary(dishes: readonly KitchenMenuItem[]): { out: number; low: number; hidden: number } {
  let out = 0
  let low = 0
  let hidden = 0
  for (const dish of dishes) {
    const state = stockState(dish)
    if (state === 'out' || state === 'sold_out') out += 1
    else if (state === 'low') low += 1
    else if (state === 'hidden') hidden += 1
  }
  return { out, low, hidden }
}
