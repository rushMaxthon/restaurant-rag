import type { FulfillmentSlot, LocationDayOfWeek, RestaurantLocation } from "@/lib/bangkok-data";

/**
 * Reading a branch's opening hours out of what the API already sends.
 *
 * `/restaurants/{id}` returns `fulfillment_slots` for every location, plus
 * `delivery_available_now` / `pickup_available_now` and the reason when either
 * is false. The customer app ignored all of it, so at 11pm — when every branch
 * is outside its schedule — you could still fill a cart, reach checkout, and
 * only then be told "This branch is unavailable for the selected fulfillment
 * type right now". The backend was right; nothing had asked it.
 *
 * The server stays the authority on whether an order may be placed. Everything
 * here is for telling the customer BEFORE they get that far.
 */

/** Used only when the location did not say; the server enforces the real limit. */
const DEFAULT_FUTURE_DAYS = 7;

export type Fulfillment = "DELIVERY" | "PICKUP";

/** Monday-first, matching LocationDayOfWeek and the admin's own ordering. */
export const DAY_ORDER: LocationDayOfWeek[] = [
  "MONDAY",
  "TUESDAY",
  "WEDNESDAY",
  "THURSDAY",
  "FRIDAY",
  "SATURDAY",
  "SUNDAY",
];

const DAY_LABELS: Record<LocationDayOfWeek, string> = {
  MONDAY: "Monday",
  TUESDAY: "Tuesday",
  WEDNESDAY: "Wednesday",
  THURSDAY: "Thursday",
  FRIDAY: "Friday",
  SATURDAY: "Saturday",
  SUNDAY: "Sunday",
};

export function dayLabel(day: LocationDayOfWeek): string {
  return DAY_LABELS[day];
}

/** JS getDay() is Sunday-first; the slot enum is Monday-first. */
export function dayFromDate(date: Date): LocationDayOfWeek {
  return DAY_ORDER[(date.getDay() + 6) % 7]!;
}

/** "21:30:00" -> "9:30 pm". The column stores seconds nobody wants to read. */
export function formatSlotTime(value: string): string {
  const [hourText, minuteText] = value.split(":");
  const hour = Number(hourText);
  const minute = Number(minuteText);
  if (Number.isNaN(hour) || Number.isNaN(minute)) return value;
  const suffix = hour < 12 ? "am" : "pm";
  const display = hour % 12 || 12;
  return minute
    ? `${display}:${String(minute).padStart(2, "0")} ${suffix}`
    : `${display} ${suffix}`;
}

export function formatSlotRange(slot: FulfillmentSlot): string {
  return `${formatSlotTime(slot.start_time)} – ${formatSlotTime(slot.end_time)}`;
}

function minutesInto(value: string): number {
  const [hour, minute] = value.split(":");
  return Number(hour) * 60 + Number(minute);
}

export function activeSlots(
  location: RestaurantLocation | undefined,
  type: Fulfillment,
): FulfillmentSlot[] {
  return (location?.fulfillment_slots ?? []).filter(
    (slot) => slot.is_active && slot.fulfillment_type === type,
  );
}

/** This location's windows for one fulfilment type, grouped Monday-first. */
export function weeklySlots(
  location: RestaurantLocation | undefined,
  type: Fulfillment,
): { day: LocationDayOfWeek; slots: FulfillmentSlot[] }[] {
  const slots = activeSlots(location, type);
  return DAY_ORDER.map((day) => ({
    day,
    slots: slots
      .filter((slot) => slot.day_of_week === day)
      .sort((a, b) => minutesInto(a.start_time) - minutesInto(b.start_time)),
  }));
}

/**
 * Whether this fulfilment is open right now, and why not when it is not.
 *
 * Prefers the server's own answer — it owns the rule, including temporary
 * closures the slot table knows nothing about — and only derives one from the
 * slots when the server did not send it.
 */
export function availabilityNow(
  location: RestaurantLocation | undefined,
  type: Fulfillment,
  now = new Date(),
): { available: boolean; reason: string | null } {
  if (!location) return { available: false, reason: null };

  const serverAnswer =
    type === "DELIVERY" ? location.delivery_available_now : location.pickup_available_now;
  const serverReason =
    type === "DELIVERY" ? location.delivery_unavailable_reason : location.pickup_unavailable_reason;
  if (typeof serverAnswer === "boolean") {
    return { available: serverAnswer, reason: serverAnswer ? null : (serverReason ?? null) };
  }

  const today = dayFromDate(now);
  const minutes = now.getHours() * 60 + now.getMinutes();
  const open = activeSlots(location, type).some(
    (slot) =>
      slot.day_of_week === today &&
      minutes >= minutesInto(slot.start_time) &&
      minutes <= minutesInto(slot.end_time),
  );
  return { available: open, reason: open ? null : "Outside the branch's opening hours." };
}

