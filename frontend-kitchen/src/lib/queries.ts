/**
 * The data layer: REST queries, refreshed by push and by poll.
 *
 * `GET /orders` takes `order_status` and `restaurant_location_id` and returns
 * a small live queue, cheap enough to ask for every few seconds and honest
 * about being a snapshot. That poll used to be the only way the board moved.
 * It is now the safety net: a Socket.IO push (`lib/realtime.ts`) invalidates
 * these queries the moment an order changes, and the poll slows to 30s while
 * the socket is live — returning to 6s the moment it is not. The data itself
 * only ever comes from here.
 */

import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { api, type KitchenOrder, type OrderStatus } from './api'
import { BOARD_COLUMNS, hiddenCount, inServiceOrder, liveWindowStart } from './board'
import { HISTORY_PAGE_SIZE, localDayKey, startOfToday } from './history'
import { POLL_INTERVAL_MS } from './realtime'

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
export function useBoard(scope: BoardScope, enabled: boolean, pollIntervalMs = POLL_INTERVAL_MS) {
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
      refetchInterval: pollIntervalMs,
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

/**
 * One page of finished orders, for the history view.
 *
 * Keyed under `['orders', ...]` on purpose: the board's advance mutation and
 * the socket both invalidate that prefix, so an order a cook marks Delivered
 * appears in an open history straight away.
 *
 * It also polls at the board's own rate. That was left out at first on the
 * reasoning above, and a browser pass showed the hole: with realtime off —
 * the default — an order completed on ANOTHER tablet reaches this one only
 * by poll, and an open history had none, so it stayed stale until reopened.
 *
 * With a search it looks through ALL history, not just today's: the question
 * behind a search is usually "this customer's receipt from yesterday", and a
 * search that could only find today's orders would say "no such order" about
 * one that exists. Without one it is today's, from local midnight.
 */
export function useOrderHistory(
  scope: BoardScope,
  {
    search,
    page,
    enabled,
    pollIntervalMs = POLL_INTERVAL_MS,
  }: { search: string | null; page: number; enabled: boolean; pollIntervalMs?: number },
) {
  const day = localDayKey()
  return useQuery({
    queryKey: [
      'orders',
      'history',
      scope.restaurantId ?? 'any',
      scope.locationId ?? 'any',
      search ?? '',
      search ? 'all' : day,
      page,
    ],
    queryFn: () =>
      api.completedOrders({
        scope,
        completedFrom: search ? undefined : startOfToday(),
        search: search ?? undefined,
        limit: HISTORY_PAGE_SIZE,
        offset: page * HISTORY_PAGE_SIZE,
      }),
    enabled,
    refetchInterval: pollIntervalMs,
    // Same reason as the board: a wall tablet is never the focused window.
    refetchIntervalInBackground: true,
    // The previous page stays on screen while the next loads, rather than the
    // list collapsing to a spinner on every arrow press.
    placeholderData: keepPreviousData,
    staleTime: 0,
    retry: 1,
  })
}
