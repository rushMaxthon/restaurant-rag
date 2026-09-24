/**
 * The polling layer.
 *
 * There is no WebSocket or SSE anywhere in this backend, so "live" is a poll.
 * That is a deliberate constraint rather than a shortcut: `GET /orders` takes
 * `order_status` and `restaurant_location_id` and returns a small live queue,
 * which is cheap enough to ask for every few seconds and honest about being a
 * snapshot.
 */

import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query'

import { api, type KitchenOrder, type OrderStatus } from './api'
import { BOARD_COLUMNS, hiddenCount, inServiceOrder, liveWindowStart } from './board'

/** Fast enough that a cook does not notice, slow enough to be unremarkable. */
export const POLL_INTERVAL_MS = 6000

export type BoardScope = { restaurantId: string | null; locationId: string | null }

export function boardQueryKey(status: OrderStatus, scope: BoardScope) {
  return ['orders', status, scope.restaurantId ?? 'any', scope.locationId ?? 'any'] as const
}

/**
 * One query per column, run together.
 *
 * Separate queries rather than one combined fetch so a column that fails —
 * or is slow — does not blank the other three. A kitchen with a working
 * "Cooking" column and a broken "New" one is still a kitchen that can work.
 */
export function useBoard(scope: BoardScope, enabled: boolean) {
  return useQueries({
    queries: BOARD_COLUMNS.map((column) => ({
      queryKey: boardQueryKey(column.status, scope),
      // The window is computed per fetch, not per render, so it advances with
      // the poll instead of being pinned to whenever the board was opened —
      // a screen left up for a week would otherwise still be asking about the
      // day it was switched on. It is deliberately NOT in the query key: a key
      // that changed every tick would make each poll a different query, and
      // react-query would show a loading state instead of the last good board.
      queryFn: async () => {
        const page = await api.ordersByStatus(column.status, scope, liveWindowStart())
        return {
          orders: inServiceOrder(page.rows),
          hidden: hiddenCount(page.total, page.rows.length),
        }
      },
      enabled,
      refetchInterval: POLL_INTERVAL_MS,
      // A board left open on a wall must keep polling; the default pauses
      // when the window is not focused, which is its permanent state here.
      refetchIntervalInBackground: true,
      // Nothing on a kitchen board is worth showing stale — the whole value is
      // that it reflects the pass right now.
      staleTime: 0,
      retry: 1,
    })),
  })
}

/**
 * Advance one order by one step.
 *
 * Deliberately NOT optimistic in the usual sense. An advance can be legally
 * refused by the server — a payment that has not settled, a status that moved
 * under the cook's finger, an order at a branch they are not pinned to — and a
 * ticket that visibly jumps a column and then jumps back is worse than one
 * that takes half a second. Instead the button shows its own pending state and
 * the board is invalidated once the server has agreed.
 */
export function useAdvanceOrder(scope: BoardScope) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      orderId,
      nextStatus,
    }: {
      orderId: string
      nextStatus: OrderStatus
      /** Carried for the caller's own error copy; unused by the request. */
      order?: KitchenOrder
    }) => api.advance(orderId, nextStatus, scope.restaurantId),
    // Two taps on one ticket would otherwise send two transitions, and the
    // second is refused with "Invalid status transition" — an error message
    // for something the cook did not do wrong.
    scope: { id: 'advance-order' },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['orders'] })
    },
  })
}
