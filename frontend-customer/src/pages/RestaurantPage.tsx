import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  api,
  createPlaceholderImage,
  formatCurrency,
} from "../services/api";
import { GeneratedComboCard } from "../components/home/GeneratedComboCard";
import { MenuItemCard } from "../components/MenuItemCard";
import { Skeleton } from "../components/Skeleton";
import { useAppStore } from "../hooks/useAppStore";
import { sortMenuItemsByRecommendationSignal } from "../utils/menuPersonalization";
import type { GeneratedCombo, MenuItem, Restaurant, RestaurantLocation } from "../types/app";
import { buildMenuItemFromGeneratedComboItem } from "../utils/generatedComboCart";
import { checkAuthAndRedirect } from "../utils/authRedirect";
import {
  getFulfillmentEtaLabel,
  getFulfillmentUnavailableReason,
  isFulfillmentAvailableNow,
  isFulfillmentEnabled,
} from "../utils/fulfillment";
import { isCustomizableMenuItem } from "../utils/menuItemCustomization";

interface RestaurantPageProps {
  restaurantId: string;
  token: string | null;
  onNavigate: (path: string) => void;
  onAddToCart: (item: MenuItem, restaurant: Restaurant) => void;
}

export function RestaurantPage({
  restaurantId,
  token,
  onNavigate,
  onAddToCart,
}: RestaurantPageProps) {
  const {
    addToCart,
    cart,
    favoritesHydrated,
    isAuthenticated,
    isFavorite,
    isFavoritePending,
    preferences,
    pushToast,
    selectedPersonalizedOffer,
    setCartFulfillmentType,
    setPendingAuthRedirectPath,
    setSelectedPersonalizedOffer,
    toggleFavorite,
    updateCartQuantity,
  } = useAppStore();
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [generatedCombos, setGeneratedCombos] = useState<GeneratedCombo[]>([]);
  const [menuItems, setMenuItems] = useState<MenuItem[]>([]);
  const [offerAvailabilityByItemId, setOfferAvailabilityByItemId] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>("All");
  const [reloadKey, setReloadKey] = useState(0);
  const [heroImageFailed, setHeroImageFailed] = useState(false);
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(null);
  const [locationPickerOpen, setLocationPickerOpen] = useState(false);

  const restaurantLocations = useMemo(
    () => restaurant?.locations ?? [],
    [restaurant?.locations],
  );
  const activeLocations = useMemo(
    () => restaurantLocations.filter((location) => location.is_active),
    [restaurantLocations],
  );
  const selectedLocation = useMemo(
    () =>
      activeLocations.find((location) => location.id === selectedLocationId)
      ?? activeLocations.find((location) => location.is_open)
      ?? activeLocations[0]
      ?? null,
    [activeLocations, selectedLocationId],
  );
  const hasActiveLocations = activeLocations.length > 0;
  const heroStatusOpen = selectedLocation?.is_open ?? restaurant?.is_open ?? false;
  const heroLocationLine = [
    selectedLocation?.address_line_2,
    selectedLocation?.address_line_1,
    selectedLocation?.city,
  ]
    .filter(Boolean)
    .join(" • ");

  const closeLocationPicker = () => setLocationPickerOpen(false);
  const handleSelectLocation = (location: RestaurantLocation) => {
    setSelectedLocationId(location.id);
    setLocationPickerOpen(false);
  };
  const deliveryEnabled = useMemo(
    () => isFulfillmentEnabled(selectedLocation, 'DELIVERY'),
    [selectedLocation],
  );
  const pickupEnabled = useMemo(
    () => isFulfillmentEnabled(selectedLocation, 'PICKUP'),
    [selectedLocation],
  );
  const activeFulfillmentAvailable = useMemo(
    () => isFulfillmentAvailableNow(selectedLocation, cart.fulfillmentType),
    [cart.fulfillmentType, selectedLocation],
  );
  const activeFulfillmentReason = useMemo(
    () => getFulfillmentUnavailableReason(selectedLocation, cart.fulfillmentType),
    [cart.fulfillmentType, selectedLocation],
  );

  useEffect(() => {
    if (!selectedLocation) {
      return;
    }
    if (cart.fulfillmentType === 'DELIVERY' && !deliveryEnabled && pickupEnabled) {
      setCartFulfillmentType('PICKUP');
      return;
    }
    if (cart.fulfillmentType === 'PICKUP' && !pickupEnabled && deliveryEnabled) {
      setCartFulfillmentType('DELIVERY');
    }
  }, [cart.fulfillmentType, deliveryEnabled, pickupEnabled, selectedLocation, setCartFulfillmentType]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadRestaurantPage() {
      setLoading(true);
      setError(null);
      setRestaurant(null);
      setGeneratedCombos([]);
      setMenuItems([]);
      setOfferAvailabilityByItemId({});
      setActiveCategory("All");

      try {
        const restaurantRow = await api.getRestaurant(restaurantId, controller.signal);
        if (controller.signal.aborted) {
          return;
        }
        const activeLocationRows = (restaurantRow.locations ?? []).filter((location) => location.is_active);
        const defaultLocation =
          activeLocationRows.find((location) => location.is_open)
          ?? activeLocationRows[0]
          ?? null;
        setRestaurant(restaurantRow);
        setSelectedLocationId(defaultLocation?.id ?? null);

        const [items, recommendationRows, comboRows] = await Promise.all([
          api.getMenuItems(restaurantId, token, controller.signal, defaultLocation?.id ?? null),
          api
            .getRecommendationsForContext({
              token,
              preferences,
            })
            .catch(() => []),
          api.getRestaurantGeneratedCombos(restaurantId, 8, defaultLocation?.id ?? null).catch(() => []),
        ]);
        if (controller.signal.aborted) {
          return;
        }
        setGeneratedCombos(comboRows);
        setMenuItems(
          sortMenuItemsByRecommendationSignal(
            items,
            recommendationRows.filter((item) => item.restaurant_id === restaurantId),
          ),
        );
      } catch (nextError: unknown) {
        if (controller.signal.aborted) {
          return;
        }
        const message =
          nextError instanceof ApiError
            ? nextError.message
            : "Unable to load this restaurant.";
        setError(message);
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    void loadRestaurantPage();

    return () => {
      controller.abort();
    };
  }, [preferences, restaurantId, token, reloadKey]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadLocationScopedContent() {
      if (!restaurant || !selectedLocation) {
        setGeneratedCombos([]);
        setMenuItems([]);
        return;
      }
      try {
        const [items, recommendationRows, comboRows] = await Promise.all([
          api.getMenuItems(restaurant.id, token, controller.signal, selectedLocation.id),
          api
            .getRecommendationsForContext({
              token,
              preferences,
            })
            .catch(() => []),
          api.getRestaurantGeneratedCombos(restaurant.id, 8, selectedLocation.id).catch(() => []),
        ]);
        if (controller.signal.aborted) {
          return;
        }
        setGeneratedCombos(comboRows);
        setMenuItems(
          sortMenuItemsByRecommendationSignal(
            items,
            recommendationRows.filter((item) => item.restaurant_id === restaurant.id),
          ),
        );
        setActiveCategory("All");
      } catch (nextError: unknown) {
        if (controller.signal.aborted) {
          return;
        }
        pushToast(
          "Location unavailable",
          nextError instanceof Error ? nextError.message : "Unable to load this branch menu right now.",
          "error",
        );
      }
    }

    void loadLocationScopedContent();
    return () => controller.abort();
  }, [preferences, pushToast, restaurant, selectedLocation, token]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadOfferAvailability() {
      if (!token || menuItems.length === 0) {
        setOfferAvailabilityByItemId({});
        return;
      }

      try {
        const rows = await api.getPersonalizedOfferAvailabilityForItems(token, {
          restaurant_id: restaurantId,
          restaurant_location_id: selectedLocation?.id ?? null,
          menu_item_ids: menuItems.map((item) => item.id),
        });
        if (controller.signal.aborted) {
          return;
        }
        setOfferAvailabilityByItemId(
          Object.fromEntries(rows.map((row) => [row.menu_item_id, row.has_offer])),
        );
      } catch {
        if (!controller.signal.aborted) {
          setOfferAvailabilityByItemId({});
        }
      }
    }

    void loadOfferAvailability();
    return () => controller.abort();
  }, [menuItems, restaurantId, selectedLocation?.id, token]);

  const categories = useMemo(
    () => ["All", ...Array.from(new Set(menuItems.map((item) => item.category)))],
    [menuItems],
  );

  const visibleItems = useMemo(
    () =>
      menuItems.filter(
        (item) =>
          activeCategory === "All" || !activeCategory || item.category === activeCategory,
      ),
    [activeCategory, menuItems],
  );
  const activeOfferForRestaurant = useMemo(
    () =>
      selectedPersonalizedOffer
      && selectedPersonalizedOffer.restaurantId === restaurantId
      && (
        !selectedPersonalizedOffer.offerRestaurantLocationId
        || selectedPersonalizedOffer.offerRestaurantLocationId === selectedLocation?.id
      )
        ? selectedPersonalizedOffer
        : null,
    [restaurantId, selectedLocation?.id, selectedPersonalizedOffer],
  );

  const cartQuantities = useMemo(
    () =>
      cart.items.reduce((map, item) => {
        map.set(item.menuItem.id, (map.get(item.menuItem.id) ?? 0) + item.quantity);
        return map;
      }, new Map<string, number>()),
    [cart.items],
  );

  const handleAddCombo = (combo: GeneratedCombo) => {
    if (!restaurant) {
      return;
    }
    for (const item of combo.items) {
      addToCart({
        menuItem: buildMenuItemFromGeneratedComboItem(item, {
          source: 'restaurant-generated-combo',
          restaurantId: combo.restaurant_id,
          restaurantLocationId: combo.restaurant_location_id,
          restaurantLocationName: combo.restaurant_location_name,
          restaurantCuisineType: restaurant.cuisine_type,
          createdAt: restaurant.created_at,
          updatedAt: restaurant.updated_at,
        }),
        restaurantId: combo.restaurant_id,
        restaurantName: combo.restaurant_name,
        restaurantLocationId: combo.restaurant_location_id,
        restaurantLocationName: combo.restaurant_location_name,
        quantity: item.quantity,
        silent: true,
      });
    }
    pushToast('Combo added', `${combo.combo_name} was added to your cart.`, 'success');
  };

  const handleToggleFavorite = async (menuItem: MenuItem) => {
    if (
      !checkAuthAndRedirect({
        isAuthenticated,
        redirectPath: `/restaurant/${restaurantId}`,
        onNavigate,
        pushToast,
        setPendingAuthRedirectPath,
      })
    ) {
      return;
    }

    try {
      const nextFavorite = await toggleFavorite({ menuItemId: menuItem.id });
      pushToast(
        nextFavorite ? 'Saved to favorites' : 'Removed from favorites',
        nextFavorite ? `${menuItem.name} is now in your favorites.` : `${menuItem.name} was removed from favorites.`,
        'success',
      );
    } catch (error) {
      pushToast(
        'Favorites unavailable',
        error instanceof Error ? error.message : 'Unable to update favorites right now.',
        'error',
      );
    }
  };

  if (loading) {
    return (
      <div className="page-stack restaurant-page">
        <section className="restaurant-hero restaurant-hero--compact">
          <Skeleton className="restaurant-hero__skeleton" />
        </section>
        <section className="section-card restaurant-page__section">
          <div className="restaurant-page__tabs restaurant-page__tabs--loading">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton className="restaurant-page__tab-skeleton" key={index} />
            ))}
          </div>
          <div className="menu-list">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton
                className="menu-item-card menu-item-card--skeleton"
                key={index}
              />
            ))}
          </div>
        </section>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page-stack restaurant-page">
        <section className="section-card restaurant-page__section">
          <div className="empty-state empty-state--with-actions">
            <strong>We couldn’t load this restaurant right now.</strong>
            <span>{error}</span>
            <div className="empty-state__actions">
              <button
                className="primary-button primary-button--small"
                onClick={() => setReloadKey((value) => value + 1)}
                type="button"
              >
                Retry
              </button>
              <button
                className="secondary-button secondary-button--small"
                onClick={() => onNavigate("/")}
                type="button"
              >
                Back to home
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  if (!restaurant) {
    return (
      <div className="empty-state">
        <strong>Restaurant not found.</strong>
        <button
          className="primary-button primary-button--small"
          onClick={() => onNavigate("/")}
          type="button"
        >
          Back to home
        </button>
      </div>
    );
  }

  return (
    <div className="page-stack restaurant-page">
      <section className="restaurant-hero restaurant-hero--compact">
        {/* Cover art, then the first dish the kitchen has a photograph of, then
            the lettered placeholder. The middle step is the one that matters:
            most restaurants never upload a cover, and a banner of initials
            where the food should be is what makes a menu look unfinished.
            Decorative — the name is set in the heading directly below it. */}
        <img
          alt=""
          className="restaurant-hero__image"
          onError={() => setHeroImageFailed(true)}
          src={
            (!heroImageFailed && restaurant.cover_image_url) ||
            menuItems.find((entry) => entry.image_url)?.image_url ||
            createPlaceholderImage(restaurant.name ?? "RS")
          }
        />
        <div className="restaurant-hero__overlay" />
        <div className="restaurant-hero__content restaurant-hero__content--compact">
          <div className="restaurant-hero__topline">
            <button
              className="restaurant-back-button"
              onClick={() => onNavigate("/")}
              type="button"
            >
              ← Back
            </button>
            <div className="restaurant-hero__floating-actions">
              <span
                className={
                  heroStatusOpen
                    ? "status-badge status-badge--open"
                    : "status-badge status-badge--closed"
                }
              >
                {heroStatusOpen ? "Open now" : "Closed"}
              </span>
            </div>
          </div>
          <div className="restaurant-hero__card">
            <div className="restaurant-hero__summary">
              <span className="eyebrow">{restaurant.cuisine_type}</span>
              <h1>{restaurant.name}</h1>
            </div>
            <button
              className="restaurant-branch-trigger"
              disabled={!hasActiveLocations}
              onClick={() => setLocationPickerOpen(true)}
              type="button"
            >
              <div className="restaurant-branch-trigger__copy">
                <span className="restaurant-branch-trigger__eyebrow">
                  {hasActiveLocations ? "Selected branch" : "Branches unavailable"}
                </span>
                <strong>{selectedLocation?.branch_name ?? "No active branch available"}</strong>
              <span>{heroLocationLine || "This restaurant does not have an active branch yet."}</span>
            </div>
            <span aria-hidden="true" className="restaurant-branch-trigger__chevron">⌄</span>
          </button>
          <div className="restaurant-fulfillment-row">
            {deliveryEnabled ? (
              <button
                className={
                  cart.fulfillmentType === 'DELIVERY'
                    ? 'restaurant-fulfillment-chip restaurant-fulfillment-chip--active'
                    : 'restaurant-fulfillment-chip'
                }
                onClick={() => setCartFulfillmentType('DELIVERY')}
                type="button"
              >
                Delivery
              </button>
            ) : null}
            {pickupEnabled ? (
              <button
                className={
                  cart.fulfillmentType === 'PICKUP'
                    ? 'restaurant-fulfillment-chip restaurant-fulfillment-chip--active'
                    : 'restaurant-fulfillment-chip'
                }
                onClick={() => setCartFulfillmentType('PICKUP')}
                type="button"
              >
                Pickup
              </button>
            ) : null}
            <span className="hero-meta-pill">
              {getFulfillmentEtaLabel(selectedLocation, cart.fulfillmentType)}
            </span>
          </div>
          {!activeFulfillmentAvailable && selectedLocation ? (
            <div className="restaurant-fulfillment-warning">
              <strong>{cart.fulfillmentType === 'DELIVERY' ? 'Delivery unavailable' : 'Pickup unavailable'}</strong>
              <span>
                {activeFulfillmentReason ?? 'This branch cannot fulfill the selected order type right now.'}
              </span>
            </div>
          ) : null}
          <div className="restaurant-hero__meta restaurant-hero__meta--compact">
            <span className="hero-meta-pill">
              {getFulfillmentEtaLabel(selectedLocation, cart.fulfillmentType)}
            </span>
              <span className="hero-meta-pill">
                Fee {formatCurrency(selectedLocation?.delivery_fee ?? restaurant.delivery_fee ?? 0)}
              </span>
              <span className="hero-meta-pill">
                Min {formatCurrency(selectedLocation?.minimum_order_amount ?? restaurant.minimum_order_amount ?? 0)}
              </span>
              <span
                className={
                  heroStatusOpen
                    ? "hero-meta-pill hero-meta-pill--open"
                    : "hero-meta-pill hero-meta-pill--closed"
                }
              >
                {heroStatusOpen ? "Open now" : "Closed"}
              </span>
            </div>
            <p className="restaurant-hero__description">
              {restaurant.description ??
                "Comfort food, quick bites, and crowd favourites in one polished menu."}
            </p>
          </div>
        </div>
      </section>

      {activeOfferForRestaurant ? (
        <div className="cart-offer-banner">
          <div>
            <strong>{activeOfferForRestaurant.title}</strong>
            <span>
              {activeOfferForRestaurant.termsLabel
                ?? activeOfferForRestaurant.discountLabel
                ?? "Add eligible items to unlock this offer."}
            </span>
          </div>
          <div className="cart-offer-banner__actions">
            <span className="cart-offer-banner__badge">
              {activeOfferForRestaurant.discountLabel ?? "Offer active"}
            </span>
            <button
              className="text-link"
              onClick={() => setSelectedPersonalizedOffer(null)}
              type="button"
            >
              Remove
            </button>
          </div>
        </div>
      ) : null}

      <section className="section-card restaurant-page__section restaurant-page__section--chips">
        <div className="restaurant-page__tabs restaurant-page__tabs--floating">
          {categories.map((category) => (
            <button
              key={category}
              className={
                activeCategory === category
                  ? "tab-chip tab-chip--active"
                  : "tab-chip"
              }
              onClick={() => setActiveCategory(category)}
              type="button"
            >
              {category}
            </button>
          ))}
        </div>
      </section>

      {locationPickerOpen ? (
        <div aria-modal="true" className="app-modal" role="dialog">
          <button
            aria-label="Close branch picker"
            className="app-modal__backdrop"
            onClick={closeLocationPicker}
            type="button"
          />
          <div className="app-modal__card app-modal__card--branch-picker">
            <span className="app-modal__badge">Branches</span>
            <div className="restaurant-page__menu-head restaurant-page__menu-head--modal">
              <div className="restaurant-page__menu-copy">
                <h2>Choose a branch</h2>
                <p>Delivery time, fees, combos, and menu items update by location.</p>
              </div>
              <button className="text-link" onClick={closeLocationPicker} type="button">
                Close
              </button>
            </div>
            <div className="restaurant-location-list restaurant-location-list--modal">
              {activeLocations.map((location) => (
                <button
                  key={location.id}
                  className={
                    selectedLocation?.id === location.id
                      ? "restaurant-location-card restaurant-location-card--active"
                      : "restaurant-location-card"
                  }
                  onClick={() => handleSelectLocation(location)}
                  type="button"
                >
                  <div className="restaurant-location-card__topline">
                    <strong>{location.branch_name}</strong>
                    {selectedLocation?.id === location.id ? (
                      <span className="restaurant-location-card__check">✓</span>
                    ) : null}
                  </div>
                  <span>{[location.address_line_2, location.address_line_1, location.city].filter(Boolean).join(" • ")}</span>
                  <div className="restaurant-location-card__meta">
                    <span
                      className={
                        location.is_open
                          ? "restaurant-location-card__status restaurant-location-card__status--open"
                          : "restaurant-location-card__status restaurant-location-card__status--closed"
                      }
                    >
                      {location.is_open ? "Open now" : "Closed"}
                    </span>
                    <span>{location.estimated_delivery_time} min</span>
                    <span>{location.pickup_enabled ? `${location.estimated_pickup_time} min pickup` : 'Pickup off'}</span>
                    <span>Fee {formatCurrency(location.delivery_fee)}</span>
                  </div>
                </button>
              ))}
              {!hasActiveLocations ? (
                <div className="empty-state">
                  <strong>No active branches available.</strong>
                  <span>Try again later or choose another restaurant.</span>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {generatedCombos.length > 0 ? (
        <section className="section-card restaurant-page__section">
          <div className="restaurant-page__menu-head">
            <div className="restaurant-page__menu-copy">
              <span className="eyebrow">Generated combos</span>
              <h2>Frequently ordered together</h2>
              <p>Real bundles learned from completed orders at this restaurant.</p>
            </div>
          </div>

          <div className="home-horizontal-row">
            {generatedCombos.map((combo) => (
              <GeneratedComboCard
                combo={combo}
                key={combo.id}
                onAddCombo={handleAddCombo}
                onOpenRestaurant={(nextRestaurantId) => onNavigate(`/restaurant/${nextRestaurantId}`)}
              />
            ))}
          </div>
        </section>
      ) : null}

      <section className="section-card restaurant-page__section">
        <div className="restaurant-page__menu-head">
          <div className="restaurant-page__menu-copy">
            <span className="eyebrow">Menu</span>
            <h2>Browse the menu</h2>
            <p>
              {selectedLocation
                ? `${menuItems.length} dishes ready at ${selectedLocation.branch_name}.`
                : hasActiveLocations
                  ? `${menuItems.length} dishes ready to order.`
                  : "No active branch menu available right now."}
            </p>
          </div>
          <button
            className="text-link"
            onClick={() => onNavigate("/chat")}
            type="button"
          >
            Ask AI for suggestions
          </button>
        </div>

        {!hasActiveLocations ? (
          <div className="empty-state">
            <strong>No active branches available for this restaurant.</strong>
            <span>We’ll show the menu here as soon as a branch goes live.</span>
          </div>
        ) : null}
        <div className="menu-list">
          {hasActiveLocations ? visibleItems.map((item) => (
            <MenuItemCard
              favoritePending={isFavoritePending(item.id)}
              hasOfferAvailable={Boolean(offerAvailabilityByItemId[item.id])}
              isFavorite={favoritesHydrated ? isFavorite(item.id) : item.is_favorite}
              item={item}
              key={item.id}
              onDecrease={(menuItem) => updateCartQuantity(menuItem.id, (cartQuantities.get(menuItem.id) ?? 0) - 1)}
              onAdd={(menuItem) => {
                if (!activeFulfillmentAvailable) {
                  pushToast(
                    cart.fulfillmentType === 'DELIVERY' ? 'Delivery unavailable' : 'Pickup unavailable',
                    activeFulfillmentReason ?? 'This branch cannot fulfill the selected order type right now.',
                    'info',
                  );
                  return;
                }
                if (isCustomizableMenuItem(menuItem)) {
                  onNavigate(`/menu-item/${menuItem.id}`);
                  return;
                }
                onAddToCart(menuItem, restaurant);
              }}
              onOpen={(menuItem) => onNavigate(`/menu-item/${menuItem.id}`)}
              onToggleFavorite={handleToggleFavorite}
              quantity={isCustomizableMenuItem(item) ? 0 : cartQuantities.get(item.id) ?? 0}
            />
          )) : null}
        </div>

        {hasActiveLocations && visibleItems.length === 0 ? (
          <div className="empty-state">
            <strong>{selectedLocation ? "No items available at this branch." : "No items available."}</strong>
            <span>
              {selectedLocation
                ? "Try another branch or ask the AI for a better match."
                : "Try another category or ask the AI for a better match."}
            </span>
          </div>
        ) : null}
      </section>
    </div>
  );
}
