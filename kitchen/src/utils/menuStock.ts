import type { KitchenMenuItem, KitchenMenuSize } from '@/types/app';

// The rules of the kitchen's stock screen, with no React in them. The same
// rules as the owner's (frontend-admin/src/services/menuStock.ts) where they
// overlap — above all that an EMPTY count means "not counted", which is a
// different fact from zero: zero is sold out, empty is unlimited.

// At or under this, a counted dish is flagged as running low.
export const LOW_STOCK_AT = 3;

export type StockState = 'hidden' | 'out' | 'sold_out' | 'low' | 'counted' | 'unlimited';

// What a dish's row says, most urgent first. "Hidden" outranks everything:
// the owner switched it off, so nothing the kitchen does puts it on sale.
export const stockState = (dish: Pick<KitchenMenuItem, 'is_available' | 'out_of_stock' | 'stock_quantity'>): StockState => {
  if (!dish.is_available) {
    return 'hidden';
  }
  if (dish.out_of_stock) {
    return 'out';
  }
  if (dish.stock_quantity === null) {
    return 'unlimited';
  }
  if (dish.stock_quantity === 0) {
    return 'sold_out';
  }
  return dish.stock_quantity <= LOW_STOCK_AT ? 'low' : 'counted';
};

export const stockLabel = (dish: KitchenMenuItem): string => {
  switch (stockState(dish)) {
    case 'hidden':
      return 'Hidden by owner';
    case 'out':
      return 'Out of stock';
    case 'sold_out':
      return 'Sold out (0 left)';
    case 'low':
    case 'counted':
      return `${dish.stock_quantity} left`;
    case 'unlimited':
      return 'In stock';
  }
};

export const sizeLabel = (size: KitchenMenuSize): string =>
  size.stock_quantity === null
    ? 'Uses dish count'
    : size.stock_quantity === 0
      ? 'Sold out'
      : `${size.stock_quantity} left`;

// A count typed into a box. Empty means "not counted" (null), never zero —
// clearing the box must not mark the dish sold out. Digits only: "12.5" and
// "-3" are typing mistakes, not counts.
export const parseCount = (typed: string): number | null => {
  const value = typed.trim();
  if (value === '') {
    return null;
  }
  if (!/^\d+$/.test(value)) {
    throw new Error('Enter a whole number, or leave it empty to stop counting.');
  }
  const count = Number.parseInt(value, 10);
  if (count > 1_000_000) {
    throw new Error('That number is too large.');
  }
  return count;
};

export const countText = (value: number | null): string => (value === null ? '' : String(value));

// Only the boxes that were changed are sent. A dish's count moves with every
// order, so an editor opened at 10 and saved after three sold must not write
// 10 back — leaving the field out is how "I changed something else" is said.
export const changedCount = (
  typed: string,
  loaded: number | null,
): { changed: false } | { changed: true; value: number | null } => {
  const value = parseCount(typed);
  return value === loaded ? { changed: false } : { changed: true, value };
};

// "Back in stock" on a counted dish at zero would leave it sold out — the
// switch is not the count. The screen asks for a count instead of pretending.
export const backInStockNeedsCount = (dish: KitchenMenuItem): boolean =>
  dish.out_of_stock && dish.stock_quantity === 0;

export type MenuFilter = 'ALL' | 'OUT' | 'LOW' | 'COUNTED' | 'HIDDEN';

export const MENU_FILTERS: { key: MenuFilter; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'OUT', label: 'Out of stock' },
  { key: 'LOW', label: 'Running low' },
  { key: 'COUNTED', label: 'Counted' },
  { key: 'HIDDEN', label: 'Hidden' },
];

export const matchesMenuFilter = (dish: KitchenMenuItem, filter: MenuFilter, search: string): boolean => {
  const query = search.trim().toLowerCase();
  if (query && !dish.name.toLowerCase().includes(query) && !dish.category.toLowerCase().includes(query)) {
    return false;
  }
  const state = stockState(dish);
  switch (filter) {
    case 'OUT':
      return state === 'out' || state === 'sold_out' || dish.sizes.some(size => size.stock_quantity === 0);
    case 'LOW':
      return state === 'low';
    case 'COUNTED':
      return dish.stock_quantity !== null || dish.sizes.some(size => size.stock_quantity !== null);
    case 'HIDDEN':
      return state === 'hidden';
    default:
      return true;
  }
};

export interface MenuSection {
  title: string;
  data: KitchenMenuItem[];
}

// Category sections in the order the server sent them (category, then name),
// prefixed by branch when the list spans several branches.
export const sectionsOf = (dishes: readonly KitchenMenuItem[], showBranch: boolean): MenuSection[] => {
  const sections = new Map<string, KitchenMenuItem[]>();
  for (const dish of dishes) {
    const title = showBranch ? `${dish.branch_name} · ${dish.category}` : dish.category;
    const list = sections.get(title);
    if (list) {
      list.push(dish);
    } else {
      sections.set(title, [dish]);
    }
  }
  return [...sections].map(([title, data]) => ({ title, data }));
};

export interface MenuSummary {
  out: number;
  low: number;
  hidden: number;
}

export const menuSummary = (dishes: readonly KitchenMenuItem[]): MenuSummary => {
  let out = 0;
  let low = 0;
  let hidden = 0;
  for (const dish of dishes) {
    const state = stockState(dish);
    if (state === 'out' || state === 'sold_out') {
      out += 1;
    } else if (state === 'low') {
      low += 1;
    } else if (state === 'hidden') {
      hidden += 1;
    }
  }
  return { out, low, hidden };
};
