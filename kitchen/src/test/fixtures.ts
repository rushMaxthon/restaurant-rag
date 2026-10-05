import type { KitchenOrder, KitchenSession, OrderLine } from '@/types/app';

// Test data only. An order with everything a ticket can show, overridable
// per test.
let counter = 0;

export const line = (overrides: Partial<OrderLine> = {}): OrderLine => ({
  id: `line-${++counter}`,
  menu_item_id: 'menu-1',
  item_name_snapshot: 'Pad Thai',
  quantity: 1,
  unit_price: '10.00',
  total_price: '10.00',
  size_name_snapshot: null,
  selected_options_snapshot: [],
  ...overrides,
});

export const order = (overrides: Partial<KitchenOrder> = {}): KitchenOrder => ({
  id: `a1b2c3d4-0000-0000-0000-${String(++counter).padStart(12, '0')}`,
  status: 'PLACED',
  payment_status: 'PAID',
  fulfillment_type: 'DELIVERY',
  schedule_type: 'ASAP',
  scheduled_at: null,
  placed_at: '2026-10-03T12:00:00.000Z',
  total_amount: '10.00',
  currency: 'USD',
  special_instructions: null,
  contact_name: 'Asha',
  contact_phone: null,
  delivery_address: null,
  restaurant_id: 'r-1',
  restaurant_location_id: 'l-1',
  restaurant_location: { id: 'l-1', branch_name: 'Downtown' },
  customer: null,
  items: [line()],
  completed_at: null,
  ...overrides,
});

export const kitchenSession = (overrides: Partial<KitchenSession> = {}): KitchenSession => ({
  token: 'token-1',
  user: { id: 'u-1', fullName: 'Line Cook', email: 'cook@example.com', role: 'KITCHEN' },
  restaurantId: 'r-1',
  restaurantLocationId: null,
  ...overrides,
});
