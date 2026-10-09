/**
 * What the courier's latest news means to the person waiting for the food.
 *
 * Pidge reports a dozen small steps ("Rider at the restaurant", "Rider at
 * your door"). The order's own status moves on only four of them, so without
 * these a customer saw "Being prepared" while a rider stood at the counter.
 */
import type { OrderDelivery } from "@/lib/api";

const NOW: Record<string, string> = {
  CREATED: "Your order is booked with a rider service",
  OUT_FOR_PICKUP: "Your rider is on the way to the restaurant",
  REACHED_PICKUP: "Your rider is at the restaurant",
  PICKED_UP: "Your rider has your food",
  OUT_FOR_DELIVERY: "Your food is on the way",
  IN_TRANSIT: "Your food is on the way",
  REACHED_DELIVERY: "Your rider is at your door",
  DELIVERED: "Delivered",
};

/** Whether the platform's own riders carry this delivery, rather than a courier. */
export function isOwnFleet(delivery: Pick<OrderDelivery, "provider"> | null | undefined): boolean {
  return delivery?.provider === "own_fleet";
}

/**
 * Our own riders, said from the delivery STATE: their timeline records the
 * offer and the restaurant, while picking up and reaching the door move the
 * state (IN_TRANSIT is our rider at the customer's door).
 */
function fleetNow(delivery: Pick<OrderDelivery, "state" | "timeline">): string | null {
  const last = delivery.timeline?.[delivery.timeline.length - 1]?.status.toUpperCase();
  switch (delivery.state) {
    case "PENDING":
      return "Finding you a rider nearby";
    case "ASSIGNED":
      return last === "ARRIVED_PICKUP"
        ? "Your rider is at the restaurant"
        : "Your rider is on the way to the restaurant";
    case "PICKED_UP":
      return "Your rider has your food and is on the way";
    case "IN_TRANSIT":
      return "Your rider is at your door";
    default:
      return null;
  }
}

/** The latest step, said to the customer, or null when there is nothing to add. */
export function courierNow(
  delivery:
    | (Pick<OrderDelivery, "state" | "timeline"> & Partial<Pick<OrderDelivery, "provider">>)
    | null
    | undefined,
): string | null {
  if (!delivery) return null;
  if (delivery.state === "FAILED") {
    return "The rider could not complete the delivery. The restaurant will be in touch.";
  }
  if (delivery.state === "CANCELLED") return null;
  if (isOwnFleet(delivery)) return fleetNow(delivery);
  const last = delivery.timeline?.[delivery.timeline.length - 1];
  return last ? (NOW[last.status.toUpperCase()] ?? null) : null;
}

/**
 * When to expect something, as a time on the clock: the rider at the door
 * once they have the food, at the restaurant before that.
 */
export function courierEta(
  delivery: Pick<OrderDelivery, "state" | "pickup_eta" | "drop_eta"> | null | undefined,
  format: (value: Date) => string = (value) =>
    value.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }),
): string | null {
  if (!delivery) return null;
  if ((delivery.state === "PICKED_UP" || delivery.state === "IN_TRANSIT") && delivery.drop_eta) {
    return `Arriving by ${format(new Date(delivery.drop_eta))}`;
  }
  if ((delivery.state === "ASSIGNED" || delivery.state === "PENDING") && delivery.pickup_eta) {
    return `Rider reaches the restaurant by ${format(new Date(delivery.pickup_eta))}`;
  }
  return null;
}

/**
 * The 4-digit code the customer reads to our rider at the door, or null.
 * The server only sends it to this order's customer while a rider is on the
 * way; the checks here keep a stale cached copy off the screen.
 */
export function deliveryCode(
  delivery:
    | (Pick<OrderDelivery, "state"> & Partial<Pick<OrderDelivery, "provider" | "delivery_otp">>)
    | null
    | undefined,
): string | null {
  if (!delivery || !isOwnFleet(delivery) || !delivery.delivery_otp) return null;
  return ["ASSIGNED", "PICKED_UP", "IN_TRANSIT"].includes(delivery.state)
    ? delivery.delivery_otp
    : null;
}

/** Google Maps at the rider's last reported position, or null without one. */
export function riderMapLink(delivery: Partial<OrderDelivery> | null | undefined): string | null {
  const lat = delivery?.rider_latitude;
  const lng = delivery?.rider_longitude;
  if (lat == null || lng == null) return null;
  return `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;
}

/** "updated 3 min ago", so a frozen position is not mistaken for a parked rider. */
export function riderSeen(iso: string | null | undefined, now: Date = new Date()): string | null {
  if (!iso) return null;
  const minutes = Math.floor((now.getTime() - new Date(iso).getTime()) / 60_000);
  return minutes < 1 ? "updated just now" : `updated ${minutes} min ago`;
}

/** "1.2 km away · about 5 min" from the server's estimate, or null without one. */
export function riderAway(delivery: Partial<OrderDelivery> | null | undefined): string | null {
  const metres = delivery?.rider_distance_m;
  const minutes = delivery?.rider_eta_minutes;
  if (metres == null || minutes == null) return null;
  if (metres < 100) return "Arriving now";
  const distance =
    metres < 1000 ? `${Math.round(metres / 50) * 50} m` : `${(metres / 1000).toFixed(1)} km`;
  return `${distance} away · about ${minutes} min`;
}
