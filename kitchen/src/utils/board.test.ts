import { line, order } from '@/test/fixtures';
import {
  advanceLabel,
  formatWait,
  hiddenCount,
  inServiceOrder,
  itemCount,
  lineModifiers,
  liveWindowStart,
  minutesUntilDue,
  newlyArrived,
  nextStatus,
  orderCode,
  payKind,
  payLabel,
  stageLabel,
  urgencyOf,
  waitingMinutes,
} from './board';

const at = (iso: string) => new Date(iso);
const placedMinutesAgo = (minutes: number, now: Date) =>
  new Date(now.getTime() - minutes * 60000).toISOString();

describe('the flow', () => {
  it('moves one step at a time and stops at delivered', () => {
    expect(nextStatus('PLACED')).toBe('ACCEPTED');
    expect(nextStatus('ACCEPTED')).toBe('PREPARING');
    expect(nextStatus('PREPARING')).toBe('OUT_FOR_DELIVERY');
    expect(nextStatus('OUT_FOR_DELIVERY')).toBe('DELIVERED');
    expect(nextStatus('DELIVERED')).toBeNull();
    expect(nextStatus('CANCELLED')).toBeNull();
    expect(nextStatus('PAYMENT_PENDING')).toBeNull();
  });

  it('never tells a pickup order it is out for delivery', () => {
    const pickup = { fulfillment_type: 'PICKUP' as const };
    expect(advanceLabel({ ...pickup, status: 'PREPARING' })).toBe('Ready for pickup');
    expect(advanceLabel({ ...pickup, status: 'OUT_FOR_DELIVERY' })).toBe('Collected');
    expect(stageLabel('OUT_FOR_DELIVERY', 'PICKUP')).toBe('Ready for pickup');
  });

  it('names the delivery hand-over for what it is', () => {
    const delivery = { fulfillment_type: 'DELIVERY' as const };
    expect(advanceLabel({ ...delivery, status: 'PLACED' })).toBe('Accept');
    expect(advanceLabel({ ...delivery, status: 'ACCEPTED' })).toBe('Start cooking');
    expect(advanceLabel({ ...delivery, status: 'PREPARING' })).toBe('Hand to rider');
    expect(advanceLabel({ ...delivery, status: 'DELIVERED' })).toBeNull();
  });
});

describe('the live window and page', () => {
  it('reaches back 24 hours from now', () => {
    expect(liveWindowStart(at('2026-10-03T12:00:00Z'))).toBe('2026-10-02T12:00:00.000Z');
  });

  it('puts a newest-first page back in service order', () => {
    expect(inServiceOrder(['newest', 'middle', 'oldest'])).toEqual(['oldest', 'middle', 'newest']);
  });

  it('reports tickets that did not fit, and never a negative count', () => {
    expect(hiddenCount(260, 200)).toBe(60);
    expect(hiddenCount(3, 3)).toBe(0);
    expect(hiddenCount(2, 3)).toBe(0);
  });
});

describe('waiting', () => {
  const now = at('2026-10-03T12:30:00Z');

  it('counts an ASAP order from when it was placed', () => {
    expect(waitingMinutes(order({ placed_at: '2026-10-03T12:00:00Z' }), now)).toBe(30);
  });

  it('counts a scheduled order from its booked time, not before', () => {
    const scheduled = order({
      placed_at: '2026-10-03T09:00:00Z',
      schedule_type: 'SCHEDULED',
      scheduled_at: '2026-10-03T12:20:00Z',
    });
    expect(waitingMinutes(scheduled, now)).toBe(10);
    expect(waitingMinutes({ ...scheduled, scheduled_at: '2026-10-03T13:00:00Z' }, now)).toBe(0);
  });

  it('says how long until a booked order is due, and nothing once it is', () => {
    const booked = order({ schedule_type: 'SCHEDULED', scheduled_at: '2026-10-03T12:55:00Z' });
    expect(minutesUntilDue(booked, now)).toBe(25);
    expect(minutesUntilDue({ ...booked, scheduled_at: '2026-10-03T12:00:00Z' }, now)).toBe(0);
    expect(minutesUntilDue(order(), now)).toBe(0);
  });

  it.each([
    [0, 'now'],
    [12, '12m'],
    [60, '1h'],
    [64, '1h 4m'],
    [1500, '1d 1h'],
    [132388, '91d'],
  ])('says %i minutes as "%s"', (minutes, text) => {
    expect(formatWait(minutes)).toBe(text);
  });
});

