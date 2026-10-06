import type { KitchenMenuItem } from '@/types/app';
import {
  backInStockNeedsCount,
  changedCount,
  matchesMenuFilter,
  menuSummary,
  parseCount,
  sectionsOf,
  stockLabel,
  stockState,
} from './menuStock';

const dish = (overrides: Partial<KitchenMenuItem> = {}): KitchenMenuItem => ({
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
  updated_at: '2026-10-06T10:00:00Z',
  ...overrides,
});

describe('stockState', () => {
  it('puts the owner’s switch above everything the kitchen can do', () => {
    expect(stockState(dish({ is_available: false, out_of_stock: true }))).toBe('hidden');
  });

  it('tells "marked out", "counted to zero" and "not counted" apart', () => {
    expect(stockState(dish({ out_of_stock: true }))).toBe('out');
    expect(stockState(dish({ stock_quantity: 0 }))).toBe('sold_out');
    expect(stockState(dish({ stock_quantity: null }))).toBe('unlimited');
  });

  it('flags a low count', () => {
    expect(stockState(dish({ stock_quantity: 3 }))).toBe('low');
    expect(stockState(dish({ stock_quantity: 4 }))).toBe('counted');
    expect(stockLabel(dish({ stock_quantity: 4 }))).toBe('4 left');
  });
});

describe('typing a count', () => {
  it('reads an empty box as "not counted", never as zero', () => {
    expect(parseCount('')).toBeNull();
    expect(parseCount('   ')).toBeNull();
    expect(parseCount('0')).toBe(0);
  });

  it('refuses fractions and negatives', () => {
    expect(() => parseCount('12.5')).toThrow();
    expect(() => parseCount('-3')).toThrow();
    expect(() => parseCount('ten')).toThrow();
  });

  it('sends only a box that changed, so orders taken meanwhile are kept', () => {
    expect(changedCount('10', 10)).toEqual({ changed: false });
    expect(changedCount('', null)).toEqual({ changed: false });
    expect(changedCount('', 7)).toEqual({ changed: true, value: null });
    expect(changedCount('4', null)).toEqual({ changed: true, value: 4 });
  });
});

describe('back in stock', () => {
  it('needs a count when the dish was counted down to zero', () => {
    expect(backInStockNeedsCount(dish({ out_of_stock: true, stock_quantity: 0 }))).toBe(true);
    expect(backInStockNeedsCount(dish({ out_of_stock: true, stock_quantity: null }))).toBe(false);
  });
});

describe('filters, sections and the summary', () => {
  const list = [
    dish({ name: 'Curry', stock_quantity: 2 }),
    dish({ name: 'Soup', is_available: false }),
    dish({ name: 'Pizza', category: 'Pizza', sizes: [{ id: 's', name: 'Large', stock_quantity: 0, stock_daily_quantity: null }] }),
    dish({ name: 'Rice', out_of_stock: true, branch_name: 'Airport' }),
  ];

  it('filters by state, including a sold-out size', () => {
    const names = (filter: Parameters<typeof matchesMenuFilter>[1]) =>
      list.filter(d => matchesMenuFilter(d, filter, '')).map(d => d.name);
    expect(names('OUT')).toEqual(['Pizza', 'Rice']);
    expect(names('LOW')).toEqual(['Curry']);
    expect(names('HIDDEN')).toEqual(['Soup']);
    expect(names('COUNTED')).toEqual(['Curry', 'Pizza']);
  });

  it('searches names and categories', () => {
    expect(list.filter(d => matchesMenuFilter(d, 'ALL', 'piz')).map(d => d.name)).toEqual(['Pizza']);
  });

  it('groups by category, and by branch when it spans several', () => {
    expect(sectionsOf(list, false).map(s => s.title)).toEqual(['Mains', 'Pizza']);
    expect(sectionsOf(list, true).map(s => s.title)).toContain('Airport · Mains');
  });

  it('counts what needs attention', () => {
    expect(menuSummary(list)).toEqual({ out: 1, low: 1, hidden: 1 });
  });
});
