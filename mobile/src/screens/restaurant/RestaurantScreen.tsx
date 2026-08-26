import { SafeAreaView } from 'react-native-safe-area-context';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Animated,
  Easing,
  FlatList,
  Image,
  LayoutAnimation,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  UIManager,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  useFocusEffect,
  useNavigation,
  useRoute,
} from '@react-navigation/native';
import type { RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { ListRenderItem } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import {
  GeneratedComboCard,
  getGeneratedComboCardMetrics,
} from '@components/home/GeneratedComboCard';
import { FulfillmentSelectionSheet } from '@components/FulfillmentSelectionSheet';
import { MenuItemCard } from '@components/MenuItemCard';
import { SkeletonBlock } from '@components/SkeletonBlock';
import { CategoryChips } from '@components/CategoryChips';
import {
  useAppActions,
  useCart,
  useFavoritesState,
  usePreferences,
  useSelectedLocation,
  useSession,
} from '@hooks/useAppStore';
import { useAppForegroundEffect } from '@hooks/useAppForegroundEffect';
import { ApiError, api, placeholderImage } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import { getOfferPalette } from '@components/offers/offerPalette';
import { getRestaurantScopedOffers } from '@components/offers/offerScope';
import type {
  GeneratedCombo,
  FulfillmentSelection,
  MenuItem,
  PersonalizedOfferCard,
  Restaurant,
  RestaurantLocation,
} from '@/types/app';
import type { RootStackParamList } from '@/navigation/AppNavigator';
import { checkAuthAndRedirect } from '@utils/authRedirect';
import { buildMenuItemFromGeneratedComboItem } from '@utils/generatedComboCart';
import {
  formatFulfillmentSelectionLabel,
  getScheduledSlotInvalidMessage,
  getFulfillmentEtaLabel,
  getFulfillmentUnavailableReason,
  isScheduledSlotPresent,
  isFulfillmentAvailableNow,
  isFulfillmentEnabled,
} from '@utils/fulfillment';
import { isCustomizableMenuItem } from '@utils/menuItemCustomization';
import { sortMenuItemsByRecommendationSignal } from '@utils/menuPersonalization';
import { buildPreferencesKey } from '@utils/preferencesKey';

type RestaurantRoute = RouteProp<RootStackParamList, 'Restaurant'>;

function formatCurrency(value: string | number | null | undefined): string {
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return `₹${numeric.toFixed(2)}`;
  }
  return `₹${value ?? '0.00'}`;
}

function getLocationAvailabilityLabel(location: RestaurantLocation): string {
  const pickupEnabled = isFulfillmentEnabled(location, 'PICKUP');
  const deliveryEnabled = isFulfillmentEnabled(location, 'DELIVERY');

  if (pickupEnabled && deliveryEnabled) {
    return 'Pickup • Delivery';
  }
  if (pickupEnabled) {
    return 'Pickup only';
  }
  if (deliveryEnabled) {
    return 'Delivery only';
  }
  return 'Currently unavailable';
}

function formatOfferEndsLabel(expiresAt: string | null): string | null {
  if (!expiresAt) {
    return null;
  }
  return `Ends ${new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
  }).format(new Date(expiresAt))}`;
}

function getOfferIconName(offer: PersonalizedOfferCard): string {
  if (offer.discount_type === 'FREE_DELIVERY') {
    return 'bicycle-outline';
  }
  if (offer.discount_type === 'FLAT') {
    return 'cash-outline';
  }
  return 'pricetag-outline';
}

