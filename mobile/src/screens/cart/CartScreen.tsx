import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  SafeAreaView,
  useSafeAreaInsets,
} from 'react-native-safe-area-context';
import {
  Animated,
  Image,
  LayoutAnimation,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  UIManager,
  useWindowDimensions,
  View,
} from 'react-native';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import Reanimated, {
  FadeInDown,
  LinearTransition,
} from 'react-native-reanimated';
import { FulfillmentSelectionSheet } from '@components/FulfillmentSelectionSheet';
import { getRestaurantScopedOffers } from '@components/offers/offerScope';
import { useAppForegroundEffect } from '@hooks/useAppForegroundEffect';
import {
  useAppActions,
  useCart,
  useSelectedLocation,
  useSelectedOffer,
  useSession,
} from '@hooks/useAppStore';
import {
  ApiError,
  api,
  formatCurrency,
  placeholderImage,
  toNumber,
} from '@services/api';
import { useTheme, useThemedStyles } from '@/theme';
import { createStyles } from './styles';
import { CartOfferPalette } from './components/CartOfferPalette';
import { CartUpsellCarousel } from './components/CartUpsellCarousel';
import { CartFulfillmentCard } from './components/CartFulfillmentCard';
import { CartSummaryCard } from './components/CartSummaryCard';
import { matchesAppliedOffer } from './offerCardHelpers';
import type { RootStackParamList } from '@/navigation/AppNavigator';
import type {
  PersonalizedOfferCard,
  ComboUpsellSuggestion,
  FulfillmentSelection,
  PersonalizedOfferPreview,
  Restaurant,
  RestaurantLocation,
} from '@/types/app';
import { checkAuthAndRedirect } from '@utils/authRedirect';
import { buildMenuItemFromGeneratedComboItem } from '@utils/generatedComboCart';
import {
  formatFulfillmentSelectionLabel,
  formatScheduledAtLabel,
  getScheduledSlotInvalidMessage,
  getFulfillmentEtaLabel,
  getFulfillmentUnavailableReason,
  isScheduledSlotPresent,
  isFulfillmentAvailableNow,
  isFulfillmentEnabled,
} from '@utils/fulfillment';
import { formatCustomizationSummary } from '@utils/menuItemCustomization';

/**
 * Settle time before previewing offers against the cart.
 *
 * Each preview round issues one request per offer, so a rapid sequence of
 * quantity taps used to multiply straight into the network.
 */
const OFFER_PREVIEW_DEBOUNCE_MS = 400;

