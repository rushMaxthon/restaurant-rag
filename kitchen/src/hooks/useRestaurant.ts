import { useEffect, useState } from 'react';
import { fetchRestaurant } from '@services/restaurants';
import type { RestaurantInfo } from '@/types/app';

// Names and branches change rarely; one fetch per restaurant per app run, and
// a failure simply leaves the header without a name rather than blocking.
const cache = new Map<string, RestaurantInfo>();

export function useRestaurant(restaurantId: string | null): RestaurantInfo | null {
  const [info, setInfo] = useState<RestaurantInfo | null>(
    restaurantId ? cache.get(restaurantId) ?? null : null,
  );

  useEffect(() => {
    if (!restaurantId) {
      setInfo(null);
      return;
    }
    const cached = cache.get(restaurantId);
    if (cached) {
      setInfo(cached);
      return;
    }
    let cancelled = false;
    fetchRestaurant(restaurantId)
      .then(result => {
        cache.set(restaurantId, result);
        if (!cancelled) {
          setInfo(result);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [restaurantId]);

  return info;
}
