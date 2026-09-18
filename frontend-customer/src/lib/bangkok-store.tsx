import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { MenuItem, RestaurantLocation } from "@/lib/bangkok-data";
import type { CartAction } from "@/lib/api";
import { planCartActions } from "@/lib/cart-actions";

/** Which part of an item a chosen option covers. Mirrors the server enum. */
export type OptionPortion = "WHOLE" | "LEFT" | "RIGHT";
import { useAppConfig, useRestaurant, pickDefaultLocation } from "@/lib/queries";
import { applyBrandColor } from "@/lib/theme";

/** See the note in auth.tsx: layout on the client, no-op effect on the server. */
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

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
  /**
   * Which half each chosen option goes on, keyed by option id.
   *
   * Added alongside `optionIds` rather than replacing it: carts already live
   * in localStorage in the old shape, and a saved basket must not be lost to
   * a type change. An option with no entry here is on the WHOLE item, which is
   * what every existing line means.
   */
  optionPortions?: Record<string, OptionPortion>;
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

export type ApplyCartActionsOutcome = {
  cart: CartLine[];
  dropped: CartAction[];
  proposals: CartAction[];
  /** False when this turn id was already applied — the idempotent no-op. */
  applied: boolean;
};

/**
 * The store's one chat-driven mutation rule, pure so it can be tested without
 * mounting the provider: applying the same turn twice (a retried stream, a
 * duplicate `done` frame) must not double-apply it.
 *
 * `lastAppliedTurnId` is the caller's own bookkeeping (a ref in the provider
 * below) rather than store state, because it is not something a saved cart
 * needs to remember across a reload — only within the session that received
 * the turn.
 */
export function applyCartActionsToCart(
  cart: CartLine[],
  turnId: string,
  lastAppliedTurnId: string | null,
  actions: CartAction[],
  menu: MenuItem[],
): ApplyCartActionsOutcome {
  if (turnId === lastAppliedTurnId) {
    return { cart, dropped: [], proposals: [], applied: false };
  }
  const { next, dropped, proposals } = planCartActions(actions, cart, menu);
  return { cart: next, dropped, proposals, applied: true };
}

type AppState = {
  branchId: string;
  /**
   * Whether the CUSTOMER picked this branch, as opposed to the app defaulting.
   *
   * Separate from `branchId` because the two mean different things and the app
   * needs both. Branches of one restaurant do not carry the same menu — Bangkok
   * Bowl runs 13, 13 and 12 items across three branches — so a silent default
   * shows a menu the customer may not be able to order from, and they are never
   * told which kitchen they are looking at. The default still happens, to give
   * the picker something to pre-select; it just no longer counts as an answer.
   */
  branchChosen: boolean;
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
  optionPortions?: Record<string, OptionPortion>;
};

type Store = AppState & {
  restaurantId: string | undefined;
  /**
   * Optional features this restaurant has, from `/app-config`.
   *
   * Read through `hasCapability`, never directly: a missing key means a
   * backend older than the capability, and that has to read as "available" —
   * hiding a feature a restaurant is paying for is the worse failure.
   */
  capabilities: Record<string, boolean>;
  restaurantName: string | undefined;
  locations: RestaurantLocation[];
  /** The restaurant's own clock; undefined falls back to the device's. */
  timeZone: string | undefined;
  currentLocation: RestaurantLocation | undefined;
  /** The branch the order will actually be placed against. */
  orderLocation: RestaurantLocation | undefined;
  /** False until the customer has actually picked a branch themselves. */
  branchChosen: boolean;
  isRestaurantLoading: boolean;
  /** The restaurant or app config could not be fetched at all. */
  isRestaurantError: boolean;
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
  /**
   * The ordering agent's only cart-mutating path. Idempotent per `turnId` and
   * snapshots the cart first, so `undoLastChatTurn` can always undo it in one
   * tap. Returns what it could NOT apply, so the caller can tell the customer:
   * `dropped` (referenced something off this branch's menu, or arrived with a
   * status this client refuses to trust) and `proposals` (needs a confirm).
   */
  applyCartActions: (
    turnId: string,
    actions: CartAction[],
    menu: MenuItem[],
  ) => { dropped: CartAction[]; proposals: CartAction[] };
  /** Restores the cart to just before the last `applyCartActions` call. */
  undoLastChatTurn: () => boolean;
  setFulfillment: (value: AppState["fulfillment"]) => void;
  toggleTheme: () => void;
  totalItems: number;
  subtotal: number;
};

