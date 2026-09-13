import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type OrderCreateRequest } from "@/lib/api";
import type { RestaurantLocation } from "@/lib/bangkok-data";

export const queryKeys = {
  appConfig: ["app-config"] as const,
  restaurant: (id: string) => ["restaurant", id] as const,
  menuItems: (restaurantId: string, locationId?: string | null) => ["menu-items", restaurantId, locationId ?? "all"] as const,
  menuItem: (id: string) => ["menu-item", id] as const,
  orders: ["orders"] as const,
  order: (id: string) => ["order", id] as const,
  combos: ["generated-combos"] as const,
  offers: ["personalized-offers"] as const,
};

export function useAppConfig() {
  return useQuery({ queryKey: queryKeys.appConfig, queryFn: api.getAppConfig, staleTime: Infinity });
}

export function useRestaurant(restaurantId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.restaurant(restaurantId ?? ""),
    queryFn: () => api.getRestaurant(restaurantId as string),
    enabled: Boolean(restaurantId),
    staleTime: 5 * 60 * 1000,
  });
}

export function useMenuItems(restaurantId: string | undefined, locationId: string | undefined | null) {
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

/** Prefers an open branch, falling back to the first one returned. */
export function pickDefaultLocation(locations: RestaurantLocation[] | undefined): RestaurantLocation | undefined {
  if (!locations?.length) return undefined;
  return locations.find((l) => l.is_open && l.is_active) ?? locations[0];
}
