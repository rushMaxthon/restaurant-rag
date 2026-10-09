import { en, gu, hi } from '@/i18n/strings';
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
        const title = en[step.titleKey];
        const body = en[step.bodyKey];
        expect(title.length).toBeGreaterThan(3);
        expect(title.length).toBeLessThanOrEqual(32);
        expect(body.length).toBeGreaterThan(10);
        expect(body.length).toBeLessThanOrEqual(140);
        // ...and in every language the rider can pick.
        for (const dict of [hi, gu]) {
          expect(dict[step.titleKey].length).toBeGreaterThan(3);
          expect(dict[step.bodyKey].length).toBeGreaterThan(10);
        }
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
