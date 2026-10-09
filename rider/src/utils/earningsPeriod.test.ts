import { PERIODS, periodFor, showsChart } from './earningsPeriod';

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
