import React, { useCallback, useMemo, useRef, useState } from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import { RestaurantCard } from '@components/RestaurantCard';
import { AiPromptCard } from '@components/home/AiPromptCard';
import { CategoryCarousel } from '@components/home/CategoryCarousel';
import {
  GeneratedComboCard,
  getGeneratedComboCardMetrics,
} from '@components/home/GeneratedComboCard';
import { HomeHeader } from '@components/home/HomeHeader';
import { HomeSectionHeader } from '@components/home/HomeSectionHeader';
import { HomeSkeleton } from '@components/home/HomeSkeleton';
import {
  MenuGridCard,
  getMenuGridMetrics,
} from '@components/home/MenuGridCard';
import { OfferBannerCard } from '@components/home/OfferBannerCard';
import { RecentOrderCard } from '@components/home/RecentOrderCard';
import { RecommendationCard } from '@components/home/RecommendationCard';
import { SearchPromptBar } from '@components/home/SearchPromptBar';
import {
  useAppActions,
  useCart,
  useFavoritesState,
  usePreferences,
  useSelectedLocation,
  useSession,
} from '@hooks/useAppStore';
import { ApiError, api } from '@services/api';
import { buildMenuItemFromGeneratedComboItem } from '@utils/generatedComboCart';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import { homeCategories } from '@/data/homeCategories';
import { searchSuggestions } from '@/data/searchSuggestions';
import type {
  AppliedPersonalizedOffer,
  GeneratedCombo,
  MenuItem,
  Order,
  PersonalizedRecommendationContext,
  PersonalizedOfferCard,
  RecommendationItem,
  Restaurant,
} from '@/types/app';
import type { ListRenderItem } from 'react-native';
import type { RootStackParamList } from '@/navigation/AppNavigator';
import { checkAuthAndRedirect } from '@utils/authRedirect';
import { isCustomizableMenuItem } from '@utils/menuItemCustomization';
import { sortMenuItemsByRecommendationSignal } from '@utils/menuPersonalization';
import { buildLocationKey, buildPreferencesKey } from '@utils/preferencesKey';

const HOME_FEED_STALE_MS = 90_000;
/**
 * Home shows a preview of the menu as a wrapping 3-per-row grid; two rows keep
 * the rest of the feed reachable, and "See full menu" opens the whole list.
 */
const HOME_MENU_PREVIEW_COUNT = 6;

interface ScopedMenuSnapshot {
  restaurant: Restaurant | null;
  items: MenuItem[];
}

const emptyMenuSnapshot: ScopedMenuSnapshot = { restaurant: null, items: [] };

/**
 * Hard ceiling on one feed load.
 *
 * The axios client already sets `timeout: 120000`, but that is not a guarantee:
 * it is implemented through the native networking module, and a connection that
 * fails at the transport layer can leave the JS promise permanently unsettled -
 * measured on iOS, where feed requests never settled even after 140s. The
 * `Promise.all` below then never resolves, its `finally` never runs, and the
 * screen sits on its skeleton forever with no error and no way back.
 *
 * 25s is well past a slow cold start on a healthy connection, so this only
 * fires when something is genuinely wrong - and when it does, the catch below
 * surfaces the "Feed unavailable" toast and pull-to-refresh still works.
 */
const HOME_FEED_TIMEOUT_MS = 25_000;

