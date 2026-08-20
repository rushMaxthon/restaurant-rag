import type {
  FulfillmentSelection,
  LocationScheduleOptionsResponse,
  OrderFulfillmentType,
  RestaurantLocation,
} from '@/types/app';

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

export function formatScheduledAtLabel(value: string | null | undefined): string {
  if (!value) {
    return 'Schedule later';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return 'Schedule later';
  }

  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfTarget = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  );
  const diffDays = Math.round(
    (startOfTarget.getTime() - startOfToday.getTime()) / 86400000,
  );

  const timeLabel = new Intl.DateTimeFormat('en-IN', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(date);

  if (diffDays === 0) {
    return `Today ${timeLabel}`;
  }
  if (diffDays === 1) {
    return `Tomorrow ${timeLabel}`;
  }

  const dayLabel = new Intl.DateTimeFormat('en-IN', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  }).format(date);
  return `${dayLabel} ${timeLabel}`;
}

export function formatFulfillmentSelectionLabel(
  location: RestaurantLocation | null | undefined,
  selection: FulfillmentSelection | null | undefined,
): string {
  const fulfillmentType = selection?.fulfillmentType ?? 'DELIVERY';
  const timingLabel =
    selection?.scheduleType === 'SCHEDULED'
      ? formatScheduledAtLabel(selection.scheduledAt)
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
