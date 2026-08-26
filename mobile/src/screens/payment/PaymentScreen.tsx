import React, { useEffect, useMemo, useState } from 'react';
import {
  LayoutAnimation,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  UIManager,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  useNavigation,
  useRoute,
  type RouteProp,
} from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import {
  PaymentSheetError,
  initPaymentSheet,
  presentPaymentSheet,
} from '@stripe/stripe-react-native';
import {
  useAppActions,
  useCart,
  useSelectedLocation,
  useSelectedOffer,
  useSession,
} from '@hooks/useAppStore';
import { useAppForegroundEffect } from '@hooks/useAppForegroundEffect';
import { api, formatCurrency, toNumber, type ApiError } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type {
  FulfillmentSelection,
  OrderFulfillmentType,
  PaymentMethod,
  PaymentStatusResponse,
  PersonalizedOfferPreview,
  Restaurant,
  RestaurantLocation,
} from '@/types/app';
import type { RootStackParamList } from '@/navigation/AppNavigator';
import {
  formatFulfillmentSelectionLabel,
  formatScheduledAtLabel,
  getFulfillmentEtaLabel,
  getFulfillmentUnavailableReason,
  getScheduledSlotInvalidMessage,
  isFulfillmentAvailableNow,
  isScheduledSlotPresent,
} from '@utils/fulfillment';

type PaymentRoute = RouteProp<RootStackParamList, 'Payment'>;
type PaymentNav = NativeStackNavigationProp<RootStackParamList>;

/**
 * Methods this app can actually complete. GOOGLE_PAY and RAZORPAY remain valid
 * enum values for historical orders, but no gateway is wired for them, so they
 * are never offered — the backend rejects them too.
 */
const SUPPORTED_PAYMENT_METHODS: PaymentMethod[] = ['CARD', 'COD'];

const PAYMENT_COPY: Record<
  PaymentMethod,
  { label: string; caption: string; icon: string }
> = {
  GOOGLE_PAY: {
    label: 'Google Pay',
    caption: 'Unavailable',
    icon: 'logo-google',
  },
  RAZORPAY: {
    label: 'Razorpay',
    caption: 'Unavailable',
    icon: 'flash-outline',
  },
  CARD: {
    label: 'Pay by Card',
    caption: 'Secure checkout powered by Stripe',
    icon: 'card-outline',
  },
  COD: {
    label: 'Cash on Delivery',
    caption: 'Pay when your order arrives',
    icon: 'cash-outline',
  },
};

/** How long to wait for the payment webhook before letting the user move on. */
const PAYMENT_CONFIRM_TIMEOUT_MS = 12_000;
const PAYMENT_CONFIRM_POLL_MS = 1_200;

function buildPickupAddress(
  restaurant: Restaurant | null,
  location: RestaurantLocation | null,
  fallbackRestaurantName: string,
  fallbackLocationName: string | null,
): string {
  if (!restaurant) {
    return fallbackLocationName ?? fallbackRestaurantName;
  }

  return [
    location?.address_line_1 ?? restaurant.address_line_1,
    location?.address_line_2 ?? restaurant.address_line_2,
    location?.city ?? restaurant.city,
    location?.state ?? restaurant.state,
    location?.postal_code ?? restaurant.postal_code,
  ]
    .filter(Boolean)
    .join(', ');
}

function isOrderDraftValidationError(message: string): boolean {
  const normalized = message.toLowerCase();
  const paymentRelatedPhrases = [
    'payment confirmation is required',
    'payment method is not enabled',
    'payment failed',
    'payment cancelled',
    'payment gateway',
    'payment reference',
  ];
  if (paymentRelatedPhrases.some(phrase => normalized.includes(phrase))) {
    return false;
  }

  const orderValidationPhrases = [
    'select a size',
    'requires at least',
    'allows at most',
    'allows only one selection',
    'does not support customization',
    'does not support size selection',
    'unavailable customization',
    'unavailable items in cart',
    'minimum order amount',
    'restaurant is currently closed',
    'restaurant location',
    'branch does not have any payment methods enabled',
    'branch is unavailable',
    'delivery unavailable',
    'pickup unavailable',
    'scheduled time',
    'slot',
  ];

  return orderValidationPhrases.some(phrase => normalized.includes(phrase));
}