export function RestaurantScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const { width: screenWidth } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const route = useRoute<RestaurantRoute>();
  const navigation =
    useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const { token, user } = useSession();
  const { preferences } = usePreferences();
  const { favoritesHydrated } = useFavoritesState();
  const customerLocation = useSelectedLocation();
  const cart = useCart();
  const {
    addToCart,
    requestAddToCart,
    isFavorite,
    isFavoritePending,
    pushToast,
    setCartFulfillmentSelection,
    toggleFavorite,
    updateCartQuantity,
  } = useAppActions();
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [generatedCombos, setGeneratedCombos] = useState<GeneratedCombo[]>([]);
  const [menuItems, setMenuItems] = useState<MenuItem[]>([]);
  const [restaurantOffers, setRestaurantOffers] = useState<
    PersonalizedOfferCard[]
  >([]);
  const [offerAvailabilityByItemId, setOfferAvailabilityByItemId] = useState<
    Record<string, boolean>
  >({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState('All');
  const [reloadKey, setReloadKey] = useState(0);
  const [headerElevated, setHeaderElevated] = useState(false);
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(
    null,
  );
  const [selectionDraftsByContext, setSelectionDraftsByContext] = useState<
    Record<string, FulfillmentSelection>
  >({});
  const [selectionDraftsByRestaurant, setSelectionDraftsByRestaurant] =
    useState<Record<string, FulfillmentSelection>>({});
  const [fulfillmentSheetVisible, setFulfillmentSheetVisible] = useState(false);
  const [pendingDeliverySelection, setPendingDeliverySelection] =
    useState<FulfillmentSelection | null>(null);
  const [scheduledSelectionValid, setScheduledSelectionValid] = useState<
    boolean | null
  >(true);
  const [scheduledSelectionReason, setScheduledSelectionReason] = useState<
    string | null
  >(null);
  const [locationSheetMounted, setLocationSheetMounted] = useState(false);
  const lastScrollY = useRef(0);
  const locationSheetAnimation = useRef(new Animated.Value(0)).current;
  const autoPromptedContextsRef = useRef<Set<string>>(new Set());
  const invalidSelectionPromptedContextsRef = useRef<Set<string>>(new Set());
  const autoAdjustedSelectionContextsRef = useRef<Set<string>>(new Set());
  const lastRestaurantRefreshAtRef = useRef(0);
  const selectedLocationIdRef = useRef<string | null>(null);
  const preferencesRef = useRef(preferences);
  const restaurantId = route.params.restaurantId;
  // Preference content, not object identity: the store replaces `preferences`
  // on every bootstrap merge and profile sync, which used to reload the menu.
  const preferencesKey = useMemo(
    () => buildPreferencesKey(preferences),
    [preferences],
  );
  const selectedLocation = useMemo<RestaurantLocation | null>(
    () =>
      restaurant?.locations?.find(
        location => location.id === selectedLocationId,
      ) ??
      restaurant?.locations?.find(
        location => location.is_open && location.is_active,
      ) ??
      restaurant?.locations?.find(location => location.is_active) ??
      null,
    [restaurant?.locations, selectedLocationId],
  );
  const restaurantContextKey = useMemo(
    () =>
      selectedLocation
        ? `${restaurantId}:${selectedLocation.id}`
        : restaurantId,
    [restaurantId, selectedLocation],
  );
  const cartContextMatches = useMemo(
    () =>
      Boolean(
        selectedLocation &&
          cart.restaurantId === restaurantId &&
          cart.restaurantLocationId === selectedLocation.id,
      ),
    [
      cart.restaurantId,
      cart.restaurantLocationId,
      restaurantId,
      selectedLocation,
    ],
  );
  const draftSelection = useMemo(
    () => selectionDraftsByContext[restaurantContextKey] ?? null,
    [restaurantContextKey, selectionDraftsByContext],
  );
  const restaurantDraftSelection = useMemo(
    () => selectionDraftsByRestaurant[restaurantId] ?? null,
    [restaurantId, selectionDraftsByRestaurant],
  );
  const effectiveSelection = useMemo<FulfillmentSelection | null>(() => {
    if (cartContextMatches && cart.restaurantId && cart.restaurantLocationId) {
      return {
        fulfillmentType: cart.fulfillmentType,
        scheduleType: cart.scheduleType,
        scheduledAt: cart.scheduledAt,
      };
    }
    return draftSelection ?? restaurantDraftSelection;
  }, [
    cart.fulfillmentType,
    cart.restaurantId,
    cart.restaurantLocationId,
    cart.scheduledAt,
    cart.scheduleType,
    cartContextMatches,
    draftSelection,
    restaurantDraftSelection,
  ]);
  const customerDeliveryAddress = useMemo(
    () => customerLocation?.address ?? user?.default_address ?? '',
    [customerLocation?.address, user?.default_address],
  );

  const comboCardMetrics = useMemo(
    () => getGeneratedComboCardMetrics(screenWidth),
    [screenWidth],
  );
  const locationOptions = useMemo(
    () => restaurant?.locations ?? [],
    [restaurant?.locations],
  );
  const locationSheetTranslateY = useMemo(
    () =>
      locationSheetAnimation.interpolate({
        inputRange: [0, 1],
        outputRange: [42, 0],
      }),
    [locationSheetAnimation],
  );
  const locationSheetOpacity = useMemo(
    () =>
      locationSheetAnimation.interpolate({
        inputRange: [0, 1],
        outputRange: [0, 1],
      }),
    [locationSheetAnimation],
  );

  useEffect(() => {
    if (
      Platform.OS === 'android' &&
      UIManager.setLayoutAnimationEnabledExperimental
    ) {
      UIManager.setLayoutAnimationEnabledExperimental(true);
    }
  }, []);

  useEffect(() => {
    selectedLocationIdRef.current = selectedLocationId;
  }, [selectedLocationId]);

  useEffect(() => {
    preferencesRef.current = preferences;
  }, [preferences]);

  // Reads the current branch from a ref so switching branches does not change
  // this callback's identity and re-arm the focus effect below.
  const refreshRestaurantSnapshot = React.useCallback(
    async (force: boolean = false) => {
      const now = Date.now();
      if (!force && now - lastRestaurantRefreshAtRef.current < 15000) {
        return;
      }
      lastRestaurantRefreshAtRef.current = now;
      const currentLocationId = selectedLocationIdRef.current;
      const restaurantRow = await api.getRestaurant(restaurantId, token);
      const nextLocationId = restaurantRow.locations?.some(
        location => location.id === currentLocationId,
      )
        ? currentLocationId
        : restaurantRow.locations?.find(
            location => location.is_open && location.is_active,
          )?.id ??
          restaurantRow.locations?.find(location => location.is_active)?.id ??
          null;
      setRestaurant(restaurantRow);
      setSelectedLocationId(nextLocationId);
    },
    [restaurantId, token],
  );

  // Resolves the restaurant and its default branch. The menu, recommendations
  // and combos are loaded exclusively by the branch-scoped effect below, so
  // opening a restaurant no longer fetches that trio twice.
  useEffect(() => {
    let active = true;

    async function loadRestaurantHeader() {
      setLoading(true);
      setError(null);
      setRestaurant(null);
      setGeneratedCombos([]);
      setMenuItems([]);
      setOfferAvailabilityByItemId({});
      setActiveCategory('All');

      try {
        const restaurantRow = await api.getRestaurant(restaurantId, token);
        if (!active) {
          return;
        }
        const defaultLocation =
          restaurantRow.locations?.find(
            location => location.is_open && location.is_active,
          ) ??
          restaurantRow.locations?.find(location => location.is_active) ??
          null;
        lastRestaurantRefreshAtRef.current = Date.now();
        setRestaurant(restaurantRow);
        setSelectedLocationId(defaultLocation?.id ?? null);
      } catch (nextError) {
        if (!active) {
          return;
        }
        const message =
          nextError instanceof Error
            ? nextError.message
            : 'Unable to load menu.';
        setError(message);
        pushToast('Menu unavailable', message, 'error');
        setLoading(false);
      }
    }

    loadRestaurantHeader();

    return () => {
      active = false;
    };
  }, [pushToast, restaurantId, token, reloadKey]);

  useFocusEffect(
    React.useCallback(() => {
      refreshRestaurantSnapshot().catch(() => undefined);
      return undefined;
    }, [refreshRestaurantSnapshot]),
  );

  useAppForegroundEffect(() => {
    refreshRestaurantSnapshot().catch(() => undefined);
  });

  // Keyed on branch and restaurant *ids*, not on the objects: the focus and
  // foreground refreshes replace the `restaurant` object with an equivalent
  // one, which used to re-run this whole bundle every time.
  useEffect(() => {
    let active = true;
    const activeRestaurantId = restaurant?.id ?? null;
    const activeLocationId = selectedLocation?.id ?? null;

    async function loadLocationScopedContent() {
      if (!activeRestaurantId) {
        return;
      }
      if (!activeLocationId) {
        // Restaurant resolved but has no bookable branch - nothing to load.
        setLoading(false);
        return;
      }

      try {
        const [items, recommendationRows, comboRows] = await Promise.all([
          api.getMenuItems(activeRestaurantId, token, activeLocationId),
          api
            .getRecommendationsForContext({
              token,
              preferences: preferencesRef.current,
            })
            .catch(() => []),
          api
            .getRestaurantGeneratedCombos(
              activeRestaurantId,
              8,
              activeLocationId,
            )
            .catch(() => []),
        ]);
        if (!active) {
          return;
        }
        LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
        setGeneratedCombos(comboRows);
        setMenuItems(
          sortMenuItemsByRecommendationSignal(
            items,
            recommendationRows.filter(
              item => item.restaurant_id === activeRestaurantId,
            ),
          ),
        );
        setActiveCategory('All');
      } catch (nextError) {
        if (!active) {
          return;
        }
        pushToast(
          'Branch unavailable',
          nextError instanceof Error
            ? nextError.message
            : 'Unable to load this branch right now.',
          'error',
        );
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    loadLocationScopedContent().catch(() => undefined);
    return () => {
      active = false;
    };
  }, [
    preferencesKey,
    pushToast,
    restaurant?.id,
    selectedLocation?.id,
    token,
    reloadKey,
  ]);

  useEffect(() => {
    let active = true;

    async function loadOfferAvailability() {
      if (!token || menuItems.length === 0) {
        setOfferAvailabilityByItemId({});
        return;
      }

      try {
        const rows = await api.getPersonalizedOfferAvailabilityForItems(token, {
          restaurant_id: restaurantId,
          restaurant_location_id: selectedLocation?.id ?? null,
          menu_item_ids: menuItems.map(item => item.id),
        });
        if (!active) {
          return;
        }
        setOfferAvailabilityByItemId(
          Object.fromEntries(
            rows.map(row => [row.menu_item_id, row.has_offer]),
          ),
        );
      } catch {
        if (active) {
          setOfferAvailabilityByItemId({});
        }
      }
    }

    loadOfferAvailability().catch(() => undefined);
    return () => {
      active = false;
    };
  }, [menuItems, restaurantId, selectedLocation?.id, token]);

  const categories = useMemo(
    () => ['All', ...Array.from(new Set(menuItems.map(item => item.category)))],
    [menuItems],
  );

  const visibleItems = useMemo(
    () =>
      menuItems.filter(
        item =>
          activeCategory === 'All' ||
          !activeCategory ||
          item.category === activeCategory,
      ),
    [activeCategory, menuItems],
  );

  const cartQuantities = useMemo(
    () =>
      cart.items.reduce((map, item) => {
        map.set(
          item.menuItem.id,
          (map.get(item.menuItem.id) ?? 0) + item.quantity,
        );
        return map;
      }, new Map<string, number>()),
    [cart.items],
  );

  const redirectToRestaurant = useMemo(
    () => ({
      screen: 'Restaurant' as const,
      params: {
        restaurantId,
        restaurantName: restaurant?.name ?? route.params.restaurantName,
      },
    }),
    [restaurant?.name, restaurantId, route.params.restaurantName],
  );
  const deliveryEnabled = useMemo(
    () => isFulfillmentEnabled(selectedLocation, 'DELIVERY'),
    [selectedLocation],
  );

  useEffect(() => {
    if (!token) {
      setRestaurantOffers([]);
      return;
    }

    let active = true;
    api
      .getPersonalizedOffers(token, 8)
      .then(offers => {
        if (!active) {
          return;
        }
        const filteredOffers = getRestaurantScopedOffers(
          offers,
          restaurantId,
          selectedLocation?.id ?? null,
        );
        setRestaurantOffers(previous => {
          const previousSerialized = JSON.stringify(previous);
          const nextSerialized = JSON.stringify(filteredOffers);
          return previousSerialized === nextSerialized
            ? previous
            : filteredOffers;
        });
      })
      .catch(error => {
        console.warn('restaurant offers load failed', error);
        if (active) {
          setRestaurantOffers([]);
        }
      });

    return () => {
      active = false;
    };
  }, [restaurantId, selectedLocation?.id, token]);
  const pickupEnabled = useMemo(
    () => isFulfillmentEnabled(selectedLocation, 'PICKUP'),
    [selectedLocation],
  );
  const locationOrderingUnavailable = !deliveryEnabled && !pickupEnabled;
  const selectedFulfillmentType =
    effectiveSelection?.fulfillmentType ?? 'DELIVERY';
  const selectedScheduledAt = effectiveSelection?.scheduledAt ?? null;

  useEffect(() => {
    if (
      !selectedLocation ||
      !effectiveSelection ||
      effectiveSelection.scheduleType !== 'SCHEDULED' ||
      !selectedScheduledAt
    ) {
      setScheduledSelectionValid(true);
      setScheduledSelectionReason(null);
      return;
    }

    let active = true;
    setScheduledSelectionValid(null);
    setScheduledSelectionReason(null);

    api
      .getRestaurantLocationScheduleOptions(
        restaurantId,
        selectedLocation.id,
        selectedFulfillmentType,
        token,
      )
      .then(response => {
        if (!active) {
          return;
        }

        const exists = isScheduledSlotPresent(response, selectedScheduledAt);

        setScheduledSelectionValid(exists);
        setScheduledSelectionReason(
          exists ? null : getScheduledSlotInvalidMessage(response),
        );
      })
      .catch(validationError => {
        if (!active) {
          return;
        }
        setScheduledSelectionValid(false);
        setScheduledSelectionReason(
          validationError instanceof Error
            ? validationError.message
            : 'Unable to validate the selected slot for this branch.',
        );
      });

    return () => {
      active = false;
    };
  }, [
    effectiveSelection,
    restaurantId,
    selectedFulfillmentType,
    selectedLocation,
    selectedScheduledAt,
    token,
  ]);

  const selectionInvalidReason = useMemo(() => {
    if (!effectiveSelection || !selectedLocation) {
      return null;
    }

    if (!isFulfillmentEnabled(selectedLocation, selectedFulfillmentType)) {
      return (
        getFulfillmentUnavailableReason(
          selectedLocation,
          selectedFulfillmentType,
        ) ??
        `This branch does not support ${
          selectedFulfillmentType === 'DELIVERY' ? 'delivery' : 'pickup'
        }.`
      );
    }

    if (effectiveSelection.scheduleType === 'SCHEDULED') {
      return scheduledSelectionValid === false
        ? scheduledSelectionReason
        : null;
    }

    return isFulfillmentAvailableNow(selectedLocation, selectedFulfillmentType)
      ? null
      : getFulfillmentUnavailableReason(
          selectedLocation,
          selectedFulfillmentType,
        ) ?? 'This branch cannot fulfill the selected order type right now.';
  }, [
    effectiveSelection,
    scheduledSelectionReason,
    scheduledSelectionValid,
    selectedFulfillmentType,
    selectedLocation,
  ]);
  const activeFulfillmentAvailable = useMemo(
    () =>
      effectiveSelection?.scheduleType === 'SCHEDULED'
        ? scheduledSelectionValid === true &&
          Boolean(effectiveSelection.scheduledAt)
        : isFulfillmentAvailableNow(selectedLocation, selectedFulfillmentType),
    [
      effectiveSelection,
      scheduledSelectionValid,
      selectedFulfillmentType,
      selectedLocation,
    ],
  );
  const activeFulfillmentReason = useMemo(
    () =>
      effectiveSelection?.scheduleType === 'SCHEDULED'
        ? scheduledSelectionReason
        : getFulfillmentUnavailableReason(
            selectedLocation,
            selectedFulfillmentType,
          ),
    [
      effectiveSelection?.scheduleType,
      scheduledSelectionReason,
      selectedFulfillmentType,
      selectedLocation,
    ],
  );

  // Writes to the store from inside an effect, so it is worth being explicit
  // about why it settles: the write switches the selection to a type this
  // branch *does* support, so the next pass takes the `selectionSupported`
  // early return. The ref is a de-duplicator for the toast, not the thing that
  // stops the loop. Both store actions it calls are identity-stable, so an
  // unrelated store change no longer re-runs this effect at all.
  const loadedRestaurantId = restaurant?.id ?? null;
  const loadedRestaurantName = restaurant?.name ?? null;

  useEffect(() => {
    if (!selectedLocation || !effectiveSelection) {
      return;
    }

    const selectionSupported = isFulfillmentEnabled(
      selectedLocation,
      selectedFulfillmentType,
    );

    if (selectionSupported || locationOrderingUnavailable) {
      autoAdjustedSelectionContextsRef.current.delete(restaurantContextKey);
      return;
    }

    const nextFulfillmentType = deliveryEnabled ? 'DELIVERY' : 'PICKUP';
    const adjustmentKey = `${restaurantContextKey}:${selectedFulfillmentType}`;
    if (autoAdjustedSelectionContextsRef.current.has(adjustmentKey)) {
      return;
    }

    autoAdjustedSelectionContextsRef.current.add(adjustmentKey);
    const nextSelection: FulfillmentSelection = {
      fulfillmentType: nextFulfillmentType,
      scheduleType: 'ASAP',
      scheduledAt: new Date().toISOString(),
    };
    setSelectionDraftsByContext(current => ({
      ...current,
      [restaurantContextKey]: nextSelection,
    }));
    setSelectionDraftsByRestaurant(current => ({
      ...current,
      [restaurantId]: nextSelection,
    }));
    if (loadedRestaurantId && (cartContextMatches || cart.items.length === 0)) {
      setCartFulfillmentSelection({
        restaurantId: loadedRestaurantId,
        restaurantName: loadedRestaurantName,
        restaurantLocationId: selectedLocation.id,
        restaurantLocationName: selectedLocation.branch_name,
        ...nextSelection,
      });
    }
    pushToast(
      selectedFulfillmentType === 'DELIVERY'
        ? 'Delivery unavailable'
        : 'Pickup unavailable',
      selectedFulfillmentType === 'DELIVERY'
        ? 'Delivery is not available at this location right now. Switched to Pickup.'
        : 'Pickup is not available at this location right now. Switched to Delivery.',
      'info',
    );
  }, [
    cartContextMatches,
    cart.items.length,
    deliveryEnabled,
    effectiveSelection,
    locationOrderingUnavailable,
    pickupEnabled,
    pushToast,
    // Only the two fields this effect reads, so a focus refresh that replaces
    // the restaurant object with an equivalent one does not re-run it.
    loadedRestaurantId,
    loadedRestaurantName,
    restaurantContextKey,
    restaurantId,
    selectedLocation,
    selectedFulfillmentType,
    setCartFulfillmentSelection,
  ]);

  const openFulfillmentSheet = React.useCallback(() => {
    if (!selectedLocation) {
      return;
    }
    if (locationOrderingUnavailable) {
      pushToast(
        'Location unavailable',
        'This location is currently unavailable for ordering.',
        'info',
      );
      return;
    }
    autoPromptedContextsRef.current.add(restaurantContextKey);
    setFulfillmentSheetVisible(true);
  }, [
    locationOrderingUnavailable,
    pushToast,
    restaurantContextKey,
    selectedLocation,
  ]);

  const handleProtectedAdd = React.useCallback(
    (menuItem: MenuItem) => {
      if (
        !checkAuthAndRedirect({
          token,
          navigation,
          pushToast,
          redirectTo: redirectToRestaurant,
        })
      ) {
        return;
      }
      if (!effectiveSelection) {
        openFulfillmentSheet();
        return;
      }
      if (!activeFulfillmentAvailable) {
        pushToast(
          effectiveSelection.fulfillmentType === 'DELIVERY'
            ? 'Delivery unavailable'
            : 'Pickup unavailable',
          activeFulfillmentReason ??
            'This branch cannot fulfill the selected order type right now.',
          'info',
        );
        return;
      }

      if (isCustomizableMenuItem(menuItem)) {
        navigation.navigate('MenuItemDetail', {
          itemId: menuItem.id,
          restaurantId,
          restaurantName: restaurant?.name ?? route.params.restaurantName,
        });
        return;
      }

      if (restaurant) {
        requestAddToCart(menuItem, restaurant.id, restaurant.name, {
          fulfillmentSelection: effectiveSelection,
        }).catch(() => undefined);
      }
    },
    [
      effectiveSelection,
      activeFulfillmentAvailable,
      activeFulfillmentReason,
      navigation,
      openFulfillmentSheet,
      pushToast,
      redirectToRestaurant,
      requestAddToCart,
      restaurant,
      token,
    ],
  );

  const handleProtectedCartOpen = React.useCallback(() => {
    if (
      !checkAuthAndRedirect({
        token,
        navigation,
        pushToast,
        redirectTo: { screen: 'Cart' },
      })
    ) {
      return;
    }

    navigation.navigate('Cart');
  }, [navigation, pushToast, token]);

  // Reads quantities from a ref: depending on the `cartQuantities` map made
  // this callback change on every cart mutation, which changed `renderMenuItem`
  // and defeated `MenuItemCard`'s memo comparator for every visible row.
  const cartQuantitiesRef = useRef(cartQuantities);
  useEffect(() => {
    cartQuantitiesRef.current = cartQuantities;
  }, [cartQuantities]);

  const handleDecreaseQuantity = React.useCallback(
    (menuItemId: string) => {
      updateCartQuantity(
        menuItemId,
        (cartQuantitiesRef.current.get(menuItemId) ?? 0) - 1,
      );
    },
    [updateCartQuantity],
  );

  const handleOpenMenuItem = React.useCallback(
    (itemId: string) => {
      navigation.navigate('MenuItemDetail', { itemId });
    },
    [navigation],
  );

  useEffect(() => {
    if (loading || !restaurant || !selectedLocation) {
      return;
    }

    if (!effectiveSelection) {
      if (autoPromptedContextsRef.current.has(restaurantContextKey)) {
        return;
      }

      autoPromptedContextsRef.current.add(restaurantContextKey);
      setFulfillmentSheetVisible(true);
      return;
    }

    if (!selectionInvalidReason) {
      invalidSelectionPromptedContextsRef.current.delete(restaurantContextKey);
      return;
    }

    if (locationOrderingUnavailable) {
      invalidSelectionPromptedContextsRef.current.delete(restaurantContextKey);
      return;
    }

    if (
      effectiveSelection.scheduleType === 'SCHEDULED' &&
      scheduledSelectionValid == null
    ) {
      return;
    }

    if (effectiveSelection.scheduleType !== 'SCHEDULED') {
      return;
    }

    if (invalidSelectionPromptedContextsRef.current.has(restaurantContextKey)) {
      return;
    }

    invalidSelectionPromptedContextsRef.current.add(restaurantContextKey);
    pushToast('Update order mode', selectionInvalidReason, 'info');
    setFulfillmentSheetVisible(true);
  }, [
    effectiveSelection,
    loading,
    pushToast,
    restaurant,
    restaurantContextKey,
    scheduledSelectionValid,
    selectionInvalidReason,
    locationOrderingUnavailable,
    selectedLocation,
  ]);

  const commitFulfillmentSelection = React.useCallback(
    (selection: FulfillmentSelection) => {
      if (!selectedLocation || !restaurant) {
        return;
      }

      setSelectionDraftsByContext(current => ({
        ...current,
        [restaurantContextKey]: selection,
      }));
      setSelectionDraftsByRestaurant(current => ({
        ...current,
        [restaurantId]: selection,
      }));
      invalidSelectionPromptedContextsRef.current.delete(restaurantContextKey);

      if (cartContextMatches || cart.items.length === 0) {
        setCartFulfillmentSelection({
          restaurantId: restaurant.id,
          restaurantName: restaurant.name,
          restaurantLocationId: selectedLocation.id,
          restaurantLocationName: selectedLocation.branch_name,
          fulfillmentType: selection.fulfillmentType,
          scheduleType: selection.scheduleType,
          scheduledAt: selection.scheduledAt,
        });
      }
    },
    [
      cart.items.length,
      cartContextMatches,
      restaurant,
      restaurantId,
      restaurantContextKey,
      selectedLocation,
      setCartFulfillmentSelection,
    ],
  );

  useEffect(() => {
    if (!pendingDeliverySelection) {
      return;
    }
    if (!customerDeliveryAddress.trim()) {
      return;
    }
    commitFulfillmentSelection(pendingDeliverySelection);
    setPendingDeliverySelection(null);
    setFulfillmentSheetVisible(false);
    pushToast(
      'Delivery ready',
      'Delivery is now selected for this branch.',
      'success',
    );
  }, [
    commitFulfillmentSelection,
    customerDeliveryAddress,
    pendingDeliverySelection,
    pushToast,
  ]);

  const handleConfirmFulfillmentSelection = React.useCallback(
    (selection: FulfillmentSelection) => {
      if (
        selection.fulfillmentType === 'DELIVERY' &&
        !customerDeliveryAddress.trim()
      ) {
        setPendingDeliverySelection(selection);
        setFulfillmentSheetVisible(false);
        pushToast(
          'Add delivery address',
          'Choose where the order should reach you before switching to Delivery.',
          'info',
        );
        navigation.navigate('LocationSelect');
        return;
      }

      commitFulfillmentSelection(selection);
      setPendingDeliverySelection(null);
      setFulfillmentSheetVisible(false);
    },
    [
      commitFulfillmentSelection,
      customerDeliveryAddress,
      navigation,
      pushToast,
    ],
  );

  const openLocationSheet = React.useCallback(() => {
    if (locationOptions.length === 0) {
      return;
    }
    setLocationSheetMounted(true);
    locationSheetAnimation.stopAnimation();
    Animated.timing(locationSheetAnimation, {
      toValue: 1,
      duration: 240,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [locationOptions.length, locationSheetAnimation]);

  const closeLocationSheet = React.useCallback(() => {
    locationSheetAnimation.stopAnimation();
    Animated.timing(locationSheetAnimation, {
      toValue: 0,
      duration: 180,
      easing: Easing.in(Easing.cubic),
      useNativeDriver: true,
    }).start(({ finished }) => {
      if (finished) {
        setLocationSheetMounted(false);
      }
    });
  }, [locationSheetAnimation]);

  const handleSelectLocation = React.useCallback(
    (locationId: string) => {
      setSelectedLocationId(locationId);
      closeLocationSheet();
    },
    [closeLocationSheet],
  );

  const handleToggleFavorite = React.useCallback(
    (item: MenuItem) => {
      if (
        !checkAuthAndRedirect({
          token,
          navigation,
          pushToast,
          redirectTo: redirectToRestaurant,
        })
      ) {
        return;
      }

      toggleFavorite({ menuItemId: item.id })
        .then(nextFavorite => {
          pushToast(
            nextFavorite ? 'Saved to favorites' : 'Removed from favorites',
            nextFavorite
              ? `${item.name} is now in your favorites.`
              : `${item.name} was removed from favorites.`,
            'success',
          );
        })
        .catch(toggleError => {
          if (
            toggleError instanceof ApiError &&
            (toggleError.status === 401 || toggleError.status === 403)
          ) {
            navigation.navigate('Login', { redirectTo: redirectToRestaurant });
          }
          pushToast(
            'Favorites unavailable',
            toggleError instanceof Error
              ? toggleError.message
              : 'Unable to update favorites right now.',
            'error',
          );
        });
    },
    [navigation, pushToast, redirectToRestaurant, token, toggleFavorite],
  );
  const handleOpenGeneratedCombo = React.useCallback(
    (combo: GeneratedCombo) => {
      if (!restaurant) {
        return;
      }
      navigation.navigate('Restaurant', {
        restaurantId: combo.restaurant_id,
        restaurantName: restaurant.name,
      });
    },
    [navigation, restaurant],
  );
  const handleAddGeneratedCombo = React.useCallback(
    (combo: GeneratedCombo) => {
      if (!restaurant) {
        return;
      }
      if (!effectiveSelection) {
        openFulfillmentSheet();
        return;
      }
      if (!activeFulfillmentAvailable) {
        pushToast(
          effectiveSelection.fulfillmentType === 'DELIVERY'
            ? 'Delivery unavailable'
            : 'Pickup unavailable',
          activeFulfillmentReason ??
            'This branch cannot fulfill the selected order type right now.',
          'info',
        );
        return;
      }
      for (const item of combo.items) {
        addToCart(
          buildMenuItemFromGeneratedComboItem(item, {
            source: 'restaurant-generated-combo',
            restaurantId: combo.restaurant_id,
            restaurantLocationId: combo.restaurant_location_id,
            restaurantLocationName: combo.restaurant_location_name,
            restaurantCuisineType: restaurant.cuisine_type,
            createdAt: restaurant.created_at,
            updatedAt: restaurant.updated_at,
          }),
          combo.restaurant_id,
          combo.restaurant_name,
          {
            quantity: item.quantity,
            silent: true,
            fulfillmentSelection: effectiveSelection,
          },
        );
      }
      pushToast(
        'Combo added',
        `${combo.combo_name} is now in your cart.`,
        'success',
      );
    },
    [
      activeFulfillmentAvailable,
      activeFulfillmentReason,
      addToCart,
      effectiveSelection,
      openFulfillmentSheet,
      pushToast,
      restaurant,
    ],
  );

  // Stable so the memoized list header below is not rebuilt every render.
  const handleSelectCategory = React.useCallback((category: string) => {
    LayoutAnimation.configureNext({
      duration: 180,
      update: {
        type: LayoutAnimation.Types.easeInEaseOut,
      },
      delete: {
        type: LayoutAnimation.Types.easeInEaseOut,
        property: LayoutAnimation.Properties.opacity,
      },
      create: {
        type: LayoutAnimation.Types.easeInEaseOut,
        property: LayoutAnimation.Properties.opacity,
      },
    });
    setActiveCategory(category);
  }, []);

  const handleScroll = (offsetY: number) => {
    lastScrollY.current = offsetY;
    if (offsetY > 6 && !headerElevated) {
      setHeaderElevated(true);
    } else if (offsetY <= 6 && headerElevated) {
      setHeaderElevated(false);
    }
  };

  // Distinct lines in the cart, matching every other cart badge in the app.
  const cartItemCount = cart.items.length;
  const heroLocationLine = [
    selectedLocation?.address_line_2,
    selectedLocation?.address_line_1,
    selectedLocation?.city,
  ]
    .filter(Boolean)
    .join(' • ');
  const heroCoverImage =
    restaurant?.cover_image_url ??
    restaurant?.logo_image_url ??
    placeholderImage(restaurant?.name ?? route.params.restaurantName);
  const heroEtaValue =
    effectiveSelection?.scheduleType === 'SCHEDULED'
      ? 'Scheduled'
      : getFulfillmentEtaLabel(selectedLocation, selectedFulfillmentType);

  // Memoized element rather than an inline one: `ListHeaderComponent` received
  // a fresh element on every render, so the hero image, the offers list, the
  // combos list and the category chips were all rebuilt on each cart tap.
  // React bails out of re-rendering the subtree when the element is identical.
  const renderHeader = useMemo(
    () => (
      <View style={styles.listHeader}>
        <View style={styles.heroCard}>
          <View style={styles.heroBanner}>
            <Image
              source={{ uri: heroCoverImage }}
              style={styles.heroBannerImage}
            />
            <View style={styles.heroBannerShade} />
            <View style={styles.heroBannerContent}>
              <Text style={styles.heroTitle}>
                {restaurant?.name ?? route.params.restaurantName}
              </Text>
              <Text style={styles.heroCuisine}>
                {restaurant?.cuisine_type ?? 'Fresh menu'}
              </Text>
            </View>
          </View>
          <View style={styles.heroBody}>
            <Pressable
              disabled={locationOptions.length === 0}
              onPress={openLocationSheet}
              style={styles.branchSelector}
            >
              <View style={styles.branchSelectorIconWrap}>
                <Icon
                  color={theme.colors.primary}
                  name="location-outline"
                  size={18}
                />
              </View>
              <View style={styles.branchSelectorCopy}>
                <Text style={styles.branchSelectorTitle}>
                  {selectedLocation?.branch_name ?? 'Select a branch'}
                </Text>
                <Text numberOfLines={1} style={styles.branchSelectorAddress}>
                  {heroLocationLine || 'Tap to choose the best branch near you'}
                </Text>
              </View>
              <View style={styles.branchSelectorChevronWrap}>
                <Icon
                  color={theme.colors.secondaryText}
                  name="chevron-down"
                  size={18}
                />
              </View>
            </Pressable>

            <Pressable
              onPress={openFulfillmentSheet}
              style={styles.fulfillmentSummaryCard}
            >
              <View style={styles.fulfillmentSummaryCopy}>
                <Text style={styles.fulfillmentSummaryLabel}>Order mode</Text>
                <Text style={styles.fulfillmentSummaryValue}>
                  {effectiveSelection
                    ? formatFulfillmentSelectionLabel(
                        selectedLocation,
                        effectiveSelection,
                      )
                    : 'Choose delivery or pickup'}
                </Text>
              </View>
              <View style={styles.fulfillmentSummaryAction}>
                <Text style={styles.fulfillmentSummaryActionText}>
                  {effectiveSelection ? 'Change' : 'Select'}
                </Text>
                <Icon
                  color={theme.colors.primary}
                  name="chevron-forward"
                  size={15}
                />
              </View>
            </Pressable>

            {effectiveSelection &&
            !activeFulfillmentAvailable &&
            selectedLocation ? (
              <View style={styles.fulfillmentUnavailableBanner}>
                <Icon
                  color={theme.colors.primary}
                  name="alert-circle-outline"
                  size={14}
                />
                <Text style={styles.fulfillmentUnavailableText}>
                  {activeFulfillmentReason ??
                    'This branch is unavailable for the selected fulfillment type right now.'}
                </Text>
              </View>
            ) : null}

            <View style={styles.heroMetaRow}>
              <View style={styles.heroMetricChip}>
                <Icon
                  color={theme.colors.primary}
                  name="time-outline"
                  size={14}
                />
                <Text style={styles.heroMetricText}>{heroEtaValue}</Text>
              </View>
              <View style={styles.heroMetricChip}>
                <Icon
                  color={theme.colors.primary}
                  name="wallet-outline"
                  size={14}
                />
                <Text style={styles.heroMetricText}>
                  Fee{' '}
                  {formatCurrency(
                    selectedFulfillmentType === 'DELIVERY'
                      ? selectedLocation?.delivery_fee ??
                          restaurant?.delivery_fee
                      : 0,
                  )}
                </Text>
              </View>
              <View style={styles.heroMetricChip}>
                <Icon
                  color={theme.colors.primary}
                  name="bag-check-outline"
                  size={14}
                />
                <Text style={styles.heroMetricText}>
                  Min{' '}
                  {formatCurrency(
                    selectedLocation?.minimum_order_amount ??
                      restaurant?.minimum_order_amount,
                  )}
                </Text>
              </View>
            </View>
          </View>
        </View>

        {restaurantOffers.length > 0 ? (
          <View style={styles.restaurantOffersSection}>
            <Text style={styles.restaurantOffersTitle}>Offers</Text>
            <FlatList
              contentContainerStyle={styles.restaurantOffersList}
              data={restaurantOffers}
              horizontal
              keyExtractor={item => item.id}
              renderItem={({ item }) => {
                const palette = getOfferPalette(
                  {
                    offer_type: item.offer_type,
                    audience_type: item.audience_type,
                    cuisine_type: item.cuisine_type,
                    discount_type: item.discount_type,
                  },
                  theme.mode,
                );
                const metaParts = [
                  Number(item.minimum_order_amount) > 0
                    ? `Min ${formatCurrency(item.minimum_order_amount)}`
                    : 'No min order',
                ];
                const endsLabel = formatOfferEndsLabel(item.expires_at);
                if (endsLabel) {
                  metaParts.push(endsLabel);
                }

                return (
                  <View
                    style={[
                      styles.restaurantOfferCard,
                      {
                        backgroundColor: palette.surface,
                        borderColor:
                          theme.mode === 'dark'
                            ? theme.colors.border
                            : `${palette.accent}22`,
                      },
                    ]}
                  >
                    <View
                      style={[
                        styles.restaurantOfferCardIconWrap,
                        { backgroundColor: palette.iconSurface },
                      ]}
                    >
                      <Icon
                        color={palette.iconText}
                        name={getOfferIconName(item)}
                        size={16}
                      />
                    </View>
                    <View style={styles.restaurantOfferCardBody}>
                      <Text
                        numberOfLines={1}
                        style={[
                          styles.restaurantOfferCardTitle,
                          { color: palette.accent },
                        ]}
                      >
                        {item.title}
                      </Text>
                      <Text
                        numberOfLines={1}
                        style={styles.restaurantOfferCardMeta}
                      >
                        {metaParts.join(' • ')}
                      </Text>
                    </View>
                  </View>
                );
              }}
              showsHorizontalScrollIndicator={false}
            />
          </View>
        ) : null}

        {generatedCombos.length > 0 ? (
          <View style={styles.comboSection}>
            <Text style={styles.comboEyebrow}>Generated combos</Text>
            <FlatList
              contentContainerStyle={styles.comboList}
              data={generatedCombos}
              horizontal
              keyExtractor={item => item.id}
              decelerationRate="fast"
              disableIntervalMomentum
              snapToAlignment="start"
              snapToInterval={comboCardMetrics.interval}
              renderItem={({ item }) => (
                <GeneratedComboCard
                  cardHeight={comboCardMetrics.cardHeight}
                  cardWidth={comboCardMetrics.cardWidth}
                  combo={item}
                  heroHeight={comboCardMetrics.heroHeight}
                  onAddCombo={handleAddGeneratedCombo}
                  onPress={handleOpenGeneratedCombo}
                />
              )}
              showsHorizontalScrollIndicator={false}
            />
          </View>
        ) : null}
        <View style={styles.chipsWrap}>
          <CategoryChips
            activeCategory={activeCategory}
            categories={categories}
            onSelect={handleSelectCategory}
          />
        </View>
      </View>
    ),
    [
      activeCategory,
      activeFulfillmentAvailable,
      activeFulfillmentReason,
      categories,
      comboCardMetrics,
      effectiveSelection,
      generatedCombos,
      handleAddGeneratedCombo,
      handleOpenGeneratedCombo,
      handleSelectCategory,
      heroCoverImage,
      heroEtaValue,
      heroLocationLine,
      locationOptions.length,
      openFulfillmentSheet,
      openLocationSheet,
      restaurant?.cuisine_type,
      restaurant?.delivery_fee,
      restaurant?.minimum_order_amount,
      restaurant?.name,
      restaurantOffers,
      route.params.restaurantName,
      selectedFulfillmentType,
      selectedLocation,
      styles,
      theme.colors.border,
      theme.colors.primary,
      theme.colors.secondaryText,
      theme.mode,
    ],
  );

  const renderMenuItem = React.useCallback<ListRenderItem<MenuItem>>(
    ({ item }) => (
      <MenuItemCard
        favoritePending={isFavoritePending(item.id)}
        hasOfferAvailable={Boolean(offerAvailabilityByItemId[item.id])}
        isFavorite={favoritesHydrated ? isFavorite(item.id) : item.is_favorite}
        item={item}
        onAdd={handleProtectedAdd}
        onDecrease={handleDecreaseQuantity}
        onOpen={handleOpenMenuItem}
        onToggleFavorite={handleToggleFavorite}
        quantity={
          isCustomizableMenuItem(item) ? 0 : cartQuantities.get(item.id) ?? 0
        }
      />
    ),
    [
      cartQuantities,
      favoritesHydrated,
      handleDecreaseQuantity,
      handleOpenMenuItem,
      handleProtectedAdd,
      handleToggleFavorite,
      offerAvailabilityByItemId,
      isFavorite,
      isFavoritePending,
    ],
  );

  if (error && !loading) {
    return (
      <SafeAreaView edges={['top']} style={styles.container}>
        <View style={[styles.header, styles.headerStatic]}>
          <Pressable
            onPress={() => navigation.goBack()}
            style={styles.backButton}
          >
            <Icon color={theme.colors.text} name="arrow-back" size={20} />
          </Pressable>
          <View style={styles.headerCopy}>
            <Text numberOfLines={1} style={styles.title}>
              {route.params.restaurantName}
            </Text>
            <Text style={styles.subtitle}>Restaurant menu</Text>
          </View>
        </View>
        <View style={styles.fallbackCard}>
          <Text style={styles.fallbackTitle}>
            We couldn’t load this restaurant.
          </Text>
          <Text style={styles.fallbackText}>{error}</Text>
          <View style={styles.fallbackActions}>
            <Pressable
              onPress={() => setReloadKey(value => value + 1)}
              style={styles.retryButton}
            >
              <Text style={styles.retryButtonText}>Retry</Text>
            </Pressable>
            <Pressable
              onPress={() => navigation.goBack()}
              style={styles.secondaryButton}
            >
              <Text style={styles.secondaryButtonText}>Go back</Text>
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} style={styles.container}>
      <View
        style={[styles.header, headerElevated ? styles.headerElevated : null]}
      >
        <Pressable
          onPress={() => navigation.goBack()}
          style={styles.backButton}
        >
          <Icon color={theme.colors.text} name="arrow-back" size={20} />
        </Pressable>
        <View style={styles.headerCopy}>
          <Text numberOfLines={1} style={styles.title}>
            {restaurant?.name ?? route.params.restaurantName}
          </Text>
          <Text numberOfLines={1} style={styles.subtitle}>
            {restaurant?.cuisine_type ?? 'Fresh menu'}
          </Text>
        </View>
        <Pressable
          onPress={handleProtectedCartOpen}
          style={styles.headerIconButton}
        >
          <Icon color={theme.colors.text} name="bag-handle-outline" size={19} />
          {cartItemCount > 0 ? (
            <View style={styles.cartBadge}>
              <Text style={styles.cartBadgeText}>
                {cartItemCount > 9 ? '9+' : cartItemCount}
              </Text>
            </View>
          ) : null}
        </Pressable>
      </View>

      <FlatList
        contentContainerStyle={styles.content}
        data={visibleItems}
        initialNumToRender={8}
        keyExtractor={item => item.id}
        ListEmptyComponent={
          loading ? (
            <View style={styles.skeletonList}>
              <SkeletonBlock height={84} />
              <SkeletonBlock height={84} />
              <SkeletonBlock height={84} />
              <SkeletonBlock height={84} />
            </View>
          ) : (
            <View style={styles.emptyState}>
              <Text style={styles.emptyTitle}>No items available</Text>
              <Text style={styles.emptyText}>
                Try another category or check back shortly.
              </Text>
            </View>
          )
        }
        ListHeaderComponent={renderHeader}
        onScroll={event => handleScroll(event.nativeEvent.contentOffset.y)}
        removeClippedSubviews
        renderItem={renderMenuItem}
        scrollEventThrottle={16}
        showsVerticalScrollIndicator={false}
        windowSize={8}
      />
      {selectedLocation ? (
        <FulfillmentSelectionSheet
          canDismiss={
            Boolean(effectiveSelection) || (!deliveryEnabled && !pickupEnabled)
          }
          initialSelection={effectiveSelection}
          location={selectedLocation}
          onConfirm={handleConfirmFulfillmentSelection}
          onDismiss={() => setFulfillmentSheetVisible(false)}
          restaurantId={restaurantId}
          token={token}
          visible={fulfillmentSheetVisible}
        />
      ) : null}
      <Modal
        animationType="none"
        onRequestClose={closeLocationSheet}
        statusBarTranslucent
        transparent
        visible={locationSheetMounted}
      >
        <View style={styles.sheetRoot}>
          <Animated.View
            style={[styles.sheetBackdrop, { opacity: locationSheetOpacity }]}
          >
            <Pressable
              onPress={closeLocationSheet}
              style={StyleSheet.absoluteFill}
            />
          </Animated.View>
          <Animated.View
            style={[
              styles.sheetPanel,
              {
                paddingBottom: Math.max(insets.bottom, 16),
                transform: [{ translateY: locationSheetTranslateY }],
              },
            ]}
          >
            <View style={styles.sheetHandle} />
            <View style={styles.sheetHeader}>
              <View style={styles.sheetHeaderCopy}>
                <Text style={styles.sheetTitle}>Choose a branch</Text>
                <Text style={styles.sheetSubtitle}>
                  Delivery times, fees, and fulfillment availability change by
                  location.
                </Text>
              </View>
              <Pressable
                onPress={closeLocationSheet}
                style={styles.sheetCloseButton}
              >
                <Icon color={theme.colors.text} name="close" size={18} />
              </Pressable>
            </View>

            <View style={styles.locationSheetList}>
              {locationOptions.map(location => {
                const isSelected = selectedLocation?.id === location.id;
                const availabilityLabel =
                  getLocationAvailabilityLabel(location);
                const isUnavailable =
                  !isFulfillmentEnabled(location, 'PICKUP') &&
                  !isFulfillmentEnabled(location, 'DELIVERY');
                return (
                  <Pressable
                    key={location.id}
                    onPress={() => handleSelectLocation(location.id)}
                    style={[
                      styles.locationSheetRow,
                      isSelected ? styles.locationSheetRowActive : null,
                    ]}
                  >
                    <View style={styles.locationSheetRowTop}>
                      <View style={styles.locationSheetRowTitleWrap}>
                        <Text style={styles.locationSheetRowTitle}>
                          {location.branch_name}
                        </Text>
                        <Text
                          numberOfLines={1}
                          style={styles.locationSheetRowAddress}
                        >
                          {[
                            location.address_line_2,
                            location.address_line_1,
                            location.city,
                          ]
                            .filter(Boolean)
                            .join(' • ')}
                        </Text>
                      </View>
                      {isSelected ? (
                        <View style={styles.locationSheetCheck}>
                          <Icon
                            color={theme.colors.white}
                            name="checkmark"
                            size={14}
                          />
                        </View>
                      ) : null}
                    </View>
                    <View style={styles.locationAvailabilityRow}>
                      <View
                        style={[
                          styles.locationStatusPill,
                          location.is_open
                            ? styles.locationStatusPillOpen
                            : styles.locationStatusPillClosed,
                        ]}
                      >
                        <Text
                          style={[
                            styles.locationStatusText,
                            location.is_open
                              ? styles.locationStatusTextOpen
                              : styles.locationStatusTextClosed,
                          ]}
                        >
                          {location.is_open ? 'Open now' : 'Closed'}
                        </Text>
                      </View>
                      <Text
                        style={[
                          styles.locationAvailabilityLabel,
                          isUnavailable
                            ? styles.locationAvailabilityLabelUnavailable
                            : null,
                        ]}
                      >
                        {availabilityLabel}
                      </Text>
                    </View>
                  </Pressable>
                );
              })}
            </View>
          </Animated.View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    container: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    header: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 8,
      paddingBottom: 10,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      backgroundColor: theme.colors.surfaceRaised,
    },
    headerStatic: {
      paddingBottom: 6,
    },
    headerElevated: {
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.08,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 14,
      elevation: 4,
      borderBottomWidth: 1,
      borderBottomColor: theme.colors.divider,
    },
    headerCopy: {
      flex: 1,
      gap: 2,
    },
    title: {
      color: theme.colors.text,
      fontSize: 20,
      fontWeight: '800',
      letterSpacing: -0.3,
    },
    subtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
    },
    backButton: {
      width: 38,
      height: 38,
      borderRadius: 19,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surface,
    },
    headerIconButton: {
      width: 44,
      height: 44,
      borderRadius: 22,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      alignItems: 'center',
      justifyContent: 'center',
      position: 'relative',
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.08,
      shadowRadius: 10,
      shadowOffset: { width: 0, height: 4 },
      elevation: 2,
    },
    cartBadge: {
      position: 'absolute',
      top: 5,
      right: 4,
      minWidth: 17,
      height: 17,
      paddingHorizontal: 4,
      borderRadius: 9,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    cartBadgeText: {
      color: theme.colors.white,
      fontSize: 9,
      fontWeight: '800',
    },
    chipsWrap: {
      paddingTop: 2,
      paddingBottom: 4,
      backgroundColor: theme.colors.background,
    },
    content: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 10,
      paddingBottom: 120,
    },
    listHeader: {
      paddingBottom: 4,
      gap: 16,
    },
    heroCard: {
      backgroundColor: theme.colors.surfaceRaised,
      borderRadius: 26,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.12,
      shadowOffset: { width: 0, height: 12 },
      shadowRadius: 24,
      elevation: 5,
    },
    heroBanner: {
      height: 188,
      position: 'relative',
      backgroundColor: theme.colors.surfaceAlt,
      borderTopLeftRadius: 26,
      borderTopRightRadius: 26,
      overflow: 'hidden',
    },
    heroBannerImage: {
      width: '100%',
      height: '100%',
    },
    heroBannerShade: {
      position: 'absolute',
      left: 0,
      right: 0,
      bottom: 0,
      height: 78,
      backgroundColor: theme.colors.darkOverlay,
    },
    heroBannerContent: {
      position: 'absolute',
      left: 16,
      right: 16,
      bottom: 14,
      gap: 2,
    },
    heroTitle: {
      color: theme.colors.white,
      fontSize: 28,
      fontWeight: '800',
      letterSpacing: -0.7,
    },
    heroCuisine: {
      color: 'rgba(255,255,255,0.82)',
      fontSize: 13,
      fontWeight: '500',
    },
    heroBody: {
      marginTop: -18,
      paddingHorizontal: 12,
      paddingTop: 0,
      paddingBottom: 10,
      gap: 9,
    },
    branchSelector: {
      minHeight: 60,
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceRaised,
      paddingHorizontal: 12,
      paddingVertical: 9,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.1,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 18,
      elevation: 3,
    },
    branchSelectorIconWrap: {
      width: 34,
      height: 34,
      borderRadius: 17,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.primarySoft : theme.tone('#FFF1E8'),
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 1,
      borderColor: theme.mode === 'dark' ? theme.colors.border : theme.tone('#F7D9C9'),
    },
    branchSelectorCopy: {
      flex: 1,
      gap: 1,
    },
    branchSelectorTitle: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
      letterSpacing: -0.2,
    },
    branchSelectorAddress: {
      color: theme.colors.secondaryText,
      fontSize: 11,
      lineHeight: 15,
    },
    branchSelectorChevronWrap: {
      width: 24,
      height: 24,
      borderRadius: 12,
      backgroundColor: theme.mode === 'dark' ? theme.colors.chip : '#F8F6F2',
      alignItems: 'center',
      justifyContent: 'center',
    },
    fulfillmentSummaryCard: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10,
      paddingHorizontal: 4,
      paddingVertical: 0,
    },
    fulfillmentSummaryCopy: {
      flex: 1,
      gap: 2,
    },
    fulfillmentSummaryLabel: {
      color: theme.colors.secondaryText,
      fontSize: 10,
      fontWeight: '700',
      textTransform: 'uppercase',
      letterSpacing: 0.7,
    },
    fulfillmentSummaryValue: {
      color: theme.colors.text,
      fontSize: 14.5,
      fontWeight: '800',
      letterSpacing: -0.2,
    },
    fulfillmentSummaryAction: {
      flexDirection: 'row',
      gap: 3,
      paddingHorizontal: 9,
      borderRadius: 999,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.primarySoft : theme.tone('#FFF2E7'),
      minHeight: 28,
      alignItems: 'center',
      justifyContent: 'center',
    },
    fulfillmentSummaryActionText: {
      color: theme.colors.primary,
      fontSize: 11.5,
      fontWeight: '800',
    },
    fulfillmentUnavailableBanner: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingHorizontal: 10,
      paddingVertical: 8,
      borderRadius: 14,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : theme.tone('#FFF5EF'),
      borderWidth: 1,
      borderColor: theme.mode === 'dark' ? theme.colors.border : theme.tone('#FFD8C3'),
    },
    fulfillmentUnavailableText: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 11,
      lineHeight: 16,
      fontWeight: '600',
    },
    heroMetaRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 6,
    },
    restaurantOffersSection: {
      marginTop: 12,
      gap: 8,
    },
    restaurantOffersTitle: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
      paddingHorizontal: theme.spacing.screen,
    },
    restaurantOffersList: {
      paddingHorizontal: theme.spacing.screen,
      gap: 8,
    },
    restaurantOfferCard: {
      width: 282,
      minHeight: 58,
      marginRight: 8,
      borderRadius: 16,
      paddingHorizontal: 10,
      paddingVertical: 9,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      borderWidth: 1,
    },
    restaurantOfferCardIconWrap: {
      width: 34,
      height: 34,
      borderRadius: 17,
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
    },
    restaurantOfferCardBody: {
      flex: 1,
      gap: 1,
    },
    restaurantOfferCardTitle: {
      fontSize: 13,
      lineHeight: 17,
      fontWeight: '800',
    },
    restaurantOfferCardMeta: {
      color: theme.colors.hint,
      fontSize: 10.5,
      fontWeight: '600',
    },
    heroMetricChip: {
      minHeight: 28,
      paddingHorizontal: 9,
      borderRadius: 999,
      backgroundColor: theme.mode === 'dark' ? theme.colors.chip : '#FAF7F3',
      borderWidth: 1,
      borderColor: theme.mode === 'dark' ? theme.colors.chipBorder : theme.tone('#F0E7DF'),
      flexDirection: 'row',
      alignItems: 'center',
      gap: 5,
    },
    heroMetricText: {
      color: theme.colors.text,
      fontSize: 11,
      fontWeight: '700',
    },
    comboSection: {
      gap: 10,
    },
    comboEyebrow: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
      textTransform: 'uppercase',
    },
    comboList: {
      paddingRight: 6,
    },
    skeletonList: {
      gap: 2,
      paddingTop: 6,
    },
    fallbackCard: {
      margin: theme.spacing.screen,
      padding: 20,
      borderRadius: 20,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      gap: 12,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.08,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 18,
      elevation: 3,
    },
    fallbackTitle: {
      color: theme.colors.text,
      fontSize: 18,
      fontWeight: '800',
    },
    fallbackText: {
      color: theme.colors.secondaryText,
      lineHeight: 22,
    },
    fallbackActions: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 10,
      marginTop: 4,
    },
    retryButton: {
      minHeight: 42,
      paddingHorizontal: 18,
      borderRadius: 999,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    retryButtonText: {
      color: theme.colors.white,
      fontWeight: '800',
    },
    secondaryButton: {
      minHeight: 42,
      paddingHorizontal: 18,
      borderRadius: 999,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      alignItems: 'center',
      justifyContent: 'center',
    },
    secondaryButtonText: {
      color: theme.colors.text,
      fontWeight: '700',
    },
    emptyState: {
      paddingVertical: 28,
      gap: 8,
    },
    emptyTitle: {
      color: theme.colors.text,
      fontSize: 18,
      fontWeight: '800',
    },
    emptyText: {
      color: theme.colors.secondaryText,
      lineHeight: 22,
    },
    sheetRoot: {
      flex: 1,
      justifyContent: 'flex-end',
    },
    sheetBackdrop: {
      ...StyleSheet.absoluteFill,
      backgroundColor: theme.colors.overlay,
    },
    sheetPanel: {
      backgroundColor: theme.colors.surfaceRaised,
      borderTopLeftRadius: 28,
      borderTopRightRadius: 28,
      paddingHorizontal: 18,
      paddingTop: 12,
      gap: 16,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.2,
      shadowOffset: { width: 0, height: -6 },
      shadowRadius: 22,
      elevation: 10,
    },
    sheetHandle: {
      alignSelf: 'center',
      width: 44,
      height: 5,
      borderRadius: 999,
      backgroundColor: theme.colors.border,
    },
    sheetHeader: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 12,
    },
    sheetHeaderCopy: {
      flex: 1,
      gap: 4,
    },
    sheetTitle: {
      color: theme.colors.text,
      fontSize: 20,
      fontWeight: '800',
      letterSpacing: -0.3,
    },
    sheetSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 19,
    },
    sheetCloseButton: {
      width: 36,
      height: 36,
      borderRadius: 18,
      backgroundColor: theme.colors.surface,
      alignItems: 'center',
      justifyContent: 'center',
    },
    locationSheetList: {
      gap: 10,
    },
    locationSheetRow: {
      borderWidth: 1,
      borderColor: theme.colors.border,
      borderRadius: 22,
      backgroundColor: theme.colors.surface,
      paddingHorizontal: 16,
      paddingVertical: 14,
      gap: 8,
      shadowColor: theme.colors.shadow,
      shadowOffset: {
        width: 0,
        height: 8,
      },
      shadowOpacity: 0.06,
      shadowRadius: 18,
      elevation: 2,
    },
    locationSheetRowActive: {
      borderColor: theme.colors.primary,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : theme.tone('#FFF8F2'),
      shadowColor: theme.colors.primary,
      shadowOpacity: 0.12,
      shadowRadius: 22,
      elevation: 4,
    },
    locationSheetRowTop: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 12,
    },
    locationSheetRowTitleWrap: {
      flex: 1,
      gap: 4,
    },
    locationSheetRowTitle: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
      letterSpacing: -0.2,
    },
    locationSheetRowAddress: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 17,
    },
    locationSheetCheck: {
      width: 24,
      height: 24,
      borderRadius: 12,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: 1,
      shadowColor: theme.colors.primary,
      shadowOffset: {
        width: 0,
        height: 6,
      },
      shadowOpacity: 0.18,
      shadowRadius: 12,
      elevation: 3,
    },
    locationAvailabilityRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
    },
    locationAvailabilityLabel: {
      flex: 1,
      textAlign: 'right',
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '700',
      letterSpacing: -0.1,
    },
    locationAvailabilityLabelUnavailable: {
      color: theme.colors.secondaryText,
    },
    locationStatusPillOpen: {
      backgroundColor: theme.colors.successSoft,
      borderColor:
        theme.mode === 'dark' ? 'rgba(72, 196, 121, 0.22)' : '#9ED6A6',
    },
    locationStatusPillClosed: {
      backgroundColor: theme.colors.dangerSoft,
      borderColor:
        theme.mode === 'dark' ? 'rgba(203, 32, 45, 0.24)' : '#F2C2C2',
    },
    locationStatusTextOpen: {
      color: theme.colors.success,
    },
    locationStatusTextClosed: {
      color: theme.colors.deepRed,
    },
    locationStatusPill: {
      minHeight: 28,
      borderRadius: 999,
      paddingHorizontal: 10,
      borderWidth: 1,
      alignItems: 'center',
      justifyContent: 'center',
    },
    locationStatusText: {
      fontSize: 11,
      fontWeight: '800',
      letterSpacing: 0.1,
    },
  });
