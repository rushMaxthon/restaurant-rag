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
  horizon.setDate(horizon.getDate() + Math.max(0, Number(location.max_future_days ?? DEFAULT_FUTURE_DAYS)));

  const times: Date[] = [];
  for (const slot of activeSlots(location, type).filter((s) => s.day_of_week === day)) {
    const start = minutesInto(slot.start_time);
    const end = minutesInto(slot.end_time);
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
