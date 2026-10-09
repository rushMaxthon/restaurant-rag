import { PERIODS, heroLine, periodFor, showsChart } from './earningsPeriod';

describe('the earnings period switch', () => {
  it('offers today, the week and the month, in that order', () => {
    expect(PERIODS.map(p => p.key)).toEqual(['today', 'week', 'month']);
    expect(PERIODS.map(p => p.days)).toEqual([1, 7, 30]);
  });

  it('labels the hero with the period', () => {
    expect(periodFor('today').heroLabel).toBe('TODAY');
    expect(periodFor('week').heroLabel).toBe('LAST 7 DAYS');
    expect(periodFor('month').heroLabel).toBe('LAST 30 DAYS');
  });

  it('has no chart for a single day: one bar says nothing', () => {
    expect(showsChart('today')).toBe(false);
    expect(showsChart('week')).toBe(true);
    expect(showsChart('month')).toBe(true);
  });

  it('falls back to the week for an unknown key from storage', () => {
    expect(periodFor('whatever' as never).key).toBe('week');
  });
});

describe('the line under the earnings total', () => {
  it('says how many deliveries and what each paid on average', () => {
    expect(heroLine(3, '132.60')).toBe('3 deliveries · ₹44 each');
  });

  it('does not say "each" about a single delivery', () => {
    expect(heroLine(1, '49')).toBe('1 delivery');
  });

  it('says so when there were none, rather than dividing by zero', () => {
    expect(heroLine(0, '0')).toBe('No deliveries yet');
  });
});
