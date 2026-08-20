import type { OrderFulfillmentType, RestaurantLocation } from '../types/app';

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
    return fulfillmentType === 'DELIVERY' ? '25-35 min' : '20 min';
  }
  return fulfillmentType === 'DELIVERY'
    ? `${location.estimated_delivery_time} min`
    : `${location.estimated_pickup_time} min`;
}
