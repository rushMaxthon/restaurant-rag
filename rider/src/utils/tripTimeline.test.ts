import type { Trip } from '@/types/api';
import { endLabel, tripTimeline } from './tripTimeline';

const base: Trip = {
  id: 't1',
  order_id: 'o1',
  order_code: 'BB-1001',
  step: 'done',
  accepted_at: '2026-10-09T10:00:00Z',
  arrived_pickup_at: '2026-10-09T10:08:00Z',
  picked_up_at: '2026-10-09T10:12:00Z',
  arrived_drop_at: '2026-10-09T10:25:00Z',
  delivered_at: '2026-10-09T10:27:00Z',
  ended_at: '2026-10-09T10:27:00Z',
  end_reason: 'DELIVERED',
  call_attempts: 0,
  distance_km: 3.2,
  earning: '52.00',
  otp_locked: false,
  otp_attempts_left: 5,
  pickup: {
    name: 'Bhagwati Bakery',
    address: 'Rander Road',
    phone: '',
    lat: null,
    lng: null,
  },
  drop: { name: 'Asha', address: 'Adajan', phone: '', lat: null, lng: null },
  items: [],
  item_count: 2,
};

describe('a finished delivery as a timeline', () => {
  it('lists the five moments in order with their times', () => {
    const rows = tripTimeline(base);
    expect(rows.map(r => r.label)).toEqual([
      'Accepted',
      'Reached restaurant',
      'Picked up',
      'Reached customer',
      'Delivered',
    ]);
    expect(rows.every(r => r.at !== null)).toBe(true);
    expect(rows[4]?.at).toBe('2026-10-09T10:27:00Z');
  });

  it('keeps a moment that never happened, marked as skipped, so the rider sees where it ended', () => {
    const rows = tripTimeline({
      ...base,
      picked_up_at: null,
      arrived_drop_at: null,
      delivered_at: null,
      end_reason: 'CANCELLED_BEFORE_PICKUP',
    });
    expect(rows.slice(0, 4).map(r => r.at)).toEqual([
      '2026-10-09T10:00:00Z',
      '2026-10-09T10:08:00Z',
      null,
      null,
    ]);
    expect(rows[2]?.done).toBe(false);
    // The last row is the cancellation itself, at the time it happened.
    expect(rows[4]).toMatchObject({
      label: 'Cancelled',
      at: '2026-10-09T10:27:00Z',
      done: true,
    });
  });

  it('ends a customer-unavailable trip with that instead of "Delivered"', () => {
    const rows = tripTimeline({
      ...base,
      delivered_at: null,
      end_reason: 'CUSTOMER_UNAVAILABLE',
    });
    expect(rows[4]).toMatchObject({
      label: 'Customer unavailable',
      at: '2026-10-09T10:27:00Z',
      done: true,
    });
  });

  it('names every way a trip can end', () => {
    expect(endLabel('DELIVERED')).toEqual({
      label: 'Delivered',
      tone: 'success',
    });
    expect(endLabel('CUSTOMER_UNAVAILABLE').tone).toBe('warning');
    expect(endLabel('CANCELLED_AFTER_PICKUP').label).toBe('Cancelled');
    expect(endLabel('REASSIGNED').tone).toBe('neutral');
    expect(endLabel(null)).toEqual({ label: 'Ended', tone: 'neutral' });
  });
});
