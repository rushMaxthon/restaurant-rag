import { TARGETS, TOURS, type TourId } from './tours';

describe('the spotlight tours', () => {
  const ids = Object.keys(TOURS) as TourId[];

  it('cover every screen a new rider meets', () => {
    expect(ids.sort()).toEqual(['earnings', 'home', 'orders', 'otp', 'trip']);
  });

  it('point every step at a control that can register itself', () => {
    for (const id of ids) {
      for (const step of TOURS[id].steps) {
        expect(Object.values(TARGETS)).toContain(step.target);
      }
    }
  });

  it('say something at every step, in one short title and one line', () => {
    for (const id of ids) {
      expect(TOURS[id].steps.length).toBeGreaterThan(0);
      for (const step of TOURS[id].steps) {
        expect(step.title.length).toBeGreaterThan(3);
        expect(step.title.length).toBeLessThanOrEqual(32);
        expect(step.body.length).toBeGreaterThan(10);
        expect(step.body.length).toBeLessThanOrEqual(140);
      }
    }
  });

  it('never reuse a target inside one tour', () => {
    for (const id of ids) {
      const targets = TOURS[id].steps.map(s => s.target);
      expect(new Set(targets).size).toBe(targets.length);
    }
  });
});

describe('which tours run under the floating tab bar', () => {
  it('marks the tab screens, so a control hidden under the bar is not pointed at', () => {
    expect(TOURS.home.tabbed).toBe(true);
    expect(TOURS.orders.tabbed).toBe(true);
    expect(TOURS.earnings.tabbed).toBe(true);
    expect(TOURS.trip.tabbed).toBe(false);
    expect(TOURS.otp.tabbed).toBe(false);
  });
});
