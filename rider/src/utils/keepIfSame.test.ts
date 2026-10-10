import { keepIfSame } from './keepIfSame';

describe('keepIfSame', () => {
  it('keeps the old object when the new answer says the same thing', () => {
    const prev = { id: 'a', items: [{ n: 1 }], at: '2026-10-10T10:00:00Z' };
    const next = { id: 'a', items: [{ n: 1 }], at: '2026-10-10T10:00:00Z' };
    expect(keepIfSame(prev, next)).toBe(prev);
  });

  it('takes the new object when anything changed', () => {
    const prev = { id: 'a', items: [{ n: 1 }] };
    const next = { id: 'a', items: [{ n: 2 }] };
    expect(keepIfSame(prev, next)).toBe(next);
  });

  it('keeps an empty list as the same list - the board polls empty most of the day', () => {
    const prev: number[] = [];
    expect(keepIfSame(prev, [])).toBe(prev);
  });

  it('handles null on either side', () => {
    const value = { id: 'a' };
    expect(keepIfSame(null, null)).toBeNull();
    expect(keepIfSame(null, value)).toBe(value);
    expect(keepIfSame(value, null)).toBeNull();
  });

  it('treats a different key order as the same answer', () => {
    const prev = { a: 1, b: 2 };
    expect(keepIfSame(prev, { b: 2, a: 1 })).toBe(prev);
  });
});
