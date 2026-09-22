/**
 * Whose marketing this is, for any screen that reads tenant-scoped data.
 *
 * Every `/marketing/*` route hands `restaurant_id` to `resolve_insights_scope`,
 * which **requires** one from an ADMIN and **refuses** one from an OWNER. So an
 * admin screen with no restaurant chosen does not degrade — every call comes
 * back `400 restaurant_id is required for admin insights requests`, and the
 * screen renders that as "this feature is broken".
 *
 * `MarketingPage` learned that the hard way and grew a picker. `ChannelsPage`
 * was then written without one and reintroduced the same bug for anyone
 * arriving by deep link or refresh, because the remembered scope lives in
 * localStorage and is only populated by having visited the Hub first in that
 * browser. Extracting it here is what stops the next page repeating it a
 * third time.
 *
 * The one rule a caller must honour: **do not fetch until `ready`.** Fetching
 * anyway is exactly what turns "pick a restaurant" into "it didn't load".
 */

import { useEffect, useState } from 'react';
import { useAdminStore } from './useAdminStore';
import { api } from '../services/api';
import { getPageSnapshot, setPageSnapshot, tokenScope } from '../services/pageCache';
import { buildAdminRestaurantsCacheKeyPrefix } from '../pages/AdminRestaurantsPage';
import { getRestaurantScope, setRestaurantScope } from '../services/marketing/marketingApi';
import type { Restaurant } from '../types/app';

export interface MarketingScope {
  isAdmin: boolean;
  /** False only for an admin who has not chosen yet. Gate every fetch on it. */
  ready: boolean;
  restaurants: Restaurant[];
  selectedRestaurantId: string;
  setSelectedRestaurantId: (id: string) => void;
}

export function useMarketingScope(): MarketingScope {
  const { token: sessionToken, role } = useAdminStore();
  const token = sessionToken ?? '';
  const isAdmin = role === 'ADMIN';
  const restaurantsKey = buildAdminRestaurantsCacheKeyPrefix(tokenScope(token));

  // Seeded during render, not in an effect: arriving from the admin
  // restaurants list means the answer is already cached, and reading it here
  // renders with a restaurant instead of flashing the picker prompt.
  const [restaurants, setRestaurants] = useState<Restaurant[]>(() =>
    isAdmin ? (getPageSnapshot<Restaurant[]>(restaurantsKey) ?? []) : [],
  );
  const [selectedRestaurantId, setSelectedRestaurantId] = useState<string>(() => {
    if (!isAdmin) {
      return '';
    }
    const remembered = getRestaurantScope() ?? '';
    const cached = getPageSnapshot<Restaurant[]>(restaurantsKey) ?? [];
    // A remembered restaurant the admin can no longer see must not stick.
    if (remembered && (cached.length === 0 || cached.some((row) => row.id === remembered))) {
      return remembered;
    }
    return cached[0]?.id ?? '';
  });

  // The scope is written before any fetch reads it. An owner writes null and
  // is pinned server-side to their own restaurant — sending one would be
  // refused, which is the other half of the same rule.
  useEffect(() => {
    setRestaurantScope(isAdmin ? selectedRestaurantId || null : null);
  }, [isAdmin, selectedRestaurantId]);

  // Only fetched when the cache the state above already read has nothing.
  useEffect(() => {
    if (!isAdmin || !token || getPageSnapshot<Restaurant[]>(restaurantsKey)) {
      return;
    }
    let live = true;
    api
      .getAdminRestaurants(token)
      .then((rows) => {
        if (!live) {
          return;
        }
        setPageSnapshot(restaurantsKey, rows);
        setRestaurants(rows);
        setSelectedRestaurantId((current) =>
          (rows.some((row) => row.id === current) ? current : '') || rows[0]?.id || '',
        );
      })
      .catch(() => {
        // Non-fatal: the picker is empty and the prompt says so, rather than
        // the screen failing outright.
        if (live) {
          setRestaurants([]);
        }
      });
    return () => {
      live = false;
    };
  }, [isAdmin, restaurantsKey, token]);

  return {
    isAdmin,
    ready: !isAdmin || Boolean(selectedRestaurantId),
    restaurants,
    selectedRestaurantId,
    setSelectedRestaurantId,
  };
}
