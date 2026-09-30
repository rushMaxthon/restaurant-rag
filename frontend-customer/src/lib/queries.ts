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
  favoriteIds: ["favorite-ids"] as const,
  favorites: ["favorites"] as const,
  order: (id: string) => ["order", id] as const,
  combos: ["generated-combos"] as const,
  offers: ["personalized-offers"] as const,
  orderDelivery: (orderId: string) => ["order-delivery", orderId] as const,
  deliveryQuote: (locationId: string, address: string) =>
    ["delivery-quote", locationId, address] as const,
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

/** Which dishes are favourites, as a set the menu can test against. */
export function useFavoriteIds(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.favoriteIds,
    queryFn: async () => new Set(await api.getFavoriteIds()),
    enabled,
    staleTime: 60 * 1000,
    retry: false,
  });
}

export function useFavorites(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.favorites,
    queryFn: api.getFavorites,
    enabled,
    staleTime: 60 * 1000,
    retry: false,
  });
}

/**
 * Turn a favourite on or off.
 *
 * Optimistic, because a heart that waits for a round trip before filling in
 * feels broken - the tap is the whole interaction. The previous set is kept so
 * a failed request puts it back rather than leaving the screen lying.
 */
export function useToggleFavorite() {
  const client = useQueryClient();
  return useMutation({
    // Serialised. Two quick taps on one heart fire an add and a remove at the
    // same time, and if they land out of order the server keeps the opposite
    // of what the screen shows — saved when you meant to unsave it. A scope
    // runs them one after another, so the last tap is the one that sticks.
    scope: { id: "favorites" },
    mutationFn: ({ menuItemId, next }: { menuItemId: string; next: boolean }) =>
      next ? api.addFavorite(menuItemId) : api.removeFavorite(menuItemId),
    onMutate: async ({ menuItemId, next }) => {
      await client.cancelQueries({ queryKey: queryKeys.favoriteIds });
      const previous = client.getQueryData<Set<string>>(queryKeys.favoriteIds);
      const optimistic = new Set(previous ?? []);
      if (next) optimistic.add(menuItemId);
      else optimistic.delete(menuItemId);
      client.setQueryData(queryKeys.favoriteIds, optimistic);
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(queryKeys.favoriteIds, context.previous);
    },
    onSettled: () => {
      client.invalidateQueries({ queryKey: queryKeys.favoriteIds });
      client.invalidateQueries({ queryKey: queryKeys.favorites });
      // The account screen counts them.
      client.invalidateQueries({ queryKey: queryKeys.profile });
    },
  });
}

/** Dishes people ordered together at this restaurant. */
export function useGeneratedCombos(restaurantId: string | undefined, limit = 12) {
  return useQuery({
    queryKey: [...queryKeys.combos, restaurantId ?? "none", limit],
    queryFn: () => api.getGeneratedCombos(restaurantId as string, limit),
    enabled: Boolean(restaurantId),
    staleTime: 5 * 60 * 1000,
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

/**
 * One order, for the tracking page.
 *
 * `fallbackPollMs` is only for when no realtime push can arrive; with the
 * socket live the push invalidates this query and nothing polls. It stops by
 * itself once the order is finished, because nothing will change after that.
 */
export function useOrder(
  orderId: string | undefined,
  enabled: boolean,
  fallbackPollMs: number | false = false,
) {
  return useQuery({
    queryKey: queryKeys.order(orderId ?? ""),
    queryFn: () => api.getOrder(orderId as string),
    enabled: Boolean(orderId) && enabled,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "DELIVERED" || status === "CANCELLED") return false;
      return fallbackPollMs;
    },
  });
}

/**
 * Where the rider is, for the customer's own order.
 *
 * Polled while the food is still moving and stopped once it is not, the same
 * rule the admin panel follows: a finished delivery cannot change, and polling
 * it forever would be a request per completed order for as long as the page
 * stayed open.
 *
 * A failure is silent. Somebody watching their dinner should see the order
 * status they already had rather than an error about a courier.
 */
export function useOrderDelivery(orderId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.orderDelivery(orderId ?? ""),
    queryFn: () => api.getOrderDelivery(orderId as string),
    enabled: Boolean(orderId) && enabled,
    retry: false,
    refetchInterval: (query) => {
      const row = query.state.data;
      if (!row) return 30_000;
      return ["DELIVERED", "CANCELLED", "FAILED"].includes(row.state) ? false : 15_000;
    },
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

/**
 * What delivery costs for this address, from the server.
 *
 * Keyed on the address text, so editing a flat number asks again and a page
 * that has already asked does not. Disabled until there is an address to
 * quote: a courier priced against an empty string is a number about nothing.
 *
 * `placeholderData` keeps the previous fee on screen while a new one is in
 * flight. Without it the delivery line blinks to the branch fee and back on
 * every keystroke, which reads as the price changing while you type.
 */
export function useDeliveryQuote(
  locationId: string | null | undefined,
  address: {
    delivery_address: string;
    city: string;
    state: string;
    postal_code: string;
    saved_address_id?: string | undefined;
    latitude?: number | undefined;
    longitude?: number | undefined;
    subtotal?: number | undefined;
    discount_amount?: number | undefined;
  } | null,
) {
  const ready = Boolean(locationId) && Boolean(address?.delivery_address.trim());
  return useQuery({
    // Keyed on every part, so correcting a postcode asks again and a page that
    // has already asked does not.
    queryKey: queryKeys.deliveryQuote(locationId ?? "", JSON.stringify(address ?? {})),
    queryFn: () =>
      api.quoteDelivery({
        restaurant_location_id: locationId as string,
        ...(address as NonNullable<typeof address>),
      }),
    enabled: ready,
    placeholderData: (previous) => previous,
    // A courier's price for one pair of points does not move minute to
    // minute, and this sits on the checkout's critical path.
    staleTime: 5 * 60 * 1000,
    retry: false,
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
