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

/** The latest step, said to the customer, or null when there is nothing to add. */
export function courierNow(delivery: Pick<OrderDelivery, "state" | "timeline"> | null | undefined): string | null {
  if (!delivery) return null;
  if (delivery.state === "FAILED") {
    return "The rider could not complete the delivery. The restaurant will be in touch.";
  }
  if (delivery.state === "CANCELLED") return null;
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