const initial: AppState = {
  branchId: "",
  branchChosen: false,
  cart: [],
  fulfillment: "DELIVERY",
  dark: false,
};
const STORAGE_KEY = "bangkok-bowl-state";
/**
 * The context, pinned so its identity survives a hot update.
 *
 * Vite's Fast Refresh re-evaluates this whole module on every edit to it. A
 * bare `createContext(...)` at module scope would therefore mint a NEW context
 * object, while the already-mounted AppShell still holds a reference to the old
 * one — so `useContext` returns null and the app dies with "Bangkok store is
 * unavailable" until someone hard-reloads. Nothing is wrong with the code at
 * that point; a cold load is always fine, which is what makes it confusing.
 *
 * `globalThis` outlives module re-evaluation, so the same context object is
 * handed back after each refresh and mounted consumers keep working. In a
 * production build this module is evaluated once and the lookup simply misses,
 * so this costs one property read at startup.
 */
const CONTEXT_KEY = "__bangkokStoreContext__";
type ContextCache = { [CONTEXT_KEY]?: React.Context<Store | null> };
const cache = globalThis as unknown as ContextCache;
const AppStore: React.Context<Store | null> =
  cache[CONTEXT_KEY] ?? (cache[CONTEXT_KEY] = createContext<Store | null>(null));

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
  // Starts at `initial` so the first client render matches the server's.
  //
  // This used to be a lazy initializer reading localStorage, to stop the
  // persist-effect below from writing an empty `initial` over a saved cart
  // before the load landed. That race is real, but the initializer bought the
  // fix at the price of a hydration mismatch: the server rendered "Cart (0)"
  // and the client rendered "Cart (3)", so React discarded the whole tree and
  // rebuilt it on every route. The race is now closed by gating the persist on
  // `hydrated` instead, which costs nothing and keeps the markup agreeing.
  const [state, setState] = useState<AppState>(initial);
  const [hydrated, setHydrated] = useState(false);

  useIsomorphicLayoutEffect(() => {
    setState(loadInitialState());
    setHydrated(true);
  }, []);

  const appConfigQuery = useAppConfig();
  const restaurantQuery = useRestaurant(appConfigQuery.data?.restaurant_id);
  // `?? []` alone builds a fresh array every render, so the effect below and
  // the context value both re-run on every render regardless of the data.
  const locations = useMemo(() => restaurantQuery.data?.locations ?? [], [restaurantQuery.data]);

  // Theme before paint, so someone on dark mode never gets a white flash.
  useIsomorphicLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", state.dark);
  }, [state.dark]);

  // Never persist before the restore has happened — this effect's first run
  // would otherwise write the empty `initial` straight over the saved cart.
  useEffect(() => {
    if (!hydrated) return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state, hydrated]);

  // Pre-select an open branch once the restaurant loads. This is a suggestion
  // for the gate to highlight, NOT a choice — `branchChosen` stays false.
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

  /**
   * Empty the basket and commit it to storage in the same tick.
   *
   * The persist effect below would normally handle the write, but the payment
   * flow clears the cart and then navigates the whole page immediately, which
   * beats a passive effect. The basket then survived its own payment: the
   * header still showed the badge and the same food could be paid for twice.
   */
  const clearCart = useCallback(() => {
    setState((s) => ({ ...s, cart: [] }));
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      const saved = raw ? (JSON.parse(raw) as Partial<AppState>) : {};
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...saved, cart: [] }));
    } catch {
      // Storage can be unavailable; the effect will catch up if it is not.
    }
  }, []);

  // Every route into this is a deliberate act — the gate, or the header
  // picker — so choosing is recorded here rather than at each call site, where
  // a future caller would have to remember to.
  const setBranchId = useCallback(
    (branchId: string) => setState((s) => ({ ...s, branchId, branchChosen: true })),
    [],
  );

  const addItem = useCallback(
    (item: MenuItem, options?: AddItemOptions) =>
      setState((s) => {
        const optionIds = options?.optionIds ?? [];
        const addOnNames = options?.addOnNames ?? [];
        const optionPortions = options?.optionPortions ?? {};
        // The portion is part of what makes a line distinct: half pepperoni and
        // whole pepperoni are two different pizzas, and without it the second
        // would silently increment the quantity of the first.
        const signature = `${item.id}-${options?.sizeId ?? ""}-${optionIds
          .slice()
          .sort()
          .map((id) => `${id}:${optionPortions[id] ?? "WHOLE"}`)
          .join("-")}`;
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
              optionPortions,
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

  // Both refs, not state: neither needs to survive a reload, and putting them
  // in `state` would mean every chat cart edit gets written to localStorage
  // twice over (once for the ref's own bookkeeping, once for the cart it
  // produced), for no reader that wants it back after a restart.
  const lastChatTurnIdRef = useRef<string | null>(null);
  const cartSnapshotRef = useRef<CartLine[] | null>(null);

  const applyCartActions = useCallback(
    (turnId: string, actions: CartAction[], menu: MenuItem[]) => {
      const outcome = applyCartActionsToCart(
        state.cart,
        turnId,
        lastChatTurnIdRef.current,
        actions,
        menu,
      );
      if (outcome.applied) {
        // One level of undo, per the spec: this snapshot is overwritten by
        // the next applied turn, not stacked.
        if (outcome.cart !== state.cart) cartSnapshotRef.current = state.cart;
        lastChatTurnIdRef.current = turnId;
        if (outcome.cart !== state.cart) {
          setState((s) => ({ ...s, cart: outcome.cart }));
        }
      }
      return { dropped: outcome.dropped, proposals: outcome.proposals };
    },
    [state.cart],
  );

  const undoLastChatTurn = useCallback(() => {
    const snapshot = cartSnapshotRef.current;
    if (!snapshot) return false;
    cartSnapshotRef.current = null;
    lastChatTurnIdRef.current = null;
    setState((s) => ({ ...s, cart: snapshot }));
    return true;
  }, []);

  const value = useMemo<Store>(
    () => ({
      ...state,
      restaurantId: appConfigQuery.data?.restaurant_id,
      // What this restaurant has switched on. Defaults to on where the
      // server said nothing: a missing answer is an older backend, not a
      // revoked feature, and hiding a working feature is the worse mistake.
      capabilities: appConfigQuery.data?.capabilities ?? {},
      restaurantName: restaurantQuery.data?.name,
      timeZone: appConfigQuery.data?.business_timezone,
      locations,
      currentLocation: locations.find((l) => l.id === state.branchId),
      // What the order is priced and scheduled against.
      //
      // `currentLocation` is whatever the branch picker is showing. The order
      // is placed against `cart[0].restaurantLocationId`, and when a cart was
      // filled at one branch and the picker later moved, those are different
      // branches — so the customer read one branch's hours, fee and slots
      // while the order went to another, and the server refused the slot.
      // Every slot rule is per LOCATION, so it has to read the location the
      // order actually names.
      orderLocation:
        locations.find((l) => l.id === (state.cart[0]?.restaurantLocationId ?? state.branchId)) ??
        locations.find((l) => l.id === state.branchId),
      branchChosen: state.branchChosen,
      isRestaurantLoading: appConfigQuery.isLoading || restaurantQuery.isLoading,
      // Distinguished from "loading" and from "empty": a menu screen that
      // says "nothing matches that" because the server was unreachable is
      // telling the customer something false about the restaurant.
      isRestaurantError: appConfigQuery.isError || restaurantQuery.isError,
      setBranchId,
      cartRestaurantId: state.cart[0]?.restaurantId,
      cartRestaurantName: state.cart[0]?.restaurantName,
      conflictsWithCart: (item: MenuItem) => cartConflictsWith(state.cart, item.restaurant_id),
      replaceCartWith,
      addItem,
      changeQuantity,
      clearCart,
      applyCartActions,
      undoLastChatTurn,
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
      clearCart,
      applyCartActions,
      undoLastChatTurn,
      appConfigQuery.isLoading,
      restaurantQuery.isLoading,
      appConfigQuery.isError,
      restaurantQuery.isError,
    ],
  );

  return <AppStore.Provider value={value}>{children}</AppStore.Provider>;
}

export function useBangkokStore() {
  const store = useContext(AppStore);
  if (!store) throw new Error("Bangkok store is unavailable");
  return store;
}

/**
 * Whether this restaurant has a feature switched on.
 *
 * Absent means yes. The backend sends every client-visible capability it
 * knows, so a key that is not there is a server older than the capability —
 * and hiding a feature a restaurant is paying for is a worse failure than
 * briefly showing one that was just switched off.
 */
export function hasCapability(
  capabilities: Record<string, boolean> | undefined,
  key: string,
): boolean {
  return capabilities?.[key] ?? true;
}
