import { useCallback, useState } from 'react';
import { ApiError } from '@services/api';
import { fetchOrder } from '@services/orders';
import type { BoardScope, KitchenOrder } from '@/types/app';
import { usePolling } from '@hooks/usePolling';

export interface OrderState {
  order: KitchenOrder | null;
  loading: boolean;
  // 404: out of this account's scope, or gone. The server does not say which,
  // on purpose, and neither does the screen.
  missing: boolean;
  error: string | null;
}

// One order, kept current while its screen is open. Seeded from the row the
// cook tapped so the screen paints at once. `completed_at` is only filled by
// the LIST endpoint, so a refetch keeps the seed's value rather than erasing
// the completion time it cannot supply.
export function useOrder(
  token: string | null,
  orderId: string,
  scope: BoardScope,
  initial: KitchenOrder | undefined,
  pollIntervalMs: number,
) {
  const [state, setState] = useState<OrderState>({
    order: initial ?? null,
    loading: !initial,
    missing: false,
    error: null,
  });

  const load = useCallback(async () => {
    if (!token) {
      return;
    }
    try {
      const fresh = await fetchOrder(token, orderId, scope);
      setState(current => ({
        order: {
          ...fresh,
          completed_at: fresh.completed_at ?? current.order?.completed_at ?? null,
        },
        loading: false,
        missing: false,
        error: null,
      }));
    } catch (error) {
      setState(current => ({
        ...current,
        loading: false,
        missing: error instanceof ApiError && error.status === 404,
        error: error instanceof Error ? error.message : 'Could not load this order.',
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, orderId, scope.restaurantId]);

  usePolling(load, pollIntervalMs, Boolean(token));

  return { ...state, reload: load };
}