export function CartScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const insets = useSafeAreaInsets();
  const { width: screenWidth } = useWindowDimensions();
  const navigation =
    useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const { token, user } = useSession();
  const cart = useCart();
  const selectedLocation = useSelectedLocation();
  const selectedPersonalizedOffer = useSelectedOffer();
  const {
    addToCart,
    clearCart,
    pushToast,
    setCartFulfillmentSelection,
    setSelectedPersonalizedOffer,
    updateCartQuantity,
  } = useAppActions();
  const [instructions, setInstructions] = useState('');
  const [orderDetailsExpanded, setOrderDetailsExpanded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [upsellSuggestions, setUpsellSuggestions] = useState<
    ComboUpsellSuggestion[]
  >([]);
  const [recentlyAddedComboItemIds, setRecentlyAddedComboItemIds] = useState<
    Set<string>
  >(new Set());
  const [visibleUpsellComboIds, setVisibleUpsellComboIds] = useState<
    Set<string>
  >(new Set());
  const [revealedUpsellComboIds, setRevealedUpsellComboIds] = useState<
    Set<string>
  >(new Set());
  const [interactedUpsellComboIds, setInteractedUpsellComboIds] = useState<
    Set<string>
  >(new Set());
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [restaurantLoading, setRestaurantLoading] = useState(false);
  const [restaurantOffers, setRestaurantOffers] = useState<
    PersonalizedOfferCard[]
  >([]);
  const [offerPreviewsByCardId, setOfferPreviewsByCardId] = useState<
    Record<string, PersonalizedOfferPreview>
  >({});
  const [offerPaletteLoading, setOfferPaletteLoading] = useState(false);
  const [fulfillmentSheetVisible, setFulfillmentSheetVisible] = useState(false);
  const [
    fulfillmentSheetInitialSelection,
    setFulfillmentSheetInitialSelection,
  ] = useState<FulfillmentSelection | null>(null);
  const [pendingDeliverySelection, setPendingDeliverySelection] =
    useState<FulfillmentSelection | null>(null);
  const [scheduledSelectionValid, setScheduledSelectionValid] = useState(true);
  const [scheduledSelectionReason, setScheduledSelectionReason] = useState<
    string | null
  >(null);
  const hasRequestedAuthRef = useRef(false);
  const autoAdjustedFulfillmentRef = useRef<Set<string>>(new Set());
  const lastRestaurantRefreshAtRef = useRef(0);
  const lastScheduledValidationAtRef = useRef(0);
  const lastScheduledValidationKeyRef = useRef<string | null>(null);
  const restaurantRef = useRef<Restaurant | null>(null);
  const restaurantRefreshPromiseRef = useRef<Promise<Restaurant | null> | null>(
    null,
  );
  const restaurantRefreshPromiseKeyRef = useRef<string | null>(null);
  const scheduledSelectionValidRef = useRef(true);
  const scheduledValidationPromiseRef = useRef<Promise<boolean> | null>(null);
  const scheduledValidationPromiseKeyRef = useRef<string | null>(null);
  const offerPreviewRequestIdRef = useRef(0);
  const orderDetailsChevron = useRef(new Animated.Value(0)).current;
  const recentlyAddedComboItemsTimerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null);
  const upsellViewabilityConfigRef = useRef({
    itemVisiblePercentThreshold: 55,
    minimumViewTime: 120,
  });
  const onUpsellViewableItemsChanged = useRef(
    ({
      viewableItems,
    }: {
      viewableItems: Array<{ item: ComboUpsellSuggestion | null }>;
    }) => {
      const nextVisibleIds = new Set<string>();
      for (const viewable of viewableItems) {
        const comboId = viewable.item?.combo_id;
        if (comboId) {
          nextVisibleIds.add(comboId);
        }
      }
      setRevealedUpsellComboIds(previous => {
        let changed = false;
        const next = new Set(previous);
        for (const id of nextVisibleIds) {
          if (!next.has(id)) {
            next.add(id);
            changed = true;
          }
        }
        return changed ? next : previous;
      });
      setVisibleUpsellComboIds(previous => {
        if (
          previous.size === nextVisibleIds.size &&
          [...nextVisibleIds].every(id => previous.has(id))
        ) {
          return previous;
        }
        return nextVisibleIds;
      });
    },
  ).current;
  const restaurantLocation: RestaurantLocation | null = useMemo(
    () =>
      restaurant?.locations?.find(
        location => location.id === cart.restaurantLocationId,
      ) ??
      restaurant?.locations?.find(location => location.is_active) ??
      null,
    [cart.restaurantLocationId, restaurant?.locations],
  );

  useEffect(() => {
    if (
      Platform.OS === 'android' &&
      UIManager.setLayoutAnimationEnabledExperimental
    ) {
      UIManager.setLayoutAnimationEnabledExperimental(true);
    }

    return () => {
      if (recentlyAddedComboItemsTimerRef.current) {
        clearTimeout(recentlyAddedComboItemsTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    Animated.timing(orderDetailsChevron, {
      toValue: orderDetailsExpanded ? 1 : 0,
      duration: 180,
      useNativeDriver: true,
    }).start();
  }, [orderDetailsChevron, orderDetailsExpanded]);
  const applyRestaurantSnapshot = React.useCallback(
    (nextRestaurant: Restaurant | null) => {
      restaurantRef.current = nextRestaurant;
      setRestaurant(previous =>
        previous === nextRestaurant ? previous : nextRestaurant,
      );
    },
    [],
  );
  const applyScheduledValidationState = React.useCallback(
    (isValid: boolean, reason: string | null) => {
      scheduledSelectionValidRef.current = isValid;
      setScheduledSelectionValid(previous =>
        previous === isValid ? previous : isValid,
      );
      setScheduledSelectionReason(previous =>
        previous === reason ? previous : reason,
      );
    },
    [],
  );

  const refreshRestaurantSnapshot = React.useCallback(
    async (force: boolean = false): Promise<Restaurant | null> => {
      if (!cart.restaurantId) {
        setRestaurantLoading(false);
        applyRestaurantSnapshot(null);
        return null;
      }
      const requestKey = String(cart.restaurantId);
      if (
        restaurantRefreshPromiseRef.current &&
        restaurantRefreshPromiseKeyRef.current === requestKey
      ) {
        return restaurantRefreshPromiseRef.current;
      }
      const now = Date.now();
      if (!force && now - lastRestaurantRefreshAtRef.current < 15000) {
        return restaurantRef.current;
      }
      lastRestaurantRefreshAtRef.current = now;
      const shouldShowLoading = !restaurantRef.current;
      if (shouldShowLoading) {
        setRestaurantLoading(previous => (previous ? previous : true));
      }
      const request = (async (): Promise<Restaurant | null> => {
        try {
          const nextRestaurant = await api.getRestaurant(
            cart.restaurantId!,
            token,
          );
          if (restaurantRefreshPromiseKeyRef.current === requestKey) {
            applyRestaurantSnapshot(nextRestaurant);
          }
          return nextRestaurant;
        } catch {
          if (!force) {
            return restaurantRef.current;
          }
          return null;
        } finally {
          if (shouldShowLoading) {
            setRestaurantLoading(false);
          }
          if (restaurantRefreshPromiseKeyRef.current === requestKey) {
            restaurantRefreshPromiseRef.current = null;
            restaurantRefreshPromiseKeyRef.current = null;
          }
        }
      })();
      restaurantRefreshPromiseRef.current = request;
      restaurantRefreshPromiseKeyRef.current = requestKey;
      return request;
    },
    [applyRestaurantSnapshot, cart.restaurantId, token],
  );

  useEffect(() => {
    if (token) {
      hasRequestedAuthRef.current = false;
      return;
    }

    if (hasRequestedAuthRef.current) {
      return;
    }

    hasRequestedAuthRef.current = true;

    checkAuthAndRedirect({
      token,
      navigation,
      pushToast,
      redirectTo: { screen: 'Cart' },
    });
  }, [navigation, pushToast, token]);

  // Keyed on which items are in the cart, not on the `cart.items` array
  // identity. The endpoint takes item ids only, so changing a quantity cannot
  // change the response - and no longer triggers a request.
  const upsellItemIds = useMemo(
    () => cart.items.map(item => item.menuItem.id),
    [cart.items],
  );
  const upsellItemsKey = upsellItemIds.join(',');

  useEffect(() => {
    if (!cart.restaurantId || upsellItemIds.length === 0) {
      setUpsellSuggestions([]);
      return;
    }

    const latestItemId = upsellItemIds[upsellItemIds.length - 1];
    let active = true;
    api
      .getCartUpsellSuggestions({
        restaurantId: cart.restaurantId,
        locationId: cart.restaurantLocationId,
        itemId: latestItemId,
        cartItemIds: upsellItemIds,
        limit: 2,
      })
      .then(rows => {
        if (active) {
          setUpsellSuggestions(rows);
        }
      })
      .catch(() => {
        if (active) {
          setUpsellSuggestions([]);
        }
      });

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [upsellItemsKey, cart.restaurantId, cart.restaurantLocationId]);

  useEffect(() => {
    if (!cart.restaurantId) {
      setRestaurantLoading(false);
      applyRestaurantSnapshot(null);
      return;
    }

    // Not forced: the focus effect below runs on mount too, and the snapshot's
    // own 15s throttle plus the request cache collapse the pair into one call.
    refreshRestaurantSnapshot().catch(() => undefined);
  }, [applyRestaurantSnapshot, cart.restaurantId, refreshRestaurantSnapshot]);

  useFocusEffect(
    React.useCallback(() => {
      refreshRestaurantSnapshot().catch(() => undefined);
      return undefined;
    }, [refreshRestaurantSnapshot]),
  );

  useAppForegroundEffect(() => {
    refreshRestaurantSnapshot(true).catch(() => undefined);
  });

  const itemCount = useMemo(
    () => cart.items.reduce((total, item) => total + item.quantity, 0),
    [cart.items],
  );
  const subtotal = useMemo(
    () =>
      cart.items.reduce(
        (total, item) => total + toNumber(item.unitPrice) * item.quantity,
        0,
      ),
    [cart.items],
  );
  const activePersonalizedOffer = useMemo(
    () =>
      selectedPersonalizedOffer &&
      selectedPersonalizedOffer.restaurantId === cart.restaurantId &&
      (!selectedPersonalizedOffer.offerRestaurantLocationId ||
        selectedPersonalizedOffer.offerRestaurantLocationId ===
          cart.restaurantLocationId)
        ? selectedPersonalizedOffer
        : null,
    [cart.restaurantId, cart.restaurantLocationId, selectedPersonalizedOffer],
  );
  const activeOfferCard = useMemo(
    () =>
      restaurantOffers.find(offer =>
        matchesAppliedOffer(offer, activePersonalizedOffer),
      ) ?? null,
    [activePersonalizedOffer, restaurantOffers],
  );
  const fulfillmentSelection = useMemo<FulfillmentSelection>(
    () => ({
      fulfillmentType: cart.fulfillmentType,
      scheduleType: cart.scheduleType,
      scheduledAt: cart.scheduledAt,
    }),
    [cart.fulfillmentType, cart.scheduleType, cart.scheduledAt],
  );
  const cartOfferItemsPayload = useMemo(
    () =>
      cart.items.map(item => ({
        menu_item_id: item.menuItem.id,
        menu_item_size_id: item.selectedSize?.id ?? null,
        selected_options: item.selectedOptions.map(option => ({
          option_id: option.optionId,
          quantity: option.quantity,
        })),
        quantity: item.quantity,
      })),
    [cart.items],
  );
  const validateScheduledSelection = React.useCallback(
    async ({
      force = false,
      openSheetOnInvalid = false,
      showFeedback = false,
    }: {
      force?: boolean;
      openSheetOnInvalid?: boolean;
      showFeedback?: boolean;
    } = {}): Promise<boolean> => {
      if (cart.scheduleType !== 'SCHEDULED') {
        applyScheduledValidationState(true, null);
        return true;
      }
      if (
        !cart.restaurantId ||
        !cart.restaurantLocationId ||
        !cart.scheduledAt
      ) {
        const reason =
          'Your selected slot is incomplete. Please choose another time.';
        applyScheduledValidationState(false, reason);
        if (showFeedback) {
          pushToast('Choose another time', reason, 'info');
        }
        if (openSheetOnInvalid) {
          setFulfillmentSheetInitialSelection({
            fulfillmentType: cart.fulfillmentType,
            scheduleType: cart.scheduleType,
            scheduledAt: cart.scheduledAt,
          });
          setFulfillmentSheetVisible(true);
        }
        return false;
      }

      const validationKey = [
        cart.restaurantId,
        cart.restaurantLocationId,
        cart.fulfillmentType,
        cart.scheduledAt,
      ].join(':');
      if (scheduledValidationPromiseRef.current) {
        if (scheduledValidationPromiseKeyRef.current === validationKey) {
          return scheduledValidationPromiseRef.current;
        }
      }
      const now = Date.now();
      if (
        !force &&
        lastScheduledValidationKeyRef.current === validationKey &&
        now - lastScheduledValidationAtRef.current < 10000
      ) {
        return scheduledSelectionValidRef.current;
      }
      lastScheduledValidationKeyRef.current = validationKey;
      lastScheduledValidationAtRef.current = now;
      const request = (async (): Promise<boolean> => {
        try {
          const response = await api.getRestaurantLocationScheduleOptions(
            cart.restaurantId!,
            cart.restaurantLocationId!,
            cart.fulfillmentType,
            token,
          );
          const exists = isScheduledSlotPresent(response, cart.scheduledAt!);
          const reason = exists
            ? null
            : getScheduledSlotInvalidMessage(response);
          if (scheduledValidationPromiseKeyRef.current === validationKey) {
            applyScheduledValidationState(exists, reason);
          }
          if (!exists) {
            if (showFeedback) {
              pushToast(
                'Choose another time',
                reason ??
                  'Your selected slot is no longer available. Please choose another time.',
                'info',
              );
            }
            if (openSheetOnInvalid) {
              setFulfillmentSheetInitialSelection({
                fulfillmentType: cart.fulfillmentType,
                scheduleType: cart.scheduleType,
                scheduledAt: cart.scheduledAt,
              });
              setFulfillmentSheetVisible(true);
            }
          }
          return exists;
        } catch (error) {
          const reason =
            error instanceof Error
              ? error.message
              : 'Unable to validate your selected time right now.';
          if (showFeedback) {
            pushToast('Unable to refresh time', reason, 'info');
          }
          return force ? false : scheduledSelectionValidRef.current;
        } finally {
          if (scheduledValidationPromiseKeyRef.current === validationKey) {
            scheduledValidationPromiseRef.current = null;
            scheduledValidationPromiseKeyRef.current = null;
          }
        }
      })();
      scheduledValidationPromiseRef.current = request;
      scheduledValidationPromiseKeyRef.current = validationKey;
      return request;
    },
    [
      applyScheduledValidationState,
      cart.fulfillmentType,
      cart.restaurantId,
      cart.restaurantLocationId,
      cart.scheduleType,
      cart.scheduledAt,
      pushToast,
      token,
    ],
  );
  useEffect(() => {
    validateScheduledSelection().catch(() => undefined);
  }, [validateScheduledSelection]);

  useFocusEffect(
    // Stays forced so an invalid slot always re-opens the fulfillment sheet.
    // The duplicate network call is absorbed by the request cache, which
    // returns the mount validation's response for the same key.
    React.useCallback(() => {
      validateScheduledSelection({
        force: true,
        openSheetOnInvalid: true,
      }).catch(() => undefined);
      return undefined;
    }, [validateScheduledSelection]),
  );

  useAppForegroundEffect(() => {
    validateScheduledSelection({
      force: true,
      openSheetOnInvalid: true,
      showFeedback: true,
    }).catch(() => undefined);
  }, cart.scheduleType === 'SCHEDULED');

  const activeOfferPreview = useMemo(
    () =>
      activeOfferCard
        ? offerPreviewsByCardId[activeOfferCard.id] ?? null
        : null,
    [activeOfferCard, offerPreviewsByCardId],
  );
  const personalizedOfferDiscount = useMemo(
    () =>
      activeOfferPreview?.eligible
        ? toNumber(activeOfferPreview.discount_amount)
        : 0,
    [activeOfferPreview],
  );
  const isMonetaryPersonalizedOffer = useMemo(
    () => activePersonalizedOffer?.discountType !== 'NONE',
    [activePersonalizedOffer],
  );
  const amountToUnlock = useMemo(
    () => toNumber(activeOfferPreview?.amount_to_unlock ?? 0),
    [activeOfferPreview?.amount_to_unlock],
  );
  const personalizedOfferRowValue = useMemo(() => {
    if (!activePersonalizedOffer || !isMonetaryPersonalizedOffer) {
      return null;
    }
    if (offerPaletteLoading) {
      return 'Checking...';
    }
    if (personalizedOfferDiscount > 0) {
      return `- ${formatCurrency(personalizedOfferDiscount)}`;
    }
    if (amountToUnlock > 0) {
      return `Add ${formatCurrency(amountToUnlock)} more`;
    }
    return (
      activeOfferPreview?.message ??
      `Unlock at ${formatCurrency(activePersonalizedOffer.minimumOrderAmount)}`
    );
  }, [
    activePersonalizedOffer,
    activeOfferPreview?.message,
    amountToUnlock,
    isMonetaryPersonalizedOffer,
    offerPaletteLoading,
    personalizedOfferDiscount,
  ]);
  const deliveryFee = useMemo(
    () =>
      cart.items.length > 0 && cart.fulfillmentType === 'DELIVERY'
        ? toNumber(
            restaurantLocation?.delivery_fee ?? restaurant?.delivery_fee ?? 0,
          )
        : 0,
    [
      cart.fulfillmentType,
      cart.items.length,
      restaurant?.delivery_fee,
      restaurantLocation?.delivery_fee,
    ],
  );
  const taxAmount = useMemo(() => subtotal * 0.05, [subtotal]);
  const total = useMemo(
    () => subtotal + deliveryFee + taxAmount - personalizedOfferDiscount,
    [deliveryFee, personalizedOfferDiscount, subtotal, taxAmount],
  );
  const deliveryAddress = useMemo(
    () => selectedLocation?.address ?? user?.default_address ?? '',
    [selectedLocation?.address, user?.default_address],
  );
  const pickupAddress = useMemo(() => {
    if (!restaurant) {
      return cart.restaurantName
        ? `${cart.restaurantLocationName ?? cart.restaurantName}`
        : 'Pickup details will appear here.';
    }

    return [
      restaurantLocation?.address_line_1 ?? restaurant.address_line_1,
      restaurantLocation?.address_line_2 ?? restaurant.address_line_2,
      restaurantLocation?.city ?? restaurant.city,
      restaurantLocation?.state ?? restaurant.state,
      restaurantLocation?.postal_code ?? restaurant.postal_code,
    ]
      .filter(Boolean)
      .join(', ');
  }, [
    cart.restaurantLocationName,
    cart.restaurantName,
    restaurant,
    restaurantLocation,
  ]);
  const requiresDeliveryAddress = cart.fulfillmentType === 'DELIVERY';
  const checkoutAddress = useMemo(
    () => (requiresDeliveryAddress ? deliveryAddress.trim() : pickupAddress),
    [deliveryAddress, pickupAddress, requiresDeliveryAddress],
  );
  const upsellCardWidth = Math.min(Math.max(screenWidth * 0.72, 236), 288);
  const offerCardWidth = useMemo(
    () => Math.min(Math.max(screenWidth * 0.7, 220), 276),
    [screenWidth],
  );
  const preDiscountTotal = useMemo(
    () => subtotal + deliveryFee + taxAmount,
    [deliveryFee, subtotal, taxAmount],
  );
  const savingsAmount = useMemo(
    () => Math.max(preDiscountTotal - total, 0),
    [preDiscountTotal, total],
  );
  const locationDisplayName =
    cart.restaurantLocationName ??
    restaurantLocation?.branch_name ??
    'Main branch';
  const fulfillmentChipLabel = formatFulfillmentSelectionLabel(
    restaurantLocation,
    fulfillmentSelection,
  );
  const deliveryEnabled = useMemo(
    () => isFulfillmentEnabled(restaurantLocation, 'DELIVERY'),
    [restaurantLocation],
  );
  const pickupEnabled = useMemo(
    () => isFulfillmentEnabled(restaurantLocation, 'PICKUP'),
    [restaurantLocation],
  );
  const locationOrderingUnavailable = !deliveryEnabled && !pickupEnabled;
  const activeFulfillmentAvailable = useMemo(
    () =>
      cart.scheduleType === 'SCHEDULED'
        ? scheduledSelectionValid === true && Boolean(cart.scheduledAt)
        : isFulfillmentAvailableNow(restaurantLocation, cart.fulfillmentType),
    [
      cart.fulfillmentType,
      cart.scheduleType,
      cart.scheduledAt,
      restaurantLocation,
      scheduledSelectionValid,
    ],
  );
  const activeFulfillmentReason = useMemo(
    () =>
      cart.scheduleType === 'SCHEDULED'
        ? scheduledSelectionReason
        : getFulfillmentUnavailableReason(
            restaurantLocation,
            cart.fulfillmentType,
          ),
    [
      cart.fulfillmentType,
      cart.scheduleType,
      restaurantLocation,
      scheduledSelectionReason,
    ],
  );
  const timingLabel = useMemo(
    () =>
      cart.scheduleType === 'SCHEDULED'
        ? formatScheduledAtLabel(cart.scheduledAt)
        : 'ASAP',
    [cart.scheduleType, cart.scheduledAt],
  );
  const timingSupportingLabel = useMemo(
    () =>
      cart.scheduleType === 'SCHEDULED'
        ? cart.fulfillmentType === 'DELIVERY'
          ? 'Scheduled delivery slot'
          : 'Scheduled pickup slot'
        : cart.fulfillmentType === 'DELIVERY'
        ? `Arrives in about ${getFulfillmentEtaLabel(
            restaurantLocation,
            cart.fulfillmentType,
          )}`
        : `Ready in about ${getFulfillmentEtaLabel(
            restaurantLocation,
            cart.fulfillmentType,
          )}`,
    [cart.fulfillmentType, cart.scheduleType, restaurantLocation],
  );
  const canPlaceOrder = useMemo(
    () =>
      !submitting &&
      Boolean(restaurantLocation) &&
      !restaurantLoading &&
      activeFulfillmentAvailable &&
      (!requiresDeliveryAddress || Boolean(deliveryAddress.trim())),
    [
      activeFulfillmentAvailable,
      deliveryAddress,
      requiresDeliveryAddress,
      restaurantLoading,
      restaurantLocation,
      submitting,
    ],
  );
  const showMissingDeliveryAddressWarning =
    requiresDeliveryAddress && !deliveryAddress.trim();
  const orderDetailsChevronRotation = useMemo(
    () =>
      orderDetailsChevron.interpolate({
        inputRange: [0, 1],
        outputRange: ['0deg', '180deg'],
      }),
    [orderDetailsChevron],
  );

  useEffect(() => {
    if (!restaurantLocation) {
      return;
    }
    if (
      isFulfillmentEnabled(restaurantLocation, cart.fulfillmentType) ||
      locationOrderingUnavailable
    ) {
      autoAdjustedFulfillmentRef.current.delete(
        `${cart.restaurantLocationId}:${cart.fulfillmentType}`,
      );
      return;
    }

    const nextFulfillmentType = deliveryEnabled ? 'DELIVERY' : 'PICKUP';
    const adjustmentKey = `${cart.restaurantLocationId}:${cart.fulfillmentType}`;
    if (autoAdjustedFulfillmentRef.current.has(adjustmentKey)) {
      return;
    }

    autoAdjustedFulfillmentRef.current.add(adjustmentKey);
    setCartFulfillmentSelection({
      restaurantId: cart.restaurantId,
      restaurantName: cart.restaurantName,
      restaurantLocationId: cart.restaurantLocationId,
      restaurantLocationName: cart.restaurantLocationName,
      fulfillmentType: nextFulfillmentType,
      scheduleType: 'ASAP',
      scheduledAt: new Date().toISOString(),
    });
    pushToast(
      cart.fulfillmentType === 'DELIVERY'
        ? 'Delivery unavailable'
        : 'Pickup unavailable',
      cart.fulfillmentType === 'DELIVERY'
        ? 'Delivery is not available at this location right now. Switched to Pickup.'
        : 'Pickup is not available at this location right now. Switched to Delivery.',
      'info',
    );
  }, [
    cart.fulfillmentType,
    cart.restaurantId,
    cart.restaurantLocationId,
    cart.restaurantLocationName,
    cart.restaurantName,
    deliveryEnabled,
    locationOrderingUnavailable,
    pickupEnabled,
    pushToast,
    restaurantLocation,
    setCartFulfillmentSelection,
  ]);

  useEffect(() => {
    if (!pendingDeliverySelection) {
      return;
    }
    if (!deliveryAddress.trim()) {
      return;
    }
    setCartFulfillmentSelection({
      restaurantId: cart.restaurantId,
      restaurantName: cart.restaurantName,
      restaurantLocationId: cart.restaurantLocationId,
      restaurantLocationName: cart.restaurantLocationName,
      fulfillmentType: pendingDeliverySelection.fulfillmentType,
      scheduleType: pendingDeliverySelection.scheduleType,
      scheduledAt: pendingDeliverySelection.scheduledAt,
    });
    setPendingDeliverySelection(null);
    pushToast(
      'Delivery ready',
      'Delivery is now selected for this order.',
      'success',
    );
  }, [
    cart.restaurantId,
    cart.restaurantLocationId,
    cart.restaurantLocationName,
    cart.restaurantName,
    deliveryAddress,
    pendingDeliverySelection,
    pushToast,
    setCartFulfillmentSelection,
  ]);

  const handleOpenFulfillmentSheet = (
    initialSelection: FulfillmentSelection = fulfillmentSelection,
  ) => {
    if (locationOrderingUnavailable) {
      pushToast(
        'Location unavailable',
        'This location is currently unavailable for ordering.',
        'info',
      );
      return;
    }
    setFulfillmentSheetInitialSelection(initialSelection);
    setFulfillmentSheetVisible(true);
  };

  const handleFulfillmentModePress = (mode: 'DELIVERY' | 'PICKUP') => {
    if (mode === cart.fulfillmentType) {
      handleOpenFulfillmentSheet();
      return;
    }

    if (mode === 'DELIVERY' && !deliveryAddress.trim()) {
      setPendingDeliverySelection({
        fulfillmentType: mode,
        scheduleType: cart.scheduleType,
        scheduledAt: cart.scheduledAt,
      });
      pushToast(
        'Add delivery address',
        'Choose where the order should reach you before switching to Delivery.',
        'info',
      );
      navigation.navigate('LocationSelect');
      return;
    }

    if (!isFulfillmentEnabled(restaurantLocation, mode)) {
      pushToast(
        mode === 'DELIVERY' ? 'Delivery unavailable' : 'Pickup unavailable',
        mode === 'DELIVERY'
          ? 'Delivery is not available at this branch.'
          : 'Pickup is not available at this branch.',
        'info',
      );
      return;
    }

    handleOpenFulfillmentSheet({
      fulfillmentType: mode,
      scheduleType: cart.scheduleType,
      scheduledAt: cart.scheduledAt,
    });
  };

  const handleAddMoreItems = React.useCallback(() => {
    if (!cart.restaurantId) {
      pushToast(
        'Restaurant unavailable',
        'We could not reopen this menu right now.',
        'error',
      );
      return;
    }

    navigation.navigate('Restaurant', {
      restaurantId: cart.restaurantId,
      restaurantName: cart.restaurantName ?? restaurant?.name ?? 'Restaurant',
    });
  }, [
    cart.restaurantId,
    cart.restaurantName,
    navigation,
    pushToast,
    restaurant?.name,
  ]);

  const toggleOrderDetails = React.useCallback(() => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setOrderDetailsExpanded(previous => !previous);
  }, []);

  useEffect(() => {
    if (!token || !cart.restaurantId || !cart.restaurantLocationId) {
      setRestaurantOffers([]);
      return;
    }

    let active = true;
    const restaurantId = cart.restaurantId;
    const restaurantLocationId = cart.restaurantLocationId;
    api
      .getPersonalizedOffers(token, 8)
      .then((offers: PersonalizedOfferCard[]) => {
        if (!active) {
          return;
        }
        const filteredOffers = getRestaurantScopedOffers(
          offers,
          restaurantId,
          restaurantLocationId,
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
        console.warn('cart offers load failed', error);
        if (active) {
          setRestaurantOffers([]);
        }
      });

    return () => {
      active = false;
    };
  }, [cart.restaurantId, cart.restaurantLocationId, token]);

  useEffect(() => {
    if (
      !token ||
      !cart.restaurantId ||
      !cart.restaurantLocationId ||
      restaurantOffers.length === 0 ||
      cartOfferItemsPayload.length === 0
    ) {
      setOfferPaletteLoading(false);
      setOfferPreviewsByCardId({});
      return;
    }

    let active = true;
    const restaurantId = cart.restaurantId;
    const restaurantLocationId = cart.restaurantLocationId;
    const requestId = offerPreviewRequestIdRef.current + 1;
    offerPreviewRequestIdRef.current = requestId;
    setOfferPaletteLoading(true);

    // Eligibility genuinely depends on quantities, so the payload is unchanged
    // - but this fires one request per offer. Debouncing collapses a burst of
    // quantity taps into a single round instead of one round per tap.
    const previewTimer = setTimeout(() => {
      if (!active) {
        return;
      }
      Promise.all(
        restaurantOffers.map(async offer => {
          const preview = await api.previewPersonalizedOffer(token, {
            offer_id: offer.offer_id,
            generated_offer_id: offer.generated_offer_id,
            generated_offer_user_match_id: offer.generated_offer_user_match_id,
            restaurant_id: restaurantId,
            restaurant_location_id: restaurantLocationId,
            fulfillment_type: cart.fulfillmentType,
            items: cartOfferItemsPayload,
          });
          return [offer.id, preview] as const;
        }),
      )
        .then(entries => {
          if (!active || offerPreviewRequestIdRef.current !== requestId) {
            return;
          }
          const nextPreviews = Object.fromEntries(entries);
          setOfferPreviewsByCardId(previous => {
            const previousSerialized = JSON.stringify(previous);
            const nextSerialized = JSON.stringify(nextPreviews);
            return previousSerialized === nextSerialized
              ? previous
              : nextPreviews;
          });
        })
        .catch(() => {
          if (active && offerPreviewRequestIdRef.current === requestId) {
            setOfferPreviewsByCardId({});
          }
        })
        .finally(() => {
          if (active && offerPreviewRequestIdRef.current === requestId) {
            setOfferPaletteLoading(false);
          }
        });
    }, OFFER_PREVIEW_DEBOUNCE_MS);

    return () => {
      active = false;
      clearTimeout(previewTimer);
    };
  }, [
    cart.fulfillmentType,
    cart.restaurantId,
    cart.restaurantLocationId,
    cartOfferItemsPayload,
    restaurantOffers,
    token,
  ]);

  useEffect(() => {
    if (
      !activePersonalizedOffer ||
      offerPaletteLoading ||
      !activeOfferPreview ||
      activeOfferPreview.eligible
    ) {
      return;
    }
    const normalizedMessage = (activeOfferPreview.message ?? '').toLowerCase();
    if (
      normalizedMessage.includes('not found') ||
      normalizedMessage.includes('no longer available')
    ) {
      setSelectedPersonalizedOffer(null);
    }
  }, [
    activePersonalizedOffer,
    activeOfferPreview,
    offerPaletteLoading,
    setSelectedPersonalizedOffer,
  ]);
  // Lifted out of the carousel row: it needs cart state and store actions,
  // so it stays on the screen and the carousel simply calls it.
  const handleAddUpsellCombo = useCallback(
    (suggestion: ComboUpsellSuggestion) => {
      setInteractedUpsellComboIds(previous => {
        if (previous.has(suggestion.combo_id)) {
          return previous;
        }
        const next = new Set(previous);
        next.add(suggestion.combo_id);
        return next;
      });
      LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
      const addedMenuItemIds: string[] = [];
      for (const item of suggestion.missing_items) {
        const existing = cart.items.find(
          entry => entry.menuItem.id === item.menu_item_id,
        );
        if (existing) {
          continue;
        }
        addedMenuItemIds.push(item.menu_item_id);
        addToCart(
          buildMenuItemFromGeneratedComboItem(item, {
            source: 'cart-combo-upsell',
            restaurantId: suggestion.restaurant_id,
            restaurantLocationId: suggestion.restaurant_location_id,
            restaurantLocationName: suggestion.restaurant_location_name,
            restaurantCuisineType: null,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          }),
          suggestion.restaurant_id,
          suggestion.restaurant_name,
          {
            quantity: item.quantity,
            silent: true,
          },
        );
      }
      if (addedMenuItemIds.length > 0) {
        setRecentlyAddedComboItemIds(new Set(addedMenuItemIds));
        if (recentlyAddedComboItemsTimerRef.current) {
          clearTimeout(recentlyAddedComboItemsTimerRef.current);
        }
        recentlyAddedComboItemsTimerRef.current = setTimeout(() => {
          setRecentlyAddedComboItemIds(new Set());
        }, 1100);
      }
      pushToast('Combo extended', suggestion.message, 'success');
    },
    [addToCart, cart.items, pushToast],
  );
  const handleChangeDeliveryAddress = useCallback(() => {
    navigation.navigate('LocationSelect');
  }, [navigation]);

  const continueToPayment = async () => {
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

    if (!token) {
      return;
    }
    if (!cart.restaurantId) {
      return;
    }
    if (submitting) {
      return;
    }
    setSubmitting(true);
    try {
      if (requiresDeliveryAddress && !deliveryAddress.trim()) {
        pushToast(
          'Add delivery address',
          'Choose where the order should reach you before checkout.',
          'info',
        );
        navigation.navigate('LocationSelect');
        return;
      }
      const latestRestaurant = await refreshRestaurantSnapshot(true);
      if (!latestRestaurant) {
        pushToast(
          'Branch unavailable',
          'We could not refresh this branch right now. Please try again.',
          'error',
        );
        return;
      }
      const latestLocation =
        latestRestaurant.locations?.find(
          location => location.id === cart.restaurantLocationId,
        ) ??
        latestRestaurant.locations?.find(location => location.is_active) ??
        null;

      if (!latestLocation) {
        pushToast(
          'Branch unavailable',
          'This branch is no longer available for ordering.',
          'error',
        );
        return;
      }
      if (cart.scheduleType === 'SCHEDULED') {
        const scheduledStillValid = await validateScheduledSelection({
          force: true,
          openSheetOnInvalid: true,
          showFeedback: true,
        });
        if (!scheduledStillValid) {
          return;
        }
      }
      if (!activeFulfillmentAvailable) {
        pushToast(
          cart.fulfillmentType === 'DELIVERY'
            ? 'Delivery unavailable'
            : 'Pickup unavailable',
          activeFulfillmentReason ??
            'This branch cannot fulfill the selected order type right now.',
          'error',
        );
        return;
      }
      if (
        cart.scheduleType !== 'SCHEDULED' &&
        !isFulfillmentAvailableNow(latestLocation, cart.fulfillmentType)
      ) {
        pushToast(
          cart.fulfillmentType === 'DELIVERY'
            ? 'Delivery unavailable'
            : 'Pickup unavailable',
          getFulfillmentUnavailableReason(
            latestLocation,
            cart.fulfillmentType,
          ) ?? 'This branch cannot fulfill the selected order type right now.',
          'error',
        );
        return;
      }

      if ((latestLocation.enabled_payment_methods?.length ?? 0) === 0) {
        pushToast(
          'Payments unavailable',
          'This branch does not have any payment methods enabled right now.',
          'error',
        );
        return;
      }

      const validationPayload = {
        restaurant_id: cart.restaurantId,
        restaurant_location_id: cart.restaurantLocationId,
        personalized_offer_id:
          activePersonalizedOffer &&
          activeOfferPreview?.eligible &&
          !activePersonalizedOffer.generatedOfferId
            ? activePersonalizedOffer.offerId
            : null,
        generated_offer_id:
          activePersonalizedOffer && activeOfferPreview?.eligible
            ? activePersonalizedOffer.generatedOfferId
            : null,
        generated_offer_user_match_id:
          activePersonalizedOffer && activeOfferPreview?.eligible
            ? activePersonalizedOffer.generatedOfferUserMatchId
            : null,
        fulfillment_type: cart.fulfillmentType,
        schedule_type: cart.scheduleType,
        scheduled_at:
          cart.scheduleType === 'SCHEDULED' ? cart.scheduledAt : null,
        items: cart.items.map(item => ({
          menu_item_id: item.menuItem.id,
          menu_item_size_id: item.selectedSize?.id ?? null,
          selected_options: item.selectedOptions.map(option => ({
            option_id: option.optionId,
            quantity: option.quantity,
          })),
          quantity: item.quantity,
        })),
        delivery_address: checkoutAddress,
        special_instructions: instructions.trim() || null,
      };

      await api.validateOrder(token, validationPayload);

      navigation.navigate('Payment', {
        instructions,
        validatedAt: new Date().toISOString(),
      });
    } catch (error) {
      pushToast(
        'Update your cart',
        error instanceof ApiError || error instanceof Error
          ? error.message
          : 'We could not validate your order right now.',
        'error',
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (!token) {
    return <SafeAreaView edges={[]} style={styles.safeArea} />;
  }

  if (cart.items.length === 0) {
    return (
      <SafeAreaView edges={[]} style={styles.safeArea}>
        {/* No card frame and no "CART" eyebrow: the header above already says
            Cart, and a border around an empty state frames nothing. What was
            missing is the app's own empty-state shape - icon, title, line,
            action - which every other screen already uses. */}
        <View style={styles.emptyWrap}>
          <View style={styles.emptyIconRing}>
            <View style={styles.emptyIconCore}>
              <Icon
                color={theme.colors.primary}
                name="bag-handle-outline"
                size={30}
              />
            </View>
          </View>
          <Text style={styles.emptyTitle}>Your cart is empty</Text>
          <Text style={styles.emptyText}>
            Add a few dishes and they will line up here, ready for a fast
            checkout.
          </Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => navigation.navigate('MainTabs', { screen: 'Home' })}
            style={({ pressed }) => [
              styles.emptyButton,
              pressed && styles.emptyButtonPressed,
            ]}
          >
            <Icon color={theme.colors.white} name="search-outline" size={17} />
            <Text style={styles.emptyButtonText}>Browse restaurants</Text>
          </Pressable>
          {/* A second way out. From an empty cart the useful next step is
              often a past order to reorder from, not the whole menu again. */}
          <Pressable
            accessibilityRole="button"
            onPress={() => navigation.navigate('MainTabs', { screen: 'Orders' })}
            style={({ pressed }) => [
              styles.emptyLink,
              pressed && styles.emptyLinkPressed,
            ]}
          >
            <Text style={styles.emptyLinkText}>See your past orders</Text>
            <Icon
              color={theme.colors.secondaryText}
              name="chevron-forward"
              size={15}
            />
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={[]} style={styles.safeArea}>
      <View style={styles.screen}>
        <ScrollView
          contentContainerStyle={styles.content}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.cartHeader}>
            <View style={styles.cartHeaderTopRow}>
              <View style={styles.cartHeaderCopy}>
                <Text numberOfLines={1} style={styles.cartHeaderTitle}>
                  {cart.restaurantName}
                </Text>
                <Text numberOfLines={1} style={styles.cartHeaderSubtitle}>
                  {locationDisplayName}
                </Text>
              </View>
              <Pressable onPress={clearCart} style={styles.clearChip}>
                <Text style={styles.clearChipText}>Clear</Text>
              </Pressable>
            </View>
          </View>

          <CartFulfillmentCard
            activeFulfillmentAvailable={activeFulfillmentAvailable}
            activeFulfillmentReason={activeFulfillmentReason}
            deliveryAddress={deliveryAddress}
            deliveryEnabled={deliveryEnabled}
            fulfillmentChipLabel={fulfillmentChipLabel}
            fulfillmentType={cart.fulfillmentType}
            onChangeAddress={handleChangeDeliveryAddress}
            onFulfillmentModePress={handleFulfillmentModePress}
            onOpenFulfillmentSheet={handleOpenFulfillmentSheet}
            pickupAddress={pickupAddress}
            pickupEnabled={pickupEnabled}
            scheduleType={cart.scheduleType}
            showMissingDeliveryAddressWarning={
              showMissingDeliveryAddressWarning
            }
            timingLabel={timingLabel}
            timingSupportingLabel={timingSupportingLabel}
          />

          <CartOfferPalette
            activePersonalizedOffer={activePersonalizedOffer}
            offerCardWidth={offerCardWidth}
            offerPaletteLoading={offerPaletteLoading}
            offerPreviewsByCardId={offerPreviewsByCardId}
            restaurantOffers={restaurantOffers}
            setSelectedPersonalizedOffer={setSelectedPersonalizedOffer}
          />

          <View style={styles.itemsPanel}>
            <View style={styles.sectionHeader}>
              <View style={styles.sectionHeaderCopy}>
                <Text style={styles.sectionTitle}>Your items</Text>
                <Text style={styles.sectionSubtitle}>
                  Review quantities before checkout
                </Text>
              </View>
              <Text style={styles.sectionCount}>{itemCount}</Text>
            </View>

            <View style={styles.itemsColumn}>
              {cart.items.map(item => {
                const itemTotal = toNumber(item.unitPrice) * item.quantity;
                const customizationLines = formatCustomizationSummary(
                  item.selectedSize,
                  item.selectedOptions,
                );
                return (
                  <Reanimated.View
                    entering={
                      recentlyAddedComboItemIds.has(item.menuItem.id)
                        ? FadeInDown.duration(280)
                            .springify()
                            .damping(16)
                            .stiffness(180)
                        : undefined
                    }
                    key={item.id}
                    layout={LinearTransition.duration(220)}
                  >
                    <View style={styles.itemCard}>
                      <View style={styles.itemImageWrap}>
                        <Image
                          source={{
                            uri:
                              item.menuItem.image_url ??
                              placeholderImage(item.menuItem.name),
                          }}
                          style={styles.itemImage}
                        />
                        <View
                          style={[
                            styles.foodBadge,
                            item.menuItem.is_veg
                              ? styles.foodBadgeVeg
                              : styles.foodBadgeNonVeg,
                          ]}
                        >
                          <View
                            style={[
                              styles.foodDot,
                              item.menuItem.is_veg
                                ? styles.foodDotVeg
                                : styles.foodDotNonVeg,
                            ]}
                          />
                        </View>
                      </View>
                      <View style={styles.itemBody}>
                        <View style={styles.itemTitleRow}>
                          <Text numberOfLines={1} style={styles.itemTitle}>
                            {item.menuItem.name}
                          </Text>
                        </View>
                        <Text numberOfLines={1} style={styles.itemMeta}>
                          {item.menuItem.category}
                        </Text>
                        {customizationLines.length > 0 ? (
                          <Text style={styles.itemCustomizationMeta}>
                            {customizationLines.join(' • ')}
                          </Text>
                        ) : null}
                        <View style={styles.itemFooter}>
                          <View style={styles.itemPriceStack}>
                            <Text style={styles.itemPriceLabel}>Each</Text>
                            <Text style={styles.itemPrice}>
                              {formatCurrency(item.unitPrice)}
                            </Text>
                          </View>
                          <Text style={styles.itemTotal}>
                            {formatCurrency(itemTotal)}
                          </Text>
                        </View>
                      </View>
                      <View style={styles.quantityBox}>
                        <Pressable
                          onPress={() =>
                            updateCartQuantity(item.id, item.quantity - 1)
                          }
                          style={styles.quantityButton}
                        >
                          <Text style={styles.quantityAction}>−</Text>
                        </Pressable>
                        <Text style={styles.quantityCount}>
                          {item.quantity}
                        </Text>
                        <Pressable
                          onPress={() =>
                            updateCartQuantity(item.id, item.quantity + 1)
                          }
                          style={styles.quantityButton}
                        >
                          <Text style={styles.quantityAction}>+</Text>
                        </Pressable>
                      </View>
                    </View>
                  </Reanimated.View>
                );
              })}

              <CartUpsellCarousel
                interactedUpsellComboIds={interactedUpsellComboIds}
                onAddCombo={handleAddUpsellCombo}
                onViewableItemsChanged={onUpsellViewableItemsChanged}
                revealedUpsellComboIds={revealedUpsellComboIds}
                upsellCardWidth={upsellCardWidth}
                upsellSuggestions={upsellSuggestions}
                viewabilityConfig={upsellViewabilityConfigRef.current}
                visibleUpsellComboIds={visibleUpsellComboIds}
              />

              <Pressable
                accessibilityHint="Returns to the current restaurant menu without clearing your cart."
                accessibilityLabel="Add more items"
                onPress={handleAddMoreItems}
                style={styles.addMoreItemsRow}
              >
                <View style={styles.addMoreItemsCopy}>
                  <View style={styles.addMoreItemsTitleRow}>
                    <Icon
                      color={theme.colors.primary}
                      name="add-circle-outline"
                      size={16}
                    />
                    <Text style={styles.addMoreItemsTitle}>Add more items</Text>
                  </View>
                  <Text style={styles.addMoreItemsSubtitle}>
                    Browse more from this restaurant
                  </Text>
                </View>
                <Icon
                  color={theme.colors.primary}
                  name="chevron-forward"
                  size={16}
                />
              </Pressable>
            </View>
          </View>

          <View style={styles.formCard}>
            <Pressable
              accessibilityHint="Expands order details to add kitchen or rider instructions."
              accessibilityLabel="Order details"
              accessibilityRole="button"
              accessibilityState={{ expanded: orderDetailsExpanded }}
              onPress={toggleOrderDetails}
              style={styles.formAccordionHeader}
            >
              <View style={styles.formAccordionCopy}>
                <Text style={styles.formTitle}>Order details</Text>
                <Text style={styles.formSubtitle}>
                  Add kitchen or rider instructions
                </Text>
              </View>
              <Animated.View
                style={{
                  transform: [{ rotate: orderDetailsChevronRotation }],
                }}
              >
                <Icon color={theme.colors.hint} name="chevron-down" size={18} />
              </Animated.View>
            </Pressable>
            {orderDetailsExpanded ? (
              <View style={styles.formAccordionBody}>
                <TextInput
                  multiline
                  onChangeText={setInstructions}
                  placeholder="Special instructions for the kitchen or rider"
                  placeholderTextColor={theme.colors.hint}
                  style={[styles.input, styles.notesInput]}
                  value={instructions}
                />
              </View>
            ) : null}
          </View>

          <CartSummaryCard
            activePersonalizedOffer={activePersonalizedOffer}
            deliveryFee={deliveryFee}
            isMonetaryPersonalizedOffer={isMonetaryPersonalizedOffer}
            taxAmount={taxAmount}
            fulfillmentChipLabel={fulfillmentChipLabel}
            personalizedOfferRowValue={personalizedOfferRowValue}
            subtotal={subtotal}
            total={total}
          />
        </ScrollView>

        <View
          style={[
            styles.checkoutBar,
            {
              paddingBottom: insets.bottom,
            },
          ]}
        >
          <View style={styles.checkoutSummary}>
            <Text style={styles.checkoutCaption}>To pay</Text>
            <Text style={styles.checkoutAmount}>{formatCurrency(total)}</Text>
            <Text style={styles.checkoutMeta}>
              {savingsAmount > 0
                ? `You save ${formatCurrency(savingsAmount)} on this order`
                : `${itemCount} item${
                    itemCount === 1 ? '' : 's'
                  } · ${fulfillmentChipLabel}`}
            </Text>
          </View>
          <Pressable
            disabled={!canPlaceOrder}
            onPress={continueToPayment}
            style={[
              styles.checkoutButton,
              !canPlaceOrder && styles.checkoutButtonDisabled,
            ]}
          >
            <Text style={styles.checkoutButtonText}>
              {submitting ? 'Continuing...' : 'Continue to payment'}
            </Text>
          </Pressable>
        </View>
      </View>
      {cart.restaurantId && restaurantLocation ? (
        <FulfillmentSelectionSheet
          canDismiss
          initialSelection={
            fulfillmentSheetInitialSelection ?? fulfillmentSelection
          }
          location={restaurantLocation}
          onConfirm={selection => {
            if (
              selection.fulfillmentType === 'DELIVERY' &&
              !deliveryAddress.trim()
            ) {
              setPendingDeliverySelection(selection);
              setFulfillmentSheetInitialSelection(null);
              setFulfillmentSheetVisible(false);
              pushToast(
                'Add delivery address',
                'Choose where the order should reach you before switching to Delivery.',
                'info',
              );
              navigation.navigate('LocationSelect');
              return;
            }
            setCartFulfillmentSelection({
              restaurantId: cart.restaurantId,
              restaurantName: cart.restaurantName,
              restaurantLocationId: cart.restaurantLocationId,
              restaurantLocationName: cart.restaurantLocationName,
              fulfillmentType: selection.fulfillmentType,
              scheduleType: selection.scheduleType,
              scheduledAt: selection.scheduledAt,
            });
            setPendingDeliverySelection(null);
            setFulfillmentSheetInitialSelection(null);
            setFulfillmentSheetVisible(false);
          }}
          onDismiss={() => {
            setFulfillmentSheetInitialSelection(null);
            setFulfillmentSheetVisible(false);
          }}
          restaurantId={cart.restaurantId}
          token={token}
          visible={fulfillmentSheetVisible}
        />
      ) : null}
    </SafeAreaView>
  );
}