/** The next window that opens, so "closed" can say when to come back. */
export function nextOpening(
  location: RestaurantLocation | undefined,
  type: Fulfillment,
  now = new Date(),
): { day: LocationDayOfWeek; slot: FulfillmentSlot; isToday: boolean } | null {
  const slots = activeSlots(location, type);
  if (slots.length === 0) return null;

  const todayIndex = DAY_ORDER.indexOf(dayFromDate(now));
  const minutes = now.getHours() * 60 + now.getMinutes();

  // Walk the week from today, so Sunday night rolls into Monday rather than
  // reporting "no upcoming slots".
  for (let offset = 0; offset < 7; offset += 1) {
    const day = DAY_ORDER[(todayIndex + offset) % 7]!;
    const candidates = slots
      .filter((slot) => slot.day_of_week === day)
      .filter((slot) => offset > 0 || minutesInto(slot.start_time) > minutes)
      .sort((a, b) => minutesInto(a.start_time) - minutesInto(b.start_time));
    if (candidates[0]) return { day, slot: candidates[0], isToday: offset === 0 };
  }
  return null;
}

/**
 * How soon this branch can realistically have an order ready.
 *
 * Mirrors the server: `max(preparation_time_minutes, the ETA for this
 * fulfilment type)`. Using preparation time alone offers slots the server then
 * rejects — delivery prep is ~16 minutes here but the ETA is ~29, and the
 * server enforces the larger.
 */
export function leadMinutes(location: RestaurantLocation | undefined, type: Fulfillment): number {
  if (!location) return 0;
  const eta = Number(
    type === "DELIVERY" ? location.estimated_delivery_time : location.estimated_pickup_time,
  );
  const prep = Number(location.preparation_time_minutes ?? 0);
  return Math.max(Number.isFinite(prep) ? prep : 0, Number.isFinite(eta) ? eta : 0);
}

