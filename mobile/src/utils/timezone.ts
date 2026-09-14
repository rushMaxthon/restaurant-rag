/**
 * Reading the clock the restaurant keeps, not the one the phone keeps.
 *
 * Opening hours, slots and cutoffs are written in the backend's
 * `business_timezone`, which now reaches the app on `/app-config`. A phone left
 * alone reads every `Date` in the DEVICE's zone: `date.getHours()` answers "what
 * time is it here", never "what time is it at the branch". On a handset in the
 * same zone as the restaurant those are the same answer, which is exactly why
 * this survives testing.
 *
 * Unlike the web client, this app never BUILDS a slot time - the server sends
 * every bookable instant already resolved, with its own label. So there is no
 * wall-clock-to-instant conversion here, and no `zonedTimeToUtc`: everything
 * below reads an instant the server chose. Adding the inverse would mean adding
 * an untested way to disagree with the server about what 7pm means.
 *
 * Everything stays a real instant. Nothing constructs a "fake local" date - the
 * kind that looks right in a debugger and is wrong on the wire.
 */

/** The phone's own zone, used whenever no branch zone is known. */
export function deviceZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/**
 * Whether this JS engine can actually format in a named zone.
 *
 * Hermes is not a browser. Its `Intl` is backed by the platform - ICU on
 * Android, Foundation on iOS - and older or slimmed-down builds ship without
 * full zone data, where `timeZone: 'Asia/Kolkata'` is silently ignored rather
 * than throwing. Silently ignored is the dangerous outcome: every reading would
 * come back in the device zone while the code believed otherwise.
 *
 * So it is proven rather than assumed, once, by formatting one known instant in
 * two zones that genuinely differ and checking that the engine agrees they do.
 * When it cannot, every function here falls back to the device zone - which is
 * precisely how the app behaved before any of this existed.
 */
let namedZoneSupport: boolean | null = null;

export function supportsNamedZones(): boolean {
  if (namedZoneSupport !== null) {
    return namedZoneSupport;
  }
  try {
    const probe = new Date('2024-01-15T12:00:00Z');
    const read = (zone: string) =>
      new Intl.DateTimeFormat('en-US', {
        timeZone: zone,
        hour: '2-digit',
        hour12: false,
      }).format(probe);
    // 12:00 UTC is 07:00 in Toronto and 17:30 in Kolkata. An engine ignoring
    // the option returns the same string for both.
    namedZoneSupport = read('America/Toronto') !== read('Asia/Kolkata');
  } catch {
    namedZoneSupport = false;
  }
  return namedZoneSupport;
}

/** Test seam: forget the probe result so a test can re-run it. */
export function resetNamedZoneSupportForTests(): void {
  namedZoneSupport = null;
  zoneUsable.clear();
}

/**
 * Whether this engine accepts this particular zone name.
 *
 * `business_timezone` is a free-text setting on the server. A typo in it - or
 * a zone this platform's data simply does not carry - makes `Intl` throw
 * `RangeError`, and an exception thrown while formatting a label takes the
 * whole screen with it. A mistyped setting should cost the customer the
 * restaurant's clock, not the cart.
 *
 * Cached per name: the answer cannot change within a run, and this sits on the
 * path of every timestamp the app renders.
 */
const zoneUsable = new Map<string, boolean>();

function isUsableZone(timeZone: string): boolean {
  const cached = zoneUsable.get(timeZone);
  if (cached !== undefined) {
    return cached;
  }
  let usable: boolean;
  try {
    new Intl.DateTimeFormat('en-US', {timeZone}).format(new Date());
    usable = true;
  } catch {
    usable = false;
  }
  zoneUsable.set(timeZone, usable);
  return usable;
}

/**
 * The zone to actually hand `Intl`, or undefined for "use the device's".
 *
 * One choke point, so an engine without zone data, an unknown branch zone and
 * an unusable zone name all degrade the same way instead of each being handled
 * at every call site.
 */
function resolveZone(timeZone: string | undefined): string | undefined {
  if (!timeZone || !supportsNamedZones() || !isUsableZone(timeZone)) {
    return undefined;
  }
  return timeZone;
}

export type ZonedParts = {
  year: number;
  /** 1-12, not the 0-11 that Date uses - this is a reading, not an index. */
  month: number;
  day: number;
  hour: number;
  minute: number;
  /** 0 = Sunday, matching `Date.getUTCDay()`. */
  weekday: number;
};

function partsFormatter(timeZone: string | undefined): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: resolveZone(timeZone),
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** What clock `timeZone` shows for this instant. */
export function zonedParts(
  date: Date,
  timeZone: string | undefined,
): ZonedParts {
  const found = new Map<string, string>();
  for (const part of partsFormatter(timeZone).formatToParts(date)) {
    if (part.type !== 'literal') {
      found.set(part.type, part.value);
    }
  }
  const num = (key: string) => Number(found.get(key) ?? 0);
  const year = num('year');
  const month = num('month');
  const day = num('day');
  return {
    year,
    month,
    day,
    // "24" for midnight is legal in the h23/h24 hour cycles and would break any
    // arithmetic assuming 0-23.
    hour: num('hour') % 24,
    minute: num('minute'),
    // The weekday of the CALENDAR DATE the zone is showing, not of the instant
    // in UTC. 20:00 UTC Monday is already Tuesday in Kolkata, and opening hours
    // are keyed by the branch's weekday - reading the device's silently looks
    // up the wrong day for part of every day.
    weekday: new Date(Date.UTC(year, month - 1, day)).getUTCDay(),
  };
}

/**
 * A whole-day number for the calendar date this zone is showing.
 *
 * Purely for subtracting one date from another to get "today / tomorrow / later"
 * without either date being converted. Because it is built from the zone's own
 * reading, it is unaffected by daylight saving: a 23-hour day still advances the
 * count by exactly one.
 */
export function zonedDayIndex(date: Date, timeZone: string | undefined): number {
  const {year, month, day} = zonedParts(date, timeZone);
  return Date.UTC(year, month - 1, day) / 86400000;
}

/** Whole days from `from`'s calendar date to `date`'s, on the branch's clock. */
export function zonedDayDifference(
  date: Date,
  from: Date,
  timeZone: string | undefined,
): number {
  return zonedDayIndex(date, timeZone) - zonedDayIndex(from, timeZone);
}

/**
 * Format an instant on the branch's clock.
 *
 * `en-CA` to match the rest of the app's formatting, so a time rendered here
 * and a price rendered by `formatCurrency` belong to the same locale.
 */
export function formatInZone(
  date: Date,
  timeZone: string | undefined,
  options: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat('en-CA', {
    ...options,
    timeZone: resolveZone(timeZone),
  }).format(date);
}
