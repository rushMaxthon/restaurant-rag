import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { MenuItem, RestaurantLocation } from "@/lib/bangkok-data";
import { useAppConfig, useRestaurant, pickDefaultLocation } from "@/lib/queries";
import { applyBrandColor } from "@/lib/theme";

export type CartLine = {
  lineId: string;
  itemId: string;
  // The order is placed against the line's OWN restaurant, not whichever one
  // the app happens to be showing. The concierge answers across the whole
  // marketplace, so a suggestion can easily belong to another kitchen; sending
  // it under the current branch failed validation with "One or more menu items
  // were not found for this restaurant".
  restaurantId: string;
  restaurantName: string | undefined;
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

/**
 * Whether adding this dish would mix two kitchens into one order.
 *
 * Exported and pure so the rule can be tested without a React tree. It is the
 * rule behind a real failure: the concierge answers across the whole
 * marketplace, so a suggestion can belong to another restaurant, and sending it
 * under the app's current branch was rejected with "One or more menu items were
 * not found for this restaurant" — at checkout, after the customer had done all
 * the work.
 */
export function cartConflictsWith(
  cart: Pick<CartLine, "restaurantId">[],
  itemRestaurantId: string,
): boolean {
  const current = cart[0]?.restaurantId;
  return Boolean(current && current !== itemRestaurantId);
}

type AppState = {
  branchId: string;
  cart: CartLine[];
  fulfillment: "DELIVERY" | "PICKUP";
  dark: boolean;
};

type AddItemOptions = {
  unitPrice?: number;
  /** Shown in the cart when the dish is not from the app's own restaurant. */
  restaurantName?: string | undefined;
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
  /** The restaurant the cart belongs to, or undefined while it is empty. */
  cartRestaurantId: string | undefined;
  cartRestaurantName: string | undefined;
  /** True when adding this dish would mix two kitchens into one order. */
  conflictsWithCart: (item: MenuItem) => boolean;
  /** Empties the cart first, so a dish from another restaurant can start one. */
  replaceCartWith: (item: MenuItem, options?: AddItemOptions) => void;
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

function loadInitialState(): AppState {
  if (typeof window === "undefined") return initial;
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved) return { ...initial, ...(JSON.parse(saved) as Partial<AppState>) };
  } catch {
    // ignore corrupt storage
  }
  return initial;
}

export function BangkokStoreProvider({ children }: { children: ReactNode }) {
  // Read localStorage synchronously at mount (lazy initializer) rather than in
  // a useEffect: a load-effect racing against the persist-effect below would,
  // on every fresh mount, have the persist-effect's first run write back the
  // still-unloaded `initial` state and clobber whatever was just saved (e.g.
  // the cart) before the load-effect's setState ever lands.
  const [state, setState] = useState<AppState>(loadInitialState);

  const appConfigQuery = useAppConfig();
  const restaurantQuery = useRestaurant(appConfigQuery.data?.restaurant_id);
  // `?? []` alone builds a fresh array every render, so the effect below and
  // the context value both re-run on every render regardless of the data.
  const locations = useMemo(() => restaurantQuery.data?.locations ?? [], [restaurantQuery.data]);

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
          return {
            ...s,
            cart: s.cart.map((line) =>
              line.lineId === signature ? { ...line, quantity: line.quantity + 1 } : line,
            ),
          };
        }
        return {
          ...s,
          cart: [
            ...s.cart,
            {
              lineId: signature,
              itemId: item.id,
              restaurantId: item.restaurant_id,
              restaurantName: options?.restaurantName,
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

  // Cart scope is restaurant + location — two kitchens cannot share one order.
  // Rather than blocking the dish (which is what made a concierge suggestion
  // feel broken), the UI offers to start a fresh cart with it.
  const replaceCartWith = useCallback(
    (item: MenuItem, options?: AddItemOptions) => {
      setState((s) => ({ ...s, cart: [] }));
      addItem(item, options);
    },
    [addItem],
  );

  const changeQuantity = useCallback(
    (lineId: string, delta: number) =>
      setState((s) => ({
        ...s,
        cart: s.cart
          .map((line) =>
            line.lineId === lineId ? { ...line, quantity: line.quantity + delta } : line,
          )
          .filter((line) => line.quantity > 0),
      })),
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
      cartRestaurantId: state.cart[0]?.restaurantId,
      cartRestaurantName: state.cart[0]?.restaurantName,
      conflictsWithCart: (item: MenuItem) => cartConflictsWith(state.cart, item.restaurant_id),
      replaceCartWith,
      addItem,
      changeQuantity,
      clearCart: () => setState((s) => ({ ...s, cart: [] })),
      setFulfillment: (fulfillment) => setState((s) => ({ ...s, fulfillment })),
      toggleTheme: () => setState((s) => ({ ...s, dark: !s.dark })),
      totalItems: state.cart.reduce((n, line) => n + line.quantity, 0),
      subtotal: state.cart.reduce((n, line) => n + line.unitPrice * line.quantity, 0),
    }),
    [
      state,
      appConfigQuery.data,
      restaurantQuery.data,
      locations,
      setBranchId,
      addItem,
      replaceCartWith,
      changeQuantity,
      appConfigQuery.isLoading,
      restaurantQuery.isLoading,
    ],
  );

  return <AppStore.Provider value={value}>{children}</AppStore.Provider>;
}

export function useBangkokStore() {
  const store = useContext(AppStore);
  if (!store) throw new Error("Bangkok store is unavailable");
  return store;
}