/** Midnight on `date`, so day arithmetic never inherits a time of day. */
function startOfDay(date: Date): Date {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

export function isSameDay(a: Date, b: Date): boolean {
  return startOfDay(a).getTime() === startOfDay(b).getTime();
}

/**
 * The days this branch can be booked for, today first.
 *
 * Bounded by the branch's own `max_future_days`, and a day only appears if it
 * has at least one time left on it — an empty day in the picker is a dead end
 * the customer has to discover by tapping.
 */
export function bookableDays(
  location: RestaurantLocation | undefined,
  type: Fulfillment,
  now = new Date(),
): Date[] {
  if (!location || location.future_order_enabled === false) return [];
  // An unknown horizon is not a zero horizon. Defaulting to 0 hid every future
  // slot the server would happily have accepted; when the field is missing the
  // limit is simply left to the server, which enforces it anyway.
  const horizon = Math.max(0, Number(location.max_future_days ?? DEFAULT_FUTURE_DAYS));
  const days: Date[] = [];
  for (let offset = 0; offset <= horizon; offset += 1) {
    const day = startOfDay(now);
    day.setDate(day.getDate() + offset);
    if (bookableTimes(location, type, dayFromDate(day), day, now).length > 0) {
      days.push(day);
    }
  }
  return days;
}

/**
 * Bookable start times on one day, as real Date objects.
 *
 * Aligned to the branch's `slot_interval_minutes` GRID rather than stepped from
 * the window's start: the server rejects anything whose minute is not a
 * multiple of the interval, so a window opening at 10:45 with a 30-minute
 * interval must offer 11:00, not 10:45.
 *
 * Nothing is offered sooner than the branch can have it ready, and nothing
 * beyond `max_future_days`.
 */
export function bookableTimes(
  location: RestaurantLocation | undefined,
  type: Fulfillment,
  day: LocationDayOfWeek,
  dayDate: Date,
  now = new Date(),
): Date[] {
  if (!location) return [];
  const step = Math.max(Number(location.slot_interval_minutes ?? 30), 5);
  const earliest = new Date(now.getTime() + leadMinutes(location, type) * 60_000);

  const horizon = new Date(now);
  horizon.setDate(
    horizon.getDate() + Math.max(0, Number(location.max_future_days ?? DEFAULT_FUTURE_DAYS)),
  );

  const times: Date[] = [];
  for (const slot of activeSlots(location, type).filter((s) => s.day_of_week === day)) {
    const start = minutesInto(slot.start_time);
    // The kitchen has to still be open while it cooks, so the window ends a
    // lead time before it shuts. Mirrors the server, which refuses anything
    // later: a branch closing at 11pm with a 15 minute prep time offered an
    // 11pm slot, and the customer only found out after filling in the form.
    const end = minutesInto(slot.end_time) - leadMinutes(location, type);
    // First grid point at or after the window opens.
    for (let minute = Math.ceil(start / step) * step; minute <= end; minute += step) {
      const at = startOfDay(dayDate);
      at.setHours(Math.floor(minute / 60), minute % 60, 0, 0);
      if (at >= earliest && at <= horizon) times.push(at);
    }
  }
  return times.sort((a, b) => a.getTime() - b.getTime());
}

/** "Today", "Tomorrow", then the weekday and date. */
export function dayChipLabel(date: Date, now = new Date()): string {
  if (isSameDay(date, now)) return "Today";
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  if (isSameDay(date, tomorrow)) return "Tomorrow";
  return new Intl.DateTimeFormat("en-CA", {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(date);
}

export function formatTimeOfDay(date: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(date);
}

/**
 * A Date as the `yyyy-mm-dd` an `<input type="date">` expects.
 *
 * Deliberately not `toISOString().slice(0, 10)`. That converts to UTC first,
 * so an evening in any negative offset reports tomorrow's date and the
 * customer books a day they did not choose. Read off the local calendar
 * instead, which is the calendar the branch's opening hours are written in.
 */
export function dateInputValue(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/**
 * The other half of that round trip.
 *
 * `new Date("2026-09-17")` is parsed as UTC midnight by spec, which is the
 * 16th in the Americas — the same off-by-one day, arriving from the other
 * direction. Building the date from its parts keeps it local.
 *
 * Returns null rather than an Invalid Date: the input is empty while someone
 * is still typing into it, and an Invalid Date propagates silently into the
 * slot maths instead of failing where it happened.
 */
export function dayFromInputValue(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const [, year, month, day] = match;
  const date = new Date(Number(year), Number(month) - 1, Number(day), 0, 0, 0, 0);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** The furthest day the branch will accept, for the date input's `max`. */
export function lastBookableDay(location: RestaurantLocation | undefined, now = new Date()): Date {
  const horizon = Math.max(0, Number(location?.max_future_days ?? DEFAULT_FUTURE_DAYS));
  const last = startOfDay(now);
  last.setDate(last.getDate() + (Number.isFinite(horizon) ? horizon : DEFAULT_FUTURE_DAYS));
  return last;
}

/**
 * Times split into morning, afternoon and evening.
 *
 * A branch open 10:30 to 22:00 on a 30-minute grid offers 24 chips. As one
 * undifferentiated block on a phone that is a wall to scroll past; under three
 * headings it is three short lists, and "evening" is what someone is actually
 * looking for. Empty parts are dropped rather than shown as empty headings.
 */
export function groupByPartOfDay(times: Date[]): { label: string; times: Date[] }[] {
  // Noon is afternoon and 5pm is evening: dinner service is the common case
  // and putting it under "Afternoon" reads as wrong to anyone booking it.
  const parts: { label: string; until: number }[] = [
    { label: "Morning", until: 12 },
    { label: "Afternoon", until: 17 },
    { label: "Evening", until: 24 },
  ];
  return parts
    .map(({ label, until }, i) => ({
      label,
      times: times.filter(
        (t) => t.getHours() < until && t.getHours() >= (parts[i - 1]?.until ?? 0),
      ),
    }))
    .filter((group) => group.times.length > 0);
}

/**
 * The soonest time this branch can actually have food ready.
 *
 * What the picker leads with, so it must be a time the server would accept,
 * not merely the next opening: a window opening at 11:00 cannot take an 11:00
 * order at 10:50 when the kitchen needs twenty minutes. Walks forward day by
 * day because "today" is often already over by the time someone asks.
 */
export function nextBookableTime(
  location: RestaurantLocation | undefined,
  type: Fulfillment,
  now = new Date(),
): Date | null {
  for (const day of bookableDays(location, type, now)) {
    const times = bookableTimes(location, type, dayFromDate(day), day, now);
    if (times[0]) return times[0];
  }
  return null;
}

/**
 * Round a time UP onto the branch's interval grid.
 *
 * Up rather than to-nearest: rounding down can land inside the prep buffer, so
 * the tidier-looking answer is the one the server refuses.
 */
export function snapToInterval(date: Date, step: number): Date {
  const safeStep = Math.max(step, 1);
  const snapped = new Date(date);
  snapped.setSeconds(0, 0);
  const remainder = snapped.getMinutes() % safeStep;
  if (remainder !== 0) snapped.setMinutes(snapped.getMinutes() + (safeStep - remainder));
  return snapped;
}

/**
 * Whether a specific time is one this branch would accept.
 *
 * The free-text time picker lets someone ask for 11:59 pm. Checking the exact
 * instant against the generated set keeps one definition of "bookable" rather
 * than a second copy of the window arithmetic that can drift from it.
 */
export function isBookableTime(
  location: RestaurantLocation | undefined,
  type: Fulfillment,
  when: Date,
  now = new Date(),
): boolean {
  const times = bookableTimes(location, type, dayFromDate(when), when, now);
  return times.some((time) => time.getTime() === when.getTime());
}

/** "21:30" — the 24-hour value an `<input type="time">` min/max expects. */
export function clockValue(date: Date): string {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}
