import type { OpenOrder } from '@/types/api';

export const HOME_PREVIEW = 3;

/**
 * Every waiting order, most worth doing first: an order in its last minute
 * before the courier gets it (it is now or never), then the nearest pickup -
 * the one the rider can reach soonest. An unknown distance goes last rather
 * than pretending to be next door. Home and the Orders tab share this, so the
 * first card on one is the first card on the other.
 */
export function rankOrders(orders: readonly OpenOrder[]): OpenOrder[] {
  return [...orders].sort((a, b) => {
    const urgent = Number(b.minutes_left <= 1) - Number(a.minutes_left <= 1);
    if (urgent !== 0) return urgent;
    return (
      (a.pickup_distance_m ?? Infinity) - (b.pickup_distance_m ?? Infinity)
    );
  });
}

/**
 * The few waiting orders Home shows, so a rider can take one without
 * opening the Orders tab. The full board stays on the Orders tab.
 */
export function homePreview(
  orders: readonly OpenOrder[],
  limit: number = HOME_PREVIEW,
): { shown: OpenOrder[]; more: number } {
  const ranked = rankOrders(orders);
  return {
    shown: ranked.slice(0, limit),
    more: Math.max(0, ranked.length - limit),
  };
}
