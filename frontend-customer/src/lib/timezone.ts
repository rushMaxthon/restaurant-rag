import type { LocationDayOfWeek } from "@/lib/bangkok-data";

/**
 * Wall-clock arithmetic in the restaurant's zone rather than the device's.
 *
 * Opening hours, slots and cutoffs are all written in one clock — the
 * backend's `business_timezone`, which now reaches the client on `/app-config`.
 * A browser, left alone, builds dates in the DEVICE's zone: `setHours(19, 0)`
 * means seven in the evening *here*, not seven at the branch. On a machine in
 * the same zone as the restaurant those are the same moment, which is exactly
 * why this went unnoticed. For a customer in Toronto ordering from Ahmedabad
 * it turned the branch's 7pm window into their own 7pm and sent an instant
 * nine and a half hours out, and the server was right to refuse it.
 *
 * Everything here works in real instants (`Date` is a UTC instant; only its
 * getters are local). Nothing invents a "fake local" date, because those look
 * correct in the debugger and are wrong on the wire.
 *
 * No library: `Intl` already knows every zone and every DST rule the platform
 * does, and a hand-rolled offset table goes stale.
 */

export type ZonedParts = {
  year: number;
  /** 1-12, not the 0-11 that Date uses — this is a reading, not an index. */
  month: number;
  day: number;
  hour: number;
  minute: number;
  weekday: LocationDayOfWeek;
};

const WEEKDAYS: LocationDayOfWeek[] = [
  "SUNDAY",
  "MONDAY",
  "TUESDAY",
  "WEDNESDAY",
  "THURSDAY",
  "FRIDAY",
  "SATURDAY",
];

/** The device's own zone, used whenever no branch zone is known yet. */
export function deviceZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

function partsFormatter(timeZone: string): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    weekday: "short",
  });
}

type RawParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
};

/** The zone's clock reading, as numbers. */
function readParts(date: Date, timeZone: string | undefined): RawParts {
  const zone = timeZone || deviceZone();
  const found = new Map<string, string>();
  for (const part of partsFormatter(zone).formatToParts(date)) {
    if (part.type !== "literal") found.set(part.type, part.value);
  }
  const num = (key: string) => Number(found.get(key) ?? 0);
  return {
    year: num("year"),
    month: num("month"),
    day: num("day"),
    // "24" for midnight is legal in the h23/h24 hour cycles and would break
    // any arithmetic that assumes 0-23.
    hour: num("hour") % 24,
    minute: num("minute"),
    second: num("second"),
  };
}

/** What clock `timeZone` shows for this instant. */
export function zonedParts(date: Date, timeZone: string | undefined): ZonedParts {
  const { year, month, day, hour, minute } = readParts(date, timeZone);
  // The weekday of the CALENDAR DATE this zone is showing, not of the instant
  // in UTC. 20:00 UTC on a Monday is already Tuesday in Kolkata, and the slot
  // table is keyed by the branch's weekday — reading the UTC one silently
  // looks up the wrong day's opening hours for a third of every day.
  const weekday = WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()]!;
  return { year, month, day, hour, minute, weekday };
}

/**
 * How far `timeZone` is from UTC at this instant, in milliseconds.
 *
 * Read at the instant rather than stored, so a zone that observes daylight
 * saving reports -04:00 in July and -05:00 in January without anything here
 * knowing the rule.
 */
export function zoneOffsetMs(date: Date, timeZone: string | undefined): number {
  const here = readParts(date, timeZone);
  // Read the zone's wall clock, then treat that reading as if it were UTC. The
  // gap between that and the real instant IS the offset.
  const asUtc = Date.UTC(here.year, here.month - 1, here.day, here.hour, here.minute, here.second);
  return asUtc - date.getTime();
}

/**
 * The instant a wall-clock time in `timeZone` actually names.
 *
 * The inverse of `zonedParts`, and the half that matters on the wire: the slot
 * table stores "19:00:00" for a branch, and this turns that into the moment the
 * server will agree is 7pm there.
 *
 * Two passes. The first guesses the offset from the naive instant; the second
 * re-reads it at the corrected instant, which is what makes the hour either
 * side of a DST change come out right instead of an hour off.
 */
export function zonedTimeToUtc(
  parts: { year: number; month: number; day: number; hour: number; minute: number },
  timeZone: string | undefined,
): Date {
  const naive = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, 0, 0);
  const firstGuess = new Date(naive - zoneOffsetMs(new Date(naive), timeZone));
  const corrected = new Date(naive - zoneOffsetMs(firstGuess, timeZone));
  return corrected;
}

/** Right now, read on the branch's clock. */
export function nowInZone(timeZone: string | undefined, now = new Date()): ZonedParts {
  return zonedParts(now, timeZone);
}

/** Format an instant on the branch's clock. en-CA to match the rest of the app. */
export function formatInZone(
  date: Date,
  timeZone: string | undefined,
  options: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat("en-CA", {
    ...options,
    timeZone: timeZone || deviceZone(),
  }).format(date);
}
