import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api, formatCurrency, toNumber } from '../services/api';
import { useAppStore } from '../hooks/useAppStore';
import { checkAuthAndRedirect } from '../utils/authRedirect';
import type { ComboUpsellSuggestion, PersonalizedOfferPreview, Restaurant } from '../types/app';
import { buildMenuItemFromGeneratedComboItem } from '../utils/generatedComboCart';
import type { RestaurantLocation } from '../types/app';
import { formatCustomizationSummary } from '../utils/menuItemCustomization';
import {
  getFulfillmentEtaLabel,
  getFulfillmentUnavailableReason,
  isFulfillmentAvailableNow,
  isFulfillmentEnabled,
} from '../utils/fulfillment';

interface CartPageProps {
  onNavigate: (path: string) => void;
}

export function CartPage({ onNavigate }: CartPageProps) {
  const {
    addToCart,
    cart,
    clearCart,
    isAuthenticated,
    pushToast,
    selectedPersonalizedOffer,
    setSelectedPersonalizedOffer,
    setCartFulfillmentType,
    setPendingAuthRedirectPath,
    token,
    updateCartQuantity,
    user,
  } = useAppStore();
  const [deliveryAddress, setDeliveryAddress] = useState(user?.default_address ?? '');
  const [editingDeliveryAddress, setEditingDeliveryAddress] = useState(!(user?.default_address ?? '').trim());
  const [specialInstructions, setSpecialInstructions] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [upsellSuggestions, setUpsellSuggestions] = useState<ComboUpsellSuggestion[]>([]);
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [offerPreview, setOfferPreview] = useState<PersonalizedOfferPreview | null>(null);
  const [offerPreviewLoading, setOfferPreviewLoading] = useState(false);
  const hasRequestedAuthRef = useRef(false);
  const restaurantLocation: RestaurantLocation | null = useMemo(
    () =>
      restaurant?.locations?.find((location) => location.id === cart.restaurantLocationId)
      ?? restaurant?.locations?.find((location) => location.is_active)
      ?? null,
    [cart.restaurantLocationId, restaurant?.locations],
  );

  useEffect(() => {
    if (deliveryAddress.trim()) {
      return;
    }
    setDeliveryAddress(user?.default_address ?? '');
  }, [deliveryAddress, user?.default_address]);

  useEffect(() => {
    if (isAuthenticated) {
      hasRequestedAuthRef.current = false;
      return;
    }

    if (hasRequestedAuthRef.current) {
      return;
    }

    hasRequestedAuthRef.current = true;

    checkAuthAndRedirect({
      isAuthenticated,
      redirectPath: '/cart',
      onNavigate,
      pushToast,
      setPendingAuthRedirectPath,
    });
  }, [isAuthenticated, onNavigate, pushToast, setPendingAuthRedirectPath]);

  useEffect(() => {
    let active = true;

    async function loadUpsellSuggestions() {
      if (!cart.restaurantId || cart.items.length === 0) {
        if (active) {
          setUpsellSuggestions([]);
        }
        return;
      }

      const latestItem = cart.items[cart.items.length - 1];
      try {
        const rows = await api.getCartUpsellSuggestions({
          restaurantId: cart.restaurantId,
          locationId: cart.restaurantLocationId,
          itemId: latestItem.menuItem.id,
          cartItemIds: cart.items.map((item) => item.menuItem.id),
          limit: 2,
        });
        if (active) {
          setUpsellSuggestions(rows);
        }
      } catch {
        if (active) {
          setUpsellSuggestions([]);
        }
      }
    }

    void loadUpsellSuggestions();

    return () => {
      active = false;
    };
  }, [cart.items, cart.restaurantId]);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    async function loadRestaurant() {
      if (!cart.restaurantId) {
        if (active) {
          setRestaurant(null);
        }
        return;
      }

      try {
        const nextRestaurant = await api.getRestaurant(cart.restaurantId, controller.signal);
        if (active) {
          setRestaurant(nextRestaurant);
        }
      } catch {
        if (active) {
          setRestaurant(null);
        }
      }
    }

    void loadRestaurant();
    return () => {
      active = false;
      controller.abort();
    };
  }, [cart.restaurantId]);

  const subtotal = useMemo(
    () => cart.items.reduce((total, item) => total + toNumber(item.unitPrice) * item.quantity, 0),
    [cart.items],
  );
  const activePersonalizedOffer = useMemo(
    () => (
      selectedPersonalizedOffer
      && selectedPersonalizedOffer.restaurantId === cart.restaurantId
      && (
        !selectedPersonalizedOffer.offerRestaurantLocationId
        || selectedPersonalizedOffer.offerRestaurantLocationId === cart.restaurantLocationId
      )
        ? selectedPersonalizedOffer
        : null
    ),
    [cart.restaurantId, cart.restaurantLocationId, selectedPersonalizedOffer],
  );
  const personalizedOfferDiscount = useMemo(
    () => (offerPreview?.eligible ? toNumber(offerPreview.discount_amount) : 0),
    [offerPreview],
  );
  const isMonetaryPersonalizedOffer = useMemo(
    () => activePersonalizedOffer?.discountType !== 'NONE',
    [activePersonalizedOffer],
  );
  const amountToUnlock = useMemo(
    () => toNumber(offerPreview?.amount_to_unlock ?? 0),
    [offerPreview?.amount_to_unlock],
  );
  const offerBannerSubtitle = useMemo(() => {
    if (!activePersonalizedOffer) {
      return null;
    }
    if (offerPreviewLoading) {
      return 'Validating offer for your cart...';
    }
    if (personalizedOfferDiscount > 0) {
      return offerPreview?.message ?? 'Discount applied to this cart.';
    }
    if (offerPreview?.eligible) {
      return isMonetaryPersonalizedOffer
        ? offerPreview?.message ?? 'Offer is eligible for this cart.'
        : activePersonalizedOffer.termsLabel ?? offerPreview?.message ?? 'Offer active for this cart.';
    }
    return offerPreview?.message ?? activePersonalizedOffer.termsLabel ?? 'Offer needs a qualifying cart.';
  }, [
    activePersonalizedOffer,
    isMonetaryPersonalizedOffer,
    offerPreview,
    offerPreviewLoading,
    personalizedOfferDiscount,
  ]);
  const offerBadgeLabel = useMemo(() => {
    if (!activePersonalizedOffer) {
      return null;
    }
    if (offerPreviewLoading) {
      return 'Checking offer';
    }
    if (personalizedOfferDiscount > 0) {
      return activePersonalizedOffer.discountLabel ?? 'Discount applied';
    }
    if (isMonetaryPersonalizedOffer) {
      return activePersonalizedOffer.discountLabel ?? 'Offer active';
    }
    return 'Offer active';
  }, [
    activePersonalizedOffer,
    isMonetaryPersonalizedOffer,
    offerPreviewLoading,
    personalizedOfferDiscount,
  ]);
  const personalizedOfferRowValue = useMemo(() => {
    if (!activePersonalizedOffer || !isMonetaryPersonalizedOffer) {
      return null;
    }
    if (offerPreviewLoading) {
      return 'Checking...';
    }
    if (personalizedOfferDiscount > 0) {
      return `- ${formatCurrency(personalizedOfferDiscount)}`;
    }
    if (amountToUnlock > 0) {
      return `Add ${formatCurrency(amountToUnlock)} more`;
    }
    return offerPreview?.message ?? `Unlock at ${formatCurrency(activePersonalizedOffer.minimumOrderAmount)}`;
  }, [
    activePersonalizedOffer,
    amountToUnlock,
    isMonetaryPersonalizedOffer,
    offerPreview?.message,
    offerPreviewLoading,
    personalizedOfferDiscount,
  ]);
  const deliveryFee = useMemo(
    () => (
      cart.items.length > 0 && cart.fulfillmentType === 'DELIVERY'
        ? toNumber(restaurantLocation?.delivery_fee ?? restaurant?.delivery_fee ?? 0)
        : 0
    ),
    [cart.fulfillmentType, cart.items.length, restaurant?.delivery_fee, restaurantLocation?.delivery_fee],
  );
  const taxAmount = useMemo(() => subtotal * 0.05, [subtotal]);
  const total = subtotal + deliveryFee + taxAmount - personalizedOfferDiscount;
  const pickupAddress = useMemo(() => {
    if (!restaurant) {
      return cart.restaurantLocationName ?? cart.restaurantName ?? 'Pickup details will appear here.';
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
  }, [cart.restaurantLocationName, cart.restaurantName, restaurant, restaurantLocation]);
  const selectedDeliveryAddress = deliveryAddress.trim();
  const requiresDeliveryAddress = cart.fulfillmentType === 'DELIVERY';
  const checkoutAddress = requiresDeliveryAddress ? selectedDeliveryAddress : pickupAddress;
  const deliveryEnabled = useMemo(
    () => isFulfillmentEnabled(restaurantLocation, 'DELIVERY'),
    [restaurantLocation],
  );
  const pickupEnabled = useMemo(
    () => isFulfillmentEnabled(restaurantLocation, 'PICKUP'),
    [restaurantLocation],
  );
  const activeFulfillmentAvailable = useMemo(
    () => isFulfillmentAvailableNow(restaurantLocation, cart.fulfillmentType),
    [cart.fulfillmentType, restaurantLocation],
  );
  const activeFulfillmentReason = useMemo(
    () => getFulfillmentUnavailableReason(restaurantLocation, cart.fulfillmentType),
    [cart.fulfillmentType, restaurantLocation],
  );
  const canPlaceOrder = !submitting && activeFulfillmentAvailable && (!requiresDeliveryAddress || Boolean(selectedDeliveryAddress));

  useEffect(() => {
    if (!restaurantLocation) {
      return;
    }
    if (cart.fulfillmentType === 'DELIVERY' && !deliveryEnabled && pickupEnabled) {
      setCartFulfillmentType('PICKUP');
      return;
    }
    if (cart.fulfillmentType === 'PICKUP' && !pickupEnabled && deliveryEnabled) {
      setCartFulfillmentType('DELIVERY');
    }
  }, [cart.fulfillmentType, deliveryEnabled, pickupEnabled, restaurantLocation, setCartFulfillmentType]);

  useEffect(() => {
    let active = true;

    async function loadOfferPreview() {
      if (!token || !activePersonalizedOffer || !cart.restaurantId || cart.items.length === 0) {
        if (active) {
          setOfferPreview(null);
          setOfferPreviewLoading(false);
        }
        return;
      }

      setOfferPreviewLoading(true);
      try {
        const preview = await api.previewPersonalizedOffer(token, {
          offer_id: activePersonalizedOffer.offerId,
          generated_offer_id: activePersonalizedOffer.generatedOfferId,
          generated_offer_user_match_id:
            activePersonalizedOffer.generatedOfferUserMatchId,
          restaurant_id: cart.restaurantId,
          restaurant_location_id: cart.restaurantLocationId,
          fulfillment_type: cart.fulfillmentType,
          items: cart.items.map((item) => ({
            menu_item_id: item.menuItem.id,
            menu_item_size_id: item.selectedSize?.id ?? null,
            selected_options: item.selectedOptions.map((option) => ({
              option_id: option.optionId,
              quantity: option.quantity,
            })),
            quantity: item.quantity,
          })),
        });
        if (active) {
          setOfferPreview(preview);
        }
      } catch {
        if (active) {
          setOfferPreview(null);
        }
      } finally {
        if (active) {
          setOfferPreviewLoading(false);
        }
      }
    }

    void loadOfferPreview();
    return () => {
      active = false;
    };
  }, [activePersonalizedOffer, cart.fulfillmentType, cart.items, cart.restaurantId, cart.restaurantLocationId, token]);

  useEffect(() => {
    if (!activePersonalizedOffer || offerPreviewLoading || !offerPreview || offerPreview.eligible) {
      return;
    }
    const normalizedMessage = (offerPreview.message ?? '').toLowerCase();
    if (normalizedMessage.includes('not found') || normalizedMessage.includes('no longer available')) {
      setSelectedPersonalizedOffer(null);
      setOfferPreview(null);
    }
  }, [activePersonalizedOffer, offerPreview, offerPreviewLoading, setSelectedPersonalizedOffer]);

  const placeOrder = async () => {
    if (
      !checkAuthAndRedirect({
        isAuthenticated,
        redirectPath: '/cart',
        onNavigate,
        pushToast,
        setPendingAuthRedirectPath,
      })
    ) {
      return;
    }

    if (!token) {
      return;
    }

    if (!cart.restaurantId || cart.items.length === 0) {
      return;
    }
    if (!activeFulfillmentAvailable) {
      pushToast(
        cart.fulfillmentType === 'DELIVERY' ? 'Delivery unavailable' : 'Pickup unavailable',
        activeFulfillmentReason ?? 'This branch cannot fulfill the selected order type right now.',
        'error',
      );
      return;
    }

    setSubmitting(true);
    try {
      const createdOrder = await api.placeOrder(token, {
        restaurant_id: cart.restaurantId,
        restaurant_location_id: cart.restaurantLocationId,
        personalized_offer_id:
          activePersonalizedOffer &&
          offerPreview?.eligible &&
          !activePersonalizedOffer.generatedOfferId
            ? activePersonalizedOffer.offerId
            : null,
        generated_offer_id:
          activePersonalizedOffer && offerPreview?.eligible
            ? activePersonalizedOffer.generatedOfferId
            : null,
        generated_offer_user_match_id:
          activePersonalizedOffer && offerPreview?.eligible
            ? activePersonalizedOffer.generatedOfferUserMatchId
            : null,
        fulfillment_type: cart.fulfillmentType,
        items: cart.items.map((item) => ({
          menu_item_id: item.menuItem.id,
          menu_item_size_id: item.selectedSize?.id ?? null,
          selected_options: item.selectedOptions.map((option) => ({
            option_id: option.optionId,
            quantity: option.quantity,
          })),
          quantity: item.quantity,
        })),
        delivery_address: checkoutAddress,
        special_instructions: specialInstructions || null,
        payment_provider: 'mock',
      });

      clearCart();
      pushToast('Order placed', 'Your mock payment cleared and the kitchen has been notified.', 'success');
      onNavigate(`/orders/${createdOrder.id}`);
    } catch (error: unknown) {
      const message = error instanceof ApiError ? error.message : 'Unable to place your order.';
      pushToast('Order failed', message, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  if (!isAuthenticated) {
    return null;
  }

  if (cart.items.length === 0) {
    return (
      <div className="empty-state">
        <strong>Your cart is empty.</strong>
        <span>Add a few dishes and they will show up here with live totals.</span>
        <button className="primary-button primary-button--small" onClick={() => onNavigate('/')} type="button">
          Browse restaurants
        </button>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <div className="section-card__header">
          <div>
            <span className="eyebrow">Checkout</span>
            <h2>{cart.restaurantName}</h2>
            <p className="section-subtle">
              {cart.restaurantLocationName
                ? `${cart.restaurantLocationName} branch`
                : 'Review your items, confirm fulfillment details, and place the order in one smooth step.'}
            </p>
          </div>
          <button className="text-link" onClick={clearCart} type="button">
            Clear cart
          </button>
        </div>

        {activePersonalizedOffer ? (
          <div className="cart-offer-banner">
            <div>
              <strong>{activePersonalizedOffer.title}</strong>
              <span>
                {offerBannerSubtitle}
              </span>
            </div>
            <div className="cart-offer-banner__actions">
              <span className="cart-offer-banner__badge">
                {offerBadgeLabel}
              </span>
              <button
                className="text-link"
                onClick={() => {
                  setSelectedPersonalizedOffer(null);
                  setOfferPreview(null);
                }}
                type="button"
              >
                Remove
              </button>
            </div>
          </div>
        ) : null}

        <div className="cart-fulfillment-card">
          <div className="cart-fulfillment-card__header">
            <div>
              <strong>Delivery or pickup</strong>
              <span>
                {cart.fulfillmentType === 'DELIVERY'
                  ? 'Choose where the order should reach you.'
                  : 'Pickup skips the delivery fee for this order.'}
              </span>
            </div>
            <div className="fulfillment-toggle" aria-label="Fulfillment preference" role="tablist">
              {deliveryEnabled ? (
              <button
                aria-pressed={cart.fulfillmentType === 'DELIVERY'}
                className={
                  cart.fulfillmentType === 'DELIVERY'
                    ? 'fulfillment-toggle__button fulfillment-toggle__button--active'
                    : 'fulfillment-toggle__button'
                }
                onClick={() => {
                  setCartFulfillmentType('DELIVERY');
                  if (!selectedDeliveryAddress) {
                    setEditingDeliveryAddress(true);
                  }
                }}
                type="button"
              >
                Delivery
              </button>
              ) : null}
              {pickupEnabled ? (
              <button
                aria-pressed={cart.fulfillmentType === 'PICKUP'}
                className={
                  cart.fulfillmentType === 'PICKUP'
                    ? 'fulfillment-toggle__button fulfillment-toggle__button--active'
                    : 'fulfillment-toggle__button'
                }
                onClick={() => {
                  setCartFulfillmentType('PICKUP');
                  setEditingDeliveryAddress(false);
                }}
                type="button"
              >
                Pickup
              </button>
              ) : null}
            </div>
          </div>

          {!activeFulfillmentAvailable ? (
            <div className="cart-fulfillment-warning">
              <strong>{cart.fulfillmentType === 'DELIVERY' ? 'Delivery unavailable' : 'Pickup unavailable'}</strong>
              <span>
                {activeFulfillmentReason ?? 'This branch cannot fulfill the selected order type right now.'}
              </span>
            </div>
          ) : null}

          {cart.fulfillmentType === 'DELIVERY' ? (
            <div className="cart-fulfillment-card__body">
              <div className="cart-fulfillment-card__info">
                <span>Delivery address</span>
                <strong>{selectedDeliveryAddress || 'No delivery address selected yet.'}</strong>
              </div>
              <button
                className="secondary-button secondary-button--small"
                onClick={() => setEditingDeliveryAddress(true)}
                type="button"
              >
                {selectedDeliveryAddress ? 'Change' : 'Select'}
              </button>
            </div>
          ) : (
            <div className="cart-fulfillment-card__body">
              <div className="cart-fulfillment-card__info">
                <span>Pickup from restaurant</span>
                <strong>{pickupAddress}</strong>
              </div>
              <div className="cart-fulfillment-card__meta">
                Ready in {getFulfillmentEtaLabel(restaurantLocation, 'PICKUP')}
              </div>
            </div>
          )}

          {cart.fulfillmentType === 'DELIVERY' && editingDeliveryAddress ? (
            <div className="cart-fulfillment-card__editor">
              <label className="form-field">
                <span>Delivery address</span>
                <textarea
                  rows={3}
                  value={deliveryAddress}
                  onChange={(event) => setDeliveryAddress(event.target.value)}
                />
              </label>
              <div className="cart-fulfillment-card__actions">
                {user?.default_address ? (
                  <button
                    className="text-link"
                    onClick={() => setDeliveryAddress(user.default_address ?? '')}
                    type="button"
                  >
                    Use saved address
                  </button>
                ) : <span />}
                <button
                  className="secondary-button secondary-button--small"
                  onClick={() => setEditingDeliveryAddress(false)}
                  type="button"
                >
                  Done
                </button>
              </div>
            </div>
          ) : null}
        </div>

        <div className="cart-layout">
          <div className="cart-items">
            {cart.items.map((item) => {
              const customizationLines = formatCustomizationSummary(
                item.selectedSize,
                item.selectedOptions,
              );
              return (
              <article className="cart-item" key={item.id}>
                <div className="cart-item__copy">
                  <strong>{item.menuItem.name}</strong>
                  <p>{item.menuItem.description ?? 'Freshly prepared and ready to go.'}</p>
                  {customizationLines.length > 0 ? (
                    <small className="cart-item__customization">
                      {customizationLines.join(' • ')}
                    </small>
                  ) : null}
                  <span>{formatCurrency(item.unitPrice)}</span>
                </div>
                <div className="quantity-picker">
                  <button onClick={() => updateCartQuantity(item.id, item.quantity - 1)} type="button">
                    −
                  </button>
                  <span>{item.quantity}</span>
                  <button onClick={() => updateCartQuantity(item.id, item.quantity + 1)} type="button">
                    +
                  </button>
                </div>
              </article>
            )})}

            {upsellSuggestions.map((suggestion) => (
              <article className="cart-item cart-item--upsell" key={suggestion.combo_id}>
                <div className="cart-item__copy">
                  <strong>{suggestion.combo_name}</strong>
                  <p>{suggestion.message}</p>
                  <span>
                    Add {suggestion.missing_items.map((item) => item.name).join(', ')} for{' '}
                    {formatCurrency(suggestion.suggested_combo_price)}
                  </span>
                </div>
                <button
                  className="primary-button primary-button--small"
                  onClick={() => {
                    for (const item of suggestion.missing_items) {
                      const menuItem =
                        cart.items.find((entry) => entry.menuItem.id === item.menu_item_id)?.menuItem ??
                        buildMenuItemFromGeneratedComboItem(item, {
                          source: 'cart-combo-upsell',
                          restaurantId: suggestion.restaurant_id,
                          restaurantLocationId: suggestion.restaurant_location_id,
                          restaurantLocationName: suggestion.restaurant_location_name,
                          restaurantCuisineType: null,
                          createdAt: new Date().toISOString(),
                          updatedAt: new Date().toISOString(),
                        });
                      const existing = cart.items.find((entry) => entry.menuItem.id === item.menu_item_id);
                      if (existing) {
                        continue;
                      }
                      addToCart({
                        menuItem,
                        restaurantId: suggestion.restaurant_id,
                        restaurantName: suggestion.restaurant_name,
                        restaurantLocationId: suggestion.restaurant_location_id,
                        restaurantLocationName: suggestion.restaurant_location_name,
                        quantity: item.quantity,
                        silent: true,
                      });
                    }
                    pushToast('Combo extended', suggestion.message, 'success');
                  }}
                  type="button"
                >
                  Add missing items
                </button>
              </article>
            ))}
          </div>

          <aside className="checkout-card">
            <div className="checkout-card__header">
              <strong>Order summary</strong>
              <span>{cart.items.length} items</span>
            </div>
            <label className="form-field">
              <span>Special instructions</span>
              <textarea rows={3} value={specialInstructions} onChange={(event) => setSpecialInstructions(event.target.value)} />
            </label>
            <div className="price-row">
              <span>Fulfillment</span>
              <strong>{cart.fulfillmentType === 'DELIVERY' ? 'Delivery' : 'Pickup'}</strong>
            </div>
            <div className="price-row"><span>Subtotal</span><strong>{formatCurrency(subtotal)}</strong></div>
            <div className="price-row"><span>Delivery fee</span><strong>{formatCurrency(deliveryFee)}</strong></div>
            <div className="price-row"><span>Taxes</span><strong>{formatCurrency(taxAmount)}</strong></div>
            {activePersonalizedOffer && isMonetaryPersonalizedOffer ? (
              <div className="price-row price-row--discount">
                <span>{activePersonalizedOffer.discountLabel ?? 'Offer discount'}</span>
                <strong>
                  {personalizedOfferRowValue}
                </strong>
              </div>
            ) : null}
            <div className="price-row price-row--total"><span>Total</span><strong>{formatCurrency(total)}</strong></div>
            <button className="primary-button" disabled={!canPlaceOrder} onClick={placeOrder} type="button">
              {submitting ? 'Placing order...' : 'Place order'}
            </button>
          </aside>
        </div>
      </section>
    </div>
  );
}
