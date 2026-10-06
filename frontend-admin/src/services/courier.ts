/**
 * The courier's words, made readable, for the admin's delivery card and the
 * live board. Pure, so it is tested without rendering a card.
 */
import type { OrderDelivery } from "../types/app";

/** Pidge's statuses, as somebody watching an order would say them. */
const STEP_LABEL: Record<string, string> = {
  CREATED: "Booked with the courier",
  PENDING: "Waiting for a rider",
  OUT_FOR_PICKUP: "Rider on the way to the restaurant",
  REACHED_PICKUP: "Rider at the restaurant",
  PICKED_UP: "Rider picked up the food",
  IN_TRANSIT: "On the way",
  OUT_FOR_DELIVERY: "On the way to the customer",
  REACHED_DELIVERY: "Rider at the customer's door",
  DELIVERED: "Delivered",
  UNDELIVERED: "Could not be delivered",
  RTO_OUT_FOR_DELIVERY: "Bringing the food back",
  RTO_UNDELIVERED: "Could not bring the food back",
  RTO_DELIVERED: "Food returned to the restaurant",
  CANCELLED: "Rider called off",
  DISPOSED: "Food disposed of",
  LOST: "Food lost",
  DAMAGED: "Food damaged",
};

export function stepLabel(status: string): string {
  const key = status.trim().toUpperCase();
  if (STEP_LABEL[key]) return STEP_LABEL[key];
  // A status nobody has seen: still shown, in its own words, rather than
  // dropped - "REACHED_GATE" read plainly is better than nothing.
  const words = key.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Steps that went wrong, drawn in the warning tone. */
const BAD = new Set(["UNDELIVERED", "RTO_OUT_FOR_DELIVERY", "RTO_UNDELIVERED", "RTO_DELIVERED", "CANCELLED", "DISPOSED", "LOST", "DAMAGED"]);

export function isBadStep(status: string): boolean {
  return BAD.has(status.trim().toUpperCase());
}

/**
 * The one ETA worth showing now: the door while the food is on its way, the
 * restaurant while a rider is coming for it, nothing once it is over.
 */
export function nextEta(delivery: Pick<OrderDelivery, "state" | "pickup_eta" | "drop_eta">): {
  label: string;
  at: string;
} | null {
  if (delivery.state === "PICKED_UP" || delivery.state === "IN_TRANSIT") {
    // The network sends its delivery deadline here, not an arrival estimate
    // (wefast: about 70 minutes after booking for a 4 km trip).
    return delivery.drop_eta ? { label: "Rider must deliver by", at: delivery.drop_eta } : null;
  }
  if (delivery.state === "ASSIGNED" || delivery.state === "PENDING") {
    return delivery.pickup_eta ? { label: "Rider expected at the restaurant", at: delivery.pickup_eta } : null;
  }
  return null;
}

/** A map link to where the rider was last reported, or null. */
export function riderMapUrl(delivery: Pick<OrderDelivery, "rider_latitude" | "rider_longitude">): string | null {
  const { rider_latitude: lat, rider_longitude: lng } = delivery;
  if (lat == null || lng == null) return null;
  return `https://www.google.com/maps?q=${lat},${lng}`;
}

/**
 * Whether the rider can still be called off. The server decides - it knows
 * the order's own status, and a delivered order whose courier row never moved
 * past PENDING must not offer it - so this only reads `can_cancel`.
 */
export function canCancelRider(delivery: Pick<OrderDelivery, "can_cancel">): boolean {
  return delivery.can_cancel === true;
}

/** The sandbox stages, in trip order, for the admin's simulate buttons. */
export const SIMULATE_STAGES: Array<{ status: string; label: string }> = [
  { status: "fulfilled|out for pickup", label: "Rider assigned" },
  { status: "fulfilled|reached pickup", label: "At restaurant" },
  { status: "fulfilled|picked up", label: "Picked up" },
  { status: "fulfilled|ofd", label: "On the way" },
  { status: "fulfilled|reached delivery", label: "At the door" },
  { status: "fulfilled|delivered", label: "Delivered" },
  { status: "fulfilled|undelivered", label: "Undelivered" },
];