export function PaymentScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation = useNavigation<PaymentNav>();
  const route = useRoute<PaymentRoute>();
  const { token, user, appConfig } = useSession();
  const cart = useCart();
  const selectedLocation = useSelectedLocation();
  const selectedPersonalizedOffer = useSelectedOffer();
  const { clearCart, pushToast, setSelectedPersonalizedOffer } =
    useAppActions();
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [selectedPaymentMethod, setSelectedPaymentMethod] =
    useState<PaymentMethod | null>(null);
  const [scheduledSelectionValid, setScheduledSelectionValid] = useState(true);
  const [scheduledSelectionReason, setScheduledSelectionReason] = useState<
    string | null
  >(null);
  const [activeOfferPreview, setActiveOfferPreview] =
    useState<PersonalizedOfferPreview | null>(null);
  const [offerPreviewLoading, setOfferPreviewLoading] = useState(false);
  // An order that exists but whose card payment has not completed. Kept so a
  // retry pays the same order instead of creating a duplicate. Seeded from the
  // route when the customer comes back to it from their order list.
  const [pendingOrderId, setPendingOrderId] = useState<string | null>(
    route.params?.retryOrderId ?? null,
  );
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const [retryStatus, setRetryStatus] = useState<PaymentStatusResponse | null>(
    null,
  );
  const retryOnlyMode = Boolean(route.params?.retryOrderId);

  const restaurantLocation = useMemo(
    () =>
      restaurant?.locations?.find(
        location => location.id === cart.restaurantLocationId,
      ) ?? null,
    [cart.restaurantLocationId, restaurant?.locations],
  );
  const subtotal = useMemo(
    () =>
      cart.items.reduce(
        (total, item) => total + toNumber(item.unitPrice) * item.quantity,
        0,
      ),
    [cart.items],
  );
  const deliveryFee = useMemo(
    () =>
      cart.fulfillmentType === 'DELIVERY'
        ? toNumber(
            restaurantLocation?.delivery_fee ?? restaurant?.delivery_fee ?? 0,
          )
        : 0,
    [
      cart.fulfillmentType,
      restaurant?.delivery_fee,
      restaurantLocation?.delivery_fee,
    ],
  );
  const taxAmount = useMemo(() => subtotal * 0.05, [subtotal]);
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
  const personalizedOfferDiscount = useMemo(
    () =>
      activeOfferPreview?.eligible
        ? toNumber(activeOfferPreview.discount_amount)
        : 0,
    [activeOfferPreview],
  );
  const total = useMemo(
    () => subtotal + deliveryFee + taxAmount - personalizedOfferDiscount,
    [deliveryFee, personalizedOfferDiscount, subtotal, taxAmount],
  );
  const deliveryAddress = useMemo(
    () => selectedLocation?.address ?? user?.default_address ?? '',
    [selectedLocation?.address, user?.default_address],
  );
  const pickupAddress = useMemo(
    () =>
      buildPickupAddress(
        restaurant,
        restaurantLocation,
        cart.restaurantName ?? 'Selected restaurant',
        cart.restaurantLocationName,
      ),
    [
      cart.restaurantLocationName,
      cart.restaurantName,
      restaurant,
      restaurantLocation,
    ],
  );
  const requiresDeliveryAddress = cart.fulfillmentType === 'DELIVERY';
  const checkoutAddress = useMemo(
    () => (requiresDeliveryAddress ? deliveryAddress.trim() : pickupAddress),
    [deliveryAddress, pickupAddress, requiresDeliveryAddress],
  );
  const timingLabel = useMemo(
    () =>
      cart.scheduleType === 'SCHEDULED'
        ? formatScheduledAtLabel(cart.scheduledAt)
        : 'ASAP',
    [cart.scheduleType, cart.scheduledAt],
  );
  const fulfillmentSelection = useMemo<FulfillmentSelection>(
    () => ({
      fulfillmentType: cart.fulfillmentType,
      scheduleType: cart.scheduleType,
      scheduledAt: cart.scheduledAt,
    }),
    [cart.fulfillmentType, cart.scheduleType, cart.scheduledAt],
  );
  // The branch's own availability, narrowed to what this build can settle.
  // A branch advertising GOOGLE_PAY/RAZORPAY simply shows fewer options rather
  // than offering a button that the backend would reject.
  const enabledPaymentMethods = useMemo(
    () =>
      (restaurantLocation?.enabled_payment_methods ?? []).filter(method =>
        SUPPORTED_PAYMENT_METHODS.includes(method),
      ),
    [restaurantLocation?.enabled_payment_methods],
  );
  const activeFulfillmentAvailable = useMemo(
    () =>
      cart.scheduleType === 'SCHEDULED'
        ? scheduledSelectionValid && Boolean(cart.scheduledAt)
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
  const paymentSummaryLabel = useMemo(() => {
    if (!restaurantLocation) {
      return 'Refresh branch details';
    }
    return formatFulfillmentSelectionLabel(
      restaurantLocation,
      fulfillmentSelection,
    );
  }, [fulfillmentSelection, restaurantLocation]);
  const restaurantLocationName =
    cart.restaurantLocationName ??
    restaurantLocation?.branch_name ??
    'Main branch';
  const etaLabel = useMemo(
    () => getFulfillmentEtaLabel(restaurantLocation, cart.fulfillmentType),
    [cart.fulfillmentType, restaurantLocation],
  );
  const appliedOfferLabel = useMemo(() => {
    if (!activePersonalizedOffer || !activeOfferPreview?.eligible) {
      return null;
    }
    return (
      activePersonalizedOffer.discountLabel ??
      activeOfferPreview.discount_label ??
      activePersonalizedOffer.title
    );
  }, [
    activeOfferPreview?.discount_label,
    activeOfferPreview?.eligible,
    activePersonalizedOffer,
  ]);
  const canSubmit = useMemo(
    () =>
      !processing &&
      Boolean(restaurantLocation) &&
      enabledPaymentMethods.length > 0 &&
      Boolean(selectedPaymentMethod) &&
      activeFulfillmentAvailable &&
      (!requiresDeliveryAddress || Boolean(deliveryAddress.trim())),
    [
      activeFulfillmentAvailable,
      deliveryAddress,
      enabledPaymentMethods.length,
      processing,
      requiresDeliveryAddress,
      restaurantLocation,
      selectedPaymentMethod,
    ],
  );

  useEffect(() => {
    if (
      Platform.OS === 'android' &&
      UIManager.setLayoutAnimationEnabledExperimental
    ) {
      UIManager.setLayoutAnimationEnabledExperimental(true);
    }
  }, []);

  const refreshRestaurant = React.useCallback(
    async (showLoader: boolean = true) => {
      if (!token || !cart.restaurantId) {
        return null;
      }
      if (showLoader) {
        setLoading(true);
      }
      try {
        const nextRestaurant = await api.getRestaurant(
          cart.restaurantId,
          token,
        );
        setRestaurant(previous =>
          previous === nextRestaurant ? previous : nextRestaurant,
        );
        return nextRestaurant;
      } catch (error) {
        pushToast(
          'Unable to refresh payment',
          error instanceof Error
            ? error.message
            : 'We could not refresh this branch right now.',
          'error',
        );
        return null;
      } finally {
        if (showLoader) {
          setLoading(false);
        }
      }
    },
    [cart.restaurantId, pushToast, token],
  );

  const validateScheduledSelection = React.useCallback(
    async (showFeedback: boolean = false): Promise<boolean> => {
      if (
        cart.scheduleType !== 'SCHEDULED' ||
        !cart.restaurantId ||
        !cart.restaurantLocationId ||
        !cart.scheduledAt
      ) {
        setScheduledSelectionValid(cart.scheduleType !== 'SCHEDULED');
        setScheduledSelectionReason(null);
        return cart.scheduleType !== 'SCHEDULED';
      }

      try {
        const response = await api.getRestaurantLocationScheduleOptions(
          cart.restaurantId,
          cart.restaurantLocationId,
          cart.fulfillmentType,
          token,
        );
        const exists = isScheduledSlotPresent(response, cart.scheduledAt);
        const reason = exists ? null : getScheduledSlotInvalidMessage(response);
        setScheduledSelectionValid(exists);
        setScheduledSelectionReason(reason);
        if (!exists && showFeedback) {
          pushToast(
            'Choose another time',
            reason ??
              'Your selected slot is no longer available. Please choose another time.',
            'info',
          );
        }
        return exists;
      } catch (error) {
        if (showFeedback) {
          pushToast(
            'Unable to refresh time',
            error instanceof Error
              ? error.message
              : 'We could not validate the selected time right now.',
            'info',
          );
        }
        return false;
      }
    },
    [
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
    refreshRestaurant().catch(() => undefined);
  }, [refreshRestaurant]);

  useEffect(() => {
    validateScheduledSelection().catch(() => undefined);
  }, [validateScheduledSelection]);

  useAppForegroundEffect(() => {
    refreshRestaurant(false).catch(() => undefined);
    validateScheduledSelection(false).catch(() => undefined);
  });

  useEffect(() => {
    if (enabledPaymentMethods.length === 0) {
      setSelectedPaymentMethod(null);
      return;
    }
    setSelectedPaymentMethod(current =>
      current && enabledPaymentMethods.includes(current)
        ? current
        : enabledPaymentMethods[0],
    );
  }, [enabledPaymentMethods]);

  useEffect(() => {
    // Switching method clears a stale decline message from the other one.
    setPaymentError(null);
  }, [selectedPaymentMethod]);

  useEffect(() => {
    const retryOrderId = route.params?.retryOrderId;
    if (!token || !retryOrderId) {
      setRetryStatus(null);
      return;
    }

    let active = true;
    api
      .getOrderPaymentStatus(token, retryOrderId)
      .then(status => {
        if (!active) {
          return;
        }
        setRetryStatus(status);
        if (status.payment_status === 'PAID') {
          // Already settled elsewhere — nothing left to pay here.
          navigation.replace('OrderSuccess', { orderId: retryOrderId });
        }
      })
      .catch(() => {
        if (active) {
          setRetryStatus(null);
        }
      });

    return () => {
      active = false;
    };
  }, [navigation, route.params?.retryOrderId, token]);

  useEffect(() => {
    if (
      !token ||
      !activePersonalizedOffer ||
      !cart.restaurantId ||
      !cart.restaurantLocationId ||
      cart.items.length === 0
    ) {
      setActiveOfferPreview(null);
      return;
    }

    let active = true;
    setOfferPreviewLoading(true);
    api
      .previewPersonalizedOffer(token, {
        offer_id: activePersonalizedOffer.offerId,
        generated_offer_id: activePersonalizedOffer.generatedOfferId,
        generated_offer_user_match_id:
          activePersonalizedOffer.generatedOfferUserMatchId,
        restaurant_id: cart.restaurantId,
        restaurant_location_id: cart.restaurantLocationId,
        fulfillment_type: cart.fulfillmentType,
        items: cart.items.map(item => ({
          menu_item_id: item.menuItem.id,
          menu_item_size_id: item.selectedSize?.id ?? null,
          selected_options: item.selectedOptions.map(option => ({
            option_id: option.optionId,
            quantity: option.quantity,
          })),
          quantity: item.quantity,
        })),
      })
      .then(preview => {
        if (!active) {
          return;
        }
        setActiveOfferPreview(preview);
        if (!preview.eligible) {
          setSelectedPersonalizedOffer(null);
        }
      })
      .catch(() => {
        if (active) {
          setActiveOfferPreview(null);
        }
      })
      .finally(() => {
        if (active) {
          setOfferPreviewLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [
    activePersonalizedOffer,
    cart.fulfillmentType,
    cart.items,
    cart.restaurantId,
    cart.restaurantLocationId,
    setSelectedPersonalizedOffer,
    token,
  ]);

  const selectPaymentMethod = (method: PaymentMethod) => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setSelectedPaymentMethod(method);
  };

  /**
   * Waits for the Stripe webhook to reach our backend.
   *
   * The PaymentSheet result says the customer's side finished; only the server
   * knows whether the charge settled, so the order is not treated as paid until
   * `payment_status` flips. A timeout is not a failure — the webhook may simply
   * be slow, and the order screen re-fetches on focus.
   */
  const waitForPaymentConfirmation = async (
    orderId: string,
  ): Promise<boolean> => {
    if (!token) {
      return false;
    }
    const deadline = Date.now() + PAYMENT_CONFIRM_TIMEOUT_MS;
    while (Date.now() < deadline) {
      try {
        const status = await api.getOrderPaymentStatus(token, orderId);
        if (status.payment_status === 'PAID') {
          return true;
        }
        if (status.payment_status === 'FAILED') {
          setPaymentError(
            status.failure_message ?? 'The payment could not be completed.',
          );
          return false;
        }
      } catch {
        // Keep polling; a transient network error is not a payment failure.
      }
      await new Promise<void>(resolve => {
        setTimeout(resolve, PAYMENT_CONFIRM_POLL_MS);
      });
    }
    return false;
  };

  /**
   * Presents the Stripe payment sheet for an existing order.
   *
   * Returns true only when the charge is confirmed server-side. On cancel or
   * failure the order is left in PAYMENT_PENDING so the same order can be
   * retried — no duplicate orders, and the cart is never cleared.
   */
  const runCardPayment = async (orderId: string): Promise<boolean> => {
    if (!token) {
      return false;
    }

    const intent = await api.createPaymentIntent(token, orderId);

    const { error: initError } = await initPaymentSheet({
      merchantDisplayName: appConfig?.display_name ?? 'QuickBite',
      paymentIntentClientSecret: intent.client_secret,
      allowsDelayedPaymentMethods: false,
      defaultBillingDetails: {
        name: user?.full_name ?? undefined,
        email: user?.email ?? undefined,
      },
    });
    if (initError) {
      setPaymentError(initError.message);
      pushToast('Payment unavailable', initError.message, 'error');
      return false;
    }

    const { error: sheetError } = await presentPaymentSheet();
    if (sheetError) {
      const cancelled = sheetError.code === PaymentSheetError.Canceled;
      if (cancelled) {
        await api.cancelOrderPayment(token, orderId).catch(() => undefined);
        setPaymentError(null);
        pushToast(
          'Payment cancelled',
          'Your order is saved — you can complete the payment when ready.',
          'info',
        );
      } else {
        setPaymentError(sheetError.message);
        pushToast('Payment failed', sheetError.message, 'error');
      }
      return false;
    }

    const confirmed = await waitForPaymentConfirmation(orderId);
    if (!confirmed && paymentError) {
      return false;
    }
    // A confirmation timeout still means the customer paid; the webhook will
    // land and the order screen reflects it.
    return true;
  };

  /** Pays an order that already exists, without touching the cart. */
  const handleRetryPendingPayment = async () => {
    if (!token || !pendingOrderId) {
      return;
    }
    setProcessing(true);
    setPaymentError(null);
    try {
      const paid = await runCardPayment(pendingOrderId);
      if (!paid) {
        return;
      }
      const paidOrderId = pendingOrderId;
      setPendingOrderId(null);
      pushToast(
        'Payment successful',
        'Payment is complete and your order is now live.',
        'success',
      );
      navigation.replace('OrderSuccess', { orderId: paidOrderId });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Unable to complete payment.';
      setPaymentError(message);
      pushToast('Payment failed', message, 'error');
    } finally {
      setProcessing(false);
    }
  };

  const handlePlaceOrder = async () => {
    if (!token) {
      return;
    }
    if (!cart.restaurantId || !cart.restaurantLocationId) {
      pushToast(
        'Cart unavailable',
        'We could not find the current branch for this order.',
        'error',
      );
      return;
    }
    if (!selectedPaymentMethod) {
      pushToast(
        'Select a payment method',
        'Choose how you want to pay before placing the order.',
        'info',
      );
      return;
    }
    if (requiresDeliveryAddress && !deliveryAddress.trim()) {
      pushToast(
        'Add delivery address',
        'Choose where the order should reach you before checkout.',
        'error',
      );
      return;
    }

    const latestRestaurant = await refreshRestaurant(false);
    const latestLocation =
      latestRestaurant?.locations?.find(
        location => location.id === cart.restaurantLocationId,
      ) ?? restaurantLocation;
    if (!latestLocation) {
      pushToast(
        'Branch unavailable',
        'This branch is no longer available for ordering.',
        'error',
      );
      return;
    }
    if (
      !latestLocation.enabled_payment_methods.includes(selectedPaymentMethod)
    ) {
      setSelectedPaymentMethod(
        latestLocation.enabled_payment_methods[0] ?? null,
      );
      pushToast(
        'Payment method unavailable',
        'This branch no longer supports that payment method. Please choose another one.',
        'error',
      );
      return;
    }
    if (cart.scheduleType === 'SCHEDULED') {
      const valid = await validateScheduledSelection(true);
      if (!valid) {
        return;
      }
    } else if (
      !isFulfillmentAvailableNow(latestLocation, cart.fulfillmentType)
    ) {
      pushToast(
        cart.fulfillmentType === 'DELIVERY'
          ? 'Delivery unavailable'
          : 'Pickup unavailable',
        getFulfillmentUnavailableReason(latestLocation, cart.fulfillmentType) ??
          'This branch cannot fulfill the selected order type right now.',
        'error',
      );
      return;
    }

    setProcessing(true);
    setPaymentError(null);
    try {
      // A card order that already exists is retried, not re-created, so a
      // decline followed by a retry never leaves two orders behind.
      if (pendingOrderId && selectedPaymentMethod === 'CARD') {
        const paid = await runCardPayment(pendingOrderId);
        if (!paid) {
          return;
        }
        const paidOrderId = pendingOrderId;
        setPendingOrderId(null);
        clearCart();
        pushToast(
          'Payment successful',
          'Payment is complete and your order is now live.',
          'success',
        );
        navigation.replace('OrderSuccess', { orderId: paidOrderId });
        return;
      }

      const orderPayload = {
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
        special_instructions: route.params?.instructions?.trim() || null,
        payment_method: selectedPaymentMethod,
      };
      const createdOrder = await api.placeOrder(token, orderPayload);

      if (selectedPaymentMethod === 'CARD') {
        // The order exists but is unpaid; hold onto it so a retry reuses it.
        setPendingOrderId(createdOrder.id);
        const paid = await runCardPayment(createdOrder.id);
        if (!paid) {
          // Cart deliberately survives: the customer can try again.
          return;
        }
        setPendingOrderId(null);
      }

      clearCart();
      pushToast(
        selectedPaymentMethod === 'COD' ? 'Order placed' : 'Payment successful',
        selectedPaymentMethod === 'COD'
          ? 'The order is live and ready to track.'
          : 'Payment is complete and your order is now live.',
        'success',
      );
      navigation.replace('OrderSuccess', { orderId: createdOrder.id });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Unable to place order.';
      if (isOrderDraftValidationError(message)) {
        navigation.goBack();
        setTimeout(() => {
          pushToast('Update your cart', message, 'error');
        }, 0);
      } else {
        pushToast('Payment failed', message, 'error');
      }
    } finally {
      setProcessing(false);
    }
  };

  // Arriving from an unpaid order in the order list: there is nothing to
  // configure, only a charge to complete, so the checkout form is skipped.
  if (retryOnlyMode) {
    return (
      <SafeAreaView edges={['bottom']} style={styles.safeArea}>
        <View style={styles.emptyWrap}>
          <Text style={styles.emptyTitle}>Complete your payment</Text>
          <Text style={styles.emptyText}>
            {retryStatus
              ? `This order is saved and waiting for a payment of ${formatCurrency(
                  toNumber(retryStatus.amount),
                )}.`
              : 'This order is saved and waiting for payment.'}
          </Text>
          {paymentError ? (
            <View style={styles.paymentErrorBanner}>
              <Icon
                color={theme.colors.deepRed}
                name="alert-circle-outline"
                size={15}
              />
              <Text style={styles.paymentErrorText}>{paymentError}</Text>
            </View>
          ) : null}
          <Pressable
            disabled={processing || retryStatus?.is_payable === false}
            onPress={handleRetryPendingPayment}
            style={[
              styles.primaryButton,
              processing || retryStatus?.is_payable === false
                ? styles.primaryButtonDisabled
                : null,
            ]}
          >
            <Text style={styles.primaryButtonText}>
              {processing ? 'Processing payment...' : 'Pay now'}
            </Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  if (cart.items.length === 0) {
    return (
      <SafeAreaView edges={['bottom']} style={styles.safeArea}>
        <View style={styles.emptyWrap}>
          <Text style={styles.emptyTitle}>Your cart is empty.</Text>
          <Text style={styles.emptyText}>
            Add a few dishes first, then come back here to pay.
          </Text>
          <Pressable
            onPress={() => navigation.navigate('MainTabs', { screen: 'Home' })}
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonText}>Browse restaurants</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <View style={styles.screen}>
        <ScrollView
          contentContainerStyle={styles.content}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.heroCard}>
            <Text style={styles.eyebrow}>Checkout</Text>
            <Text style={styles.heroTitle}>Choose your payment method</Text>
            <Text style={styles.heroSubtitle}>
              Your cart already has the full order review.
            </Text>
          </View>

          <View style={styles.summaryCard}>
            <View style={styles.summaryCopy}>
              <Text numberOfLines={1} style={styles.summaryRestaurantName}>
                {cart.restaurantName}
              </Text>
              <Text numberOfLines={1} style={styles.summaryBranchName}>
                {restaurantLocationName}
              </Text>
            </View>

            <View style={styles.summaryMetaGroup}>
              <Text style={styles.summaryModeText}>
                {paymentSummaryLabel}
                {cart.scheduleType === 'ASAP' ? ` • ${etaLabel}` : ''}
              </Text>
              {requiresDeliveryAddress ? (
                <Text numberOfLines={3} style={styles.summaryAddressText}>
                  {checkoutAddress}
                </Text>
              ) : null}
            </View>

            <View style={styles.summaryAmountRow}>
              <Text style={styles.summaryAmountLabel}>Amount to pay</Text>
              <Text style={styles.summaryAmountValue}>
                {formatCurrency(total)}
              </Text>
            </View>

            {activePersonalizedOffer ? (
              <View style={styles.offerPill}>
                <View style={styles.offerPillCopy}>
                  <Text style={styles.offerPillLabel}>Applied offer</Text>
                  <Text numberOfLines={1} style={styles.offerPillTitle}>
                    {appliedOfferLabel ?? activePersonalizedOffer.title}
                  </Text>
                </View>
                <Text style={styles.offerPillValue}>
                  {offerPreviewLoading
                    ? 'Checking...'
                    : `- ${formatCurrency(personalizedOfferDiscount)}`}
                </Text>
              </View>
            ) : null}

            {activeFulfillmentReason && !activeFulfillmentAvailable ? (
              <View style={styles.warningPill}>
                <Icon
                  color={theme.colors.warning}
                  name="alert-circle-outline"
                  size={14}
                />
                <Text style={styles.warningText}>
                  {activeFulfillmentReason}
                </Text>
              </View>
            ) : null}
          </View>

          <View style={styles.panel}>
            <Text style={styles.panelTitle}>Payment methods</Text>
            {enabledPaymentMethods.length === 0 ? (
              <View style={styles.emptyPaymentState}>
                <Text style={styles.emptyPaymentTitle}>
                  No payment methods enabled
                </Text>
                <Text style={styles.emptyPaymentText}>
                  This branch needs at least one payment option enabled before
                  checkout can continue.
                </Text>
              </View>
            ) : (
              <View style={styles.paymentMethodList}>
                {enabledPaymentMethods.map(method => {
                  const methodCopy = PAYMENT_COPY[method];
                  const selected = selectedPaymentMethod === method;

                  return (
                    <View
                      key={method}
                      style={[
                        styles.paymentMethodCard,
                        selected ? styles.paymentMethodCardSelected : null,
                      ]}
                    >
                      <Pressable
                        onPress={() => selectPaymentMethod(method)}
                        style={styles.paymentMethodRow}
                      >
                        <View
                          style={[
                            styles.paymentMethodIcon,
                            selected ? styles.paymentMethodIconSelected : null,
                          ]}
                        >
                          <Icon
                            color={
                              selected
                                ? theme.colors.onPrimary
                                : theme.colors.primary
                            }
                            name={methodCopy.icon}
                            size={18}
                          />
                        </View>
                        <View style={styles.paymentMethodCopy}>
                          <Text style={styles.paymentMethodTitle}>
                            {methodCopy.label}
                          </Text>
                          <Text style={styles.paymentMethodSubtitle}>
                            {methodCopy.caption}
                          </Text>
                        </View>
                        {selected ? (
                          <Icon
                            color={theme.colors.primary}
                            name="checkmark-circle"
                            size={20}
                          />
                        ) : null}
                      </Pressable>
                      {selected && method === 'CARD' ? (
                        <View style={styles.cardNotice}>
                          <Icon
                            color={theme.colors.primary}
                            name="lock-closed-outline"
                            size={14}
                          />
                          <Text style={styles.cardNoticeText}>
                            Card details are entered in Stripe's secure sheet on
                            the next step. We never see or store your card.
                          </Text>
                        </View>
                      ) : null}
                    </View>
                  );
                })}
              </View>
            )}
          </View>
        </ScrollView>

        <View style={styles.footer}>
          {paymentError ? (
            <View style={styles.paymentErrorBanner}>
              <Icon
                color={theme.colors.deepRed}
                name="alert-circle-outline"
                size={15}
              />
              <Text style={styles.paymentErrorText}>{paymentError}</Text>
            </View>
          ) : null}
          {pendingOrderId && !paymentError ? (
            <View style={styles.paymentPendingBanner}>
              <Icon
                color={theme.colors.primary}
                name="time-outline"
                size={15}
              />
              <Text style={styles.paymentPendingText}>
                Your order is saved and waiting for payment.
              </Text>
            </View>
          ) : null}
          <View style={styles.footerRow}>
            <View style={styles.footerCopy}>
              <Text style={styles.footerLabel}>To pay</Text>
              <Text style={styles.footerAmount}>{formatCurrency(total)}</Text>
            </View>
            <Pressable
              disabled={!canSubmit || loading}
              onPress={handlePlaceOrder}
              style={[
                styles.primaryButton,
                !canSubmit || loading ? styles.primaryButtonDisabled : null,
              ]}
            >
              <Text style={styles.primaryButtonText}>
                {processing
                  ? selectedPaymentMethod === 'COD'
                    ? 'Placing order...'
                    : 'Processing payment...'
                  : selectedPaymentMethod === 'COD'
                  ? 'Place order'
                  : pendingOrderId
                  ? 'Retry payment'
                  : 'Pay now'}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </SafeAreaView>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    screen: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    content: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 10,
      paddingBottom: 112,
      gap: 10,
    },
    heroCard: {
      borderRadius: 20,
      paddingHorizontal: 14,
      paddingVertical: 12,
      gap: 4,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceRaised : theme.tone('#FFF4EC'),
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : theme.primaryTint(0.08),
    },
    eyebrow: {
      color: theme.colors.primary,
      fontSize: 10,
      fontWeight: '800',
      textTransform: 'uppercase',
      letterSpacing: 0.4,
    },
    heroTitle: {
      color: theme.colors.text,
      fontSize: 19,
      lineHeight: 23,
      fontWeight: '900',
    },
    heroSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 11.5,
      lineHeight: 16,
    },
    panel: {
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 12,
      gap: 10,
    },
    panelTitle: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    summaryCard: {
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      paddingHorizontal: 12,
      paddingVertical: 11,
      gap: 9,
    },
    summaryCopy: {
      gap: 1,
    },
    summaryRestaurantName: {
      color: theme.colors.text,
      fontSize: 16.5,
      lineHeight: 20,
      fontWeight: '900',
    },
    summaryBranchName: {
      color: theme.colors.secondaryText,
      fontSize: 11.5,
      lineHeight: 15,
      fontWeight: '700',
    },
    summaryMetaGroup: {
      gap: 3,
    },
    summaryModeText: {
      color: theme.colors.text,
      fontSize: 12.5,
      lineHeight: 16,
      fontWeight: '700',
    },
    summaryAddressText: {
      color: theme.colors.secondaryText,
      fontSize: 11.5,
      lineHeight: 16,
      fontWeight: '600',
    },
    summaryAmountRow: {
      flexDirection: 'row',
      alignItems: 'baseline',
      justifyContent: 'space-between',
      gap: 10,
    },
    summaryAmountLabel: {
      color: theme.colors.hint,
      fontSize: 10.5,
      fontWeight: '800',
      textTransform: 'uppercase',
      letterSpacing: 0.2,
    },
    summaryAmountValue: {
      color: theme.colors.primary,
      fontSize: 20,
      lineHeight: 23,
      fontWeight: '900',
    },
    warningPill: {
      minHeight: 30,
      borderRadius: 15,
      paddingHorizontal: 10,
      paddingVertical: 6,
      backgroundColor: theme.colors.warningSoft,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    warningText: {
      flex: 1,
      color: theme.colors.warning,
      fontSize: 11,
      lineHeight: 15,
      fontWeight: '700',
    },
    offerPill: {
      borderRadius: 15,
      paddingHorizontal: 11,
      paddingVertical: 9,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : 'rgba(72, 196, 121, 0.10)',
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark'
          ? theme.colors.border
          : 'rgba(72, 196, 121, 0.14)',
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10,
    },
    offerPillCopy: {
      flex: 1,
      gap: 2,
      minWidth: 0,
    },
    offerPillLabel: {
      color: theme.colors.hint,
      fontSize: 9.5,
      fontWeight: '800',
      textTransform: 'uppercase',
      letterSpacing: 0.3,
    },
    offerPillTitle: {
      color: theme.colors.text,
      fontSize: 12,
      fontWeight: '800',
    },
    offerPillValue: {
      color: theme.colors.success,
      fontSize: 12,
      fontWeight: '900',
    },
    paymentMethodList: {
      gap: 8,
    },
    paymentMethodCard: {
      borderRadius: 15,
      borderWidth: 1,
      borderColor: theme.colors.border,
      paddingHorizontal: 11,
      paddingVertical: 10,
      backgroundColor: theme.colors.surface,
      gap: 10,
    },
    paymentMethodCardSelected: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primarySoft,
    },
    paymentMethodRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
    },
    paymentMethodIcon: {
      width: 34,
      height: 34,
      borderRadius: 17,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : theme.primaryTint(0.08),
    },
    paymentMethodIconSelected: {
      backgroundColor: theme.colors.primary,
    },
    paymentMethodCopy: {
      flex: 1,
      gap: 1,
    },
    paymentMethodTitle: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    paymentMethodSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 11,
      lineHeight: 14,
    },
    cardNotice: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 7,
      borderTopWidth: 1,
      borderTopColor:
        theme.mode === 'dark' ? theme.colors.border : theme.primaryTint(0.08),
      paddingTop: 10,
    },
    cardNoticeText: {
      flex: 1,
      color: theme.colors.secondaryText,
      fontSize: 11,
      lineHeight: 16,
    },
    emptyPaymentState: {
      borderRadius: 18,
      padding: 14,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : theme.colors.cream,
      gap: 5,
    },
    emptyPaymentTitle: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
    },
    emptyPaymentText: {
      color: theme.colors.secondaryText,
      fontSize: 11,
      lineHeight: 16,
    },
    footer: {
      position: 'absolute',
      left: 0,
      right: 0,
      bottom: 0,
      gap: 8,
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 10,
      paddingBottom: 14,
      backgroundColor:
        theme.mode === 'dark'
          ? 'rgba(14, 17, 22, 0.96)'
          : 'rgba(255, 255, 255, 0.96)',
      borderTopWidth: 1,
      borderTopColor: theme.colors.border,
    },
    footerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
    },
    paymentErrorBanner: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 7,
      borderRadius: 12,
      paddingHorizontal: 10,
      paddingVertical: 7,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : 'rgba(203,32,45,0.08)',
    },
    paymentErrorText: {
      flex: 1,
      color: theme.colors.deepRed,
      fontSize: 11.5,
      lineHeight: 16,
      fontWeight: '700',
    },
    paymentPendingBanner: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 7,
      borderRadius: 12,
      paddingHorizontal: 10,
      paddingVertical: 7,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : theme.colors.primarySoft,
    },
    paymentPendingText: {
      flex: 1,
      color: theme.colors.secondaryText,
      fontSize: 11.5,
      lineHeight: 16,
      fontWeight: '700',
    },
    footerCopy: {
      flex: 1,
      gap: 1,
    },
    footerLabel: {
      color: theme.colors.secondaryText,
      fontSize: 10,
      fontWeight: '700',
      textTransform: 'uppercase',
      letterSpacing: 0.3,
    },
    footerAmount: {
      color: theme.colors.text,
      fontSize: 20,
      fontWeight: '900',
    },
    primaryButton: {
      minHeight: 48,
      borderRadius: 16,
      backgroundColor: theme.colors.primary,
      paddingHorizontal: 18,
      alignItems: 'center',
      justifyContent: 'center',
    },
    primaryButtonDisabled: {
      opacity: 0.5,
    },
    primaryButtonText: {
      color: theme.colors.onPrimary,
      fontSize: 14,
      fontWeight: '900',
    },
    emptyWrap: {
      flex: 1,
      paddingHorizontal: theme.spacing.screen,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 12,
    },
    emptyTitle: {
      color: theme.colors.text,
      fontSize: 22,
      fontWeight: '900',
      textAlign: 'center',
    },
    emptyText: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 20,
      textAlign: 'center',
    },
  });

