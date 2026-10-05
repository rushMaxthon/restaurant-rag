import { completedLabel, searchTerm, settledPaymentLabel, startOfToday } from './history';

describe('searchTerm', () => {
  it('drops the # and whitespace, and treats blank as no search', () => {
    expect(searchTerm('  #3f2a ')).toBe('3f2a');
    expect(searchTerm('#')).toBeNull();
    expect(searchTerm('   ')).toBeNull();
  });
});

describe('startOfToday', () => {
  it('is the device’s local midnight, not UTC’s', () => {
    const now = new Date(2026, 9, 3, 15, 45);
    const midnight = new Date(startOfToday(now));
    expect([midnight.getHours(), midnight.getMinutes(), midnight.getDate()]).toEqual([0, 0, 3]);
  });
});

describe('completedLabel', () => {
  const now = new Date(2026, 9, 3, 18, 0);

  it('shows only a time for today', () => {
    expect(completedLabel(new Date(2026, 9, 3, 14, 32).toISOString(), now)).not.toMatch(/,/);
  });

  it('adds the date for any other day, so last Tuesday is not read as today', () => {
    expect(completedLabel(new Date(2026, 8, 29, 14, 32).toISOString(), now)).toMatch(/,/);
  });

  it('says so when there is no completion time', () => {
    expect(completedLabel(null, now)).toBe('Time not recorded');
    expect(completedLabel('not a date', now)).toBe('Time not recorded');
  });
});

describe('settledPaymentLabel', () => {
  it('never says "collect cash" about an order that already went out', () => {
    expect(settledPaymentLabel('COD')).toBe('Cash on delivery');
    expect(settledPaymentLabel('PAID')).toBe('Paid online');
  });
});
