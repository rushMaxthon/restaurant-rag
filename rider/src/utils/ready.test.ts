import { readyLabel } from './ready';

// Built in local time, so the clock reads the same on any machine.
const READY = new Date(2026, 9, 10, 19, 45).toISOString();
const at = (h: number, m: number, s = 0) => new Date(2026, 9, 10, h, m, s);

describe('readyLabel', () => {
  it('says when the food will be ready and how long that is', () => {
    expect(readyLabel(READY, at(19, 27))).toBe('Food ready at 7:45 PM · in 18 min');
  });
  it('rounds a part minute up, never to "in 0 min"', () => {
    expect(readyLabel(READY, at(19, 44, 30))).toBe('Food ready at 7:45 PM · in 1 min');
  });
  it('says it should be ready once the time has come', () => {
    expect(readyLabel(READY, at(19, 45))).toBe('Food should be ready now');
    expect(readyLabel(READY, at(19, 52))).toBe('Food should be ready now');
  });
  it('says nothing when the restaurant has no preparation time set', () => {
    expect(readyLabel(null, at(19, 0))).toBeNull();
    expect(readyLabel(undefined, at(19, 0))).toBeNull();
  });
  it('says nothing for a time it cannot read', () => {
    expect(readyLabel('not a date', at(19, 0))).toBeNull();
  });
});
