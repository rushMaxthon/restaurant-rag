import React, {
  useCallback,
  createContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';
import {
  ApiError,
  api,
  invalidateRequestCache,
  setAppIdentityHeaders,
} from '@services/api';
import { firebaseAuthService } from '@services/firebaseAuth';
import {
  setPushRegistrationAuthToken,
  syncPushTokenRegistration,
} from '@services/pushNotifications';
import { setNotificationNavigationAuthToken } from '@/navigation/navigationService';
import { resolveAppIdentity } from '@services/appInfo';
import type { ThemePreference } from '@/theme';
import type {
  AppConfig,
  AppliedPersonalizedOffer,
  CartFulfillmentType,
  CartSelectedOption,
  CartSelectedSize,
  CartReplacementPrompt,
  CartState,
  FavoriteItem,
  FulfillmentSelection,
  MenuItem,
  OrderScheduleType,
  PendingOfferPrompt,
  PersonalizedOfferCard,
  SelectedLocation,
  ToastMessage,
  User,
  UserPreferences,
} from '@/types/app';
import { storage } from '@services/storage';
import {
  buildLineItemId,
  calculateUnitPrice,
} from '@/utils/menuItemCustomization';

/**
 * The store is published as several narrow contexts rather than one object.
 *
 * A toast, a cart quantity change and a favourite toggle are unrelated events;
 * when they shared a context value every one of them re-rendered every screen
 * in the app. Each slice below notifies only the consumers that read it, and
 * the actions slice never changes at all.
 */
/**
 * 'unresolved' means the backend has never told this install what it is —
 * neither now nor on a previous launch. It is NOT a synonym for marketplace.
 */
export type AppConfigStatus = 'resolved' | 'unresolved';

export interface SessionValue {
  bootstrapped: boolean;
  /**
   * Backend-resolved identity for this build, and the single source of truth
   * for app mode, linked restaurant, and branding. Null only when the config
   * could not be resolved and nothing was cached.
   */
  appConfig: AppConfig | null;
  /**
   * Whether `appConfig` is trustworthy, as distinct from what it contains.
   *
   * `appConfig === null` is ambiguous on its own: it reads as "marketplace" to
   * any consumer that asks `app_mode === 'SINGLE_RESTAURANT'`, which is how a
   * failed config fetch silently turned a single-restaurant build into a
   * marketplace one. Screens that scope on app mode MUST branch on this first
   * and render a loading state while it is 'unresolved' — never guess a mode.
   *
   * 'resolved' covers a cached config too: it was fetched from the backend on
   * an earlier launch, so it is real, just possibly stale.
   */
  appConfigStatus: AppConfigStatus;
  token: string | null;
  user: User | null;
}

export interface PreferencesValue {
  preferences: UserPreferences | null;
  preferencesOnboardingCompleted: boolean;
}

export interface FavoritesValue {
  favoriteIds: string[];
  favoritePendingIds: string[];
  favoritesHydrated: boolean;
  favoriteVersion: number;
}

export interface PromptsValue {
  pendingCartReplacement: CartReplacementPrompt | null;
  pendingOfferPrompt: PendingOfferPrompt | null;
}

export interface AppStoreActions {
  /**
   * Re-resolves this build's app config from the backend.
   *
   * Bootstrap already retries, so this exists for the case that outlives it:
   * the app opened while the API was asleep and every attempt was exhausted.
   * A screen sitting on 'unresolved' calls this to recover without the user
   * having to force-quit and relaunch. Resolves to the new status.
   */
  refreshAppConfig: () => Promise<AppConfigStatus>;
  setSession: (
    token: string,
    user: User,
    appIdentity?: StoredAppIdentity,
  ) => Promise<void>;
  updateUser: (user: User) => void;
  setThemePreference: (value: ThemePreference) => Promise<void>;
  setSelectedLocation: (location: SelectedLocation | null) => void;
  savePreferences: (
    preferences: UserPreferences | null,
    options?: {
      sync?: boolean;
      markOnboardingCompleted?: boolean;
    },
  ) => Promise<void>;
  skipPreferencesOnboarding: () => void;
  refreshFavoriteIds: () => Promise<void>;
  toggleFavorite: (input: {
    menuItemId: string;
    shouldFavorite?: boolean;
  }) => Promise<boolean>;
  isFavorite: (menuItemId: string) => boolean;
  isFavoritePending: (menuItemId: string) => boolean;
  getFavoriteItem: (menuItemId: string) => Promise<FavoriteItem | null>;
  logout: () => void;
  setSelectedPersonalizedOffer: (
    offer: AppliedPersonalizedOffer | null,
  ) => void;
  addToCart: (
    menuItem: MenuItem,
    restaurantId: string,
    restaurantName: string,
    options?: {
      quantity?: number;
      silent?: boolean;
      fulfillmentSelection?: FulfillmentSelection;
      selectedSize?: CartSelectedSize | null;
      selectedOptions?: CartSelectedOption[];
      unitPrice?: number;
    },
  ) => void;
  requestAddToCart: (
    menuItem: MenuItem,
    restaurantId: string,
    restaurantName: string,
    options?: {
      quantity?: number;
      silent?: boolean;
      fulfillmentSelection?: FulfillmentSelection;
      selectedSize?: CartSelectedSize | null;
      selectedOptions?: CartSelectedOption[];
      unitPrice?: number;
    },
  ) => Promise<void>;
  setCartFulfillmentType: (value: CartFulfillmentType) => void;
  setCartFulfillmentSelection: (input: {
    restaurantId?: string | null;
    restaurantName?: string | null;
    restaurantLocationId?: string | null;
    restaurantLocationName?: string | null;
    fulfillmentType: CartFulfillmentType;
    scheduleType: OrderScheduleType;
    scheduledAt: string | null;
  }) => void;
  updateCartQuantity: (cartItemId: string, nextQuantity: number) => void;
  clearCart: () => void;
  confirmCartReplacement: () => void;
  dismissCartReplacement: () => void;
  applyPendingOfferPrompt: (offerId: string) => void;
  continuePendingOfferPrompt: () => void;
  dismissPendingOfferPrompt: () => void;
  setChatSessionId: (value: string | null) => void;
  pushToast: (
    title: string,
    description: string,
    tone?: ToastMessage['tone'],
  ) => void;
  dismissToast: (id: number) => void;
}

/** App this session belongs to, stored beside the token. */
interface StoredAppIdentity {
  appClientId: string | null;
  appKey: string | null;
}

const emptyCart: CartState = {
  restaurantId: null,
  restaurantName: null,
  restaurantLocationId: null,
  restaurantLocationName: null,
  fulfillmentType: 'DELIVERY',
  scheduleType: 'ASAP',
  scheduledAt: null,
  items: [],
};

function isValidDateString(value: string | null | undefined): boolean {
  if (!value) {
    return false;
  }
  return !Number.isNaN(Date.parse(value));
}

/**
 * Drops a persisted cart that belongs to a different restaurant.
 *
 * A build can be re-pointed at another restaurant by changing its bundle ID,
 * so a cart saved under the previous configuration must not survive into the
 * new one. Defence in depth: the backend would reject the order anyway.
 */
function scopeCartToAppConfig(
  cart: CartState | null,
  appConfig: AppConfig | null,
): CartState {
  if (!cart) {
    return emptyCart;
  }
  const scopedRestaurantId =
    appConfig?.app_mode === 'SINGLE_RESTAURANT'
      ? appConfig.restaurant_id
      : null;
  if (!scopedRestaurantId || !cart.restaurantId) {
    return cart;
  }
  if (cart.restaurantId === scopedRestaurantId) {
    return cart;
  }

  console.warn(
    `[AppScope] Discarding cart from ${cart.restaurantId}; this build is scoped to ${scopedRestaurantId}`,
  );
  return emptyCart;
}

function normalizeCartState(value: CartState | null): CartState | null {
  if (!value) {
    return null;
  }

  const scheduledSelectionIsValid =
    value.scheduleType === 'SCHEDULED' && isValidDateString(value.scheduledAt);

  return {
    restaurantId: value.restaurantId ?? null,
    restaurantName: value.restaurantName ?? null,
    restaurantLocationId: value.restaurantLocationId ?? null,
    restaurantLocationName: value.restaurantLocationName ?? null,
    fulfillmentType: value.fulfillmentType === 'PICKUP' ? 'PICKUP' : 'DELIVERY',
    scheduleType: scheduledSelectionIsValid ? 'SCHEDULED' : 'ASAP',
    scheduledAt: scheduledSelectionIsValid ? value.scheduledAt ?? null : null,
    items: Array.isArray(value.items)
      ? value.items.map(item => ({
          id:
            item.id ??
            buildLineItemId({
              menuItemId: item.menuItem.id,
              selectedSizeId: item.selectedSize?.id ?? null,
              selectedOptions: item.selectedOptions ?? [],
            }),
          menuItem: {
            ...item.menuItem,
            has_sizes: item.menuItem.has_sizes ?? false,
            has_customizations: item.menuItem.has_customizations ?? false,
            sizes: item.menuItem.sizes ?? [],
            customization_groups: item.menuItem.customization_groups ?? [],
          },
          quantity: item.quantity,
          selectedSize: item.selectedSize ?? null,
          selectedOptions: item.selectedOptions ?? [],
          unitPrice:
            item.unitPrice ??
            calculateUnitPrice({
              menuItem: {
                ...item.menuItem,
                has_sizes: item.menuItem.has_sizes ?? false,
                has_customizations: item.menuItem.has_customizations ?? false,
                sizes: item.menuItem.sizes ?? [],
                customization_groups: item.menuItem.customization_groups ?? [],
              },
              selectedSize: item.selectedSize ?? null,
              selectedOptions: item.selectedOptions ?? [],
            }),
        }))
      : [],
  };
}

export const AppStoreActionsContext = createContext<AppStoreActions | null>(
  null,
);
export const SessionContext = createContext<SessionValue | null>(null);
export const PreferencesContext = createContext<PreferencesValue | null>(null);
export const CartContext = createContext<CartState | null>(null);
export const FavoritesContext = createContext<FavoritesValue | null>(null);
export const PromptsContext = createContext<PromptsValue | null>(null);
export const ToastsContext = createContext<ToastMessage[] | null>(null);
export const ThemePreferenceContext = createContext<ThemePreference | null>(
  null,
);
export const SelectedLocationContext = createContext<SelectedLocation | null>(
  null,
);
export const SelectedOfferContext =
  createContext<AppliedPersonalizedOffer | null>(null);
export const ChatSessionContext = createContext<string | null>(null);

function buildDefaultFulfillmentSelection(
  fulfillmentType: CartFulfillmentType = 'DELIVERY',
): FulfillmentSelection {
  return {
    fulfillmentType,
    scheduleType: 'ASAP',
    scheduledAt: new Date().toISOString(),
  };
}

function isNotFoundError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

function isAuthError(error: unknown): boolean {
  return (
    error instanceof ApiError && (error.status === 401 || error.status === 403)
  );
}

function mergePreferences(
  local: UserPreferences | null,
  remote: UserPreferences | null,
): UserPreferences | null {
  if (!local) {
    return remote;
  }
  if (!remote) {
    return local;
  }

  const localUpdatedAt = Date.parse(local.updated_at ?? '');
  const remoteUpdatedAt = Date.parse(remote.updated_at ?? '');

  if (Number.isFinite(localUpdatedAt) && Number.isFinite(remoteUpdatedAt)) {
    return localUpdatedAt >= remoteUpdatedAt ? local : remote;
  }

  if (Number.isFinite(localUpdatedAt)) {
    return local;
  }

  return remote;
}

function normalizeFavoriteIds(ids: string[]): string[] {
  return Array.from(new Set(ids)).sort();
}

function buildStoredLocationFromAddress(address: string): SelectedLocation {
  const parts = address
    .split(',')
    .map(part => part.trim())
    .filter(Boolean);
  return {
    latitude: null,
    longitude: null,
    address,
    city: parts[1] ?? parts[0] ?? 'Saved address',
    isDefault: true,
  };
}

function areSelectedLocationsEqual(
  left: SelectedLocation | null,
  right: SelectedLocation | null,
): boolean {
  if (left === right) {
    return true;
  }
  if (!left || !right) {
    return false;
  }

  return (
    left.latitude === right.latitude &&
    left.longitude === right.longitude &&
    left.address === right.address &&
    left.city === right.city &&
    (left.savedAddressId ?? null) === (right.savedAddressId ?? null) &&
    (left.label ?? null) === (right.label ?? null) &&
    (left.phoneNumber ?? null) === (right.phoneNumber ?? null) &&
    Boolean(left.isDefault) === Boolean(right.isDefault)
  );
}

/**
 * Field-by-field comparison of two user records.
 *
 * `updateUser` is called with a freshly deserialized object every time the
 * profile summary or a saved address is loaded. Replacing the stored user with
 * an identical copy used to re-run every effect keyed on it - re-fetching
 * favorites and re-registering the push token for no reason.
 */
function areUsersEqual(left: User | null, right: User | null): boolean {
  if (left === right) {
    return true;
  }
  if (!left || !right) {
    return false;
  }

  const keys = new Set([...Object.keys(left), ...Object.keys(right)]) as Set<
    keyof User
  >;

  for (const key of keys) {
    if (left[key] !== right[key]) {
      return false;
    }
  }
  return true;
}

function areFavoriteIdListsEqual(left: string[], right: string[]): boolean {
  if (left.length !== right.length) {
    return false;
  }
  return left.every((value, index) => value === right[index]);
}

/**
 * Keeps a ref pointing at the latest render's value.
 *
 * Lets an action read current state without listing that state as a
 * dependency, which is what makes the action identity-stable.
 */
function useLatestRef<T>(value: T) {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}

export function AppStoreProvider({ children }: PropsWithChildren) {
  const [bootstrapped, setBootstrapped] = useState(false);
  const [appConfig, setAppConfig] = useState<AppConfig | null>(null);
  const [appConfigStatus, setAppConfigStatus] =
    useState<AppConfigStatus>('unresolved');
  const [appIdentity, setAppIdentity] = useState<StoredAppIdentity | null>(
    null,
  );
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [cart, setCart] = useState<CartState>(emptyCart);
  const [chatSessionId, setChatSessionIdState] = useState<string | null>(null);
  const [selectedPersonalizedOffer, setSelectedPersonalizedOfferState] =
    useState<AppliedPersonalizedOffer | null>(null);
  const [selectedLocation, setSelectedLocationState] =
    useState<SelectedLocation | null>(null);
  const [preferences, setPreferencesState] = useState<UserPreferences | null>(
    null,
  );
  const [favoriteIds, setFavoriteIdsState] = useState<string[]>([]);
  const [favoritePendingIds, setFavoritePendingIds] = useState<string[]>([]);
  const [favoritesHydrated, setFavoritesHydrated] = useState(false);
  const [favoriteVersion, setFavoriteVersion] = useState(0);
  const [themePreference, setThemePreferenceState] =
    useState<ThemePreference>('system');
  const [preferencesOnboardingCompleted, setPreferencesOnboardingCompleted] =
    useState(false);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [pendingCartReplacement, setPendingCartReplacement] =
    useState<CartReplacementPrompt | null>(null);
  const [pendingOfferPrompt, setPendingOfferPrompt] =
    useState<PendingOfferPrompt | null>(null);
  const toastRef = useRef(1);
  const favoriteIdsRef = useRef<Set<string>>(new Set());
  const favoritePendingIdsRef = useRef<Set<string>>(new Set());
  const dismissedOfferPromptKeysRef = useRef<Set<string>>(new Set());

  // Every action below reads its current state through these refs instead of
  // closing over the state value. That keeps each callback's identity stable
  // for the lifetime of the provider, so the actions context never changes and
  // consumers never re-render because an unrelated action was recreated.
  const tokenRef = useLatestRef(token);
  const appConfigStatusRef = useLatestRef(appConfigStatus);
  const userRef = useLatestRef(user);
  const preferencesRef = useLatestRef(preferences);
  const selectedPersonalizedOfferRef = useLatestRef(selectedPersonalizedOffer);
  const pendingCartReplacementRef = useLatestRef(pendingCartReplacement);
  const pendingOfferPromptRef = useLatestRef(pendingOfferPrompt);

  const commitFavoriteIds = useCallback((nextIds: string[]) => {
    const normalized = normalizeFavoriteIds(nextIds);
    const current = normalizeFavoriteIds(Array.from(favoriteIdsRef.current));
    favoriteIdsRef.current = new Set(normalized);
    setFavoriteIdsState(normalized);
    if (!areFavoriteIdListsEqual(normalized, current)) {
      setFavoriteVersion(currentVersion => currentVersion + 1);
    }
  }, []);

  const getOfferForRestaurant = useCallback(
    (
      offer: AppliedPersonalizedOffer | null,
      restaurantId: string,
      locationId: string | null,
    ): AppliedPersonalizedOffer | null => {
      if (!offer || offer.restaurantId !== restaurantId) {
        return null;
      }
      if (
        offer.offerRestaurantLocationId &&
        offer.offerRestaurantLocationId !== locationId
      ) {
        return null;
      }
      return offer;
    },
    [],
  );

  useEffect(() => {
    let active = true;

    /**
     * Resolves this build's configuration from its own bundle ID.
     *
     * Falls back to the last cached config so a cold start without
     * connectivity still boots, and never throws: startup must not depend on
     * the network.
     */
    async function loadAppConfig(
      cachedAppConfig: AppConfig | null,
    ): Promise<AppConfig | null> {
      const identity = await resolveAppIdentity();
      // Applied before any request so every call — including this one — carries
      // the app identity the backend scopes on.
      setAppIdentityHeaders(identity);
      const bundleId = identity.bundleId;
      try {
        const resolved = await api.getAppConfig();
        console.log(
          '[AppConfig] Resolved:',
          `app_key=${resolved.app_key}`,
          `app_mode=${resolved.app_mode}`,
          `restaurant_id=${resolved.restaurant_id ?? 'null'}`,
          `display_name="${resolved.display_name}"`,
          `order_prefix=${resolved.order_prefix}`,
          `primary_color=${resolved.branding?.primary_color ?? 'none'}`,
          `min_version=${resolved.minimum_supported_version}`,
        );
        if (__DEV__) {
          console.log('[AppConfig] Full response:', JSON.stringify(resolved));
        }
        void storage.writeAppConfig(resolved);
        return resolved;
      } catch (error) {
        const status = error instanceof ApiError ? error.status : 'no response';
        const message = error instanceof Error ? error.message : String(error);
        console.warn(
          `[AppConfig] FAILED for ${bundleId} (status: ${status}): ${message}`,
        );
        if (cachedAppConfig) {
          console.warn(
            `[AppConfig] Falling back to cached config: app_key=${cachedAppConfig.app_key} app_mode=${cachedAppConfig.app_mode}`,
          );
        } else {
          console.warn(
            '[AppConfig] No cached config available, continuing without one',
          );
        }
        return cachedAppConfig;
      }
    }

    async function bootstrap() {
      const [
        auth,
        storedCart,
        storedSession,
        storedLocation,
        storedPreferences,
        storedPreferencesOnboardingCompleted,
        storedSelectedPersonalizedOffer,
        storedThemePreference,
        storedAppConfig,
      ] = await Promise.all([
        storage.readAuth(),
        storage.readCart(),
        storage.readChatSession(),
        storage.readLocation(),
        storage.readPreferences(),
        storage.readPreferencesOnboardingCompleted(),
        storage.readSelectedPersonalizedOffer(),
        storage.readThemePreference(),
        storage.readAppConfig(),
      ]);
      if (!active) {
        return;
      }

      // Awaited before the app is marked bootstrapped, so no screen ever
      // renders without the app identity resolved.
      const resolvedAppConfig = await loadAppConfig(storedAppConfig);
      if (!active) {
        return;
      }
      setAppConfig(resolvedAppConfig);
      // Only a config that actually came from the backend — now, or on an
      // earlier launch — counts as resolved. Null stays 'unresolved' so no
      // screen can read it as marketplace.
      setAppConfigStatus(resolvedAppConfig ? 'resolved' : 'unresolved');

      // A stored session belongs to one app. If this build now resolves to a
      // different app client - the bundle id changed, or the app was re-pointed
      // - that session can never be used again, so drop it locally rather than
      // waiting for the backend to reject every request with a 401.
      const storedAppClientId = auth?.appClientId ?? null;
      const sessionBelongsToAnotherApp = Boolean(
        auth?.token &&
          storedAppClientId &&
          resolvedAppConfig?.app_client_id &&
          storedAppClientId !== resolvedAppConfig.app_client_id,
      );
      if (sessionBelongsToAnotherApp) {
        console.warn(
          `[AppScope] Discarding session issued for app ${storedAppClientId}; this build is ${resolvedAppConfig?.app_client_id}`,
        );
        void storage.writeAuth(null);
      }
      const activeAuth = sessionBelongsToAnotherApp ? null : auth;

      const resolvedPreferences = storedPreferences;
      const resolvedOnboardingCompleted =
        storedPreferencesOnboardingCompleted || Boolean(resolvedPreferences);

      setToken(activeAuth?.token ?? null);
      setUser(activeAuth?.user ?? null);
      setAppIdentity(
        activeAuth
          ? {
              appClientId: activeAuth.appClientId ?? null,
              appKey: activeAuth.appKey ?? null,
            }
          : null,
      );
      setCart(
        scopeCartToAppConfig(normalizeCartState(storedCart), resolvedAppConfig),
      );
      setChatSessionIdState(storedSession);
      const scopedRestaurantId =
        resolvedAppConfig?.app_mode === 'SINGLE_RESTAURANT'
          ? resolvedAppConfig.restaurant_id
          : null;
      setSelectedPersonalizedOfferState(
        storedSelectedPersonalizedOffer &&
          scopedRestaurantId &&
          storedSelectedPersonalizedOffer.restaurantId !== scopedRestaurantId
          ? null
          : storedSelectedPersonalizedOffer,
      );
      setThemePreferenceState(storedThemePreference);
      setPreferencesState(resolvedPreferences);
      setPreferencesOnboardingCompleted(resolvedOnboardingCompleted);
      setSelectedLocationState(
        storedLocation ??
          (activeAuth?.user?.default_address
            ? buildStoredLocationFromAddress(activeAuth.user.default_address)
            : null),
      );
      setBootstrapped(true);

      if (!activeAuth?.token || activeAuth.user?.role !== 'CUSTOMER') {
        setFavoritesHydrated(true);
        return;
      }

      try {
        const remotePreferences = await api.getUserPreferences(
          activeAuth.token,
        );
        if (!active) {
          return;
        }
        setPreferencesState(current =>
          mergePreferences(current, remotePreferences),
        );
        setPreferencesOnboardingCompleted(true);
      } catch (error) {
        if (!active || isNotFoundError(error)) {
          return;
        }

        if (isAuthError(error)) {
          setToken(null);
          setUser(null);
        }
      }
    }

    void bootstrap();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    favoriteIdsRef.current = new Set(favoriteIds);
  }, [favoriteIds]);

  const setThemePreference = useCallback(async (value: ThemePreference) => {
    setThemePreferenceState(current => (current === value ? current : value));
    await storage.writeThemePreference(value);
  }, []);

  useEffect(() => {
    favoritePendingIdsRef.current = new Set(favoritePendingIds);
  }, [favoritePendingIds]);

  useEffect(() => {
    if (!bootstrapped) {
      return;
    }
    void storage.writeAuth(
      token && user
        ? {
            token,
            user,
            appClientId: appIdentity?.appClientId ?? null,
            appKey: appIdentity?.appKey ?? null,
          }
        : null,
    );
  }, [appIdentity, bootstrapped, token, user]);

  useEffect(() => {
    if (!bootstrapped) {
      return;
    }
    void storage.writeCart(cart);
  }, [bootstrapped, cart]);

  useEffect(() => {
    if (!bootstrapped) {
      return;
    }
    void storage.writeChatSession(chatSessionId);
  }, [bootstrapped, chatSessionId]);

  useEffect(() => {
    if (!bootstrapped) {
      return;
    }
    void storage.writeLocation(selectedLocation);
  }, [bootstrapped, selectedLocation]);

  useEffect(() => {
    if (!bootstrapped) {
      return;
    }
    void storage.writePreferences(preferences);
  }, [bootstrapped, preferences]);

  useEffect(() => {
    if (!bootstrapped) {
      return;
    }
    void storage.writePreferencesOnboardingCompleted(
      preferencesOnboardingCompleted,
    );
  }, [bootstrapped, preferencesOnboardingCompleted]);

  useEffect(() => {
    if (!bootstrapped) {
      return;
    }
    void storage.writeSelectedPersonalizedOffer(selectedPersonalizedOffer);
  }, [bootstrapped, selectedPersonalizedOffer]);

  const pushToast = useCallback(
    (
      title: string,
      description: string,
      tone: ToastMessage['tone'] = 'info',
    ) => {
      const id = toastRef.current++;
      setToasts(current => [...current, { id, title, description, tone }]);
      setTimeout(() => {
        setToasts(current => current.filter(toast => toast.id !== id));
      }, 3200);
    },
    [],
  );

  const refreshFavoriteIds = useCallback(async () => {
    const currentToken = tokenRef.current;
    if (!currentToken || !userRef.current) {
      commitFavoriteIds([]);
      setFavoritePendingIds([]);
      setFavoritesHydrated(true);
      return;
    }

    const ids = await api.getFavoriteIds(currentToken);
    commitFavoriteIds(ids);
    setFavoritesHydrated(true);
  }, [commitFavoriteIds, tokenRef, userRef]);

  const setSession = useCallback(
    async (
      nextToken: string,
      nextUser: User,
      nextAppIdentity?: StoredAppIdentity,
    ) => {
      // Nothing cached for the previous session may be served to this one.
      invalidateRequestCache();
      setToken(nextToken);
      setUser(nextUser);
      setAppIdentity(nextAppIdentity ?? null);

      const mergedLocalPreferences = preferencesRef.current;
      if (mergedLocalPreferences) {
        try {
          const syncedPreferences = await api.updateUserPreferences(
            nextToken,
            mergedLocalPreferences,
          );
          setPreferencesState(syncedPreferences);
          setPreferencesOnboardingCompleted(true);
        } catch (error) {
          pushToast(
            'Preferences saved locally',
            error instanceof Error
              ? error.message
              : 'Unable to sync preferences right now.',
            'info',
          );
        }
        return;
      }

      try {
        const remotePreferences = await api.getUserPreferences(nextToken);
        setPreferencesState(remotePreferences);
        setPreferencesOnboardingCompleted(true);
      } catch (error) {
        if (!isNotFoundError(error)) {
          pushToast(
            'Profile sync delayed',
            error instanceof Error
              ? error.message
              : 'Unable to load your saved preferences.',
            'info',
          );
        }
      }
    },
    [preferencesRef, pushToast],
  );

  const updateUser = useCallback((nextUser: User) => {
    setUser(previousUser => {
      if (areUsersEqual(previousUser, nextUser)) {
        return previousUser;
      }

      const previousDefault = previousUser?.default_address ?? null;
      const nextDefault = nextUser.default_address ?? null;

      if (previousDefault !== nextDefault) {
        setSelectedLocationState(currentLocation => {
          if (!nextDefault) {
            if (
              currentLocation?.isDefault ||
              currentLocation?.address === previousDefault
            ) {
              return null;
            }
            return currentLocation;
          }

          if (
            !currentLocation ||
            currentLocation.isDefault ||
            currentLocation.address === previousDefault
          ) {
            const nextLocation = buildStoredLocationFromAddress(nextDefault);
            return areSelectedLocationsEqual(currentLocation, nextLocation)
              ? currentLocation
              : nextLocation;
          }

          return currentLocation;
        });
      }

      return nextUser;
    });
  }, []);

  const setSelectedLocation = useCallback(
    (location: SelectedLocation | null) => {
      setSelectedLocationState(current =>
        areSelectedLocationsEqual(current, location) ? current : location,
      );
    },
    [],
  );

  const savePreferences = useCallback(
    async (
      nextPreferences: UserPreferences | null,
      options: {
        sync?: boolean;
        markOnboardingCompleted?: boolean;
      } = {},
    ) => {
      setPreferencesState(nextPreferences);
      if (options.markOnboardingCompleted !== false) {
        setPreferencesOnboardingCompleted(true);
      }

      const currentToken = tokenRef.current;
      if (!currentToken || !nextPreferences || options.sync === false) {
        return;
      }

      try {
        const syncedPreferences = await api.updateUserPreferences(
          currentToken,
          nextPreferences,
        );
        setPreferencesState(syncedPreferences);
      } catch (error) {
        pushToast(
          'Preferences saved locally',
          error instanceof Error
            ? error.message
            : 'Unable to sync preferences right now.',
          'info',
        );
        throw error;
      }
    },
    [pushToast, tokenRef],
  );

  const skipPreferencesOnboarding = useCallback(() => {
    setPreferencesOnboardingCompleted(true);
  }, []);

  // Keyed on who the user is, not on the `user` object: the profile screen and
  // the saved-address editor both call `updateUser`, and re-hydrating
  // favorites on every one of those replacements re-fetched the list and
  // flickered `favoritesHydrated` for the whole app.
  const userId = user?.id ?? null;

  useEffect(() => {
    let active = true;

    async function hydrateFavorites() {
      if (!token || !userId) {
        commitFavoriteIds([]);
        setFavoritePendingIds([]);
        setFavoritesHydrated(true);
        return;
      }

      setFavoritesHydrated(false);
      try {
        const ids = await api.getFavoriteIds(token);
        if (!active) {
          return;
        }
        commitFavoriteIds(ids);
      } catch (error) {
        if (!active) {
          return;
        }
        if (isAuthError(error)) {
          setToken(null);
          setUser(null);
          return;
        }
        pushToast(
          'Favorites sync delayed',
          error instanceof Error
            ? error.message
            : 'Unable to refresh your favorites right now.',
          'info',
        );
      } finally {
        if (active) {
          setFavoritesHydrated(true);
        }
      }
    }

    void hydrateFavorites();
    return () => {
      active = false;
    };
  }, [commitFavoriteIds, pushToast, token, userId]);

  useEffect(() => {
    setPushRegistrationAuthToken(token);
    setNotificationNavigationAuthToken(token);

    if (!token || !userId) {
      return;
    }

    void syncPushTokenRegistration(token);
  }, [token, userId]);

  const isFavorite = useCallback(
    (menuItemId: string) => favoriteIdsRef.current.has(menuItemId),
    [],
  );

  const isFavoritePending = useCallback(
    (menuItemId: string) => favoritePendingIdsRef.current.has(menuItemId),
    [],
  );

  const getFavoriteItem = useCallback(
    async (menuItemId: string): Promise<FavoriteItem | null> => {
      const currentToken = tokenRef.current;
      if (!currentToken) {
        return null;
      }
      const items = await api.getFavorites(currentToken);
      return items.find(item => item.id === menuItemId) ?? null;
    },
    [tokenRef],
  );

  const toggleFavorite = useCallback(
    async (input: { menuItemId: string; shouldFavorite?: boolean }) => {
      const currentToken = tokenRef.current;
      if (!currentToken || !userRef.current) {
        throw new ApiError('Please login to continue.', 401);
      }

      if (favoritePendingIdsRef.current.has(input.menuItemId)) {
        return favoriteIdsRef.current.has(input.menuItemId);
      }

      const previousIds = Array.from(favoriteIdsRef.current);
      const currentlyFavorite = favoriteIdsRef.current.has(input.menuItemId);
      const nextFavorite = input.shouldFavorite ?? !currentlyFavorite;
      if (currentlyFavorite === nextFavorite) {
        return nextFavorite;
      }

      favoritePendingIdsRef.current.add(input.menuItemId);
      setFavoritePendingIds(Array.from(favoritePendingIdsRef.current));
      commitFavoriteIds(
        nextFavorite
          ? [...previousIds, input.menuItemId]
          : previousIds.filter(menuItemId => menuItemId !== input.menuItemId),
      );

      try {
        if (nextFavorite) {
          await api.addFavorite(currentToken, input.menuItemId);
        } else {
          await api.removeFavorite(currentToken, input.menuItemId);
        }
        return nextFavorite;
      } catch (error) {
        commitFavoriteIds(previousIds);
        throw error;
      } finally {
        favoritePendingIdsRef.current.delete(input.menuItemId);
        setFavoritePendingIds(Array.from(favoritePendingIdsRef.current));
      }
    },
    [commitFavoriteIds, tokenRef, userRef],
  );

  const logout = useCallback(() => {
    invalidateRequestCache();
    setAppIdentity(null);
    void firebaseAuthService.signOutFirebasePhoneAuth();
    setToken(null);
    setUser(null);
    setChatSessionIdState(null);
    setSelectedPersonalizedOfferState(null);
    setSelectedLocationState(null);
    commitFavoriteIds([]);
    setFavoritePendingIds([]);
    setFavoritesHydrated(true);
    dismissedOfferPromptKeysRef.current.clear();
    setPendingOfferPrompt(null);
  }, [commitFavoriteIds]);

  function toAppliedOffer(
    offer: PersonalizedOfferCard,
  ): AppliedPersonalizedOffer {
    return {
      generatedOfferId: offer.generated_offer_id,
      generatedOfferUserMatchId: offer.generated_offer_user_match_id,
      offerId: offer.offer_id,
      offerName: offer.offer_name,
      offerType: offer.offer_type,
      audienceType: offer.audience_type,
      targetType: offer.target_type,
      restaurantId: offer.restaurant_id,
      restaurantName: offer.restaurant_name,
      restaurantLocationId: offer.restaurant_location_id,
      restaurantLocationName: offer.restaurant_location_name,
      offerRestaurantLocationId: offer.offer_restaurant_location_id,
      menuItemId: offer.menu_item_id,
      generatedComboId: offer.generated_combo_id,
      cuisineType: offer.cuisine_type,
      title: offer.title,
      ctaLabel: offer.cta_label,
      discountType: offer.discount_type,
      discountValue: offer.discount_value,
      discountLabel: offer.discount_label,
      maxDiscountAmount: offer.max_discount_amount,
      minimumOrderAmount: offer.minimum_order_amount,
      termsLabel: offer.terms_label,
      expiresAt: offer.expires_at,
    };
  }

  const buildOfferPromptKey = useCallback(
    (offer: PersonalizedOfferCard, menuItem: MenuItem) =>
      `${offer.offer_id}:${offer.restaurant_id}:${
        menuItem.restaurant_location_id ?? ''
      }:${menuItem.id}`,
    [],
  );

  const performAddToCart = useCallback(
    (
      menuItem: MenuItem,
      restaurantId: string,
      restaurantName: string,
      options?: {
        quantity?: number;
        silent?: boolean;
        offerOverride?: AppliedPersonalizedOffer | null;
        fulfillmentSelection?: FulfillmentSelection;
        selectedSize?: CartSelectedSize | null;
        selectedOptions?: CartSelectedOption[];
        unitPrice?: number;
      },
    ) => {
      const quantity = options?.quantity ?? 1;
      const silent = options?.silent ?? false;
      const offerOverride = options?.offerOverride;
      const fulfillmentSelection = options?.fulfillmentSelection;
      const selectedSize = options?.selectedSize ?? null;
      const selectedOptions = options?.selectedOptions ?? [];
      const unitPrice =
        options?.unitPrice ??
        calculateUnitPrice({
          menuItem,
          selectedSize,
          selectedOptions,
        });
      const lineItemId = buildLineItemId({
        menuItemId: menuItem.id,
        selectedSizeId: selectedSize?.id ?? null,
        selectedOptions,
      });
      setCart(current => {
        const locationId = menuItem.restaurant_location_id ?? null;
        const locationName =
          menuItem.restaurant_location_name ?? restaurantName;
        if (
          current.restaurantId &&
          (current.restaurantId !== restaurantId ||
            current.restaurantLocationId !== locationId)
        ) {
          setPendingCartReplacement({
            menuItem,
            restaurantId,
            restaurantName,
            restaurantLocationId: locationId ?? '',
            restaurantLocationName: locationName,
            selectedPersonalizedOffer: getOfferForRestaurant(
              offerOverride ?? selectedPersonalizedOfferRef.current,
              restaurantId,
              locationId,
            ),
            fulfillmentSelection,
            quantity,
            selectedSize,
            selectedOptions,
            unitPrice,
          });
          return current;
        }

        const existing = current.items.find(item => item.id === lineItemId);
        const items = existing
          ? current.items.map(item =>
              item.id === lineItemId
                ? { ...item, quantity: item.quantity + quantity }
                : item,
            )
          : [
              ...current.items,
              {
                id: lineItemId,
                menuItem,
                quantity,
                selectedSize,
                selectedOptions,
                unitPrice,
              },
            ];

        if (!existing && !silent) {
          pushToast(
            'Added to cart',
            `${menuItem.name} is waiting in your cart.`,
            'success',
          );
        }
        return {
          restaurantId,
          restaurantName,
          restaurantLocationId: locationId,
          restaurantLocationName: locationName,
          fulfillmentType:
            fulfillmentSelection?.fulfillmentType ??
            (current.restaurantId === restaurantId &&
            current.restaurantLocationId === locationId
              ? current.fulfillmentType
              : 'DELIVERY'),
          scheduleType:
            fulfillmentSelection?.scheduleType ??
            (current.restaurantId === restaurantId &&
            current.restaurantLocationId === locationId
              ? current.scheduleType
              : 'ASAP'),
          scheduledAt:
            fulfillmentSelection?.scheduledAt ??
            (current.restaurantId === restaurantId &&
            current.restaurantLocationId === locationId
              ? current.scheduledAt
              : new Date().toISOString()),
          items,
        };
      });
    },
    [getOfferForRestaurant, pushToast, selectedPersonalizedOfferRef],
  );

  const addToCart = useCallback(
    (
      menuItem: MenuItem,
      restaurantId: string,
      restaurantName: string,
      options?: {
        quantity?: number;
        silent?: boolean;
        fulfillmentSelection?: FulfillmentSelection;
        selectedSize?: CartSelectedSize | null;
        selectedOptions?: CartSelectedOption[];
        unitPrice?: number;
      },
    ) => {
      performAddToCart(menuItem, restaurantId, restaurantName, options);
    },
    [performAddToCart],
  );

  const requestAddToCart = useCallback(
    async (
      menuItem: MenuItem,
      restaurantId: string,
      restaurantName: string,
      options?: {
        quantity?: number;
        silent?: boolean;
        fulfillmentSelection?: FulfillmentSelection;
        selectedSize?: CartSelectedSize | null;
        selectedOptions?: CartSelectedOption[];
        unitPrice?: number;
      },
    ) => {
      const quantity = options?.quantity ?? 1;
      const silent = options?.silent ?? false;
      const fulfillmentSelection = options?.fulfillmentSelection;
      const selectedSize = options?.selectedSize ?? null;
      const selectedOptions = options?.selectedOptions ?? [];
      const unitPrice = options?.unitPrice;

      if (!tokenRef.current) {
        performAddToCart(menuItem, restaurantId, restaurantName, {
          quantity,
          silent,
          fulfillmentSelection,
          selectedSize,
          selectedOptions,
          unitPrice,
        });
        return;
      }

      const currentOffer = getOfferForRestaurant(
        selectedPersonalizedOfferRef.current,
        restaurantId,
        menuItem.restaurant_location_id ?? null,
      );
      if (currentOffer) {
        performAddToCart(menuItem, restaurantId, restaurantName, {
          quantity,
          silent,
          offerOverride: currentOffer,
          fulfillmentSelection,
          selectedSize,
          selectedOptions,
          unitPrice,
        });
        return;
      }
      performAddToCart(menuItem, restaurantId, restaurantName, {
        quantity,
        silent,
        fulfillmentSelection,
        selectedSize,
        selectedOptions,
        unitPrice,
      });
    },
    [
      getOfferForRestaurant,
      performAddToCart,
      selectedPersonalizedOfferRef,
      tokenRef,
    ],
  );

  const setCartFulfillmentSelection = useCallback(
    (input: {
      restaurantId?: string | null;
      restaurantName?: string | null;
      restaurantLocationId?: string | null;
      restaurantLocationName?: string | null;
      fulfillmentType: CartFulfillmentType;
      scheduleType: OrderScheduleType;
      scheduledAt: string | null;
    }) => {
      setCart(current => {
        return {
          ...current,
          restaurantId: input.restaurantId ?? current.restaurantId,
          restaurantName: input.restaurantName ?? current.restaurantName,
          restaurantLocationId:
            input.restaurantLocationId ?? current.restaurantLocationId,
          restaurantLocationName:
            input.restaurantLocationName ?? current.restaurantLocationName,
          fulfillmentType: input.fulfillmentType,
          scheduleType: input.scheduleType,
          scheduledAt:
            input.scheduleType === 'SCHEDULED'
              ? input.scheduledAt
              : input.scheduledAt ?? new Date().toISOString(),
        };
      });
    },
    [],
  );

  const setCartFulfillmentType = useCallback((value: CartFulfillmentType) => {
    setCart(current => {
      if (!current.restaurantId || current.fulfillmentType === value) {
        return current;
      }
      const nextSelection = buildDefaultFulfillmentSelection(value);
      return {
        ...current,
        fulfillmentType: nextSelection.fulfillmentType,
        scheduleType: nextSelection.scheduleType,
        scheduledAt: nextSelection.scheduledAt,
      };
    });
  }, []);

  const updateCartQuantity = useCallback(
    (cartItemId: string, nextQuantity: number) => {
      setCart(current => {
        const matchedCartItem =
          current.items.find(item => item.id === cartItemId) ??
          current.items.find(item => item.menuItem.id === cartItemId) ??
          null;
        if (!matchedCartItem) {
          return current;
        }
        const items = current.items
          .map(item =>
            item.id === matchedCartItem.id
              ? { ...item, quantity: Math.max(nextQuantity, 0) }
              : item,
          )
          .filter(item => item.quantity > 0);

        if (items.length === 0) {
          setSelectedPersonalizedOfferState(null);
          return emptyCart;
        }
        return { ...current, items };
      });
    },
    [],
  );

  const clearCart = useCallback(() => {
    setCart(emptyCart);
    setSelectedPersonalizedOfferState(null);
    setPendingOfferPrompt(null);
    dismissedOfferPromptKeysRef.current.clear();
  }, []);

  const dismissCartReplacement = useCallback(() => {
    setPendingCartReplacement(null);
  }, []);

  const confirmCartReplacement = useCallback(() => {
    const pendingCartReplacement = pendingCartReplacementRef.current;
    if (!pendingCartReplacement) {
      return;
    }

    setCart({
      restaurantId: pendingCartReplacement.restaurantId,
      restaurantName: pendingCartReplacement.restaurantName,
      restaurantLocationId: pendingCartReplacement.restaurantLocationId,
      restaurantLocationName: pendingCartReplacement.restaurantLocationName,
      fulfillmentType:
        pendingCartReplacement.fulfillmentSelection?.fulfillmentType ??
        'DELIVERY',
      scheduleType:
        pendingCartReplacement.fulfillmentSelection?.scheduleType ?? 'ASAP',
      scheduledAt:
        pendingCartReplacement.fulfillmentSelection?.scheduledAt ??
        new Date().toISOString(),
      items: [
        {
          id: buildLineItemId({
            menuItemId: pendingCartReplacement.menuItem.id,
            selectedSizeId: pendingCartReplacement.selectedSize?.id ?? null,
            selectedOptions: pendingCartReplacement.selectedOptions ?? [],
          }),
          menuItem: pendingCartReplacement.menuItem,
          quantity: pendingCartReplacement.quantity ?? 1,
          selectedSize: pendingCartReplacement.selectedSize ?? null,
          selectedOptions: pendingCartReplacement.selectedOptions ?? [],
          unitPrice:
            pendingCartReplacement.unitPrice ??
            calculateUnitPrice({
              menuItem: pendingCartReplacement.menuItem,
              selectedSize: pendingCartReplacement.selectedSize ?? null,
              selectedOptions: pendingCartReplacement.selectedOptions ?? [],
            }),
        },
      ],
    });
    setSelectedPersonalizedOfferState(
      pendingCartReplacement.selectedPersonalizedOffer,
    );
    setPendingCartReplacement(null);
    dismissedOfferPromptKeysRef.current.clear();
    pushToast(
      'Cart updated',
      `${pendingCartReplacement.menuItem.name} is waiting in your cart.`,
      'success',
    );
  }, [pendingCartReplacementRef, pushToast]);

  const dismissPendingOfferPrompt = useCallback(() => {
    setPendingOfferPrompt(null);
  }, []);

  const continuePendingOfferPrompt = useCallback(() => {
    const pendingOfferPrompt = pendingOfferPromptRef.current;
    if (!pendingOfferPrompt) {
      return;
    }
    pendingOfferPrompt.offers.forEach(offer => {
      dismissedOfferPromptKeysRef.current.add(
        buildOfferPromptKey(offer, pendingOfferPrompt.menuItem),
      );
    });
    setPendingOfferPrompt(null);
    setSelectedPersonalizedOfferState(null);
    performAddToCart(
      pendingOfferPrompt.menuItem,
      pendingOfferPrompt.restaurantId,
      pendingOfferPrompt.restaurantName,
      {
        quantity: pendingOfferPrompt.quantity,
        silent: pendingOfferPrompt.silent,
        offerOverride: null,
        fulfillmentSelection: pendingOfferPrompt.fulfillmentSelection,
        selectedSize: pendingOfferPrompt.selectedSize ?? null,
        selectedOptions: pendingOfferPrompt.selectedOptions ?? [],
        unitPrice:
          pendingOfferPrompt.unitPrice != null
            ? Number(pendingOfferPrompt.unitPrice)
            : undefined,
      },
    );
  }, [buildOfferPromptKey, pendingOfferPromptRef, performAddToCart]);

  const applyPendingOfferPrompt = useCallback(
    (offerId: string) => {
      const pendingOfferPrompt = pendingOfferPromptRef.current;
      if (!pendingOfferPrompt) {
        return;
      }
      const selectedOffer =
        pendingOfferPrompt.offers.find(offer => offer.offer_id === offerId) ??
        pendingOfferPrompt.offers[0];
      if (!selectedOffer) {
        return;
      }
      const appliedOffer = toAppliedOffer(selectedOffer);
      setPendingOfferPrompt(null);
      setSelectedPersonalizedOfferState(appliedOffer);
      performAddToCart(
        pendingOfferPrompt.menuItem,
        pendingOfferPrompt.restaurantId,
        pendingOfferPrompt.restaurantName,
        {
          quantity: pendingOfferPrompt.quantity,
          silent: pendingOfferPrompt.silent,
          offerOverride: appliedOffer,
          fulfillmentSelection: pendingOfferPrompt.fulfillmentSelection,
          selectedSize: pendingOfferPrompt.selectedSize ?? null,
          selectedOptions: pendingOfferPrompt.selectedOptions ?? [],
          unitPrice:
            pendingOfferPrompt.unitPrice != null
              ? Number(pendingOfferPrompt.unitPrice)
              : undefined,
        },
      );
    },
    [pendingOfferPromptRef, performAddToCart],
  );

  const setChatSessionId = useCallback((nextValue: string | null) => {
    setChatSessionIdState(nextValue);
  }, []);

  const setSelectedPersonalizedOffer = useCallback(
    (offer: AppliedPersonalizedOffer | null) => {
      setSelectedPersonalizedOfferState(offer);
    },
    [],
  );

  const dismissToast = useCallback((id: number) => {
    setToasts(current => current.filter(toast => toast.id !== id));
  }, []);

  // Every action is identity-stable, so this object is built once and the
  // actions context never notifies a consumer.
  /**
   * Re-resolves the app config after bootstrap gave up.
   *
   * A failure here deliberately leaves any existing config in place: a refresh
   * that cannot reach the backend must never downgrade a build that already
   * knows which app it is.
   */
  const refreshAppConfig = useCallback(async (): Promise<AppConfigStatus> => {
    try {
      const identity = await resolveAppIdentity();
      setAppIdentityHeaders(identity);
      const resolved = await api.getAppConfig();
      void storage.writeAppConfig(resolved);
      setAppConfig(resolved);
      setAppConfigStatus('resolved');
      console.log(
        `[AppConfig] Refreshed: app_key=${resolved.app_key} app_mode=${resolved.app_mode}`,
      );
      return 'resolved';
    } catch (error) {
      console.warn(
        `[AppConfig] Refresh failed: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
      return appConfigStatusRef.current;
    }
  }, [appConfigStatusRef]);

  const actions = useMemo<AppStoreActions>(
    () => ({
      refreshAppConfig,
      setSession,
      updateUser,
      setThemePreference,
      setSelectedLocation,
      savePreferences,
      skipPreferencesOnboarding,
      refreshFavoriteIds,
      toggleFavorite,
      isFavorite,
      isFavoritePending,
      getFavoriteItem,
      logout,
      setSelectedPersonalizedOffer,
      addToCart,
      requestAddToCart,
      setCartFulfillmentType,
      setCartFulfillmentSelection,
      updateCartQuantity,
      clearCart,
      confirmCartReplacement,
      dismissCartReplacement,
      applyPendingOfferPrompt,
      continuePendingOfferPrompt,
      dismissPendingOfferPrompt,
      setChatSessionId,
      pushToast,
      dismissToast,
    }),
    [
      addToCart,
      applyPendingOfferPrompt,
      clearCart,
      confirmCartReplacement,
      continuePendingOfferPrompt,
      dismissCartReplacement,
      dismissPendingOfferPrompt,
      dismissToast,
      getFavoriteItem,
      isFavorite,
      isFavoritePending,
      logout,
      pushToast,
      refreshAppConfig,
      refreshFavoriteIds,
      requestAddToCart,
      savePreferences,
      setCartFulfillmentSelection,
      setCartFulfillmentType,
      setChatSessionId,
      setSelectedLocation,
      setSelectedPersonalizedOffer,
      setSession,
      setThemePreference,
      skipPreferencesOnboarding,
      toggleFavorite,
      updateCartQuantity,
      updateUser,
    ],
  );

  const session = useMemo<SessionValue>(
    () => ({ bootstrapped, appConfig, appConfigStatus, token, user }),
    [appConfig, appConfigStatus, bootstrapped, token, user],
  );

  const preferencesValue = useMemo<PreferencesValue>(
    () => ({ preferences, preferencesOnboardingCompleted }),
    [preferences, preferencesOnboardingCompleted],
  );

  const favorites = useMemo<FavoritesValue>(
    () => ({
      favoriteIds,
      favoritePendingIds,
      favoritesHydrated,
      favoriteVersion,
    }),
    [favoriteIds, favoritePendingIds, favoritesHydrated, favoriteVersion],
  );

  const prompts = useMemo<PromptsValue>(
    () => ({ pendingCartReplacement, pendingOfferPrompt }),
    [pendingCartReplacement, pendingOfferPrompt],
  );

  // Nesting order is irrelevant to correctness; the slices are independent.
  return (
    <AppStoreActionsContext.Provider value={actions}>
      <SessionContext.Provider value={session}>
        <PreferencesContext.Provider value={preferencesValue}>
          <ThemePreferenceContext.Provider value={themePreference}>
            <SelectedLocationContext.Provider value={selectedLocation}>
              <CartContext.Provider value={cart}>
                <SelectedOfferContext.Provider
                  value={selectedPersonalizedOffer}
                >
                  <ChatSessionContext.Provider value={chatSessionId}>
                    <FavoritesContext.Provider value={favorites}>
                      <PromptsContext.Provider value={prompts}>
                        <ToastsContext.Provider value={toasts}>
                          {children}
                        </ToastsContext.Provider>
                      </PromptsContext.Provider>
                    </FavoritesContext.Provider>
                  </ChatSessionContext.Provider>
                </SelectedOfferContext.Provider>
              </CartContext.Provider>
            </SelectedLocationContext.Provider>
          </ThemePreferenceContext.Provider>
        </PreferencesContext.Provider>
      </SessionContext.Provider>
    </AppStoreActionsContext.Provider>
  );
}
