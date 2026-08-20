import { memo, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api, formatCurrency, formatDateTime, toNumber } from '../services/api';
import { RestaurantCard } from '../components/RestaurantCard';
import { Skeleton } from '../components/Skeleton';
import { CategoryChip } from '../components/home/CategoryChip';
import { GeneratedComboCard } from '../components/home/GeneratedComboCard';
import { ItemCard } from '../components/home/ItemCard';
import { OfferCard } from '../components/home/OfferCard';
import { SectionWrapper } from '../components/home/SectionWrapper';
import { useAppStore } from '../hooks/useAppStore';
import type {
  AppliedPersonalizedOffer,
  GeneratedCombo,
  MenuItem,
  Order,
  PersonalizedOfferCard,
  RecommendationItem,
  Restaurant,
  UserPreferences,
} from '../types/app';
import { buildMenuItemFromGeneratedComboItem } from '../utils/generatedComboCart';
import { checkAuthAndRedirect } from '../utils/authRedirect';
import { isCustomizableMenuItem } from '../utils/menuItemCustomization';

interface HomePageProps {
  addToCart: (input: {
    menuItem: MenuItem;
    restaurantId: string;
    restaurantName: string;
    restaurantLocationId?: string | null;
    restaurantLocationName?: string | null;
    quantity?: number;
    silent?: boolean;
  }) => void;
  token: string | null;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
  preferences: UserPreferences | null;
}

interface RecentOrderCardData {
  orderId: string;
  restaurantId: string;
  restaurantName: string;
  cuisine: string;
  total: string;
  placedAt: string;
  status: Order['status'];
  itemCount: number;
}

const QUICK_SEARCHES = ['Biryani', 'Healthy bowls', 'Budget snacks', 'Desserts'];
const CATEGORY_FALLBACK = ['All', 'Pizza', 'Chinese', 'Burgers', 'Healthy', 'Desserts'];

