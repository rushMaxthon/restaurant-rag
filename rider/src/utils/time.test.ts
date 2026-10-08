import { secondsLeft } from './time';

describe('secondsLeft', () => {
  it('rounds up so the last partial second still shows 1', () => {
    expect(secondsLeft(10_100, 10_000)).toBe(1);
  });
  it('is exactly the whole seconds at a boundary', () => {
    expect(secondsLeft(40_000, 10_000)).toBe(30);
  });
  it('never goes negative once the offer has expired', () => {
    expect(secondsLeft(10_000, 99_000)).toBe(0);
  });
});
