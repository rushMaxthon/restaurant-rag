import {
  AUTH_INVALID_EVENT,
  ApiError,
  api,
} from '../services/api';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';
import type {
  AppliedPersonalizedOffer,
  CartFulfillmentType,
  CartReplacementPrompt,
  CartState,
  FavoriteItem,
  MenuItem,
  PendingOfferPrompt,
  PersonalizedOfferCard,
  ToastMessage,
  User,
  UserPreferences,
} from '../types/app';
import {storage} from '../services/storage';
import {
  buildLineItemId,
  calculateUnitPrice,
} from '../utils/menuItemCustomization';
import {
  AppStoreContext,
  type AddToCartInput,
  type AppStoreValue,
} from './AppStoreContext';

const emptyCart: CartState = {
  restaurantId: null,
  restaurantName: null,
  restaurantLocationId: null,
  restaurantLocationName: null,
  fulfillmentType: 'DELIVERY',
  items: [],
};

function normalizeCartState(value: CartState | null): CartState | null {
  if (!value) {
    return null;
  }

  return {
    restaurantId: value.restaurantId ?? null,
    restaurantName: value.restaurantName ?? null,
    restaurantLocationId: value.restaurantLocationId ?? null,
    restaurantLocationName: value.restaurantLocationName ?? null,
    fulfillmentType: value.fulfillmentType === 'PICKUP' ? 'PICKUP' : 'DELIVERY',
    items: Array.isArray(value.items)
      ? value.items.map((item) => ({
          id:
            item.id
            ?? buildLineItemId({
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
            item.unitPrice
            ?? calculateUnitPrice({
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

function isCustomerUser(user: User): boolean {
  return user.role === 'CUSTOMER';
}

function normalizeFavoriteIds(ids: string[]): string[] {
  return Array.from(new Set(ids));
}

function areFavoriteIdListsEqual(left: string[], right: string[]): boolean {
  if (left.length !== right.length) {
    return false;
  }
  return left.every((value, index) => value === right[index]);
}

export function AppStoreProvider({children}: PropsWithChildren) {
  const storedAuth = typeof window !== 'undefined' ? storage.readAuth() : null;
  const storedCart = typeof window !== 'undefined' ? normalizeCartState(storage.readCart()) : null;
  const storedChatSession = typeof window !== 'undefined' ? storage.readChatSession() : null;
  const storedPendingRedirect =
    typeof window !== 'undefined' ? storage.readPendingAuthRedirect() : null;
  const storedPreferences =
    typeof window !== 'undefined' ? storage.readPreferences() : null;
  const storedSelectedPersonalizedOffer =
    typeof window !== 'undefined' ? storage.readSelectedPersonalizedOffer() : null;
  const storedPreferencesOnboardingCompleted =
    typeof window !== 'undefined'
      ? storage.readPreferencesOnboardingCompleted()
      : false;

  const [token, setToken] = useState<string | null>(storedAuth?.token ?? null);
  const [user, setUser] = useState<User | null>(storedAuth?.user ?? null);
  const [cart, setCart] = useState<CartState>(storedCart ?? emptyCart);
  const [chatSessionId, setChatSessionIdState] = useState<string | null>(storedChatSession);
  const [selectedPersonalizedOffer, setSelectedPersonalizedOfferState] =
    useState<AppliedPersonalizedOffer | null>(storedSelectedPersonalizedOffer);
  const [pendingCartReplacement, setPendingCartReplacement] =
    useState<CartReplacementPrompt | null>(null);
  const [pendingOfferPrompt, setPendingOfferPrompt] =
    useState<PendingOfferPrompt | null>(null);
  const [pendingAuthRedirectPath, setPendingAuthRedirectPathState] = useState<string | null>(
    storedPendingRedirect,
  );
  const [preferences, setPreferencesState] = useState<UserPreferences | null>(storedPreferences);
  const [favoriteIds, setFavoriteIdsState] = useState<string[]>([]);
  const [favoritePendingIds, setFavoritePendingIds] = useState<string[]>([]);
  const [favoritesHydrated, setFavoritesHydrated] = useState(!storedAuth?.token);
  const [favoriteVersion, setFavoriteVersion] = useState(0);
  const [preferencesOnboardingCompleted, setPreferencesOnboardingCompleted] = useState(
    storedPreferencesOnboardingCompleted || Boolean(storedPreferences),
  );
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const toastIdRef = useRef(1);
  const cartRef = useRef<CartState>(storedCart ?? emptyCart);
  const favoriteIdsRef = useRef<Set<string>>(new Set());
  const favoritePendingIdsRef = useRef<Set<string>>(new Set());
  const dismissedOfferPromptKeysRef = useRef<Set<string>>(new Set());

  const commitFavoriteIds = useCallback((nextIds: string[]) => {
    const normalized = normalizeFavoriteIds(nextIds).sort();
    if (areFavoriteIdListsEqual(normalized, [...favoriteIdsRef.current].sort())) {
      favoriteIdsRef.current = new Set(normalized);
      setFavoriteIdsState(normalized);
      return;
    }
    favoriteIdsRef.current = new Set(normalized);
    setFavoriteIdsState(normalized);
    setFavoriteVersion((current) => current + 1);
  }, []);

  useEffect(() => {
    storage.writeAuth(token && user ? {token, user} : null);
  }, [token, user]);

  useEffect(() => {
    storage.writeCart(cart);
  }, [cart]);

  useEffect(() => {
    cartRef.current = cart;
  }, [cart]);

  useEffect(() => {
    favoriteIdsRef.current = new Set(favoriteIds);
  }, [favoriteIds]);

  useEffect(() => {
    favoritePendingIdsRef.current = new Set(favoritePendingIds);
  }, [favoritePendingIds]);

  useEffect(() => {
    storage.writeChatSession(chatSessionId);
  }, [chatSessionId]);

  useEffect(() => {
    storage.writePendingAuthRedirect(pendingAuthRedirectPath);
  }, [pendingAuthRedirectPath]);

  useEffect(() => {
    storage.writePreferences(preferences);
  }, [preferences]);

  useEffect(() => {
    storage.writeSelectedPersonalizedOffer(selectedPersonalizedOffer);
  }, [selectedPersonalizedOffer]);

  useEffect(() => {
    storage.writePreferencesOnboardingCompleted(preferencesOnboardingCompleted);
  }, [preferencesOnboardingCompleted]);

  const pushToast = useCallback((title: string, description: string, tone: ToastMessage['tone'] = 'info') => {
    const id = toastIdRef.current;
    toastIdRef.current += 1;
    const nextToast: ToastMessage = {id, title, description, tone};
    setToasts((current) => [...current, nextToast]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 3200);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const getOfferForRestaurant = useCallback((
    offer: AppliedPersonalizedOffer | null,
    restaurantId: string,
    locationId: string | null,
  ): AppliedPersonalizedOffer | null => {
    if (!offer || offer.restaurantId !== restaurantId) {
      return null;
    }
    if (
      offer.offerRestaurantLocationId
      && offer.offerRestaurantLocationId !== locationId
    ) {
      return null;
    }
    return offer;
  }, []);

  useEffect(() => {
    let active = true;

    async function hydrateRemotePreferences() {
      if (!token) {
        return;
      }

      try {
        const remotePreferences = await api.getUserPreferences(token);
        if (!active) {
          return;
        }
        setPreferencesState((current) => mergePreferences(current, remotePreferences));
        setPreferencesOnboardingCompleted(true);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) {
          if (!active) {
            return;
          }
          pushToast(
            'Preferences sync delayed',
            error instanceof Error ? error.message : 'Unable to load saved preferences.',
            'info',
          );
        }
      }
    }

    void hydrateRemotePreferences();
    return () => {
      active = false;
    };
  }, [pushToast, token]);

  const refreshFavoriteIds = useCallback(async () => {
    if (!token || !user) {
      commitFavoriteIds([]);
      setFavoritePendingIds([]);
      setFavoritesHydrated(true);
      return;
    }

    const ids = await api.getFavoriteIds(token);
    commitFavoriteIds(ids);
    setFavoritesHydrated(true);
  }, [commitFavoriteIds, token, user]);

  useEffect(() => {
    let active = true;

    async function hydrateFavorites() {
      if (!token || !user) {
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
        pushToast(
          'Favorites sync delayed',
          error instanceof Error ? error.message : 'Unable to refresh your favorites right now.',
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
  }, [commitFavoriteIds, pushToast, token, user]);

  useEffect(() => {
    const handleAuthInvalid = () => {
      if (!token || !user) {
        return;
      }
      setToken(null);
      setUser(null);
      setChatSessionIdState(null);
      const id = toastIdRef.current;
      toastIdRef.current += 1;
      setToasts((current) => [
        ...current,
        {
          id,
          title: 'Session expired',
          description: 'Please sign in again to continue with personalized features.',
          tone: 'info',
        },
      ]);
      window.setTimeout(() => {
        setToasts((current) => current.filter((toast) => toast.id !== id));
      }, 3200);
    };

    window.addEventListener(AUTH_INVALID_EVENT, handleAuthInvalid);
    return () => {
      window.removeEventListener(AUTH_INVALID_EVENT, handleAuthInvalid);
    };
  }, [token, user]);

  const setSession = useCallback(async (nextToken: string, nextUser: User) => {
    if (!isCustomerUser(nextUser)) {
      throw new ApiError(
        'Admin/Owner accounts cannot access the customer app.',
        403,
      );
    }

    setToken(nextToken);
    setUser(nextUser);
    if (nextUser.default_address && cart.items.length === 0) {
      setCart((current) => ({...current}));
    }

    if (preferences) {
      try {
        const syncedPreferences = await api.updateUserPreferences(nextToken, preferences);
        setPreferencesState(syncedPreferences);
        setPreferencesOnboardingCompleted(true);
      } catch (error) {
        pushToast(
          'Preferences saved locally',
          error instanceof Error ? error.message : 'Unable to sync preferences right now.',
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
      if (!(error instanceof ApiError && error.status === 404)) {
        pushToast(
          'Profile sync delayed',
          error instanceof Error ? error.message : 'Unable to load saved preferences.',
          'info',
        );
      }
    }
  }, [cart.items.length, preferences, pushToast]);

  const updateUser = useCallback((nextUser: User) => {
    setUser(nextUser);
  }, []);

  const savePreferences = useCallback(async (
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

    if (!token || !nextPreferences || options.sync === false) {
      return;
    }

    try {
      const syncedPreferences = await api.updateUserPreferences(token, nextPreferences);
      setPreferencesState(syncedPreferences);
    } catch (error) {
      pushToast(
        'Preferences saved locally',
        error instanceof Error ? error.message : 'Unable to sync preferences right now.',
        'info',
      );
      throw error;
    }
  }, [pushToast, token]);

  const skipPreferencesOnboarding = useCallback(() => {
    setPreferencesOnboardingCompleted(true);
  }, []);

  const isFavorite = useCallback((menuItemId: string) => favoriteIdsRef.current.has(menuItemId), []);

  const isFavoritePending = useCallback(
    (menuItemId: string) => favoritePendingIdsRef.current.has(menuItemId),
    [],
  );

  const getFavoriteItem = useCallback(async (menuItemId: string): Promise<FavoriteItem | null> => {
    if (!token) {
      return null;
    }
    const items = await api.getFavorites(token);
    return items.find((item) => item.id === menuItemId) ?? null;
  }, [token]);

  const toggleFavorite = useCallback(async (
    input: {
      menuItemId: string;
      shouldFavorite?: boolean;
    },
  ) => {
    if (!token || !user) {
      throw new ApiError('Please login to continue.', 401);
    }

    if (favoritePendingIdsRef.current.has(input.menuItemId)) {
      return favoriteIdsRef.current.has(input.menuItemId);
    }

    const previousIds = [...favoriteIdsRef.current];
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
        : previousIds.filter((menuItemId) => menuItemId !== input.menuItemId),
    );

    try {
      if (nextFavorite) {
        await api.addFavorite(token, input.menuItemId);
      } else {
        await api.removeFavorite(token, input.menuItemId);
      }
      return nextFavorite;
    } catch (error) {
      commitFavoriteIds(previousIds);
      throw error;
    } finally {
      favoritePendingIdsRef.current.delete(input.menuItemId);
      setFavoritePendingIds(Array.from(favoritePendingIdsRef.current));
    }
  }, [commitFavoriteIds, token, user]);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setChatSessionIdState(null);
    setSelectedPersonalizedOfferState(null);
    setPendingCartReplacement(null);
    setPendingOfferPrompt(null);
    setPendingAuthRedirectPathState(null);
    commitFavoriteIds([]);
    setFavoritePendingIds([]);
    setFavoritesHydrated(true);
    dismissedOfferPromptKeysRef.current.clear();
  }, [commitFavoriteIds]);

  function toAppliedOffer(offer: PersonalizedOfferCard): AppliedPersonalizedOffer {
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

  const buildOfferPromptKey = useCallback((
    offer: PersonalizedOfferCard,
    menuItem: MenuItem,
  ) => `${offer.offer_id}:${offer.restaurant_id}:${menuItem.restaurant_location_id ?? ''}:${menuItem.id}`, []);

  const performAddToCart = useCallback(({
    menuItem,
    restaurantId,
    restaurantName,
    restaurantLocationId,
    restaurantLocationName,
    quantity = 1,
    silent = false,
    offerOverride,
    selectedSize = null,
    selectedOptions = [],
    unitPrice,
  }: AddToCartInput & {offerOverride?: AppliedPersonalizedOffer | null}) => {
    const currentCart = cartRef.current;
    const resolvedLocationId = restaurantLocationId ?? menuItem.restaurant_location_id ?? null;
    const resolvedLocationName =
      restaurantLocationName ?? menuItem.restaurant_location_name ?? null;
    const resolvedUnitPrice =
      unitPrice
      ?? calculateUnitPrice({
        menuItem,
        selectedSize,
        selectedOptions,
      });
    const lineItemId = buildLineItemId({
      menuItemId: menuItem.id,
      selectedSizeId: selectedSize?.id ?? null,
      selectedOptions,
    });
    if (
      currentCart.restaurantId &&
      (
        currentCart.restaurantId !== restaurantId
        || currentCart.restaurantLocationId !== resolvedLocationId
      )
    ) {
      setPendingCartReplacement({
        menuItem,
        restaurantId,
        restaurantName,
        restaurantLocationId: resolvedLocationId ?? '',
        restaurantLocationName: resolvedLocationName ?? restaurantName,
        selectedPersonalizedOffer: getOfferForRestaurant(
          offerOverride ?? selectedPersonalizedOffer,
          restaurantId,
          resolvedLocationId,
        ),
        quantity,
        selectedSize,
        selectedOptions,
        unitPrice: resolvedUnitPrice,
      });
      return;
    }

    const existing = currentCart.items.find((item) => item.id === lineItemId);
    const nextItems = existing
      ? currentCart.items.map((item) =>
          item.id === lineItemId ? {...item, quantity: item.quantity + quantity} : item,
        )
      : [
          ...currentCart.items,
          {
            id: lineItemId,
            menuItem,
            quantity,
            selectedSize,
            selectedOptions,
            unitPrice: resolvedUnitPrice,
          },
        ];

    const nextCart: CartState = {
      restaurantId,
      restaurantName,
      restaurantLocationId: resolvedLocationId,
      restaurantLocationName: resolvedLocationName,
      fulfillmentType:
        currentCart.restaurantId === restaurantId && currentCart.restaurantLocationId === resolvedLocationId
          ? currentCart.fulfillmentType
          : 'DELIVERY',
      items: nextItems,
    };
    cartRef.current = nextCart;
    setCart(nextCart);

    if (!silent) {
      pushToast('Added to cart', `${menuItem.name} is ready when you are.`, 'success');
    }
  }, [getOfferForRestaurant, pushToast, selectedPersonalizedOffer]);

  const addToCart = useCallback((input: AddToCartInput) => {
    performAddToCart(input);
  }, [performAddToCart]);

  const requestAddToCart = useCallback(async (input: AddToCartInput) => {
    const quantity = input.quantity ?? 1;
    const silent = input.silent ?? false;
    const resolvedLocationId = input.restaurantLocationId ?? input.menuItem.restaurant_location_id ?? null;
    const resolvedLocationName =
      input.restaurantLocationName ?? input.menuItem.restaurant_location_name ?? input.restaurantName;

    if (!token) {
      performAddToCart({...input, quantity, silent});
      return;
    }

    const currentOffer = getOfferForRestaurant(
      selectedPersonalizedOffer,
      input.restaurantId,
      resolvedLocationId,
    );
    if (currentOffer) {
      performAddToCart({
        ...input,
        quantity,
        silent,
        restaurantLocationId: resolvedLocationId,
        restaurantLocationName: resolvedLocationName,
        offerOverride: currentOffer,
      });
      return;
    }

    try {
      const offers = await api.getPersonalizedOffersForContext(token, {
        restaurant_id: input.restaurantId,
        restaurant_location_id: resolvedLocationId,
        menu_item_id: input.menuItem.id,
      });
      if (offers.length === 0) {
        performAddToCart({
          ...input,
          quantity,
          silent,
          restaurantLocationId: resolvedLocationId,
          restaurantLocationName: resolvedLocationName,
        });
        return;
      }

      const visibleOffers = offers.filter(
        (offer) => !dismissedOfferPromptKeysRef.current.has(buildOfferPromptKey(offer, input.menuItem)),
      );
      if (visibleOffers.length === 0) {
        performAddToCart({
          ...input,
          quantity,
          silent,
          restaurantLocationId: resolvedLocationId,
          restaurantLocationName: resolvedLocationName,
        });
        return;
      }

      setPendingOfferPrompt({
        menuItem: input.menuItem,
        restaurantId: input.restaurantId,
        restaurantName: input.restaurantName,
        restaurantLocationId: resolvedLocationId ?? '',
        restaurantLocationName: resolvedLocationName ?? input.restaurantName,
        quantity,
        silent,
        offers: visibleOffers,
      });
    } catch {
      performAddToCart({
        ...input,
        quantity,
        silent,
        restaurantLocationId: resolvedLocationId,
        restaurantLocationName: resolvedLocationName,
      });
    }
  }, [
    buildOfferPromptKey,
    getOfferForRestaurant,
    performAddToCart,
    selectedPersonalizedOffer,
    token,
  ]);

  const setCartFulfillmentType = useCallback((value: CartFulfillmentType) => {
    setCart((current) => {
      if (!current.restaurantId || current.fulfillmentType === value) {
        return current;
      }
      const nextCart: CartState = {
        ...current,
        fulfillmentType: value,
      };
      cartRef.current = nextCart;
      return nextCart;
    });
  }, []);

  const updateCartQuantity = useCallback((cartItemId: string, nextQuantity: number) => {
    const currentCart = cartRef.current;
    const matchedCartItem =
      currentCart.items.find((item) => item.id === cartItemId)
      ?? currentCart.items.find((item) => item.menuItem.id === cartItemId)
      ?? null;
    if (!matchedCartItem) {
      return;
    }
    const nextItems = currentCart.items
      .map((item) =>
        item.id === matchedCartItem.id ? {...item, quantity: Math.max(nextQuantity, 0)} : item,
      )
      .filter((item) => item.quantity > 0);

    const nextCart =
      nextItems.length === 0
        ? emptyCart
        : {
            ...currentCart,
            items: nextItems,
          };
    cartRef.current = nextCart;
    setCart(nextCart);
    if (nextItems.length === 0) {
      setSelectedPersonalizedOfferState(null);
    }
  }, []);

  const clearCart = useCallback(() => {
    cartRef.current = emptyCart;
    setCart(emptyCart);
    setSelectedPersonalizedOfferState(null);
    setPendingCartReplacement(null);
    setPendingOfferPrompt(null);
    dismissedOfferPromptKeysRef.current.clear();
  }, []);

  const dismissCartReplacement = useCallback(() => {
    setPendingCartReplacement(null);
  }, []);

  const confirmCartReplacement = useCallback(() => {
    if (!pendingCartReplacement) {
      return;
    }

    const nextCart: CartState = {
      restaurantId: pendingCartReplacement.restaurantId,
      restaurantName: pendingCartReplacement.restaurantName,
      restaurantLocationId: pendingCartReplacement.restaurantLocationId,
      restaurantLocationName: pendingCartReplacement.restaurantLocationName,
      fulfillmentType: 'DELIVERY',
      items: [
        {
          id: buildLineItemId({
            menuItemId: pendingCartReplacement.menuItem.id,
            selectedSizeId: pendingCartReplacement.selectedSize?.id ?? null,
            selectedOptions: pendingCartReplacement.selectedOptions ?? [],
          }),
          menuItem: pendingCartReplacement.menuItem,
          quantity: pendingCartReplacement.quantity,
          selectedSize: pendingCartReplacement.selectedSize ?? null,
          selectedOptions: pendingCartReplacement.selectedOptions ?? [],
          unitPrice:
            pendingCartReplacement.unitPrice
            ?? calculateUnitPrice({
              menuItem: pendingCartReplacement.menuItem,
              selectedSize: pendingCartReplacement.selectedSize ?? null,
              selectedOptions: pendingCartReplacement.selectedOptions ?? [],
            }),
        },
      ],
    };
    cartRef.current = nextCart;
    setCart(nextCart);
    setSelectedPersonalizedOfferState(
      pendingCartReplacement.selectedPersonalizedOffer,
    );
    setPendingCartReplacement(null);
    dismissedOfferPromptKeysRef.current.clear();
    pushToast(
      'Cart updated',
      `${pendingCartReplacement.menuItem.name} is ready when you are.`,
      'success',
    );
  }, [pendingCartReplacement, pushToast]);

  const dismissPendingOfferPrompt = useCallback(() => {
    setPendingOfferPrompt(null);
  }, []);

  const continuePendingOfferPrompt = useCallback(() => {
    if (!pendingOfferPrompt) {
      return;
    }
    pendingOfferPrompt.offers.forEach((offer) => {
      dismissedOfferPromptKeysRef.current.add(
        buildOfferPromptKey(offer, pendingOfferPrompt.menuItem),
      );
    });
    setPendingOfferPrompt(null);
    setSelectedPersonalizedOfferState(null);
    performAddToCart({
      menuItem: pendingOfferPrompt.menuItem,
      restaurantId: pendingOfferPrompt.restaurantId,
      restaurantName: pendingOfferPrompt.restaurantName,
      restaurantLocationId: pendingOfferPrompt.restaurantLocationId,
      restaurantLocationName: pendingOfferPrompt.restaurantLocationName,
      quantity: pendingOfferPrompt.quantity,
      silent: pendingOfferPrompt.silent,
      offerOverride: null,
      selectedSize: pendingOfferPrompt.selectedSize ?? null,
      selectedOptions: pendingOfferPrompt.selectedOptions ?? [],
      unitPrice:
        pendingOfferPrompt.unitPrice != null
          ? Number(pendingOfferPrompt.unitPrice)
          : undefined,
    });
  }, [buildOfferPromptKey, pendingOfferPrompt, performAddToCart]);

  const applyPendingOfferPrompt = useCallback((offerId: string) => {
    if (!pendingOfferPrompt) {
      return;
    }
    const selectedOffer =
      pendingOfferPrompt.offers.find((offer) => offer.offer_id === offerId)
      ?? pendingOfferPrompt.offers[0];
    if (!selectedOffer) {
      return;
    }
    const appliedOffer = toAppliedOffer(selectedOffer);
    setPendingOfferPrompt(null);
    setSelectedPersonalizedOfferState(appliedOffer);
    performAddToCart({
      menuItem: pendingOfferPrompt.menuItem,
      restaurantId: pendingOfferPrompt.restaurantId,
      restaurantName: pendingOfferPrompt.restaurantName,
      restaurantLocationId: pendingOfferPrompt.restaurantLocationId,
      restaurantLocationName: pendingOfferPrompt.restaurantLocationName,
      quantity: pendingOfferPrompt.quantity,
      silent: pendingOfferPrompt.silent,
      offerOverride: appliedOffer,
      selectedSize: pendingOfferPrompt.selectedSize ?? null,
      selectedOptions: pendingOfferPrompt.selectedOptions ?? [],
      unitPrice:
        pendingOfferPrompt.unitPrice != null
          ? Number(pendingOfferPrompt.unitPrice)
          : undefined,
    });
  }, [pendingOfferPrompt, performAddToCart]);

  const setChatSessionId = useCallback((value: string | null) => {
    setChatSessionIdState(value);
  }, []);

  const setSelectedPersonalizedOffer = useCallback((offer: AppliedPersonalizedOffer | null) => {
    setSelectedPersonalizedOfferState(offer);
  }, []);

  const setPendingAuthRedirectPath = useCallback((path: string | null) => {
    setPendingAuthRedirectPathState(path);
  }, []);

  const consumePendingAuthRedirectPath = useCallback(() => {
    const nextPath = pendingAuthRedirectPath;
    setPendingAuthRedirectPathState(null);
    return nextPath;
  }, [pendingAuthRedirectPath]);

  const value = useMemo<AppStoreValue>(
    () => ({
      token,
      user,
      cart,
      selectedPersonalizedOffer,
      chatSessionId,
      pendingCartReplacement,
      pendingOfferPrompt,
      pendingAuthRedirectPath,
      preferences,
      favoriteIds,
      favoritesHydrated,
      favoritePendingIds,
      favoriteVersion,
      preferencesOnboardingCompleted,
      toasts,
      isAuthenticated: Boolean(token && user),
      setSession,
      updateUser,
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
      updateCartQuantity,
      clearCart,
      confirmCartReplacement,
      dismissCartReplacement,
      applyPendingOfferPrompt,
      continuePendingOfferPrompt,
      dismissPendingOfferPrompt,
      setChatSessionId,
      setPendingAuthRedirectPath,
      consumePendingAuthRedirectPath,
      pushToast,
      dismissToast,
    }),
    [
      cart,
      selectedPersonalizedOffer,
      chatSessionId,
      pendingCartReplacement,
      pendingOfferPrompt,
      pendingAuthRedirectPath,
      preferences,
      favoriteIds,
      favoritesHydrated,
      favoritePendingIds,
      favoriteVersion,
      preferencesOnboardingCompleted,
      toasts,
      token,
      user,
      addToCart,
      requestAddToCart,
      applyPendingOfferPrompt,
      clearCart,
      confirmCartReplacement,
      continuePendingOfferPrompt,
      dismissToast,
      dismissCartReplacement,
      dismissPendingOfferPrompt,
      getFavoriteItem,
      isFavorite,
      isFavoritePending,
      consumePendingAuthRedirectPath,
      logout,
      pushToast,
      refreshFavoriteIds,
      savePreferences,
      setCartFulfillmentType,
      setChatSessionId,
      setSelectedPersonalizedOffer,
      setPendingAuthRedirectPath,
      setSession,
      skipPreferencesOnboarding,
      toggleFavorite,
      updateUser,
      updateCartQuantity,
    ],
  );

  return <AppStoreContext.Provider value={value}>{children}</AppStoreContext.Provider>;
}
