import type {
  FulfillmentSelection,
  LocationScheduleOptionsResponse,
  OrderFulfillmentType,
  RestaurantLocation,
} from '@/types/app';
import {formatInZone, zonedDayDifference} from '@utils/timezone';

/**
 * Every label below takes an optional trailing `timeZone`: the restaurant's own
 * clock, from `/app-config`. It is optional and last on purpose - omitted, each
 * function reads the device clock exactly as it did before, so a screen that has
 * not been given the zone yet (or an older backend that does not send one) keeps
 * working rather than rendering a wrong time confidently.
 */

export function isFulfillmentEnabled(
  location: RestaurantLocation | null | undefined,
  fulfillmentType: OrderFulfillmentType,
): boolean {
  if (!location) {
    return fulfillmentType === 'DELIVERY';
  }
  return fulfillmentType === 'DELIVERY'
    ? location.delivery_enabled
    : location.pickup_enabled;
}

export function isFulfillmentAvailableNow(
  location: RestaurantLocation | null | undefined,
  fulfillmentType: OrderFulfillmentType,
): boolean {
  if (!location) {
    return fulfillmentType === 'DELIVERY';
  }
  return fulfillmentType === 'DELIVERY'
    ? location.delivery_available_now
    : location.pickup_available_now;
}

export function getFulfillmentUnavailableReason(
  location: RestaurantLocation | null | undefined,
  fulfillmentType: OrderFulfillmentType,
): string | null {
  if (!location) {
    return null;
  }
  return fulfillmentType === 'DELIVERY'
    ? location.delivery_unavailable_reason
    : location.pickup_unavailable_reason;
}

export function getFulfillmentEtaLabel(
  location: RestaurantLocation | null | undefined,
  fulfillmentType: OrderFulfillmentType,
): string {
  if (!location) {
    return fulfillmentType === 'DELIVERY' ? '25-35 mins' : '20 mins';
  }
  return fulfillmentType === 'DELIVERY'
    ? `${location.estimated_delivery_time} mins`
    : `${location.estimated_pickup_time} mins`;
}

/**
 * The ETA as a number of minutes, or null when there isn't one.
 *
 * The label above can be a range ("25-35 mins") when no branch has loaded, and
 * a range has no single arrival time - so this returns null rather than picking
 * an end of it and presenting a guess as a fact.
 */
export function getFulfillmentEtaMinutes(
  location: RestaurantLocation | null | undefined,
  fulfillmentType: OrderFulfillmentType,
): number | null {
  if (!location) {
    return null;
  }
  const minutes =
    fulfillmentType === 'DELIVERY'
      ? location.estimated_delivery_time
      : location.estimated_pickup_time;
  const numeric = Number(minutes);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
}

/**
 * The clock time an ETA lands on, read on the restaurant's clock.
 *
 * "Arrives in about 29 min" asks someone to do arithmetic at the exact moment
 * they are deciding whether to order. This is the other half: "by 2:57 p.m.".
 *
 * The branch's clock, not the phone's, for the same reason everything else here
 * is: a customer ordering from a branch in another zone should be told the time
 * the kitchen is working to.
 */
export function etaClockTime(
  minutes: number | null,
  now: Date = new Date(),
  timeZone?: string,
): string | null {
  if (minutes === null || !Number.isFinite(minutes)) {
    return null;
  }
  const arrival = new Date(now.getTime() + minutes * 60000);
  return formatInZone(arrival, timeZone, {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

/**
 * A slot the customer already picked, said back to them.
 *
 * The instant comes from the server, which chose it on the restaurant's clock
 * and labelled it that way in the picker. Re-reading it on the phone's clock is
 * how the picker and the cart came to disagree: choose "Tomorrow 7:00 PM" at a
 * branch in Kolkata from a phone in Toronto and the cart said "Today 9:30 a.m."
 * - the same instant, described in a way the customer never chose and the
 * kitchen would not recognise.
 *
 * Both halves have to move together. Formatting the time in the branch's zone
 * while still bucketing "Today"/"Tomorrow" on the device's calendar produces a
 * worse answer than either alone, because the day and the time would then be
 * read off two different clocks.
 */
export function formatScheduledAtLabel(
  value: string | null | undefined,
  timeZone?: string,
): string {
  if (!value) {
    return 'Schedule later';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return 'Schedule later';
  }

  const diffDays = zonedDayDifference(date, new Date(), timeZone);

  const timeLabel = formatInZone(date, timeZone, {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });

  if (diffDays === 0) {
    return `Today ${timeLabel}`;
  }
  if (diffDays === 1) {
    return `Tomorrow ${timeLabel}`;
  }

  const dayLabel = formatInZone(date, timeZone, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
  return `${dayLabel} ${timeLabel}`;
}

export function formatFulfillmentSelectionLabel(
  location: RestaurantLocation | null | undefined,
  selection: FulfillmentSelection | null | undefined,
  timeZone?: string,
): string {
  const fulfillmentType = selection?.fulfillmentType ?? 'DELIVERY';
  const timingLabel =
    selection?.scheduleType === 'SCHEDULED'
      ? formatScheduledAtLabel(selection.scheduledAt, timeZone)
      : `ASAP • ${getFulfillmentEtaLabel(location, fulfillmentType)}`;
  return `${fulfillmentType === 'DELIVERY' ? 'Delivery' : 'Pickup'} • ${timingLabel}`;
}

export function isScheduledSlotPresent(
  response: LocationScheduleOptionsResponse | null | undefined,
  scheduledAt: string | null | undefined,
): boolean {
  if (!response || !scheduledAt) {
    return false;
  }
  return response.groups.some(group =>
    group.slots.some(slot => slot.scheduled_at === scheduledAt),
  );
}

export function getScheduledSlotInvalidMessage(
  response: LocationScheduleOptionsResponse | null | undefined,
): string {
  return (
    response?.scheduled_unavailable_reason ??
    'Your selected slot is no longer available. Please choose another time.'
  );
}
