import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, formatCurrency, toNumber } from '../services/api';
import { AppIcon } from '../components/AppIcon';
import { AiPromptCard } from '../components/app/AiPromptCard';
import { CategoryRail } from '../components/app/CategoryRail';
import { buildMenuCategories } from '../components/app/menuCategories';
import { DishCard } from '../components/app/DishCard';
import { SearchBar } from '../components/app/SearchBar';
import { SectionHeader } from '../components/app/SectionHeader';
import { GeneratedComboCard } from '../components/home/GeneratedComboCard';
import { ItemCard } from '../components/home/ItemCard';
import { OfferCard } from '../components/home/OfferCard';
import { useAppStore } from '../hooks/useAppStore';
import { useAppConfig } from '../store/useAppConfig';
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
import { buildPreferencesKey } from '../utils/preferencesKey';
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

/**
 * How much of the menu the home screen previews before "See full menu".
 *
 * Eight rather than nine: the grid is two-up on a phone and four-up at the
 * site width, and nine left a single stranded card on the last row of both.
 */
const MENU_PREVIEW_COUNT = 8;

function greetingName(fullName: string | null | undefined): string {
  const first = (fullName ?? '').trim().split(/\s+/)[0];
  return first || 'there';
}

/**
 * The single-restaurant home screen, section for section as the app builds it:
 * hero, categories, the kitchen's menu, the AI prompt, personalized picks,
 * combos, offers, then what you ordered last.
 *
 * The two marketplace rails the app renders — "Popular Now" and "Restaurants" —
 * are absent by design. A branded app has exactly one restaurant, so both would
 * point back at the kitchen the customer is already standing in.
 */