export const HomePage = memo(function HomePage({
  addToCart,
  token,
  onNavigate,
  onToast,
  preferences,
}: HomePageProps) {
  const {
    favoritesHydrated,
    isAuthenticated,
    isFavorite,
    isFavoritePending,
    setSelectedPersonalizedOffer,
    setPendingAuthRedirectPath,
    toggleFavorite,
  } = useAppStore();
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [offers, setOffers] = useState<PersonalizedOfferCard[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>([]);
  const [generatedCombos, setGeneratedCombos] = useState<GeneratedCombo[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [query, setQuery] = useState('');
  const [activeCuisine, setActiveCuisine] = useState('All');
  const [loading, setLoading] = useState(true);
  const [navigatingRestaurantId, setNavigatingRestaurantId] = useState<string | null>(null);
  const [pendingAddItemIds, setPendingAddItemIds] = useState<string[]>([]);
  const pendingAddItemIdsRef = useRef<Set<string>>(new Set());
  const addReleaseTimersRef = useRef<Map<string, number>>(new Map());
  const trackedOfferIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    let active = true;

    async function loadHomePage() {
      setLoading(true);

      try {
        const [restaurantRows, comboRows, recommendationRows, orderRows, offerRows] = await Promise.all([
          api.getRestaurants(),
          api.getGeneratedCombos(8).catch(() => []),
          api
            .getRecommendationsForContext({
              token,
              preferences,
              dedupeMultiLocation: true,
            })
            .catch(() => []),
          token ? api.getOrders(token).catch(() => []) : Promise.resolve([]),
          token
            ? api.getPersonalizedOffers(token, 4).catch((error) => {
                console.warn('personalized offers load failed', error);
                return [];
              })
            : Promise.resolve([]),
        ]);
        if (!active) {
          return;
        }
        setRestaurants(restaurantRows);
        setGeneratedCombos(comboRows);
        setRecommendations(recommendationRows);
        setOrders(orderRows);
        setOffers(offerRows);
      } catch (error: unknown) {
        if (!active) {
          return;
        }
        const message = error instanceof ApiError ? error.message : 'Unable to load restaurants right now.';
        onToast('Home unavailable', message, 'error');
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadHomePage();

    return () => {
      active = false;
    };
  }, [onToast, preferences, token]);

  useEffect(() => {
    trackedOfferIdsRef.current.clear();
  }, [token]);

  useEffect(() => () => {
    for (const timerId of addReleaseTimersRef.current.values()) {
      window.clearTimeout(timerId);
    }
    addReleaseTimersRef.current.clear();
    pendingAddItemIdsRef.current.clear();
  }, []);

  const cuisines = useMemo(() => {
    const discovered = Array.from(new Set(restaurants.map((restaurant) => restaurant.cuisine_type))).slice(0, 7);
    if (discovered.length === 0) {
      return CATEGORY_FALLBACK;
    }
    return ['All', ...discovered];
  }, [restaurants]);

  const deferredQuery = useDeferredValue(query);
  const filteredRestaurants = useMemo(() => {
    const normalized = deferredQuery.trim().toLowerCase();
    return restaurants.filter((restaurant) => {
      if (activeCuisine !== 'All' && restaurant.cuisine_type !== activeCuisine) {
        return false;
      }
      if (!normalized) {
        return true;
      }
      return [restaurant.name, restaurant.cuisine_type, restaurant.city].some((value) =>
        value.toLowerCase().includes(normalized),
      );
    });
  }, [activeCuisine, deferredQuery, restaurants]);

  const popularRestaurants = useMemo(
    () =>
      [...restaurants]
        .sort((left, right) => {
          const openDiff = Number(right.is_open) - Number(left.is_open);
          if (openDiff !== 0) {
            return openDiff;
          }
          return toNumber(left.delivery_fee) - toNumber(right.delivery_fee);
        })
        .slice(0, 6),
    [restaurants],
  );

  const recentOrders = useMemo<RecentOrderCardData[]>(() => {
    const uniqueByRestaurant = new Set<string>();
    return orders
      .filter((order) => {
        if (uniqueByRestaurant.has(order.restaurant_id)) {
          return false;
        }
        uniqueByRestaurant.add(order.restaurant_id);
        return true;
      })
      .slice(0, 4)
      .map((order) => ({
        orderId: order.id,
        restaurantId: order.restaurant_id,
        restaurantName: order.restaurant.name,
        cuisine: order.restaurant.cuisine_type,
        total: formatCurrency(order.total_amount),
        placedAt: formatDateTime(order.placed_at),
        status: order.status,
        itemCount: order.items.reduce((sum, item) => sum + item.quantity, 0),
      }));
  }, [orders]);

  const suggestions = useMemo(() => {
    if (preferences?.cuisines.length) {
      return preferences.cuisines.slice(0, 4);
    }
    return QUICK_SEARCHES;
  }, [preferences]);

  const quickHighlights = useMemo(
    () => [
      {
        label: 'Smart picks',
        value: recommendations.length ? `${recommendations.length}+` : 'Fresh daily',
      },
      {
        label: 'Popular now',
        value: popularRestaurants.length ? popularRestaurants[0]?.cuisine_type ?? 'Curated daily' : 'Curated daily',
      },
      {
        label: 'Fast delivery',
        value: restaurants.length ? '25-35 min' : '30 min avg',
      },
    ],
    [popularRestaurants, recommendations.length, restaurants.length],
  );

  const handleOpenRestaurant = useCallback((restaurantId: string) => {
    if (navigatingRestaurantId) {
      return;
    }
    setNavigatingRestaurantId(restaurantId);
    onNavigate(`/restaurant/${restaurantId}`);
  }, [navigatingRestaurantId, onNavigate]);

  useEffect(() => {
    if (!token || offers.length === 0) {
      return;
    }
    const untrackedOffers = offers.filter((offer) => !trackedOfferIdsRef.current.has(offer.id));
    if (untrackedOffers.length === 0) {
      return;
    }
    for (const offer of untrackedOffers) {
      trackedOfferIdsRef.current.add(offer.id);
    }
    void api.trackPersonalizedOfferEvents(
      token,
      untrackedOffers.map((offer) => ({
        offer_id: offer.offer_id,
        generated_offer_id: offer.generated_offer_id,
        generated_offer_user_match_id: offer.generated_offer_user_match_id,
        event_type: 'VIEWED' as const,
        target_type: offer.target_type,
        target_id:
          offer.menu_item_id
          ?? offer.generated_combo_id
          ?? offer.restaurant_location_id
          ?? offer.restaurant_id,
      })),
    ).catch(() => undefined);
  }, [offers, token]);

  const handleSearchChip = useCallback((value: string) => {
    setQuery(value);
    setActiveCuisine('All');
  }, []);

  const handleAddCombo = useCallback((combo: GeneratedCombo) => {
    for (const item of combo.items) {
      const restaurant = restaurants.find((entry) => entry.id === combo.restaurant_id);
      if (!restaurant) {
        continue;
      }
      addToCart({
        menuItem: buildMenuItemFromGeneratedComboItem(item, {
          source: 'home-generated-combo',
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
    onToast('Combo added', `${combo.combo_name} was added to your cart.`, 'success');
  }, [addToCart, onToast, restaurants]);

  const handleAddRecommendationToCart = useCallback((item: RecommendationItem) => {
    if (item.requires_location_selection && (item.available_locations_count ?? 1) > 1) {
      onToast(
        'Choose a branch',
        `${item.name} is available at ${item.available_locations_count} locations. Open the restaurant to pick a branch before adding it.`,
        'info',
      );
      onNavigate(`/restaurants/${item.restaurant_id}`);
      return;
    }

    if (pendingAddItemIdsRef.current.has(item.id)) {
      return;
    }

    if (isCustomizableMenuItem(item)) {
      onNavigate(`/menu-item/${item.preferred_menu_item_id ?? item.id}`);
      return;
    }

    pendingAddItemIdsRef.current.add(item.id);
    setPendingAddItemIds((current) => [...current, item.id]);
    const existingTimer = addReleaseTimersRef.current.get(item.id);
    if (existingTimer) {
      window.clearTimeout(existingTimer);
    }
    addToCart({
      menuItem: {
        ...item,
        id: item.preferred_menu_item_id ?? item.id,
        restaurant_location_id: item.preferred_location_id ?? item.restaurant_location_id,
        restaurant_location_name: item.preferred_location_name ?? item.restaurant_location_name,
      },
      restaurantId: item.restaurant_id,
      restaurantName: item.restaurant.name,
      restaurantLocationId: item.preferred_location_id ?? item.restaurant_location_id,
      restaurantLocationName: item.preferred_location_name ?? item.restaurant_location_name,
    });
    const timerId = window.setTimeout(() => {
      addReleaseTimersRef.current.delete(item.id);
      pendingAddItemIdsRef.current.delete(item.id);
      setPendingAddItemIds((current) => current.filter((entry) => entry !== item.id));
    }, 320);
    addReleaseTimersRef.current.set(item.id, timerId);
  }, [addToCart, onNavigate, onToast]);

  const handleOpenOffer = useCallback((offer: PersonalizedOfferCard) => {
    const selectedOffer: AppliedPersonalizedOffer = {
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

    setSelectedPersonalizedOffer(selectedOffer);
    if (token) {
      void api.trackPersonalizedOfferEvents(token, [
        {
          offer_id: offer.offer_id,
          generated_offer_id: offer.generated_offer_id,
          generated_offer_user_match_id: offer.generated_offer_user_match_id,
          event_type: 'CLICKED',
          target_type: offer.target_type,
          target_id:
            offer.menu_item_id
            ?? offer.generated_combo_id
            ?? offer.restaurant_location_id
            ?? offer.restaurant_id,
        },
      ]).catch(() => undefined);
    }

    if (offer.target_type === 'ITEM' && offer.menu_item_id) {
      onNavigate(`/menu-item/${offer.menu_item_id}`);
      return;
    }
    onNavigate(`/restaurant/${offer.restaurant_id}`);
  }, [onNavigate, setSelectedPersonalizedOffer, token]);

  const handleToggleFavorite = useCallback(async (item: RecommendationItem) => {
    if (
      !checkAuthAndRedirect({
        isAuthenticated,
        redirectPath: '/',
        onNavigate,
        pushToast: onToast,
        setPendingAuthRedirectPath,
      })
    ) {
      return;
    }

    try {
      const nextFavorite = await toggleFavorite({ menuItemId: item.id });
      onToast(
        nextFavorite ? 'Saved to favorites' : 'Removed from favorites',
        nextFavorite ? `${item.name} is now in your favorites.` : `${item.name} was removed from favorites.`,
        'success',
      );
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Unable to update favorites right now.';
      onToast('Favorites unavailable', message, 'error');
    }
  }, [isAuthenticated, onNavigate, onToast, setPendingAuthRedirectPath, toggleFavorite]);

  return (
    <div className="page-stack home-page">
      <section className="home-hero">
        <div className="home-hero__copy">
          <span className="eyebrow">Food delivery, refined</span>
          <h1>What are you craving today?</h1>
          <p>
            Discover restaurants, quick deals, and AI-powered suggestions tuned to your tastes and the food you keep
            coming back to.
          </p>
          <div className="home-hero__stats">
            {quickHighlights.map((highlight) => (
              <div className="home-hero__stat" key={highlight.label}>
                <strong>{highlight.value}</strong>
                <span>{highlight.label}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="home-hero__panel">
          <label className="home-search-card">
            <span className="eyebrow">Search smarter</span>
            <input
              placeholder="Try: spicy Chinese under ₹200"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <div className="home-search-card__chips">
              {suggestions.map((entry) => (
                <button className="quick-chip" key={entry} onClick={() => handleSearchChip(entry)} type="button">
                  {entry}
                </button>
              ))}
            </div>
          </label>
          <div className="home-hero__aside">
            <span className="home-hero__aside-label">Personalized for</span>
            <strong>{preferences?.cuisines.length ? preferences.cuisines.join(', ') : 'Everyday comfort food'}</strong>
            <p>
              {preferences?.budget
                ? `Budget: ${preferences.budget.toLowerCase()} spend, spice: ${preferences.spice_level?.toLowerCase() ?? 'balanced'}`
                : 'Use onboarding preferences and live restaurant data to shape recommendations.'}
            </p>
          </div>
        </div>
      </section>

      <SectionWrapper
        action={<span className="hint-text">{cuisines.length - 1 > 0 ? `${cuisines.length - 1} cuisines` : 'Curated daily'}</span>}
        eyebrow="Browse"
        subtitle="Start with the cuisines and moods that fit your next order."
        title="Categories"
      >
        <div className="home-category-row">
          {cuisines.map((cuisine) => (
            <CategoryChip
              active={activeCuisine === cuisine}
              key={cuisine}
              label={cuisine}
              onClick={() => setActiveCuisine(cuisine)}
            />
          ))}
        </div>
      </SectionWrapper>

      <button className="home-ai-card" onClick={() => onNavigate('/chat')} type="button">
        <div className="home-ai-card__icon">AI</div>
        <div className="home-ai-card__copy">
          <span className="eyebrow">Ask AI what to eat</span>
          <strong>Not sure what to eat?</strong>
          <p>Get personalized recommendations based on your cravings, budget, and cuisine preferences.</p>
        </div>
        <span className="home-ai-card__cta">Ask AI</span>
      </button>

      <SectionWrapper
        action={
          <button className="text-link" onClick={() => onNavigate('/chat')} type="button">
            Ask AI for more
          </button>
        }
        eyebrow="For you"
        subtitle="Preference-aware dishes surfaced from live restaurant context."
        title="Personalized Picks"
      >
        <div className="home-horizontal-row">
          {loading
            ? Array.from({ length: 4 }).map((_, index) => <Skeleton className="home-item-card" key={index} />)
            : recommendations.slice(0, 6).map((item) => (
                <ItemCard
                  addDisabled={pendingAddItemIds.includes(item.id)}
                  disabled={navigatingRestaurantId !== null}
                  favoritePending={isFavoritePending(item.id)}
                  isFavorite={favoritesHydrated ? isFavorite(item.id) : item.is_favorite}
                  item={item}
                  key={item.id}
                  onAddToCart={handleAddRecommendationToCart}
                  onOpenRestaurant={handleOpenRestaurant}
                  onToggleFavorite={handleToggleFavorite}
                />
                ))}
          {!loading && recommendations.length === 0 ? (
            <div className="home-inline-empty">
              <strong>No personalized picks yet.</strong>
              <span>Complete your preferences or ask AI for something specific to unlock smarter suggestions.</span>
            </div>
          ) : null}
        </div>
      </SectionWrapper>

      <SectionWrapper
        action={<span className="hint-text">Popular around you</span>}
        eyebrow="Discovery"
        subtitle="Popular restaurants with dependable delivery windows and strong menu depth."
        title="Popular Now"
      >
        <div className="home-horizontal-row">
          {loading
            ? Array.from({ length: 4 }).map((_, index) => (
                <Skeleton className="restaurant-card restaurant-card--compact" key={index} />
              ))
            : popularRestaurants.map((restaurant) => (
                <RestaurantCard
                  disabled={navigatingRestaurantId !== null}
                  key={restaurant.id}
                  onOpen={handleOpenRestaurant}
                  restaurant={restaurant}
                  variant="compact"
                />
              ))}
        </div>
      </SectionWrapper>

      {generatedCombos.length > 0 ? (
        <SectionWrapper
          action={<span className="hint-text">{`${generatedCombos.length} live combos`}</span>}
          eyebrow="Trending"
          subtitle="Auto-generated bundles created from the dishes customers already order together."
          title="Frequently Ordered Together"
        >
          <div className="home-horizontal-row">
            {generatedCombos.map((combo) => (
              <GeneratedComboCard
                combo={combo}
                disabled={navigatingRestaurantId !== null}
                key={combo.id}
                onAddCombo={handleAddCombo}
                onOpenRestaurant={handleOpenRestaurant}
              />
            ))}
          </div>
        </SectionWrapper>
      ) : null}

      {token && (loading || offers.length > 0) ? (
        <SectionWrapper
          action={<span className="hint-text">{offers.length ? `${offers.length} active campaigns` : 'Live restaurant campaigns'}</span>}
          eyebrow="Campaigns"
          subtitle="Manual restaurant and branch offers that unlock automatically when your cart qualifies."
          title="Offers"
        >
          <div className="home-horizontal-row">
            {loading
              ? Array.from({ length: 4 }).map((_, index) => <Skeleton className="home-offer-card" key={index} />)
              : offers.map((offer) => (
                  <OfferCard
                    disabled={navigatingRestaurantId !== null}
                    key={offer.id}
                    onOpen={handleOpenOffer}
                    offer={offer}
                  />
                ))}
          </div>
        </SectionWrapper>
      ) : null}

      {recentOrders.length > 0 ? (
        <SectionWrapper
          action={<span className="hint-text">{`${recentOrders.length} recent spots`}</span>}
          eyebrow="Reorder"
          subtitle="Quick access to the places you recently trusted for delivery."
          title="Recently Ordered"
        >
          <div className="home-recent-grid">
            {recentOrders.map((order) => (
              <button
                className="home-recent-card"
                key={order.orderId}
                onClick={() => onNavigate(`/profile/orders`)}
                type="button"
              >
                <div className="home-recent-card__topline">
                  <strong>{order.restaurantName}</strong>
                  <span className="chip chip--muted">{order.status.replaceAll('_', ' ')}</span>
                </div>
                <p>{order.cuisine}</p>
                <div className="home-recent-card__meta">
                  <span>{order.itemCount} items</span>
                  <span>{order.total}</span>
                </div>
                <span className="home-recent-card__timestamp">{order.placedAt}</span>
              </button>
            ))}
          </div>
        </SectionWrapper>
      ) : null}

      <SectionWrapper
        action={<span className="hint-text">Tap any card to open</span>}
        eyebrow="Nearby"
        subtitle="A polished list of restaurants ready to deliver right now."
        title="Restaurants"
      >
        <div className="restaurant-grid home-restaurant-grid">
          {loading
            ? Array.from({ length: 6 }).map((_, index) => (
                <Skeleton className="restaurant-card restaurant-card--skeleton" key={index} />
              ))
            : filteredRestaurants.map((restaurant) => (
                <RestaurantCard
                  disabled={navigatingRestaurantId !== null}
                  key={restaurant.id}
                  onOpen={handleOpenRestaurant}
                  restaurant={restaurant}
                />
              ))}
        </div>
        {!loading && filteredRestaurants.length === 0 ? (
          <div className="empty-state">
            <strong>No restaurants matched your search.</strong>
            <span>Try another cuisine, city, or a shorter keyword.</span>
          </div>
        ) : null}
      </SectionWrapper>

    </div>
  );
});
