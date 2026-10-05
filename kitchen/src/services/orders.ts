import { request, requestPage } from '@services/api';
import type { BoardScope, KitchenOrder, LiveStatus, OrderStatus } from '@/types/app';

// The API's ceiling. Inside the live window a branch is not expected to come
// near it; a column that does reports the overflow rather than hiding it.
const LIVE_PAGE_LIMIT = 200;

const scopeQuery = (scope: BoardScope) => ({
  restaurant_id: scope.restaurantId,
  restaurant_location_id: scope.locationId,
});

// One column of the board. One call per status rather than one filtered on
// the device: DELIVERED history is far larger than the live queue.
export const fetchOrdersByStatus = (
  token: string,
  status: LiveStatus,
  scope: BoardScope,
  dueFrom: string,
) =>
  requestPage<KitchenOrder>('/orders', {
    token,
    query: {
      order_status: status,
      ...scopeQuery(scope),
      // Only this service's work — see LIVE_WINDOW_HOURS.
      due_from: dueFrom,
      limit: LIVE_PAGE_LIMIT,
      // Newest first on the wire so the page limit drops the OLDEST tickets,
      // never the one a customer is waiting on now; put back to oldest-first
      // by inServiceOrder before it reaches the screen.
      sort: 'placed_at:desc',
    },
  });

// Finished orders, most recently completed first. Today's when completedFrom
// is given; all history when it is not (a search).
export const fetchCompletedOrders = (
  token: string,
  {
    scope,
    completedFrom,
    search,
    limit,
    offset,
  }: {
    scope: BoardScope;
    completedFrom?: string;
    search?: string;
    limit: number;
    offset: number;
  },
) =>
  requestPage<KitchenOrder>('/orders', {
    token,
    query: {
      order_status: 'DELIVERED',
      ...scopeQuery(scope),
      completed_from: completedFrom,
      search,
      sort: 'completed_at:desc',
      limit,
      offset,
    },
  });

// Out-of-scope orders come back 404, not 403 — the board learns nothing about
// an order it may not see, including whether it exists. Takes no scope
// parameters: the server resolves it from the signed-in account alone.
export const fetchOrder = (token: string, orderId: string) =>
  request<KitchenOrder>(`/orders/${orderId}`, { token });

// One step along the flow. The server refuses anything but the single legal
// next status. restaurant_id matters only for an ADMIN; an OWNER or KITCHEN
// account is scoped by its own row and a disagreeing value is refused.
export const advanceOrder = (
  token: string,
  orderId: string,
  nextStatus: OrderStatus,
  scope: BoardScope,
) =>
  request<KitchenOrder>(`/orders/${orderId}/status`, {
    method: 'PATCH',
    token,
    body: { status: nextStatus },
    query: { restaurant_id: scope.restaurantId },
  });
