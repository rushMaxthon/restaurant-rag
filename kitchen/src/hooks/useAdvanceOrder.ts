import { useCallback, useState } from 'react';
import { advanceOrder } from '@services/orders';
import { ordersChanged } from '@services/orderEvents';
import type { BoardScope, KitchenOrder } from '@/types/app';
import { nextStatus } from '@utils/board';

// Orders with an advance on the wire, across every screen. A second tap on
// the same ticket would send a second transition, which the server refuses
// with "Invalid status transition" — an error for something nobody did wrong.
const inFlight = new Set<string>();

// Advance one order by one step. Deliberately not optimistic: the server can
// legally refuse (payment not settled, status moved under the cook's finger),
// and a ticket that jumps a column and then jumps back is worse than one that
// takes half a second. The button shows its own pending state; everything
// refetches once the server agrees.
export function useAdvanceOrder(token: string | null, scope: BoardScope) {
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const advance = useCallback(
    async (order: KitchenOrder): Promise<KitchenOrder | null> => {
      const next = nextStatus(order.status);
      if (!token || !next || inFlight.has(order.id)) {
        return null;
      }
      inFlight.add(order.id);
      setPending(current => new Set(current).add(order.id));
      setErrors(({ [order.id]: _cleared, ...rest }) => rest);
      try {
        const updated = await advanceOrder(token, order.id, next, scope);
        ordersChanged();
        return updated;
      } catch (error) {
        // The server's own sentence: it refuses for real reasons, and
        // paraphrasing would lose the one that matters.
        setErrors(current => ({
          ...current,
          [order.id]: error instanceof Error ? error.message : 'That did not go through.',
        }));
        // The order may have moved on another tablet; show where it is now.
        ordersChanged();
        return null;
      } finally {
        inFlight.delete(order.id);
        setPending(current => {
          const rest = new Set(current);
          rest.delete(order.id);
          return rest;
        });
      }
    },
    [token, scope],
  );

  const clearError = useCallback(
    (orderId: string) => setErrors(({ [orderId]: _cleared, ...rest }) => rest),
    [],
  );

  return { advance, pending, errors, clearError };
}