/** Rejects if `promise` has not settled within `ms`, so a caller cannot hang. */
function withTimeout<T>(
  promise: Promise<T>,
  ms: number,
  label: string,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`${label} timed out after ${ms}ms`)),
      ms,
    );
    promise.then(
      value => {
        clearTimeout(timer);
        resolve(value);
      },
      error => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

/**
 * Loads the branded app's own menu the same way the restaurant screen does:
 * resolve the restaurant detail, pick its default bookable branch, then read
 * that branch's menu. The backend also scopes `/menu-items` to the app client,
 * so a branded build cannot receive another restaurant's items.
 */
async function loadScopedRestaurantMenu(
  restaurantId: string,
  token: string | null,
): Promise<ScopedMenuSnapshot> {
  const restaurant = await api.getRestaurant(restaurantId, token);
  const location =
    restaurant.locations?.find(entry => entry.is_open && entry.is_active) ??
    restaurant.locations?.find(entry => entry.is_active) ??
    null;
  const items = await api.getMenuItems(
    restaurantId,
    token,
    location?.id ?? null,
  );
  return { restaurant, items };
}

export function HomeScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const { width: screenWidth } = useWindowDimensions();
  const { token, user, appConfig, appConfigStatus } = useSession();
  const { preferences } = usePreferences();
  const { favoritesHydrated } = useFavoritesState();
  const selectedLocation = useSelectedLocation();
  const cart = useCart();
  const {
    isFavorite,
    isFavoritePending,
    pushToast,
    refreshAppConfig,
    addToCart,
    requestAddToCart,
    setSelectedPersonalizedOffer,
    toggleFavorite,
    updateCartQuantity,
  } = useAppActions();
  const navigation =
    useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const [selectedCategoryId, setSelectedCategoryId] = useState('all');
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [generatedCombos, setGeneratedCombos] = useState<GeneratedCombo[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>(
    [],
  );
  const [recommendationContext, setRecommendationContext] =
    useState<PersonalizedRecommendationContext | null>(null);
  const [offers, setOffers] = useState<PersonalizedOfferCard[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [menuItems, setMenuItems] = useState<MenuItem[]>([]);
  const [menuRestaurant, setMenuRestaurant] = useState<Restaurant | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // Distinguishes "still trying to resolve the app config" from "tried and
  // could not", so the screen shows a retry instead of an endless skeleton.
  const [appConfigRetrying, setAppConfigRetrying] = useState(false);
  const [appConfigRetryFailed, setAppConfigRetryFailed] = useState(false);
  const trackedOfferIdsRef = useRef<Set<string>>(new Set());
  const hasLoadedFeedRef = useRef(false);
  const isFeedRequestInFlightRef = useRef(false);
  const lastFeedLoadedAtRef = useRef(0);
  const lastFeedScopeKeyRef = useRef<string | null>(null);
  // The feed request bodies are read from refs so that replacing the
  // `preferences` or `selectedLocation` object without changing its content
  // cannot re-arm the focus effect below. `feedScopeKey` covers real changes.
  const preferencesRef = useRef(preferences);
  const selectedLocationRef = useRef(selectedLocation);

  React.useEffect(() => {
    preferencesRef.current = preferences;
    selectedLocationRef.current = selectedLocation;
  }, [preferences, selectedLocation]);

  const firstName = user?.full_name?.trim().split(/\s+/)[0] ?? 'there';
  const locationLabel =
    selectedLocation?.address.split(',')[0]?.trim() ||
    user?.default_address?.split(',')[0]?.trim() ||
    'Current location';
  const locationSubLabel =
    selectedLocation?.city ||
    user?.default_address?.split(',').map(part => part.trim())[1] ||
    'Tap to choose delivery area';
  const profileInitial = user?.full_name?.trim().charAt(0).toUpperCase() ?? '';
  // `appConfigStatus` is checked FIRST and deliberately: with an unresolved
  // config this expression is false, which is indistinguishable from a genuine
  // marketplace build. That is how a single-restaurant app rendered every
  // restaurant on the platform when the config fetch failed. While unresolved
  // the screen shows the skeleton below instead of committing to either mode.
  const appConfigResolved = appConfigStatus === 'resolved';
  const isSingleRestaurant =
    appConfigResolved &&
    appConfig?.app_mode === 'SINGLE_RESTAURANT' &&
    Boolean(appConfig?.restaurant_id);
  const scopedRestaurantId = isSingleRestaurant
    ? appConfig?.restaurant_id ?? null
    : null;

  const handleRetryAppConfig = useCallback(async () => {
    setAppConfigRetrying(true);
    setAppConfigRetryFailed(false);
    const status = await refreshAppConfig();
    setAppConfigRetrying(false);
    if (status !== 'resolved') {
      setAppConfigRetryFailed(true);
    }
  }, [refreshAppConfig]);

  // One automatic attempt when this screen appears without a config. Bootstrap
  // already retried on its own schedule; this covers the case where the API was
  // still waking when that budget ran out. Ref-guarded so a re-focus cannot
  // turn it into a retry loop — after this, recovery is the user's tap.
  const autoRetriedAppConfigRef = useRef(false);
  useFocusEffect(
    useCallback(() => {
      if (appConfigResolved || autoRetriedAppConfigRef.current) {
        return;
      }
      autoRetriedAppConfigRef.current = true;
      void handleRetryAppConfig();
    }, [appConfigResolved, handleRetryAppConfig]),
  );
  const allCategory = useMemo(
    () => ({ id: 'all', label: 'All', icon: 'apps', query: '' }),
    [],
  );
  const categories = useMemo(() => {
    // A single-restaurant app browses one menu, so the chips come from the
    // dishes that restaurant actually sells rather than the platform-wide
    // cuisine list.
    if (isSingleRestaurant) {
      // The restaurant's own menu is the source of truth for the chips; the
      // recommendation feed is only a fallback while the menu is still loading.
      const categorySource = menuItems.length > 0 ? menuItems : recommendations;
      const menuCategories = Array.from(
        new Set(
          categorySource
            .map(item => item.category?.trim())
            .filter((value): value is string => Boolean(value)),
        ),
      ).sort((first, second) => first.localeCompare(second));

      if (menuCategories.length > 0) {
        return [
          allCategory,
          ...menuCategories.map(category => ({
            id: category.toLowerCase(),
            label: category,
            icon: 'restaurant-outline',
            query: category.toLowerCase(),
          })),
        ];
      }
    }

    return [allCategory, ...homeCategories];
  }, [allCategory, isSingleRestaurant, menuItems, recommendations]);
  const comboCardMetrics = useMemo(
    () => getGeneratedComboCardMetrics(screenWidth),
    [screenWidth],
  );
  const preferenceScopeKey = useMemo(
    () => buildPreferencesKey(preferences),
    [preferences],
  );
  const locationScopeKey = useMemo(
    () => buildLocationKey(selectedLocation),
    [selectedLocation],
  );
  const feedScopeKey = useMemo(
    () =>
      JSON.stringify({
        userId: user?.id ?? null,
        hasToken: Boolean(token),
        preferences: preferenceScopeKey,
        selectedLocation: locationScopeKey,
        // The app scope belongs in this key, not just in loadHomeFeed's deps.
        // `shouldLoad` short-circuits on `hasLoadedFeedRef`, so a feed fetched
        // while the config was still unresolved — unscoped, no restaurant menu
        // — would otherwise be kept until it went stale, even after the config
        // arrived and told us this is a single-restaurant build.
        scopedRestaurantId,
      }),
    [locationScopeKey, preferenceScopeKey, scopedRestaurantId, token, user?.id],
  );

  const loadHomeFeed = useCallback(
    async ({
      force = false,
      mode = 'focus',
    }: {
      force?: boolean;
      mode?: 'focus' | 'manual' | 'scope_change';
    } = {}) => {
      const now = Date.now();
      const scopeChanged = lastFeedScopeKeyRef.current !== feedScopeKey;
      const isStale =
        !lastFeedLoadedAtRef.current ||
        now - lastFeedLoadedAtRef.current >= HOME_FEED_STALE_MS;
      const shouldLoad =
        force || !hasLoadedFeedRef.current || scopeChanged || isStale;

      if (!shouldLoad || isFeedRequestInFlightRef.current) {
        return;
      }

      isFeedRequestInFlightRef.current = true;

      if (mode === 'manual') {
        setRefreshing(true);
      } else if (!hasLoadedFeedRef.current) {
        setLoading(true);
      }

      try {
        const [
          restaurantRows,
          comboRows,
          recommendationRows,
          recommendationContextRow,
          orderRows,
          offerRows,
          menuSnapshot,
        ] = await withTimeout(
          Promise.all([
            api.getRestaurants(token),
            api.getGeneratedCombos(8).catch(() => []),
            api
              .getRecommendationsForContext({
                token,
                preferences: preferencesRef.current,
                dedupeMultiLocation: true,
                selectedLocation: selectedLocationRef.current,
              })
              .catch(() => []),
            token
              ? api
                  .getPersonalizedRecommendationContext(token)
                  .catch(() => null)
              : Promise.resolve(null),
            token ? api.getOrders(token).catch(() => []) : Promise.resolve([]),
            token
              ? api.getPersonalizedOffers(token, 4).catch(error => {
                  console.warn('personalized offers load failed', error);
                  return [];
                })
              : Promise.resolve([]),
            scopedRestaurantId
              ? loadScopedRestaurantMenu(scopedRestaurantId, token).catch(
                  error => {
                    console.warn('scoped menu load failed', error);
                    return emptyMenuSnapshot;
                  },
                )
              : Promise.resolve(emptyMenuSnapshot),
          ]),
          HOME_FEED_TIMEOUT_MS,
          'Home feed',
        );
        setRestaurants(restaurantRows);
        setGeneratedCombos(comboRows);
        setRecommendations(recommendationRows);
        setRecommendationContext(recommendationContextRow);
        setOrders(orderRows);
        setOffers(offerRows);
        setMenuRestaurant(menuSnapshot.restaurant);
        setMenuItems(
          // Same personalization the restaurant screen applies, so the menu
          // preview leads with the dishes this customer is most likely to want.
          sortMenuItemsByRecommendationSignal(
            menuSnapshot.items,
            recommendationRows.filter(
              item => item.restaurant_id === menuSnapshot.restaurant?.id,
            ),
          ),
        );
        hasLoadedFeedRef.current = true;
        lastFeedLoadedAtRef.current = Date.now();
        lastFeedScopeKeyRef.current = feedScopeKey;
      } catch (error) {
        if (!hasLoadedFeedRef.current || mode === 'manual') {
          pushToast(
            'Feed unavailable',
            error instanceof Error
              ? error.message
              : 'Unable to load home feed.',
            'error',
          );
        }
      } finally {
        isFeedRequestInFlightRef.current = false;
        if (mode === 'manual') {
          setRefreshing(false);
        } else {
          setLoading(false);
        }
      }
    },
    [feedScopeKey, pushToast, scopedRestaurantId, token],
  );

  useFocusEffect(
    useCallback(() => {
      void loadHomeFeed({ mode: 'focus' });
    }, [loadHomeFeed]),
  );

  React.useEffect(() => {
    trackedOfferIdsRef.current.clear();
  }, [token]);

  const activeCategory = useMemo(
    () => categories.find(category => category.id === selectedCategoryId),
    [categories, selectedCategoryId],
  );

  const filteredRestaurants = useMemo(() => {
    // In a single-restaurant app the chips filter dishes, not restaurants, so
    // the one restaurant always stays visible.
    if (isSingleRestaurant) {
      return restaurants;
    }
    return restaurants.filter(restaurant => {
      if (activeCategory && activeCategory.query) {
        const label = activeCategory.query.toLowerCase();
        const haystack = [
          restaurant.name,
          restaurant.cuisine_type,
          restaurant.city,
        ]
          .join(' ')
          .toLowerCase();
        if (!haystack.includes(label)) {
          return false;
        }
      }
      return true;
    });
  }, [activeCategory, isSingleRestaurant, restaurants]);
  const restaurantPreview = useMemo(
    () => filteredRestaurants.slice(0, 3),
    [filteredRestaurants],
  );

  const popularRestaurants = useMemo(
    () =>
      [...restaurants]
        .sort(
          (left, right) =>
            Number(right.is_open) - Number(left.is_open) ||
            Number(left.delivery_fee) - Number(right.delivery_fee),
        )
        .slice(0, 3),
    [restaurants],
  );

  const recentOrders = useMemo(() => orders.slice(0, 3), [orders]);

  const personalizedPicks = useMemo(() => {
    if (isSingleRestaurant && activeCategory?.query) {
      const selected = activeCategory.query.toLowerCase();
      return recommendations
        .filter(item => item.category?.trim().toLowerCase() === selected)
        .slice(0, 8);
    }
    return recommendations.slice(0, 8);
  }, [activeCategory, isSingleRestaurant, recommendations]);
  const hasPersonalizedPicks = personalizedPicks.length > 0;

  const filteredMenuItems = useMemo(() => {
    if (!activeCategory?.query) {
      return menuItems;
    }
    const selected = activeCategory.query.toLowerCase();
    return menuItems.filter(
      item => item.category?.trim().toLowerCase() === selected,
    );
  }, [activeCategory, menuItems]);
  const menuPreview = useMemo(
    () => filteredMenuItems.slice(0, HOME_MENU_PREVIEW_COUNT),
    [filteredMenuItems],
  );
  const menuGridMetrics = useMemo(
    () => getMenuGridMetrics(screenWidth),
    [screenWidth],
  );
  const menuCartQuantities = useMemo(
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
  const personalizedSectionTitle =
    recommendationContext?.ai_collection_title?.trim() || 'Personalized Picks';
  const personalizedSectionSubtitle = hasPersonalizedPicks
    ? recommendationContext?.ai_insight?.trim() ||
      'Fresh matches ranked for your tastes.'
    : token
    ? 'We are refreshing your personalized feed. Popular picks stay visible in the meantime.'
    : 'Set a few food signals to make these picks feel even smarter.';

  React.useEffect(() => {
    if (!token || offers.length === 0) {
      return;
    }
    const untrackedOffers = offers.filter(
      offer => !trackedOfferIdsRef.current.has(offer.id),
    );
    if (untrackedOffers.length === 0) {
      return;
    }
    for (const offer of untrackedOffers) {
      trackedOfferIdsRef.current.add(offer.id);
    }
    void api
      .trackPersonalizedOfferEvents(
        token,
        untrackedOffers.map(offer => ({
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

  const handleOpenCart = useCallback(() => {
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

  const handleOpenProfile = useCallback(() => {
    navigation.navigate('MainTabs', { screen: 'Profile' });
  }, [navigation]);
  const handleOpenLocationSelect = useCallback(() => {
    navigation.navigate('LocationSelect');
  }, [navigation]);
  const handleOpenFavorites = useCallback(() => {
    navigation.navigate('Favorites');
  }, [navigation]);
  const handleOpenNotifications = useCallback(() => {
    navigation.navigate('NotificationSettings');
  }, [navigation]);
  const handleOpenSearch = useCallback(() => {
    navigation.navigate('Search');
  }, [navigation]);
  const handleOpenChat = useCallback(() => {
    navigation.navigate('MainTabs', { screen: 'Chat' });
  }, [navigation]);
  const handleOpenRestaurant = useCallback(
    (restaurant: Restaurant) => {
      navigation.navigate('Restaurant', {
        restaurantId: restaurant.id,
        restaurantName: restaurant.name,
      });
    },
    [navigation],
  );
  const handleOpenOrderRestaurant = useCallback(
    (order: Order) => {
      navigation.navigate('Restaurant', {
        restaurantId: order.restaurant_id,
        restaurantName: order.restaurant.name,
      });
    },
    [navigation],
  );

  // Distinct lines in the cart, matching every other cart badge in the app.
  const cartItemCount = cart.items.length;
  const handleManualRefresh = useCallback(() => {
    void loadHomeFeed({ force: true, mode: 'manual' });
  }, [loadHomeFeed]);
  const handleOpenPersonalizedPicks = useCallback(() => {
    navigation.navigate('PersonalizedPicks', {
      initialRecommendations: recommendations,
    });
  }, [navigation, recommendations]);
  const handleOpenRecommendation = useCallback(
    (item: RecommendationItem) => {
      if (
        item.requires_location_selection &&
        (item.available_locations_count ?? 1) > 1
      ) {
        pushToast(
          'Choose a branch',
          `${item.name} is available at ${item.available_locations_count} locations. Pick a branch from the restaurant page first.`,
          'info',
        );
        navigation.navigate('Restaurant', {
          restaurantId: item.restaurant_id,
          restaurantName: item.restaurant.name,
        });
        return;
      }

      navigation.navigate('MenuItemDetail', {
        itemId: item.preferred_menu_item_id ?? item.id,
        restaurantId: item.restaurant_id,
        restaurantName: item.restaurant.name,
      });
    },
    [navigation, pushToast],
  );
  const handleAddRecommendationToCart = useCallback(
    (item: RecommendationItem) => {
      if (
        item.requires_location_selection &&
        (item.available_locations_count ?? 1) > 1
      ) {
        pushToast(
          'Choose a branch',
          `${item.name} is available at ${item.available_locations_count} locations. Open the restaurant to pick a branch before adding it.`,
          'info',
        );
        navigation.navigate('Restaurant', {
          restaurantId: item.restaurant_id,
          restaurantName: item.restaurant.name,
        });
        return;
      }
      if (isCustomizableMenuItem(item)) {
        navigation.navigate('MenuItemDetail', {
          itemId: item.preferred_menu_item_id ?? item.id,
          restaurantId: item.restaurant_id,
          restaurantName: item.restaurant.name,
        });
        return;
      }
      void requestAddToCart(
        {
          ...item,
          id: item.preferred_menu_item_id ?? item.id,
          restaurant_location_id:
            item.preferred_location_id ?? item.restaurant_location_id,
          restaurant_location_name:
            item.preferred_location_name ?? item.restaurant_location_name,
        },
        item.restaurant_id,
        item.restaurant.name,
      );
    },
    [navigation, pushToast, requestAddToCart],
  );
  const handleOpenOffer = useCallback(
    (offer: PersonalizedOfferCard) => {
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
        void api
          .trackPersonalizedOfferEvents(token, [
            {
              offer_id: offer.offer_id,
              generated_offer_id: offer.generated_offer_id,
              generated_offer_user_match_id:
                offer.generated_offer_user_match_id,
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
        navigation.navigate('MenuItemDetail', {
          itemId: offer.menu_item_id,
          restaurantId: offer.restaurant_id,
          restaurantName: offer.restaurant_name,
        });
        return;
      }

      navigation.navigate('Restaurant', {
        restaurantId: offer.restaurant_id,
        restaurantName: offer.restaurant_name,
      });
    },
    [navigation, setSelectedPersonalizedOffer, token],
  );
  const menuRestaurantName =
    menuRestaurant?.name ?? appConfig?.display_name ?? 'Menu';
  const handleOpenMenuItem = useCallback(
    (itemId: string) => {
      if (!scopedRestaurantId) {
        return;
      }
      navigation.navigate('MenuItemDetail', {
        itemId,
        restaurantId: scopedRestaurantId,
        restaurantName: menuRestaurantName,
      });
    },
    [menuRestaurantName, navigation, scopedRestaurantId],
  );
  const handleAddMenuItem = useCallback(
    (item: MenuItem) => {
      if (!scopedRestaurantId) {
        return;
      }
      if (isCustomizableMenuItem(item)) {
        handleOpenMenuItem(item.id);
        return;
      }
      void requestAddToCart(item, scopedRestaurantId, menuRestaurantName);
    },
    [
      handleOpenMenuItem,
      menuRestaurantName,
      requestAddToCart,
      scopedRestaurantId,
    ],
  );
  const handleDecreaseMenuItem = useCallback(
    (itemId: string) => {
      updateCartQuantity(itemId, (menuCartQuantities.get(itemId) ?? 0) - 1);
    },
    [menuCartQuantities, updateCartQuantity],
  );
  const handleOpenFullMenu = useCallback(() => {
    if (!scopedRestaurantId) {
      return;
    }
    navigation.navigate('Restaurant', {
      restaurantId: scopedRestaurantId,
      restaurantName: menuRestaurantName,
    });
  }, [menuRestaurantName, navigation, scopedRestaurantId]);
  const handleToggleRecommendationFavorite = useCallback(
    (item: MenuItem) => {
      if (
        !checkAuthAndRedirect({
          token,
          navigation,
          pushToast,
          redirectTo: { screen: 'MainTabs', params: { screen: 'Home' } },
        })
      ) {
        return;
      }

      void toggleFavorite({ menuItemId: item.id })
        .then(nextFavorite => {
          pushToast(
            nextFavorite ? 'Saved to favorites' : 'Removed from favorites',
            nextFavorite
              ? `${item.name} is now in your favorites.`
              : `${item.name} was removed from favorites.`,
            'success',
          );
        })
        .catch(error => {
          if (
            error instanceof ApiError &&
            (error.status === 401 || error.status === 403)
          ) {
            navigation.navigate('Login', {
              redirectTo: { screen: 'MainTabs', params: { screen: 'Home' } },
            });
          }
          pushToast(
            'Favorites unavailable',
            error instanceof Error
              ? error.message
              : 'Unable to update favorites right now.',
            'error',
          );
        });
    },
    [navigation, pushToast, token, toggleFavorite],
  );
  const renderRecommendationItem = useCallback<
    ListRenderItem<RecommendationItem>
  >(
    ({ item }) => (
      <RecommendationCard
        favoritePending={isFavoritePending(item.id)}
        isFavorite={favoritesHydrated ? isFavorite(item.id) : item.is_favorite}
        item={item}
        onAddToCart={handleAddRecommendationToCart}
        onPress={handleOpenRecommendation}
        onToggleFavorite={handleToggleRecommendationFavorite}
      />
    ),
    [
      favoritesHydrated,
      handleAddRecommendationToCart,
      handleOpenRecommendation,
      handleToggleRecommendationFavorite,
      isFavorite,
      isFavoritePending,
    ],
  );
  const renderMenuItem = useCallback(
    (item: MenuItem) => (
      <MenuGridCard
        key={item.id}
        cardWidth={menuGridMetrics.cardWidth}
        imageHeight={menuGridMetrics.imageHeight}
        item={item}
        onAdd={handleAddMenuItem}
        onDecrease={handleDecreaseMenuItem}
        onOpen={handleOpenMenuItem}
        quantity={
          isCustomizableMenuItem(item)
            ? 0
            : menuCartQuantities.get(item.id) ?? 0
        }
      />
    ),
    [
      handleAddMenuItem,
      handleDecreaseMenuItem,
      handleOpenMenuItem,
      menuCartQuantities,
      menuGridMetrics,
    ],
  );
  const renderPopularRestaurant = useCallback<ListRenderItem<Restaurant>>(
    ({ item }) => (
      <RestaurantCard
        onPress={handleOpenRestaurant}
        restaurant={item}
        variant="compact"
      />
    ),
    [handleOpenRestaurant],
  );
  const renderOfferItem = useCallback<ListRenderItem<PersonalizedOfferCard>>(
    ({ item }) => <OfferBannerCard offer={item} onPress={handleOpenOffer} />,
    [handleOpenOffer],
  );
  const renderRestaurantPreview = useCallback(
    (item: Restaurant) => (
      <RestaurantCard
        key={item.id}
        onPress={handleOpenRestaurant}
        restaurant={item}
      />
    ),
    [handleOpenRestaurant],
  );
  const handleOpenGeneratedCombo = useCallback(
    (combo: GeneratedCombo) => {
      navigation.navigate('Restaurant', {
        restaurantId: combo.restaurant_id,
        restaurantName: combo.restaurant_name,
      });
    },
    [navigation],
  );
  const handleAddGeneratedCombo = useCallback(
    (combo: GeneratedCombo) => {
      const restaurant = restaurants.find(
        entry => entry.id === combo.restaurant_id,
      );
      if (!restaurant) {
        return;
      }
      for (const item of combo.items) {
        addToCart(
          buildMenuItemFromGeneratedComboItem(item, {
            source: 'home-generated-combo',
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
          },
        );
      }
      pushToast(
        'Combo added',
        `${combo.combo_name} is now in your cart.`,
        'success',
      );
    },
    [addToCart, pushToast, restaurants],
  );
  const renderGeneratedCombo = useCallback<ListRenderItem<GeneratedCombo>>(
    ({ item }) => (
      <GeneratedComboCard
        cardHeight={comboCardMetrics.cardHeight}
        cardWidth={comboCardMetrics.cardWidth}
        combo={item}
        heroHeight={comboCardMetrics.heroHeight}
        onAddCombo={handleAddGeneratedCombo}
        onPress={handleOpenGeneratedCombo}
      />
    ),
    [comboCardMetrics, handleAddGeneratedCombo, handleOpenGeneratedCombo],
  );

  const header = (
    <HomeHeader
      cartItemCount={cartItemCount}
      locationLabel={locationLabel}
      locationSubLabel={locationSubLabel}
      onOpenCart={handleOpenCart}
      onOpenFavorites={handleOpenFavorites}
      onOpenLocation={handleOpenLocationSelect}
      onOpenNotifications={handleOpenNotifications}
      onOpenProfile={handleOpenProfile}
      profileInitial={profileInitial}
    />
  );

  // Rendered BEFORE the loading branch and before any feed content: without a
  // resolved config this build does not yet know whether it is a marketplace
  // or a single restaurant, and guessing shows a Bangkok Bowl customer every
  // competitor on the platform. Waiting is the only safe answer.
  if (!appConfigResolved) {
    return (
      <SafeAreaView edges={['top']} style={styles.safeArea}>
        {header}
        <ScrollView
          contentContainerStyle={styles.content}
          showsVerticalScrollIndicator={false}
        >
          {appConfigRetryFailed && !appConfigRetrying ? (
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>Can't reach the server</Text>
              <Text style={styles.emptyText}>
                We couldn't load this app's settings. Check your connection and
                try again.
              </Text>
              <Pressable
                accessibilityRole="button"
                onPress={handleRetryAppConfig}
                style={styles.retryButton}
              >
                <Text style={styles.retryButtonText}>Try again</Text>
              </Pressable>
            </View>
          ) : (
            <HomeSkeleton />
          )}
        </ScrollView>
      </SafeAreaView>
    );
  }

  if (loading) {
    return (
      <SafeAreaView edges={['top']} style={styles.safeArea}>
        {header}

        <ScrollView
          contentContainerStyle={styles.content}
          showsVerticalScrollIndicator={false}
        >
          <HomeSkeleton />
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} style={styles.safeArea}>
      {header}

      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            onRefresh={handleManualRefresh}
            refreshing={refreshing}
            tintColor={theme.colors.primary}
          />
        }
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.heroCard}>
          <View style={styles.heroGlowPrimary} />
          <View style={styles.heroGlowSecondary} />
          <Text style={styles.greeting}>Hi {firstName} 👋</Text>
          <Text style={styles.heroTitle}>What are you craving today?</Text>
          <Text style={styles.heroSubtitle}>
            Discover restaurants, quick deals, and AI-powered meal ideas built
            around your mood.
          </Text>

          <SearchPromptBar
            onPress={handleOpenSearch}
            placeholder={
              isSingleRestaurant && appConfig?.display_name
                ? `Search ${appConfig.display_name}`
                : searchSuggestions[0]
            }
            readOnly
          />
        </View>

        <View style={styles.sectionGap}>
          <HomeSectionHeader
            subtitle="Browse by what fits the craving first."
            title="Categories"
          />
          <CategoryCarousel
            categories={categories}
            onSelectCategory={value => {
              const match = categories.find(
                category => category.label === value,
              );
              setSelectedCategoryId(match?.id ?? 'all');
            }}
            selectedCategory={
              categories.find(category => category.id === selectedCategoryId)
                ?.label ?? 'All'
            }
          />
        </View>

        {isSingleRestaurant ? (
          <View style={styles.sectionGap}>
            <HomeSectionHeader
              actionLabel={menuItems.length > 0 ? 'See full menu' : undefined}
              onActionPress={
                menuItems.length > 0 ? handleOpenFullMenu : undefined
              }
              subtitle={
                activeCategory?.query
                  ? `${filteredMenuItems.length} ${activeCategory.label} ${
                      filteredMenuItems.length === 1 ? 'dish' : 'dishes'
                    } ready to order.`
                  : 'Browse the kitchen and add straight to your cart.'
              }
              title="Explore Menu"
            />
            {menuPreview.length > 0 ? (
              <View style={styles.menuGrid}>
                {menuPreview.map(renderMenuItem)}
              </View>
            ) : (
              <View style={styles.empty}>
                <Text style={styles.emptyTitle}>
                  {menuItems.length > 0
                    ? 'Nothing in this category yet.'
                    : 'Menu is loading.'}
                </Text>
                <Text style={styles.emptyText}>
                  {menuItems.length > 0
                    ? 'Pick another category to see more dishes.'
                    : 'The kitchen menu will appear here in a moment.'}
                </Text>
              </View>
            )}
          </View>
        ) : null}

        <AiPromptCard onPress={handleOpenChat} />

        <View style={styles.sectionGap}>
          <HomeSectionHeader
            actionLabel={hasPersonalizedPicks ? 'See all' : 'Tune picks'}
            onActionPress={() =>
              hasPersonalizedPicks
                ? handleOpenPersonalizedPicks()
                : navigation.navigate('UserPreferences', { mode: 'edit' })
            }
            subtitle={personalizedSectionSubtitle}
            title={personalizedSectionTitle}
          />
          {hasPersonalizedPicks ? (
            <FlatList
              data={personalizedPicks}
              horizontal
              keyExtractor={item => item.id}
              renderItem={renderRecommendationItem}
              showsHorizontalScrollIndicator={false}
            />
          ) : (
            <View style={styles.personalizedFallbackCard}>
              <Text style={styles.personalizedFallbackTitle}>
                Picks are still loading
              </Text>
              <Text style={styles.personalizedFallbackText}>
                {token
                  ? 'Your account is active, but the personalized ranking is still catching up. You can keep browsing restaurants and update taste preferences anytime.'
                  : 'Browse popular restaurants now, or tell us more about your tastes to unlock stronger recommendation matches.'}
              </Text>
            </View>
          )}
        </View>

        {/* A branded app has exactly one restaurant, so a "popular spots" rail
            would just point back at the restaurant the customer is already in. */}
        {!isSingleRestaurant ? (
          <View style={styles.sectionGap}>
            <HomeSectionHeader
              actionLabel={
                popularRestaurants.length > 0 ? 'See all' : undefined
              }
              onActionPress={
                popularRestaurants.length > 0
                  ? () =>
                      navigation.navigate('Restaurants', {
                        initialRestaurants: restaurants,
                      })
                  : undefined
              }
              subtitle="Popular spots worth checking first."
              title="Popular Now"
            />
            <FlatList
              contentContainerStyle={styles.horizontalList}
              data={popularRestaurants}
              horizontal
              keyExtractor={item => item.id}
              renderItem={renderPopularRestaurant}
              showsHorizontalScrollIndicator={false}
            />
          </View>
        ) : null}

        {generatedCombos.length > 0 ? (
          <View style={styles.sectionGap}>
            <HomeSectionHeader
              subtitle="Auto-generated bundles built from real completed orders."
              title="Frequently Ordered Together"
            />
            <FlatList
              contentContainerStyle={styles.horizontalList}
              data={generatedCombos}
              horizontal
              keyExtractor={item => item.id}
              decelerationRate="fast"
              disableIntervalMomentum
              snapToAlignment="start"
              snapToInterval={comboCardMetrics.interval}
              renderItem={renderGeneratedCombo}
              showsHorizontalScrollIndicator={false}
            />
          </View>
        ) : null}

        {token && offers.length > 0 ? (
          <View style={styles.sectionGap}>
            <HomeSectionHeader
              subtitle="Manual restaurant and branch offers that unlock automatically when your cart qualifies."
              title="Offers"
            />
            <FlatList
              data={offers}
              horizontal
              keyExtractor={item => item.id}
              renderItem={renderOfferItem}
              showsHorizontalScrollIndicator={false}
            />
          </View>
        ) : null}

        {recentOrders.length > 0 ? (
          <View style={styles.sectionGap}>
            <HomeSectionHeader
              subtitle="Jump back into meals you already liked."
              title="Recently Ordered"
            />
            <View style={styles.stack}>
              {recentOrders.map(order => (
                <RecentOrderCard
                  key={order.id}
                  onPress={handleOpenOrderRestaurant}
                  order={order}
                />
              ))}
            </View>
          </View>
        ) : null}

        <View style={styles.sectionGap}>
          <HomeSectionHeader
            actionLabel={filteredRestaurants.length > 0 ? 'See all' : undefined}
            onActionPress={
              filteredRestaurants.length > 0
                ? () =>
                    navigation.navigate('Restaurants', {
                      initialRestaurants: filteredRestaurants,
                    })
                : undefined
            }
            subtitle="Open kitchens, fresh menus, and fast delivery around you."
            title="Restaurants"
          />
          <View style={styles.stack}>
            {restaurantPreview.length > 0 ? (
              restaurantPreview.map(renderRestaurantPreview)
            ) : (
              <View style={styles.empty}>
                <Text style={styles.emptyTitle}>
                  No restaurants matched that search.
                </Text>
                <Text style={styles.emptyText}>
                  Try a different category or check back after more restaurants
                  go live nearby.
                </Text>
              </View>
            )}
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    stickyHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      paddingHorizontal: 16,
      paddingTop: 6,
      paddingBottom: 10,
      backgroundColor: theme.colors.background,
    },
    profileButton: {
      width: 44,
      height: 44,
      borderRadius: 22,
      backgroundColor: theme.colors.primarySoft,
      borderWidth: 1,
      borderColor: theme.mode === 'dark' ? theme.colors.border : '#FFD8C7',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
    },
    profileInitial: {
      color: theme.colors.primary,
      fontSize: 16,
      fontWeight: '900',
    },
    headerLocationCard: {
      flex: 1,
      minWidth: 0,
      minHeight: 48,
      borderRadius: 22,
      backgroundColor: theme.colors.surfaceAlt,
      borderWidth: 1,
      borderColor: theme.mode === 'dark' ? theme.colors.border : '#FFE0D1',
      paddingHorizontal: 14,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
    },
    headerLocationCopy: {
      flex: 1,
      minWidth: 0,
    },
    headerLocationText: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    headerLocationSubText: {
      color: theme.colors.secondaryText,
      fontSize: 11,
      marginTop: 1,
    },
    headerActions: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      flexShrink: 0,
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
    content: {
      paddingHorizontal: 16,
      paddingTop: 12,
      gap: 20,
    },
    heroCard: {
      borderRadius: 26,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : '#FFF2EA',
      padding: 16,
      gap: 10,
      overflow: 'hidden',
      position: 'relative',
    },
    heroGlowPrimary: {
      position: 'absolute',
      width: 166,
      height: 166,
      borderRadius: 83,
      top: -44,
      right: -18,
      backgroundColor: 'rgba(255, 82, 0, 0.12)',
    },
    heroGlowSecondary: {
      position: 'absolute',
      width: 104,
      height: 104,
      borderRadius: 52,
      bottom: -34,
      left: -16,
      backgroundColor: 'rgba(255, 189, 153, 0.35)',
    },
    greeting: {
      color: theme.colors.primary,
      fontWeight: '800',
      fontSize: 14,
    },
    heroTitle: {
      color: theme.colors.text,
      fontSize: 26,
      fontWeight: '900',
      lineHeight: 31,
    },
    heroSubtitle: {
      color: theme.colors.secondaryText,
      lineHeight: 19,
      fontSize: 12,
    },
    sectionGap: {
      gap: 12,
    },
    personalizedFallbackCard: {
      borderRadius: 18,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 16,
      gap: 8,
    },
    personalizedFallbackTitle: {
      color: theme.colors.text,
      fontWeight: '800',
      fontSize: 15,
    },
    personalizedFallbackText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 20,
    },
    stack: {
      gap: 14,
    },
    horizontalList: {
      paddingRight: 16,
    },
    menuGrid: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      // Cards keep their own height instead of stretching to the row height.
      alignItems: 'flex-start',
      gap: 10,
    },
    empty: {
      borderRadius: 24,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 20,
      gap: 8,
    },
    emptyTitle: {
      color: theme.colors.text,
      fontWeight: '800',
      fontSize: 16,
    },
    emptyText: {
      color: theme.colors.secondaryText,
      lineHeight: 20,
    },
    retryButton: {
      marginTop: 12,
      alignSelf: 'flex-start',
      borderRadius: 999,
      paddingHorizontal: 20,
      paddingVertical: 10,
      backgroundColor: theme.colors.primary,
    },
    retryButtonText: {
      color: theme.colors.onPrimary,
      fontWeight: '700',
    },
  });

export const styles = createStyles(theme);
