import { actionId, distance, initials, rupees } from './format';

describe('rupees', () => {
  it('groups the Indian way', () => {
    expect(rupees(123456)).toBe('₹1,23,456');
    expect(rupees('1500')).toBe('₹1,500');
  });
  it('keeps paise only when there are some', () => {
    expect(rupees('49.00')).toBe('₹49');
    expect(rupees('49.50')).toBe('₹49.50');
  });
  it('never prints NaN', () => {
    expect(rupees('abc')).toBe('₹0');
    expect(rupees(null)).toBe('₹0');
  });
});

describe('distance', () => {
  it('rounds short hops to 50 m and longer ones to 0.1 km', () => {
    expect(distance(420)).toBe('400 m');
    expect(distance(2380)).toBe('2.4 km');
  });
  it('shows a dash when unknown', () => {
    expect(distance(null)).toBe('—');
  });
});

describe('initials', () => {
  it('takes first and last names', () => {
    expect(initials('Ravi Kumar Patel')).toBe('RP');
    expect(initials('ravi')).toBe('R');
  });
});

describe('actionId', () => {
  it('is unique per tap', () => {
    expect(new Set(Array.from({ length: 50 }, actionId)).size).toBe(50);
  });
});

describe('weekday and prettyPhone', () => {
  it('names the weekday of a date', () => {
    const { weekday } = require('./format');
    expect(weekday('2026-10-08')).toBe('Thu');
  });
  it('spaces an Indian mobile number', () => {
    const { prettyPhone } = require('./format');
    expect(prettyPhone('+919876543210')).toBe('+91 98765 43210');
  });
});

describe('initials skips words that are not names', () => {
  it('reads past brackets and punctuation', () => {
    expect(initials('Test Rider (test)')).toBe('TR');
    expect(initials('Ravi - Cycle')).toBe('RC');
  });
});
