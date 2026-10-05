import { order } from '@/test/fixtures';
import { boardMetrics, matchesFilter, priorityLabel } from './metrics';

const now = new Date('2026-10-03T12:30:00Z');
const ago = (minutes: number) => new Date(now.getTime() - minutes * 60000).toISOString();

describe('boardMetrics', () => {
  it('takes the median wait, so one stuck ticket cannot skew it', () => {
    const orders = [ago(2), ago(4), ago(90)].map(placed_at =>
      order({ status: 'PREPARING', placed_at }),
    );
    expect(boardMetrics(orders, now).medianWait).toBe(4);
  });

  it('averages the middle two for an even count', () => {
    const orders = [ago(2), ago(4)].map(placed_at => order({ status: 'PREPARING', placed_at }));
    expect(boardMetrics(orders, now).medianWait).toBe(3);
  });

  it('counts only late tickets as overdue, and has no median when empty', () => {
    expect(boardMetrics([order({ placed_at: ago(6) }), order({ placed_at: ago(1) })], now).overdue).toBe(1);
    expect(boardMetrics([], now)).toEqual({ overdue: 0, medianWait: null, total: 0 });
  });
});

describe('priorityLabel', () => {
  it('derives the badge from waiting time alone', () => {
    expect(priorityLabel(order({ placed_at: ago(1) }), now)).toBeNull();
    expect(priorityLabel(order({ placed_at: ago(3) }), now)).toBe('SOON');
    expect(priorityLabel(order({ placed_at: ago(9) }), now)).toBe('URGENT');
  });
});

describe('matchesFilter', () => {
  const pickup = order({ id: 'abcd1234-x', fulfillment_type: 'PICKUP', placed_at: ago(1) });

  it('matches an order code read aloud, with or without #, any case', () => {
    expect(matchesFilter(pickup, 'ALL', '#ABCD', now)).toBe(true);
    expect(matchesFilter(pickup, 'ALL', 'abcd12', now)).toBe(true);
    expect(matchesFilter(pickup, 'ALL', 'bcd', now)).toBe(false);
  });

  it('filters by fulfillment and by priority', () => {
    expect(matchesFilter(pickup, 'PICKUP', '', now)).toBe(true);
    expect(matchesFilter(pickup, 'DELIVERY', '', now)).toBe(false);
    expect(matchesFilter(pickup, 'PRIORITY', '', now)).toBe(false);
    expect(matchesFilter({ ...pickup, placed_at: ago(4) }, 'PRIORITY', '', now)).toBe(true);
  });
});