describe('urgency', () => {
  const now = at('2026-10-03T12:30:00Z');

  it('goes calm, due, late as a new order waits', () => {
    expect(urgencyOf(order({ placed_at: placedMinutesAgo(1, now) }), now)).toBe('calm');
    expect(urgencyOf(order({ placed_at: placedMinutesAgo(3, now) }), now)).toBe('due');
    expect(urgencyOf(order({ placed_at: placedMinutesAgo(5, now) }), now)).toBe('late');
  });

  it('gives cooking more patience than a new ticket', () => {
    const cooking = order({ status: 'PREPARING', placed_at: placedMinutesAgo(12, now) });
    expect(urgencyOf(cooking, now)).toBe('calm');
    expect(urgencyOf({ ...cooking, placed_at: placedMinutesAgo(25, now) }, now)).toBe('late');
  });

  it('never flags a finished order', () => {
    expect(urgencyOf(order({ status: 'DELIVERED', placed_at: placedMinutesAgo(999, now) }), now)).toBe(
      'calm',
    );
  });
});

describe('arrivals', () => {
  it('lists only ids the previous load did not have', () => {
    const a = order();
    const b = order();
    expect(newlyArrived(new Set([a.id]), [a, b])).toEqual([b.id]);
    expect(newlyArrived(new Set([a.id, b.id]), [a, b])).toEqual([]);
  });
});

describe('what a ticket prints', () => {
  it('uses the receipt’s eight-character code', () => {
    expect(orderCode({ id: 'a1b2c3d4-ffff' })).toBe('#A1B2C3D4');
  });

  it('only shouts about cash owed', () => {
    expect(payLabel('COD')).toBe('Collect cash');
    expect(payKind('COD')).toBe('COD');
    expect(payKind('REFUNDED')).toBe('PAID');
    expect(payLabel('PENDING')).toBe('Unpaid');
    expect(payKind('PENDING')).toBe('UNPAID');
  });

  it('counts items by quantity', () => {
    expect(itemCount([{ quantity: 2 }, { quantity: 1 }])).toBe('3 items');
    expect(itemCount([{ quantity: 1 }])).toBe('1 item');
  });
});

describe('lineModifiers', () => {
  it('prints size first, then groups in the order they were built', () => {
    const rows = lineModifiers(
      line({
        size_name_snapshot: 'Large',
        selected_options_snapshot: [
          { group_id: 'g1', group_title: 'Crust', option_name: 'Thin' },
          { group_id: 'g2', group_title: 'Extras', option_name: 'Cheese', quantity: 2 },
          { group_id: 'g2', group_title: 'Extras', option_name: 'Olives' },
        ],
      }),
    );
    expect(rows).toEqual([
      { label: 'Size', half: null, text: 'Large' },
      { label: 'Crust', half: null, text: 'Thin' },
      { label: 'Extras', half: null, text: 'Cheese ×2 · Olives' },
    ]);
  });

  it('gives each half of a split group its own row', () => {
    const rows = lineModifiers(
      line({
        selected_options_snapshot: [
          { group_id: 'g', group_title: 'Toppings', option_name: 'Pepperoni', portion: 'LEFT' },
          { group_id: 'g', group_title: 'Toppings', option_name: 'Mushroom', portion: 'right' },
        ],
      }),
    );
    expect(rows).toEqual([
      { label: 'Toppings', half: 'LEFT', text: 'Pepperoni' },
      { label: 'Toppings', half: 'RIGHT', text: 'Mushroom' },
    ]);
  });

  it('drops nothing from an old snapshot missing keys', () => {
    const rows = lineModifiers(line({ selected_options_snapshot: [{ option_name: null }] }));
    expect(rows).toEqual([{ label: null, half: null, text: 'Option' }]);
  });
});
