/**
 * The labels a customer reads back after choosing a time.
 *
 * The instants here are real ones taken from the server's own
 * `/schedule-options` response for a branch on `Asia/Kolkata`: it serialises
 * every slot WITH the branch's offset (`2026-09-15T11:30:00+05:30`) and labels
 * it "11:30 AM". The app's job is to keep saying that, from any phone.
 */

import type {RestaurantLocation} from '@/types/app';
import {
  etaClockTime,
  formatFulfillmentSelectionLabel,
  formatScheduledAtLabel,
  getFulfillmentEtaMinutes,
} from './fulfillment';

const KOLKATA = 'Asia/Kolkata';
const TORONTO = 'America/Toronto';

/** A slot the server offered, labelled "11:30 AM" by the server itself. */
const SLOT = '2026-09-15T11:30:00+05:30';

function locationWith(
  overrides: Partial<RestaurantLocation> = {},
): RestaurantLocation {
  return {
    estimated_delivery_time: 29,
    estimated_pickup_time: 20,
    ...overrides,
  } as RestaurantLocation;
}

describe('formatScheduledAtLabel', () => {
  it('says the time the branch would say, from a phone in another zone', () => {
    // The whole bug in one assertion: the same instant, read on the branch's
    // clock, is 11:30 - which is the label the customer tapped in the picker.
    expect(formatScheduledAtLabel(SLOT, KOLKATA)).toContain('11:30');
    // Left to the device zone the app would say 2:00 a.m. - an hour no kitchen
    // in this story is open, and a time the customer never chose.
    expect(formatScheduledAtLabel(SLOT, TORONTO)).toContain('2:00');
  });

  it('buckets Today/Tomorrow on the branch calendar, not the phone calendar', () => {
    jest.useFakeTimers();
    try {
      // 20:00 UTC on the 14th: still Monday the 14th in Toronto, already
      // Tuesday the 15th in Kolkata.
      jest.setSystemTime(new Date('2026-09-14T20:00:00Z'));
      // Same day at the branch, so the branch would call this "Today".
      expect(formatScheduledAtLabel(SLOT, KOLKATA)).toMatch(/^Today /);
      // The device's calendar has not turned over yet, so reading it there
      // produces a different word for the same slot.
      expect(formatScheduledAtLabel(SLOT, TORONTO)).toMatch(/^Tomorrow /);
    } finally {
      jest.useRealTimers();
    }
  });

  it('keeps the day and the time on the SAME clock', () => {
    jest.useFakeTimers();
    try {
      jest.setSystemTime(new Date('2026-09-14T20:00:00Z'));
      // A half-migrated version formatting the time in the branch zone while
      // still bucketing the day on the device's would emit "Tomorrow 11:30" -
      // an instant that does not exist. Both halves move together or neither.
      expect(formatScheduledAtLabel(SLOT, KOLKATA)).toBe(
        `Today ${formatScheduledAtLabel(SLOT, KOLKATA).split('Today ')[1]}`,
      );
      expect(formatScheduledAtLabel(SLOT, KOLKATA)).not.toMatch(/^Tomorrow/);
    } finally {
      jest.useRealTimers();
    }
  });

  it('falls back to the device clock when no zone is known', () => {
    // An older backend sends no `business_timezone`. That must render the way
    // the app always did, not blank and not a crash.
    expect(formatScheduledAtLabel(SLOT)).toBe(formatScheduledAtLabel(SLOT, undefined));
    expect(formatScheduledAtLabel(SLOT)).not.toBe('Schedule later');
  });

  it('still says "Schedule later" for nothing and for nonsense', () => {
    expect(formatScheduledAtLabel(null, KOLKATA)).toBe('Schedule later');
    expect(formatScheduledAtLabel(undefined, KOLKATA)).toBe('Schedule later');
    expect(formatScheduledAtLabel('not-a-date', KOLKATA)).toBe('Schedule later');
  });

  it('names a weekday for anything past tomorrow', () => {
    jest.useFakeTimers();
    try {
      jest.setSystemTime(new Date('2026-09-14T20:00:00Z'));
      const label = formatScheduledAtLabel('2026-09-20T11:30:00+05:30', KOLKATA);
      expect(label).not.toMatch(/^Today|^Tomorrow/);
      expect(label).toMatch(/Sep/);
    } finally {
      jest.useRealTimers();
    }
  });
});

describe('formatFulfillmentSelectionLabel', () => {
  it('carries the zone through to the scheduled time', () => {
    const selection = {
      fulfillmentType: 'DELIVERY' as const,
      scheduleType: 'SCHEDULED' as const,
      scheduledAt: SLOT,
    };
    expect(
      formatFulfillmentSelectionLabel(locationWith(), selection, KOLKATA),
    ).toContain('11:30');
    expect(
      formatFulfillmentSelectionLabel(locationWith(), selection, TORONTO),
    ).toContain('2:00');
  });

  it('leaves the ASAP label alone - it is a duration, not a clock time', () => {
    const selection = {
      fulfillmentType: 'DELIVERY' as const,
      scheduleType: 'ASAP' as const,
      scheduledAt: null,
    };
    expect(
      formatFulfillmentSelectionLabel(locationWith(), selection, KOLKATA),
    ).toBe(
      formatFulfillmentSelectionLabel(locationWith(), selection, TORONTO),
    );
  });
});

describe('getFulfillmentEtaMinutes', () => {
  it('reads the minutes for the fulfillment type actually chosen', () => {
    expect(getFulfillmentEtaMinutes(locationWith(), 'DELIVERY')).toBe(29);
    expect(getFulfillmentEtaMinutes(locationWith(), 'PICKUP')).toBe(20);
  });

  it('returns null with no branch, because the fallback ETA is a range', () => {
    expect(getFulfillmentEtaMinutes(null, 'DELIVERY')).toBeNull();
    expect(getFulfillmentEtaMinutes(undefined, 'PICKUP')).toBeNull();
  });

  it('returns null rather than a nonsense arrival time', () => {
    expect(
      getFulfillmentEtaMinutes(
        locationWith({estimated_delivery_time: 0}),
        'DELIVERY',
      ),
    ).toBeNull();
  });
});

describe('etaClockTime', () => {
  it('adds the ETA to now and reads the result on the branch clock', () => {
    // 10:00 IST + 29 min = 10:29 at the branch. The same instant read in
    // Toronto is 12:59 a.m. - nearly half a day out, and what a customer there
    // would have been told their food was arriving by.
    const now = new Date('2026-09-15T10:00:00+05:30');
    expect(etaClockTime(29, now, KOLKATA)).toMatch(/^10:29/);
    expect(etaClockTime(29, now, TORONTO)).toMatch(/^12:59 a/);
  });

  it('crosses midnight at the branch without changing the instant', () => {
    const now = new Date('2026-09-15T23:50:00+05:30');
    expect(etaClockTime(29, now, KOLKATA)).toMatch(/^12:19/);
  });

  it('says nothing rather than guessing when there is no ETA', () => {
    expect(etaClockTime(null, new Date(), KOLKATA)).toBeNull();
  });
});
