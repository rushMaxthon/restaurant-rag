import type { OpenOrder } from '@/types/api';
import { homePreview } from './homeOrders';

function order(id: string, over: Partial<OpenOrder> = {}): OpenOrder {
  return {
    order_id: id,
    restaurant_name: 'Bhagwati Bakery',
    branch: 'Rander Road',
    pickup_address: '12 Rander Road',
    pickup_distance_m: 1000,
    trip_distance_km: 3,
    earning_estimate: '40.00',
    drop_area: 'Adajan',
    item_count: 2,
    minutes_left: 4,
    missed: false,
    ...over,
  };
}

describe('which waiting orders Home shows', () => {
  it('shows nothing when the board is empty', () => {
    expect(homePreview([])).toEqual({ shown: [], more: 0 });
  });

  it('shows at most three and counts the rest for "See all"', () => {
    const all = ['a', 'b', 'c', 'd', 'e'].map(id => order(id));
    const { shown, more } = homePreview(all);
    expect(shown).toHaveLength(3);
    expect(more).toBe(2);
  });

  it('puts the nearest pickup first: the one the rider reaches soonest', () => {
    const { shown } = homePreview([
      order('far', { pickup_distance_m: 4000 }),
      order('near', { pickup_distance_m: 300 }),
      order('mid', { pickup_distance_m: 1500 }),
    ]);
    expect(shown.map(o => o.order_id)).toEqual(['near', 'mid', 'far']);
  });

  it('puts an order about to go to the courier ahead of a nearer one with time to spare', () => {
    const { shown } = homePreview([
      order('near', { pickup_distance_m: 300, minutes_left: 4 }),
      order('lastcall', { pickup_distance_m: 2000, minutes_left: 1 }),
    ]);
    expect(shown[0]?.order_id).toBe('lastcall');
  });

  it('keeps an order with no known distance, after the ones that have one', () => {
    const { shown } = homePreview([
      order('unknown', { pickup_distance_m: null }),
      order('known', { pickup_distance_m: 2500 }),
    ]);
    expect(shown.map(o => o.order_id)).toEqual(['known', 'unknown']);
  });

  it('does not reorder the board it was given', () => {
    const all = [
      order('b', { pickup_distance_m: 900 }),
      order('a', { pickup_distance_m: 100 }),
    ];
    homePreview(all);
    expect(all.map(o => o.order_id)).toEqual(['b', 'a']);
  });
});
