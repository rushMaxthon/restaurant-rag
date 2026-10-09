import { jobMinutes, awayLabel, etaMinutes, metresBetween } from './geo';

describe('metresBetween', () => {
  it('is about 1.1 km for 0.01 degrees of latitude', () => {
    expect(metresBetween(21.2, 72.8, 21.21, 72.8)).toBeGreaterThan(1100);
    expect(metresBetween(21.2, 72.8, 21.21, 72.8)).toBeLessThan(1125);
  });
  it('is zero for the same point', () => {
    expect(metresBetween(21.2, 72.8, 21.2, 72.8)).toBe(0);
  });
});

describe('etaMinutes', () => {
  it('rides the road (x1.3) at 18 km/h', () => {
    // 3 km straight -> 3.9 km road -> 13 min at 18 km/h
    expect(etaMinutes(3000)).toBe(13);
  });
  it('is at least a minute', () => {
    expect(etaMinutes(20)).toBe(1);
  });
});

describe('awayLabel', () => {
  // The distance shown is the ROAD estimate (x1.3), the one the rider rides.
  it('says how far and how long', () => {
    expect(awayLabel(1400)).toBe('1.8 km away · about 6 min');
  });
  it('calls a very short distance arriving', () => {
    expect(awayLabel(60)).toBe('Arriving now');
  });
  it('shows short distances in metres', () => {
    expect(awayLabel(450)).toBe('600 m away · about 2 min');
  });
});

describe('jobMinutes', () => {
  // Pickup is straight-line from the server (x1.3 for roads); the trip is
  // already road km. Both at 18 km/h.
  it('adds the ride to the restaurant and the trip', () => {
    expect(jobMinutes(1000, 4)).toBe(18); // 1.3 km + 4 km = 5.3 km -> 17.7 min
  });
  it('is never zero', () => {
    expect(jobMinutes(0, 0)).toBe(1);
  });
  it('copes with an unknown pickup distance', () => {
    expect(jobMinutes(null, 3)).toBe(10);
  });
});
