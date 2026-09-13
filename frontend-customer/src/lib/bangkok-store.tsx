import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { MenuItem, RestaurantLocation } from "@/lib/bangkok-data";
import { useAppConfig, useRestaurant, pickDefaultLocation } from "@/lib/queries";
import { applyBrandColor } from "@/lib/theme";

export type CartLine = {
  lineId: string;
  itemId: string;
  restaurantLocationId: string;
  name: string;
  image_url: string | null;
  quantity: number;
  unitPrice: number;
  sizeId: string | undefined;
  sizeName: string | undefined;
  optionIds: string[];
  addOnNames: string[];
};

type AppState = { branchId: string; cart: CartLine[]; fulfillment: "DELIVERY" | "PICKUP"; dark: boolean };

type AddItemOptions = {
  unitPrice?: number;
  sizeId: string | undefined;
  sizeName: string | undefined;
  optionIds?: string[];
  addOnNames?: string[];
};

type Store = AppState & {
  restaurantId: string | undefined;
  restaurantName: string | undefined;
  locations: RestaurantLocation[];
  currentLocation: RestaurantLocation | undefined;
  isRestaurantLoading: boolean;
  setBranchId: (id: string) => void;
  addItem: (item: MenuItem, options?: AddItemOptions) => void;
  changeQuantity: (lineId: string, delta: number) => void;
  clearCart: () => void;
  setFulfillment: (value: AppState["fulfillment"]) => void;
  toggleTheme: () => void;
  totalItems: number;
  subtotal: number;
};

const initial: AppState = { branchId: "", cart: [], fulfillment: "DELIVERY", dark: false };
const STORAGE_KEY = "bangkok-bowl-state";
const AppStore = createContext<Store | null>(null);

export function BangkokStoreProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState>(initial);

  const appConfigQuery = useAppConfig();
  const restaurantQuery = useRestaurant(appConfigQuery.data?.restaurant_id);
  const locations = restaurantQuery.data?.locations ?? [];

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try {
        setState((s) => ({ ...s, ...(JSON.parse(saved) as Partial<AppState>) }));
      } catch {
        // ignore corrupt storage
      }
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    document.documentElement.classList.toggle("dark", state.dark);
  }, [state]);

  // Default to an open branch once the restaurant loads, if none is chosen yet.
  useEffect(() => {
    if (!locations.length) return;
    setState((s) => {
      if (s.branchId && locations.some((l) => l.id === s.branchId)) return s;
      const preferred = pickDefaultLocation(locations);
      return preferred ? { ...s, branchId: preferred.id } : s;
    });
  }, [locations]);

  useEffect(() => {
    applyBrandColor(appConfigQuery.data?.branding.primary_color);
  }, [appConfigQuery.data?.branding.primary_color]);

  const setBranchId = useCallback((branchId: string) => setState((s) => ({ ...s, branchId })), []);

  const addItem = useCallback(
    (item: MenuItem, options?: AddItemOptions) =>
      setState((s) => {
        const optionIds = options?.optionIds ?? [];
        const addOnNames = options?.addOnNames ?? [];
        const signature = `${item.id}-${options?.sizeId ?? ""}-${optionIds.slice().sort().join("-")}`;
        const found = s.cart.find((line) => line.lineId === signature);
        if (found) {
          return { ...s, cart: s.cart.map((line) => (line.lineId === signature ? { ...line, quantity: line.quantity + 1 } : line)) };
        }
        return {
          ...s,
          cart: [
            ...s.cart,
            {
              lineId: signature,
              itemId: item.id,
              restaurantLocationId: item.restaurant_location_id,
              name: item.name,
              image_url: item.image_url,
              quantity: 1,
              unitPrice: options?.unitPrice ?? Number(item.price),
              sizeId: options?.sizeId,
              sizeName: options?.sizeName,
              optionIds,
              addOnNames,
            },
          ],
        };
      }),
    [],
  );

  const changeQuantity = useCallback(
    (lineId: string, delta: number) =>
      setState((s) => ({ ...s, cart: s.cart.map((line) => (line.lineId === lineId ? { ...line, quantity: line.quantity + delta } : line)).filter((line) => line.quantity > 0) })),
    [],
  );

  const value = useMemo<Store>(
    () => ({
      ...state,
      restaurantId: appConfigQuery.data?.restaurant_id,
      restaurantName: restaurantQuery.data?.name,
      locations,
      currentLocation: locations.find((l) => l.id === state.branchId),
      isRestaurantLoading: appConfigQuery.isLoading || restaurantQuery.isLoading,
      setBranchId,
      addItem,
      changeQuantity,
      clearCart: () => setState((s) => ({ ...s, cart: [] })),
      setFulfillment: (fulfillment) => setState((s) => ({ ...s, fulfillment })),
      toggleTheme: () => setState((s) => ({ ...s, dark: !s.dark })),
      totalItems: state.cart.reduce((n, line) => n + line.quantity, 0),
      subtotal: state.cart.reduce((n, line) => n + line.unitPrice * line.quantity, 0),
    }),
    [state, appConfigQuery.data, restaurantQuery.data, locations, setBranchId, addItem, changeQuantity, appConfigQuery.isLoading, restaurantQuery.isLoading],
  );

  return <AppStore.Provider value={value}>{children}</AppStore.Provider>;
}

export function useBangkokStore() {
  const store = useContext(AppStore);
  if (!store) throw new Error("Bangkok store is unavailable");
  return store;
}
