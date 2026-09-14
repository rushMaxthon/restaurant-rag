/**
 * The zone primitives, and the one thing they exist to prevent.
 *
 * Every case below is written against a REAL instant and two zones that
 * genuinely disagree about what day and hour it is. Asserting against a single
 * zone would pass on a machine sitting in that zone and prove nothing, which is
 * how the bug this fixes survived in the first place.
 */

import {
  deviceZone,
  formatInZone,
  resetNamedZoneSupportForTests,
  supportsNamedZones,
  zonedDayDifference,
  zonedDayIndex,
  zonedParts,
} from './timezone';

const TORONTO = 'America/Toronto';
const KOLKATA = 'Asia/Kolkata';

beforeEach(() => {
  resetNamedZoneSupportForTests();
});

describe('supportsNamedZones', () => {
  it('recognises an engine that honours a named zone', () => {
    expect(supportsNamedZones()).toBe(true);
  });

  it('reports no support when the engine ignores the zone option', () => {
    // Hermes on a slimmed-down build accepts `timeZone` and silently ignores
    // it. Simulated here by an Intl that always formats the same way.
    const real = Intl.DateTimeFormat;
    const fake = function (locale?: string, options?: Intl.DateTimeFormatOptions) {
      return new real(locale, { ...options, timeZone: 'UTC' });
    } as unknown as typeof Intl.DateTimeFormat;
    (Intl as { DateTimeFormat: typeof Intl.DateTimeFormat }).DateTimeFormat = fake;
    try {
      expect(supportsNamedZones()).toBe(false);
    } finally {
      (Intl as { DateTimeFormat: typeof Intl.DateTimeFormat }).DateTimeFormat = real;
    }
  });

  it('reports no support rather than throwing when Intl blows up', () => {
    const real = Intl.DateTimeFormat;
    (Intl as { DateTimeFormat: typeof Intl.DateTimeFormat }).DateTimeFormat = (() => {
      throw new Error('no ICU');
    }) as unknown as typeof Intl.DateTimeFormat;
    try {
      expect(supportsNamedZones()).toBe(false);
    } finally {
      (Intl as { DateTimeFormat: typeof Intl.DateTimeFormat }).DateTimeFormat = real;
    }
  });
});

describe('deviceZone', () => {
  it('returns an IANA name', () => {
    expect(deviceZone()).toMatch(/^[A-Za-z]+(\/[A-Za-z_+\-0-9]+)*$/);
  });
});

describe('zonedParts', () => {
  it('reads the clock of the zone asked for, not the runtime', () => {
    // 11:30 IST on the 15th is 02:00 EDT on the same morning.
    const instant = new Date('2026-09-15T11:30:00+05:30');
    expect(zonedParts(instant, KOLKATA)).toMatchObject({
      year: 2026,
      month: 9,
      day: 15,
      hour: 11,
      minute: 30,
    });
    expect(zonedParts(instant, TORONTO)).toMatchObject({
      year: 2026,
      month: 9,
      day: 15,
      hour: 2,
      minute: 0,
    });
  });

  it('gives the two zones different calendar DAYS when they disagree', () => {
    // 20:00 UTC Monday is already Tuesday in Kolkata. Opening hours are keyed
    // by weekday, so reading the wrong one looks up the wrong day's hours.
    const instant = new Date('2026-09-14T20:00:00Z');
    expect(zonedParts(instant, TORONTO).day).toBe(14);
    expect(zonedParts(instant, KOLKATA).day).toBe(15);
  });

  it('numbers the weekday from the zone calendar date, Sunday first', () => {
    const instant = new Date('2026-09-14T20:00:00Z');
    // Monday in Toronto, already Tuesday in Kolkata.
    expect(zonedParts(instant, TORONTO).weekday).toBe(1);
    expect(zonedParts(instant, KOLKATA).weekday).toBe(2);
  });

  it('reports midnight as hour 0, never 24', () => {
    const midnight = new Date('2026-09-15T00:00:00+05:30');
    expect(zonedParts(midnight, KOLKATA).hour).toBe(0);
  });

  it('falls back to the device zone when the zone is unknown', () => {
    const instant = new Date('2026-09-15T11:30:00+05:30');
    expect(zonedParts(instant, undefined)).toEqual(
      zonedParts(instant, deviceZone()),
    );
  });
});

describe('zonedDayIndex / zonedDayDifference', () => {
  it('counts a calendar day as one, across a daylight-saving change', () => {
    // Toronto loses an hour overnight on 2026-03-08: a 23-hour day that must
    // still advance the calendar by exactly one.
    const before = new Date('2026-03-07T12:00:00-05:00');
    const after = new Date('2026-03-08T12:00:00-04:00');
    expect(zonedDayDifference(after, before, TORONTO)).toBe(1);
  });

  it('disagrees between zones exactly where the calendars do', () => {
    const now = new Date('2026-09-14T20:00:00Z');
    const slot = new Date('2026-09-15T11:30:00+05:30');
    // Kolkata is already on the 15th, so that slot is later the same day.
    expect(zonedDayDifference(slot, now, KOLKATA)).toBe(0);
    // Toronto is still on the 14th, so the same instant is tomorrow.
    expect(zonedDayDifference(slot, now, TORONTO)).toBe(1);
  });

  it('is a whole number of days regardless of the time of day', () => {
    const a = new Date('2026-09-14T23:59:00+05:30');
    const b = new Date('2026-09-15T00:01:00+05:30');
    expect(zonedDayIndex(b, KOLKATA) - zonedDayIndex(a, KOLKATA)).toBe(1);
  });
});

describe('formatInZone', () => {
  it('renders one instant differently in two zones', () => {
    const instant = new Date('2026-09-15T11:30:00+05:30');
    const options: Intl.DateTimeFormatOptions = {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    };
    expect(formatInZone(instant, KOLKATA, options)).toMatch(/^11:30/);
    expect(formatInZone(instant, TORONTO, options)).toMatch(/^2:00/);
  });

  it('falls back to the device zone rather than throwing on a bad zone name', () => {
    const instant = new Date('2026-09-15T11:30:00+05:30');
    // A zone the engine rejects must not take the screen down with it.
    expect(() =>
      formatInZone(instant, 'Not/AZone', { hour: 'numeric' }),
    ).not.toThrow();
  });
});
