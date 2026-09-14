import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type OrderCreateRequest } from "@/lib/api";
import type { RestaurantLocation } from "@/lib/bangkok-data";

export const queryKeys = {
  appConfig: ["app-config"] as const,
  restaurant: (id: string) => ["restaurant", id] as const,
  menuItems: (restaurantId: string, locationId?: string | null) =>
    ["menu-items", restaurantId, locationId ?? "all"] as const,
  menuItem: (id: string) => ["menu-item", id] as const,
  orders: ["orders"] as const,
  profile: ["profile"] as const,
  order: (id: string) => ["order", id] as const,
  combos: ["generated-combos"] as const,
  offers: ["personalized-offers"] as const,
};

export function useAppConfig() {
  return useQuery({
    queryKey: queryKeys.appConfig,
    queryFn: api.getAppConfig,
    staleTime: Infinity,
  });
}

/**
 * The signed-in customer's own details, for filling in what we already know.
 *
 * Guarded on `enabled` rather than on a thrown 401: an anonymous checkout is a
 * normal thing, not an error to report. Kept fresh for a few minutes because
 * nothing else in a checkout changes it.
 */
export function useProfile(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.profile,
    queryFn: api.getProfile,
    enabled,
    staleTime: 5 * 60 * 1000,
    // A customer who has no profile row, or an account the endpoint refuses
    // (it is customers-only), must not turn into a retry storm behind a
    // checkout form that works perfectly well empty.
    retry: false,
  });
}

export function useRestaurant(restaurantId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.restaurant(restaurantId ?? ""),
    queryFn: () => api.getRestaurant(restaurantId as string),
    enabled: Boolean(restaurantId),
    staleTime: 5 * 60 * 1000,
  });
}

export function useMenuItems(
  restaurantId: string | undefined,
  locationId: string | undefined | null,
) {
  return useQuery({
    queryKey: queryKeys.menuItems(restaurantId ?? "", locationId),
    queryFn: () => api.getMenuItems(restaurantId as string, locationId),
    enabled: Boolean(restaurantId && locationId),
    staleTime: 60 * 1000,
  });
}

export function useMenuItem(menuItemId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.menuItem(menuItemId ?? ""),
    queryFn: () => api.getMenuItem(menuItemId as string),
    enabled: Boolean(menuItemId),
  });
}

export function usePaymentConfig(enabled = true) {
  return useQuery({
    queryKey: ["payment-config"],
    queryFn: api.getPaymentConfig,
    // Needs a token, so it must not run before sign-in — an early 401 would be
    // cached as "card unavailable" for the whole session.
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}

export function useOrders(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.orders, queryFn: api.getOrders, enabled });
}

export function useOrder(orderId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.order(orderId ?? ""),
    queryFn: () => api.getOrder(orderId as string),
    enabled: Boolean(orderId) && enabled,
  });
}

/**
 * Reconcile a card order with Stripe while it is still unpaid.
 *
 * `GET /orders/{id}` reports what the database holds; only
 * `GET /orders/{id}/payment-status` asks Stripe and promotes the order. The
 * webhook normally does that, but it can be late, and locally it never
 * arrives at all — so without this the customer who just paid sits on "Card
 * payment confirming..." until they think to refresh.
 *
 * Polls only while the order is unpaid, and stops as soon as it is not.
 */
export function usePaymentReconciliation(orderId: string | undefined, unpaid: boolean) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["payment-status", orderId ?? ""],
    queryFn: async () => {
      const status = await api.getPaymentStatus(orderId as string);
      if (status.order_status !== "PAYMENT_PENDING") {
        // The order row has just changed server-side; pull the real thing.
        await queryClient.invalidateQueries({ queryKey: queryKeys.order(orderId ?? "") });
        await queryClient.invalidateQueries({ queryKey: queryKeys.orders });
      }
      return status;
    },
    enabled: Boolean(orderId) && unpaid,
    refetchInterval: (query) =>
      query.state.data && query.state.data.order_status !== "PAYMENT_PENDING" ? false : 2500,
    refetchOnWindowFocus: true,
    // Nothing here is worth showing stale: the whole point is the newest answer.
    staleTime: 0,
  });
}

export function useValidateOrder() {
  return useMutation({ mutationFn: (payload: OrderCreateRequest) => api.validateOrder(payload) });
}

export function useCreateOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: OrderCreateRequest) => api.createOrder(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.orders });
    },
  });
}

export function useSendChatMessage() {
  return useMutation({ mutationFn: api.sendChatMessage });
}

export function usePersonalizedOffers(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.offers,
    queryFn: api.getPersonalizedOffers,
    enabled,
    staleTime: 60 * 1000,
  });
}

/** Prefers an open branch, falling back to the first one returned. */
export function pickDefaultLocation(
  locations: RestaurantLocation[] | undefined,
): RestaurantLocation | undefined {
  if (!locations?.length) return undefined;
  return locations.find((l) => l.is_open && l.is_active) ?? locations[0];
}
