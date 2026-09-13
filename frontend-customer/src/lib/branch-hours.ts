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
 * Bookable start times inside a slot, as real Date objects.
 *
 * Stepped by the branch's own `slot_interval_minutes`, and never earlier than
 * its preparation time from now — offering a pickup in five minutes that the
 * kitchen cannot make is worse than offering nothing.
 */
export function bookableTimes(
  location: RestaurantLocation | undefined,
  type: Fulfillment,
  day: LocationDayOfWeek,
  dayDate: Date,
  now = new Date(),
): Date[] {
  if (!location) return [];
  const step = Math.max(location.slot_interval_minutes ?? 30, 5);
  const leadMinutes = location.preparation_time_minutes ?? 0;
  const earliest = new Date(now.getTime() + leadMinutes * 60_000);

  const times: Date[] = [];
  for (const slot of activeSlots(location, type).filter((s) => s.day_of_week === day)) {
    const start = minutesInto(slot.start_time);
    const end = minutesInto(slot.end_time);
    for (let minute = start; minute <= end; minute += step) {
      const at = new Date(dayDate);
      at.setHours(Math.floor(minute / 60), minute % 60, 0, 0);
      if (at >= earliest) times.push(at);
    }
  }
  return times.sort((a, b) => a.getTime() - b.getTime());
}

export function formatTimeOfDay(date: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(date);
}
