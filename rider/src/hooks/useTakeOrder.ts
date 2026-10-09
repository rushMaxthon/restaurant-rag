import { useCallback, useEffect, useState } from 'react';

import { useNav } from '@navigation/types';
import { ApiError } from '@/services/http';
import { useRider } from '@/store/RiderProvider';
import { useApi } from '@/store/SessionProvider';
import type { OpenOrder } from '@/types/api';
import { haptic } from '@utils/haptics';
import { claimErrorMessage, takeBlockedReason } from '@utils/openOrders';

/**
 * Taking an order from the board, for Home and the Orders tab alike: one
 * request, one error wording, one place that knows a claim starts a trip.
 * The server decides (online, free, nobody faster); `blocked` only says in
 * advance what it would answer.
 */
export function useTakeOrder() {
  const api = useApi();
  const nav = useNav();
  const { me, trip, setTrip, refreshMe, refreshOpenOrders } = useRider();
  const [taking, setTaking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const blocked = takeBlockedReason(me?.status, trip !== null);
  // The Orders tab stays mounted: an error left up would still be there a
  // whole delivery later, about an order long gone.
  useEffect(() => {
    if (!error) return;
    const t = setTimeout(() => setError(null), 6000);
    return () => clearTimeout(t);
  }, [error]);

  const take = useCallback(
    async (order: OpenOrder) => {
      setTaking(order.order_id);
      setError(null);
      try {
        const started = await api.claim(order.order_id);
        haptic('success');
        setTrip(started);
        void refreshMe();
        void refreshOpenOrders();
        nav.navigate('Trip');
      } catch (e) {
        haptic('error');
        setError(
          claimErrorMessage(
            e instanceof ApiError && typeof e.detail === 'string'
              ? e.detail
              : undefined,
          ),
        );
        void refreshOpenOrders();
      } finally {
        setTaking(null);
      }
    },
    [api, nav, setTrip, refreshMe, refreshOpenOrders],
  );

  /** Why this card's Take is off: another order is being taken, or the rider can't. */
  const blockedFor = (order: OpenOrder) =>
    taking !== null && taking !== order.order_id
      ? 'Taking another order'
      : blocked;

  return { take, taking, error, blockedFor };
}