export const HomePage = memo(function HomePage({
  addToCart,
  token,
  onNavigate,
  onToast,
  preferences,
}: HomePageProps) {
  const {
    cart,
    favoritesHydrated,
    isAuthenticated,
    isFavorite,
    isFavoritePending,
    requestAddToCart,
    setSelectedPersonalizedOffer,
    setPendingAuthRedirectPath,
    toggleFavorite,
    updateCartQuantity,
    user,
  } = useAppStore();
  const { displayName, restaurantId, ready } = useAppConfig();

  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [menuItems, setMenuItems] = useState<MenuItem[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>([]);
  const [combos, setCombos] = useState<GeneratedCombo[]>([]);
  const [offers, setOffers] = useState<PersonalizedOfferCard[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [selectedCategoryId, setSelectedCategoryId] = useState('all');
  const [loading, setLoading] = useState(true);
  const trackedOfferIdsRef = useRef<Set<string>>(new Set());

  // Latest values for the loader, which is keyed on `feedScopeKey` rather than
  // on these directly. Kept in sync during render so the effect never reads a
  // value from the previous commit.
  const tokenRef = useRef(token);
  const preferencesRef = useRef(preferences);
  const restaurantIdRef = useRef(restaurantId);
  tokenRef.current = token;
  preferencesRef.current = preferences;
  restaurantIdRef.current = restaurantId;

  /**
   * One string that changes only when the feed genuinely should be refetched.
   *
   * Keying the effect on `preferences` directly re-ran it every time the store
   * replaced that object — which it does on hydrate and on every profile sync,
   * with identical contents. Together with `ready` flipping as `/app-config`
   * resolved, the whole home feed was being fetched three times per visit:
   * fifteen API calls where five will do.
   */
  const feedScopeKey = useMemo(
    () =>
      JSON.stringify({
        hasToken: Boolean(token),
        preferences: buildPreferencesKey(preferences),
        restaurantId,
      }),
    [preferences, restaurantId, token],
  );

  useEffect(() => {
    // Wait for the config before the first fetch. Firing early produces an
    // unscoped feed that is thrown away the moment the restaurant is known.
    if (!ready) {
      return;
    }
    let active = true;

    async function load() {
      setLoading(true);
      try {
        const scoped = restaurantIdRef.current;
        const restaurantRow = scoped ? await api.getRestaurant(scoped).catch(() => null) : null;
        // The open branch is what the app prices and stocks the menu against;
        // an inactive one would show dishes the kitchen cannot make.
        const location =
          restaurantRow?.locations?.find((entry) => entry.is_open && entry.is_active) ??
          restaurantRow?.locations?.find((entry) => entry.is_active) ??
          null;

        const [menuRows, comboRows, recommendationRows, orderRows, offerRows] = await Promise.all([
          scoped
            ? api.getMenuItems(scoped, tokenRef.current, undefined, location?.id ?? null).catch(() => [])
            : Promise.resolve<MenuItem[]>([]),
          api.getGeneratedCombos(12).catch(() => []),
          api
            .getRecommendationsForContext({
              token: tokenRef.current,
              preferences: preferencesRef.current,
              dedupeMultiLocation: true,
            })
            .catch(() => []),
          tokenRef.current ? api.getOrders(tokenRef.current).catch(() => []) : Promise.resolve<Order[]>([]),
          tokenRef.current
            ? api.getPersonalizedOffers(tokenRef.current, 6).catch(() => [])
            : Promise.resolve<PersonalizedOfferCard[]>([]),
        ]);

        if (!active) {
          return;
        }
        setRestaurant(restaurantRow);
        setMenuItems(menuRows);
        // Everything below is fetched unscoped because the endpoints are shared
        // with the marketplace build. Narrowing here keeps one restaurant's app
        // from advertising another's food.
        setCombos(scoped ? comboRows.filter((row) => row.restaurant_id === scoped) : comboRows);
        setRecommendations(
          scoped ? recommendationRows.filter((row) => row.restaurant.id === scoped) : recommendationRows,
        );
        setOrders(scoped ? orderRows.filter((row) => row.restaurant_id === scoped) : orderRows);
        setOffers(scoped ? offerRows.filter((row) => row.restaurant_id === scoped) : offerRows);
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
    // `feedScopeKey` is the dependency; the values it summarises are read
    // through refs so that a new object identity alone cannot re-fire this.
  }, [feedScopeKey, ready]);

  useEffect(() => {
    if (!token || offers.length === 0) {
      return;
    }
    // Keyed on the match rather than the offer: the same offer can be matched
    // to a customer more than once, and each match is its own impression.
    const keyOf = (offer: PersonalizedOfferCard) =>
      `${offer.generated_offer_user_match_id ?? ''}:${offer.generated_offer_id ?? ''}:${offer.offer_id}`;
    const fresh = offers.filter((offer) => !trackedOfferIdsRef.current.has(keyOf(offer)));
    if (fresh.length === 0) {
      return;
    }
    fresh.forEach((offer) => trackedOfferIdsRef.current.add(keyOf(offer)));
    void api
      .trackPersonalizedOfferEvents(
        token,
        fresh.map((offer) => ({
          offer_id: offer.offer_id,
          generated_offer_id: offer.generated_offer_id,
          generated_offer_user_match_id: offer.generated_offer_user_match_id,
          event_type: 'VIEWED' as const,
          target_type: offer.target_type,
          target_id:
            offer.menu_item_id ??
            offer.generated_combo_id ??
            offer.restaurant_location_id ??
            offer.restaurant_id,
        })),
      )
      .catch(() => undefined);
  }, [offers, token]);

  const categories = useMemo(() => buildMenuCategories(menuItems), [menuItems]);
  const activeCategory = categories.find((entry) => entry.id === selectedCategoryId);

  const filteredMenuItems = useMemo(() => {
    if (!activeCategory || activeCategory.id === 'all') {
      return menuItems;
    }
    return menuItems.filter((item) => (item.category ?? '').toLowerCase() === activeCategory.id);
  }, [activeCategory, menuItems]);

  // A category can disappear when the menu reloads — a branch swap, a dish
  // going off — and a filter pinned to a section that no longer exists would
  // silently show an empty menu.
  useEffect(() => {
    if (selectedCategoryId !== 'all' && !categories.some((entry) => entry.id === selectedCategoryId)) {
      setSelectedCategoryId('all');
    }
  }, [categories, selectedCategoryId]);

  const menuPreview = filteredMenuItems.slice(0, MENU_PREVIEW_COUNT);

  /** Quantity already in the cart, so a tile can show its stepper. */
  const quantityFor = useCallback(
    (menuItemId: string) =>
      cart.items
        .filter((entry) => entry.menuItem.id === menuItemId)
        .reduce((total, entry) => total + entry.quantity, 0),
    [cart.items],
  );

  const requireAuth = useCallback(
    (redirectPath: string) =>
      checkAuthAndRedirect({
        isAuthenticated,
        redirectPath,
        onNavigate,
        pushToast: onToast,
        setPendingAuthRedirectPath,
      }),
    [isAuthenticated, onNavigate, onToast, setPendingAuthRedirectPath],
  );

  /**
   * What the banner shows, in the order a storefront should try: the cover
   * photo the restaurant chose, then its logo, then the first dish it has a
   * picture of. The last is the case that matters — most seeded kitchens have
   * no cover art, and a lettered block where the food should be is the one
   * thing that makes a food page look unfinished.
   */
  const heroImage = useMemo(
    () =>
      restaurant?.cover_image_url ??
      restaurant?.logo_image_url ??
      menuItems.find((item) => item.image_url)?.image_url ??
      null,
    [menuItems, restaurant],
  );

  const restaurantName = restaurant?.name ?? displayName;

  const handleAddMenuItem = useCallback(
    (item: MenuItem) => {
      if (!requireAuth('/')) {
        return;
      }
      // A dish with sizes or add-ons cannot be priced from a tile, so the phone
      // opens it rather than guessing a default.
      if (isCustomizableMenuItem(item)) {
        onNavigate(`/menu-item/${item.id}`);
        return;
      }
      void requestAddToCart({
        menuItem: item,
        restaurantId: item.restaurant_id,
        restaurantName,
      });
    },
    [onNavigate, requestAddToCart, requireAuth, restaurantName],
  );

  const handleDecrease = useCallback(
    (menuItemId: string) => {
      const entry = [...cart.items].reverse().find((row) => row.menuItem.id === menuItemId);
      if (entry) {
        updateCartQuantity(entry.id, entry.quantity - 1);
      }
    },
    [cart.items, updateCartQuantity],
  );

  const handleAddCombo = useCallback(
    (combo: GeneratedCombo) => {
      if (!requireAuth('/')) {
        return;
      }
      for (const item of combo.items) {
        addToCart({
          menuItem: buildMenuItemFromGeneratedComboItem(item, {
            source: 'home-generated-combo',
            restaurantId: combo.restaurant_id,
            restaurantLocationId: combo.restaurant_location_id,
            restaurantLocationName: combo.restaurant_location_name,
            restaurantCuisineType: restaurant?.cuisine_type ?? null,
            createdAt: combo.created_at,
            updatedAt: combo.updated_at,
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
    },
    [addToCart, onToast, requireAuth, restaurant],
  );

  const handleOpenOffer = useCallback(
    (offer: PersonalizedOfferCard) => {
      const selected: AppliedPersonalizedOffer = {
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
      setSelectedPersonalizedOffer(selected);
      if (token) {
        void api
          .trackPersonalizedOfferEvents(token, [
            {
              offer_id: offer.offer_id,
              generated_offer_id: offer.generated_offer_id,
              generated_offer_user_match_id: offer.generated_offer_user_match_id,
              event_type: 'CLICKED',
              target_type: offer.target_type,
              target_id:
                offer.menu_item_id ??
                offer.generated_combo_id ??
                offer.restaurant_location_id ??
                offer.restaurant_id,
            },
          ])
          .catch(() => undefined);
      }
      if (offer.target_type === 'ITEM' && offer.menu_item_id) {
        onNavigate(`/menu-item/${offer.menu_item_id}`);
        return;
      }
      onNavigate('/menu');
    },
    [onNavigate, setSelectedPersonalizedOffer, token],
  );

  const recentOrders = orders.slice(0, 3);
  const hasPicks = recommendations.length > 0;

  return (
    <div className="screen screen--flush home">
      {/* --- hero -----------------------------------------------------------
          One element, two readings. On a phone it is the app's tinted greeting
          card. On a desktop it becomes the restaurant's storefront banner, with
          the cover photo and the facts a first-time visitor looks for before
          they will order: what kind of food, whether the kitchen is open, and
          what delivery costs. */}
      <section className="home-hero">
        {/* The photograph is the banner now, not a panel beside it. Decorative:
            every dish it shows is named and priced in the menu below, so a
            screen reader gains nothing from it. */}
        <div aria-hidden="true" className="home-hero__art">
          {heroImage ? (
            <img alt="" decoding="async" fetchPriority="high" src={heroImage} />
          ) : (
            <span className="home-hero__art-fallback">{displayName.slice(0, 2).toUpperCase()}</span>
          )}
        </div>

        <div className="home-hero__copy">
          <p className="home-hero__greeting">
            <span aria-hidden="true">👋</span> Hi {greetingName(user?.full_name)}
          </p>
          <h1 className="home-hero__title">What are you craving today?</h1>
          <p className="home-hero__subtitle">
            Browse the kitchen, grab today&rsquo;s deals, and let AI build a meal around your
            mood.
          </p>

          <div className="home-hero__facts">
            <span className={restaurant?.is_open === false ? 'fact fact--shut' : 'fact fact--open'}>
              <span className="fact__dot" />
              {restaurant?.is_open === false ? 'Currently closed' : 'Open now'}
            </span>
            {restaurant?.cuisine_type ? <span className="fact">{restaurant.cuisine_type}</span> : null}
            {restaurant ? (
              <span className="fact">
                {toNumber(restaurant.delivery_fee) === 0
                  ? 'Free delivery'
                  : `${formatCurrency(restaurant.delivery_fee)} delivery`}
              </span>
            ) : null}
            {restaurant && toNumber(restaurant.minimum_order_amount) > 0 ? (
              <span className="fact">
                Min {formatCurrency(restaurant.minimum_order_amount)}
              </span>
            ) : null}
            {(restaurant?.locations?.length ?? 0) > 1 ? (
              <span className="fact">{restaurant?.locations?.length} branches</span>
            ) : null}
          </div>

          <SearchBar onPress={() => onNavigate('/search')} placeholder={`Search ${displayName}`} />

          <div className="home-hero__actions">
            <button className="btn" onClick={() => onNavigate('/menu')} type="button">
              See the full menu
            </button>
            <button className="btn btn--quiet" onClick={() => onNavigate('/chat')} type="button">
              Ask AI what to order
            </button>
          </div>
        </div>

      </section>

      {/* --- categories ---------------------------------------------------- */}
      {categories.length > 1 ? (
        <section className="section">
          <SectionHeader
            subtitle="Browse by what fits the craving first."
            title="Categories"
          />
          <CategoryRail
            categories={categories}
            onSelect={setSelectedCategoryId}
            selectedId={selectedCategoryId}
          />
        </section>
      ) : null}

      {/* --- the kitchen's menu -------------------------------------------- */}
      <section className="section">
        <SectionHeader
          actionLabel={menuItems.length > 0 ? 'See full menu' : undefined}
          onAction={menuItems.length > 0 ? () => onNavigate('/menu') : undefined}
          subtitle={
            activeCategory && activeCategory.id !== 'all'
              ? `${filteredMenuItems.length} ${activeCategory.label} ${
                  filteredMenuItems.length === 1 ? 'dish' : 'dishes'
                } ready to order.`
              : 'Browse the kitchen and add straight to your cart.'
          }
          title="Explore Menu"
        />
        {loading && menuItems.length === 0 ? (
          <div className="dish-grid">
            {Array.from({ length: 8 }, (_, index) => (
              <div className="dish-card dish-card--skeleton" key={index} />
            ))}
          </div>
        ) : menuPreview.length > 0 ? (
          <div className="dish-grid">
            {menuPreview.map((item) => (
              <DishCard
                favoritePending={isFavoritePending(item.id)}
                isFavorite={isFavorite(item.id)}
                item={item}
                key={item.id}
                onAdd={handleAddMenuItem}
                onDecrease={handleDecrease}
                onOpen={(itemId) => onNavigate(`/menu-item/${itemId}`)}
                onToggleFavorite={(dish) => void toggleFavorite({ menuItemId: dish.id })}
                quantity={quantityFor(item.id)}
              />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <p className="empty-state__title">
              {menuItems.length > 0 ? 'Nothing in this category yet.' : 'Menu is loading.'}
            </p>
            <p className="empty-state__text">
              {menuItems.length > 0
                ? 'Pick another category to see more dishes.'
                : 'The kitchen menu will appear here in a moment.'}
            </p>
          </div>
        )}
      </section>

      {/* --- ask AI --------------------------------------------------------- */}
      <AiPromptCard onPress={() => onNavigate('/chat')} />

      {/* --- personalized picks --------------------------------------------- */}
      <section className="section">
        <SectionHeader
          actionLabel={hasPicks ? 'See all' : 'Tune picks'}
          onAction={() => onNavigate(hasPicks ? '/picks' : '/profile/preferences')}
          subtitle={
            hasPicks
              ? 'Ranked against your taste profile and order history.'
              : 'Tell us what you like and the ranking sharpens up.'
          }
          title="Personalized Picks"
        />
        {hasPicks ? (
          <div className="rail">
            {recommendations.slice(0, 8).map((item) => (
              <ItemCard
                addDisabled={!favoritesHydrated && false}
                favoritePending={isFavoritePending(item.id)}
                isFavorite={isFavorite(item.id)}
                item={item}
                key={item.id}
                onAddToCart={() => onNavigate(`/menu-item/${item.id}`)}
                onOpenRestaurant={() => onNavigate(`/menu-item/${item.id}`)}
                onToggleFavorite={() => void toggleFavorite({ menuItemId: item.id })}
              />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <p className="empty-state__title">Picks are still warming up</p>
            <p className="empty-state__text">
              {token
                ? 'Your account is active, but the personalized ranking is still catching up. Keep browsing — it sharpens with every order.'
                : 'Log in and tell us about your tastes to unlock stronger matches.'}
            </p>
          </div>
        )}
      </section>

      {/* --- combos ---------------------------------------------------------- */}
      {combos.length > 0 ? (
        <section className="section">
          <SectionHeader
            subtitle="Auto-generated bundles built from real completed orders."
            title="Frequently Ordered Together"
          />
          <div className="rail">
            {combos.map((combo) => (
              <GeneratedComboCard
                combo={combo}
                key={combo.id}
                onAddCombo={handleAddCombo}
                onOpenRestaurant={() => onNavigate('/menu')}
              />
            ))}
          </div>
        </section>
      ) : null}

      {/* --- offers ---------------------------------------------------------- */}
      {token && offers.length > 0 ? (
        <section className="section">
          <SectionHeader
            subtitle="Unlocked automatically the moment your cart qualifies."
            title="Offers"
          />
          <div className="rail">
            {offers.map((offer) => (
              <OfferCard key={`${offer.generated_offer_user_match_id ?? offer.offer_id}`} offer={offer} onOpen={handleOpenOffer} />
            ))}
          </div>
        </section>
      ) : null}

      {/* --- reorder ---------------------------------------------------------- */}
      {recentOrders.length > 0 ? (
        <section className="section">
          <SectionHeader
            actionLabel="See all"
            onAction={() => onNavigate('/orders')}
            subtitle="Jump back into meals you already liked."
            title="Recently Ordered"
          />
          <div className="stack">
            {recentOrders.map((order) => (
              <button
                className="recent-order"
                key={order.id}
                onClick={() => onNavigate(`/orders/${order.id}`)}
                type="button"
              >
                <span className="recent-order__mark">
                  <AppIcon name="receipt" size={18} />
                </span>
                <span className="recent-order__copy">
                  <strong>{order.restaurant.name}</strong>
                  <small>
                    {order.items.length} {order.items.length === 1 ? 'item' : 'items'} ·{' '}
                    {order.status.replaceAll('_', ' ').toLowerCase()}
                  </small>
                </span>
                <span className="recent-order__total">
                  {formatCurrency(toNumber(order.total_amount))}
                </span>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
});
