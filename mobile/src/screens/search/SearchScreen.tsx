import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import { FavoriteIconButton } from '@components/FavoriteIconButton';
import { RestaurantCard } from '@components/RestaurantCard';
import { SkeletonBlock } from '@components/SkeletonBlock';
import { homeCategories } from '@/data/homeCategories';
import { searchSuggestions } from '@/data/searchSuggestions';
import {
  useAppActions,
  useFavoritesState,
  usePreferences,
  useSession,
} from '@hooks/useAppStore';
import { ApiError, api, formatCurrency, placeholderImage } from '@services/api';
import { storage } from '@services/storage';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { MenuItem, RecommendationItem, Restaurant } from '@/types/app';
import type { RootStackParamList } from '@/navigation/AppNavigator';
import { isCustomizableMenuItem } from '@utils/menuItemCustomization';
import { buildPreferencesKey } from '@utils/preferencesKey';

type SearchNavigation = NativeStackNavigationProp<RootStackParamList>;

type SearchDishResult = {
  item: MenuItem;
  restaurantId: string;
  restaurantName: string;
  restaurantCuisine: string;
  restaurantCity: string;
  source: 'recommendation' | 'menu';
  matchScore: number;
};

const POPULAR_SEARCHES = [
  'Pizza',
  'Burger',
  'Biryani',
  'Momos',
  'Dessert',
  'Coffee',
  'Rolls',
  'Healthy',
] as const;

const MAX_RECENT_SEARCHES = 8;

function normalizeText(value: string): string {
  return value.trim().toLowerCase();
}

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function buildRecentSearchHistory(
  current: string[],
  nextValue: string,
): string[] {
  const normalized = nextValue.trim();
  if (!normalized) {
    return current;
  }

  return [
    normalized,
    ...current.filter(
      value => value.toLowerCase() !== normalized.toLowerCase(),
    ),
  ].slice(0, MAX_RECENT_SEARCHES);
}

function getTextMatchScore(
  value: string | null | undefined,
  query: string,
): number {
  const normalizedValue = normalizeText(value ?? '');
  if (!normalizedValue || !query) {
    return 0;
  }
  if (normalizedValue === query) {
    return 120;
  }
  if (normalizedValue.startsWith(query)) {
    return 80;
  }
  if (normalizedValue.includes(query)) {
    return 40;
  }
  return 0;
}

function getRestaurantMatchScore(
  restaurant: Restaurant,
  query: string,
): number {
  if (!query) {
    return 0;
  }

  return (
    getTextMatchScore(restaurant.name, query) * 2 +
    getTextMatchScore(restaurant.cuisine_type, query) +
    getTextMatchScore(restaurant.city, query) +
    getTextMatchScore(restaurant.address_line_1, query)
  );
}

function getDishMatchScore(
  result: Omit<SearchDishResult, 'matchScore'>,
  query: string,
): number {
  if (!query) {
    return 0;
  }

  return (
    getTextMatchScore(result.item.name, query) * 2 +
    getTextMatchScore(result.item.category, query) +
    getTextMatchScore(result.item.description, query) +
    getTextMatchScore(result.restaurantName, query) +
    getTextMatchScore(result.restaurantCuisine, query)
  );
}

function SearchScreenSkeleton(): React.JSX.Element {
  const styles = useThemedStyles(createStyles);

  return (
    <ScrollView
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
    >
      <SkeletonBlock height={62} />
      <SkeletonBlock height={132} />
      <View style={styles.discoverySkeletonRow}>
        <SkeletonBlock height={40} width="31%" />
        <SkeletonBlock height={40} width="31%" />
        <SkeletonBlock height={40} width="31%" />
      </View>
      <SkeletonBlock height={18} width="42%" />
      <SkeletonBlock height={112} />
      <SkeletonBlock height={112} />
      <SkeletonBlock height={18} width="36%" />
      <SkeletonBlock height={96} />
      <SkeletonBlock height={96} />
    </ScrollView>
  );
}

function SectionHeader({
  title,
  subtitle,
  rightLabel,
  actionLabel,
  onActionPress,
}: {
  title: string;
  subtitle?: string;
  rightLabel?: string;
  actionLabel?: string;
  onActionPress?: () => void;
}): React.JSX.Element {
  const styles = useThemedStyles(createStyles);

  return (
    <View style={styles.sectionHeader}>
      <View style={styles.sectionHeaderCopy}>
        <Text style={styles.sectionTitle}>{title}</Text>
        {subtitle ? (
          <Text style={styles.sectionSubtitle}>{subtitle}</Text>
        ) : null}
      </View>
      {actionLabel && onActionPress ? (
        <Pressable onPress={onActionPress} style={styles.sectionAction}>
          <Text style={styles.sectionActionText}>{actionLabel}</Text>
        </Pressable>
      ) : rightLabel ? (
        <Text style={styles.sectionMeta}>{rightLabel}</Text>
      ) : null}
    </View>
  );
}

function HighlightedText({
  text,
  query,
  style,
  highlightStyle,
  numberOfLines,
}: {
  text: string;
  query: string;
  style: object;
  highlightStyle: object;
  numberOfLines?: number;
}): React.JSX.Element {
  const normalizedQuery = normalizeText(query);
  const lowerText = text.toLowerCase();

  if (!normalizedQuery || !lowerText.includes(normalizedQuery)) {
    return (
      <Text numberOfLines={numberOfLines} style={style}>
        {text}
      </Text>
    );
  }

  const nodes: React.ReactNode[] = [];
  let searchIndex = 0;
  let key = 0;

  while (searchIndex < text.length) {
    const matchIndex = lowerText.indexOf(normalizedQuery, searchIndex);
    if (matchIndex === -1) {
      nodes.push(<Text key={`plain-${key++}`}>{text.slice(searchIndex)}</Text>);
      break;
    }

    if (matchIndex > searchIndex) {
      nodes.push(
        <Text key={`plain-${key++}`}>
          {text.slice(searchIndex, matchIndex)}
        </Text>,
      );
    }

    nodes.push(
      <Text key={`match-${key++}`} style={highlightStyle}>
        {text.slice(matchIndex, matchIndex + normalizedQuery.length)}
      </Text>,
    );
    searchIndex = matchIndex + normalizedQuery.length;
  }

  return (
    <Text numberOfLines={numberOfLines} style={style}>
      {nodes}
    </Text>
  );
}

function SearchChipComponent({
  icon,
  label,
  onPress,
  tone = 'default',
}: {
  icon?: string;
  label: string;
  onPress: () => void;
  tone?: 'default' | 'accent';
}): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const accent = tone === 'accent';

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        accent ? styles.discoveryChipAccent : styles.discoveryChip,
        pressed ? styles.discoveryChipPressed : null,
      ]}
    >
      {icon ? (
        <Icon
          color={accent ? theme.colors.primary : theme.colors.hint}
          name={icon}
          size={14}
        />
      ) : null}
      <Text
        style={
          accent ? styles.discoveryChipTextAccent : styles.discoveryChipText
        }
      >
        {label}
      </Text>
    </Pressable>
  );
}

/**
 * Memoized: the search screen re-renders on every keystroke, and these
 * cards depend only on their props.
 */
const SearchChip = React.memo(SearchChipComponent);

function CuisineCardComponent({
  label,
  query,
  onPress,
}: {
  label: string;
  query: string;
  onPress: () => void;
}): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);

  return (
    <Pressable onPress={onPress} style={styles.cuisineCard}>
      <View style={styles.cuisineIconWrap}>
        <Icon
          color={theme.colors.primary}
          name="restaurant-outline"
          size={16}
        />
      </View>
      <View style={styles.cuisineCopy}>
        <HighlightedText
          highlightStyle={styles.cuisineHighlight}
          query={query}
          style={styles.cuisineTitle}
          text={label}
        />
        <Text style={styles.cuisineMeta}>Cuisine match</Text>
      </View>
      <Icon color={theme.colors.primary} name="arrow-forward" size={16} />
    </Pressable>
  );
}

/**
 * Memoized: the search screen re-renders on every keystroke, and these
 * cards depend only on their props.
 */
const CuisineCard = React.memo(CuisineCardComponent);

function RestaurantResultCardComponent({
  restaurant,
  query,
  onPress,
}: {
  restaurant: Restaurant;
  query: string;
  onPress: () => void;
}): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.restaurantCard,
        pressed ? styles.cardPressed : null,
      ]}
    >
      <Image
        source={{
          uri: restaurant.cover_image_url ?? placeholderImage(restaurant.name),
        }}
        style={styles.restaurantImage}
      />
      <View style={styles.restaurantCardCopy}>
        <View style={styles.restaurantCardTopRow}>
          <HighlightedText
            highlightStyle={styles.resultHighlight}
            numberOfLines={1}
            query={query}
            style={styles.restaurantCardTitle}
            text={restaurant.name}
          />
          <View
            style={[
              styles.statusPill,
              restaurant.is_open
                ? styles.statusPillOpen
                : styles.statusPillClosed,
            ]}
          >
            <Text
              style={[
                styles.statusPillText,
                restaurant.is_open
                  ? styles.statusPillTextOpen
                  : styles.statusPillTextClosed,
              ]}
            >
              {restaurant.is_open ? 'Open' : 'Closed'}
            </Text>
          </View>
        </View>
        <HighlightedText
          highlightStyle={styles.resultHighlight}
          numberOfLines={1}
          query={query}
          style={styles.restaurantCardMeta}
          text={`${restaurant.cuisine_type} • ${restaurant.city}`}
        />
        <View style={styles.restaurantBadgeRow}>
          <View style={styles.inlineMetaBadge}>
            <Icon
              color={theme.colors.primary}
              name="bicycle-outline"
              size={13}
            />
            <Text style={styles.inlineMetaBadgeText}>
              {formatCurrency(restaurant.delivery_fee)}
            </Text>
          </View>
          <View style={styles.inlineMetaBadge}>
            <Icon
              color={theme.colors.primary}
              name="wallet-outline"
              size={13}
            />
            <Text style={styles.inlineMetaBadgeText}>
              Min {formatCurrency(restaurant.minimum_order_amount)}
            </Text>
          </View>
        </View>
      </View>
      <View style={styles.restaurantActionWrap}>
        <Text style={styles.restaurantActionText}>Open</Text>
        <Icon color={theme.colors.primary} name="chevron-forward" size={16} />
      </View>
    </Pressable>
  );
}

/**
 * Memoized: the search screen re-renders on every keystroke, and these
 * cards depend only on their props.
 */
const RestaurantResultCard = React.memo(RestaurantResultCardComponent);

function DishResultCardComponent({
  result,
  query,
  isFavorite,
  favoritePending,
  onOpenDish,
  onOpenRestaurant,
  onAddToCart,
  onToggleFavorite,
}: {
  result: SearchDishResult;
  query: string;
  isFavorite: boolean;
  favoritePending: boolean;
  onOpenDish: () => void;
  onOpenRestaurant: () => void;
  onAddToCart: () => void;
  onToggleFavorite: () => void;
}): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const { item } = result;

  return (
    <Pressable
      onPress={onOpenDish}
      style={({ pressed }) => [
        styles.dishCard,
        pressed ? styles.cardPressed : null,
      ]}
    >
      <Image
        source={{ uri: item.image_url ?? placeholderImage(item.name) }}
        style={styles.dishImage}
      />
      <View style={styles.dishCardCopy}>
        <View style={styles.dishCardTopRow}>
          <View style={styles.dishTitleWrap}>
            <View
              style={[
                styles.vegDot,
                {
                  backgroundColor: item.is_veg
                    ? theme.colors.offer
                    : theme.colors.deepRed,
                },
              ]}
            />
            <HighlightedText
              highlightStyle={styles.resultHighlight}
              numberOfLines={1}
              query={query}
              style={styles.dishTitle}
              text={item.name}
            />
          </View>
          <FavoriteIconButton
            active={isFavorite}
            disabled={favoritePending}
            onPress={onToggleFavorite}
          />
        </View>
        <Pressable onPress={onOpenRestaurant} style={styles.dishRestaurantRow}>
          <HighlightedText
            highlightStyle={styles.resultHighlight}
            numberOfLines={1}
            query={query}
            style={styles.dishRestaurant}
            text={`${result.restaurantName} • ${result.restaurantCuisine}`}
          />
        </Pressable>
        <Text numberOfLines={2} style={styles.dishDescription}>
          {item.description ?? `${item.category} from ${result.restaurantName}`}
        </Text>
        <View style={styles.dishCardBottomRow}>
          <View style={styles.dishMetaStack}>
            <Text style={styles.dishPrice}>{formatCurrency(item.price)}</Text>
            <View style={styles.dishBadgeRow}>
              <View style={styles.tinyBadge}>
                <Text style={styles.tinyBadgeText}>{item.category}</Text>
              </View>
              {item.is_bestseller ? (
                <View style={styles.tinyBadgeAccent}>
                  <Text style={styles.tinyBadgeTextAccent}>Popular</Text>
                </View>
              ) : null}
              {item.is_new ? (
                <View style={styles.tinyBadgeAccent}>
                  <Text style={styles.tinyBadgeTextAccent}>New</Text>
                </View>
              ) : null}
            </View>
          </View>
          <Pressable
            disabled={!item.is_available}
            onPress={onAddToCart}
            style={[
              styles.addButton,
              !item.is_available ? styles.addButtonDisabled : null,
            ]}
          >
            <Text
              style={[
                styles.addButtonText,
                !item.is_available ? styles.addButtonTextDisabled : null,
              ]}
            >
              {item.is_available ? 'ADD' : 'Sold out'}
            </Text>
          </Pressable>
        </View>
      </View>
    </Pressable>
  );
}

/**
 * Memoized: the search screen re-renders on every keystroke, and these
 * cards depend only on their props.
 */
const DishResultCard = React.memo(DishResultCardComponent);

function PopularPickMiniCardComponent({
  result,
  onPress,
}: {
  result: SearchDishResult;
  onPress: () => void;
}): React.JSX.Element {
  const styles = useThemedStyles(createStyles);

  return (
    <Pressable onPress={onPress} style={styles.popularPickCard}>
      <Text numberOfLines={1} style={styles.popularPickTitle}>
        {result.item.name}
      </Text>
      <Text numberOfLines={1} style={styles.popularPickMeta}>
        {result.restaurantName}
      </Text>
      <Text style={styles.popularPickPrice}>
        {formatCurrency(result.item.price)}
      </Text>
    </Pressable>
  );
}

/**
 * Memoized: the search screen re-renders on every keystroke, and these
 * cards depend only on their props.
 */
const PopularPickMiniCard = React.memo(PopularPickMiniCardComponent);

function DiscoveryDishCarouselCardComponent({
  result,
  badgeLabel,
  onOpenDish,
  onAddToCart,
}: {
  result: SearchDishResult;
  badgeLabel?: string;
  onOpenDish: () => void;
  onAddToCart: () => void;
}): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);

  return (
    <Pressable
      onPress={onOpenDish}
      style={({ pressed }) => [
        styles.discoveryDishCard,
        pressed ? styles.cardPressed : null,
      ]}
    >
      <View style={styles.discoveryDishImageWrap}>
        <Image
          source={{
            uri: result.item.image_url ?? placeholderImage(result.item.name),
          }}
          style={styles.discoveryDishImage}
        />
        {badgeLabel ? (
          <View style={styles.discoveryDishBadge}>
            <Text style={styles.discoveryDishBadgeText}>{badgeLabel}</Text>
          </View>
        ) : null}
      </View>

      <View style={styles.discoveryDishBody}>
        <View style={styles.discoveryDishTitleRow}>
          <View
            style={[
              styles.vegDot,
              {
                backgroundColor: result.item.is_veg
                  ? theme.colors.offer
                  : theme.colors.deepRed,
              },
            ]}
          />
          <Text numberOfLines={1} style={styles.discoveryDishTitle}>
            {result.item.name}
          </Text>
        </View>

        <Text numberOfLines={1} style={styles.discoveryDishMeta}>
          {result.restaurantName} • {result.restaurantCuisine}
        </Text>

        <View style={styles.discoveryDishChipRow}>
          <View style={styles.discoveryMiniChip}>
            <Text numberOfLines={1} style={styles.discoveryMiniChipText}>
              {result.item.category}
            </Text>
          </View>
          {result.item.is_bestseller ? (
            <View style={styles.discoveryMiniChipAccent}>
              <Text
                numberOfLines={1}
                style={styles.discoveryMiniChipTextAccent}
              >
                Popular
              </Text>
            </View>
          ) : null}
        </View>

        <View style={styles.discoveryDishFooter}>
          <Text style={styles.discoveryDishPrice}>
            {formatCurrency(result.item.price)}
          </Text>
          <Pressable
            disabled={!result.item.is_available}
            onPress={event => {
              event.stopPropagation();
              onAddToCart();
            }}
            style={[
              styles.discoveryAddButton,
              !result.item.is_available ? styles.addButtonDisabled : null,
            ]}
          >
            <Text
              style={[
                styles.discoveryAddButtonText,
                !result.item.is_available ? styles.addButtonTextDisabled : null,
              ]}
            >
              {result.item.is_available ? 'Add' : 'Sold'}
            </Text>
          </Pressable>
        </View>
      </View>
    </Pressable>
  );
}

/**
 * Memoized: the search screen re-renders on every keystroke, and these
 * cards depend only on their props.
 */
const DiscoveryDishCarouselCard = React.memo(
  DiscoveryDishCarouselCardComponent,
);

export function SearchScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation = useNavigation<SearchNavigation>();
  const { token, appConfig, appConfigStatus } = useSession();
  const { preferences } = usePreferences();
  const { favoritesHydrated } = useFavoritesState();
  const {
    isFavorite,
    isFavoritePending,
    pushToast,
    requestAddToCart,
    toggleFavorite,
  } = useAppActions();
  // Same rule as HomeScreen: an unresolved config must never read as
  // marketplace, or a single-restaurant build would search the whole platform
  // and surface competitors' dishes. The loading gate below holds the screen
  // until the mode is known.
  const appConfigResolved = appConfigStatus === 'resolved';
  const isSingleRestaurant =
    appConfigResolved &&
    appConfig?.app_mode === 'SINGLE_RESTAURANT' &&
    Boolean(appConfig?.restaurant_id);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>(
    [],
  );
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const [menuItemsByRestaurant, setMenuItemsByRestaurant] = useState<
    Record<string, MenuItem[]>
  >({});
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [menuSearchLoading, setMenuSearchLoading] = useState(false);
  const [inputFocused, setInputFocused] = useState(false);
  const [screenError, setScreenError] = useState<string | null>(null);
  const [showAllPopularSearches, setShowAllPopularSearches] = useState(false);
  const [showAllCuisines, setShowAllCuisines] = useState(false);
  const [showAllRecentSearches, setShowAllRecentSearches] = useState(false);
  const menuItemsByRestaurantRef = useRef<Record<string, MenuItem[]>>({});
  const inFlightRestaurantIdsRef = useRef(new Set<string>());
  const menuFetchGenerationRef = useRef(0);
  const preferencesRef = useRef(preferences);
  // Preference content, so a replaced-but-identical preferences object no
  // longer refetches the search feed.
  const preferencesKey = useMemo(
    () => buildPreferencesKey(preferences),
    [preferences],
  );

  useEffect(() => {
    menuItemsByRestaurantRef.current = menuItemsByRestaurant;
  }, [menuItemsByRestaurant]);

  useEffect(() => {
    preferencesRef.current = preferences;
  }, [preferences]);

  const persistRecentSearches = useCallback(async (nextSearches: string[]) => {
    setRecentSearches(nextSearches);
    await storage.writeSearchHistory(nextSearches);
  }, []);

  const commitSearch = useCallback(
    async (value: string) => {
      const trimmed = value.trim();
      if (!trimmed) {
        return;
      }
      const nextHistory = buildRecentSearchHistory(recentSearches, trimmed);
      await persistRecentSearches(nextHistory);
    },
    [persistRecentSearches, recentSearches],
  );

  const loadSearchFeed = useCallback(
    async (isRefresh = false) => {
      setScreenError(null);
      if (isRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      try {
        const [restaurantsResult, recommendationsResult] =
          await Promise.allSettled([
            api.getRestaurants(token),
            api.getRecommendationsForContext({
              token,
              preferences: preferencesRef.current,
            }),
          ]);

        if (restaurantsResult.status === 'fulfilled') {
          setRestaurants(restaurantsResult.value);
        } else {
          const message =
            restaurantsResult.reason instanceof Error
              ? restaurantsResult.reason.message
              : 'Unable to load search content right now.';
          console.warn(
            '[SearchScreen] getRestaurants failed',
            restaurantsResult.reason,
          );
          setScreenError(message);
          pushToast('Search unavailable', message, 'error');
        }

        if (recommendationsResult.status === 'fulfilled') {
          setRecommendations(recommendationsResult.value);
        } else {
          console.warn(
            '[SearchScreen] getRecommendationsForContext failed',
            recommendationsResult.reason,
          );
          setRecommendations([]);
        }
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : 'Unable to load search content right now.';
        console.error('[SearchScreen] loadSearchFeed crashed', error);
        setScreenError(message);
        pushToast('Search unavailable', message, 'error');
      } finally {
        if (isRefresh) {
          setRefreshing(false);
        } else {
          setLoading(false);
        }
      }
    },
    // `preferences` is read from a ref; this key is what re-runs the feed when
    // the preference content actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [preferencesKey, pushToast, token],
  );

  useEffect(() => {
    void loadSearchFeed();
  }, [loadSearchFeed]);

  useEffect(() => {
    let active = true;

    const loadSearchHistory = async () => {
      try {
        const history = await storage.readSearchHistory();
        if (active) {
          setRecentSearches(history);
        }
      } catch (error) {
        console.warn('[SearchScreen] readSearchHistory failed', error);
      }
    };

    void loadSearchHistory();

    return () => {
      active = false;
    };
  }, []);

  const [debouncedMenuQuery, setDebouncedMenuQuery] = useState('');

  useEffect(() => {
    const timeout = setTimeout(() => {
      setDebouncedMenuQuery(query.trim());
    }, 280);

    return () => clearTimeout(timeout);
  }, [query]);

  const restaurantsById = useMemo(
    () =>
      restaurants.reduce<Record<string, Restaurant>>(
        (accumulator, restaurant) => {
          accumulator[restaurant.id] = restaurant;
          return accumulator;
        },
        {},
      ),
    [restaurants],
  );

  const cuisineCatalog = useMemo(() => {
    const restaurantCuisines = restaurants.map(
      restaurant => restaurant.cuisine_type,
    );

    // A single-restaurant app should only suggest what that restaurant serves,
    // never the platform-wide cuisine list.
    if (isSingleRestaurant) {
      const menuCategories = Object.values(menuItemsByRestaurant)
        .flat()
        .map(item => item.category);
      return uniqueStrings([...restaurantCuisines, ...menuCategories]).slice(
        0,
        10,
      );
    }

    return uniqueStrings([
      ...homeCategories.map(category => category.label),
      ...restaurantCuisines,
    ]).slice(0, 10);
  }, [isSingleRestaurant, menuItemsByRestaurant, restaurants]);

  const discoveryRestaurants = useMemo(
    () =>
      [...restaurants]
        .sort((left, right) => Number(right.is_open) - Number(left.is_open))
        .slice(0, 6),
    [restaurants],
  );

  const featuredRecommendationResults = useMemo(
    () =>
      recommendations.slice(0, 6).map(result => ({
        item: result,
        restaurantId: result.restaurant_id,
        restaurantName: result.restaurant.name,
        restaurantCuisine: result.restaurant.cuisine_type,
        restaurantCity: result.restaurant.city,
        source: 'recommendation' as const,
        matchScore: 0,
      })),
    [recommendations],
  );

  const normalizedQuery = useMemo(() => normalizeText(query), [query]);
  const hasActiveQuery = normalizedQuery.length > 0;

  const searchableDishResults = useMemo(() => {
    const dishMap = new Map<string, SearchDishResult>();

    recommendations.forEach(item => {
      dishMap.set(item.id, {
        item,
        restaurantId: item.restaurant_id,
        restaurantName: item.restaurant.name,
        restaurantCuisine: item.restaurant.cuisine_type,
        restaurantCity: item.restaurant.city,
        source: 'recommendation',
        matchScore: 0,
      });
    });

    Object.entries(menuItemsByRestaurant).forEach(([restaurantId, items]) => {
      const restaurant = restaurantsById[restaurantId];
      if (!restaurant) {
        return;
      }

      items.forEach(item => {
        if (!dishMap.has(item.id)) {
          dishMap.set(item.id, {
            item,
            restaurantId,
            restaurantName: restaurant.name,
            restaurantCuisine: restaurant.cuisine_type,
            restaurantCity: restaurant.city,
            source: 'menu',
            matchScore: 0,
          });
        }
      });
    });

    return Array.from(dishMap.values());
  }, [menuItemsByRestaurant, recommendations, restaurantsById]);

  const matchingRestaurants = useMemo(() => {
    if (!hasActiveQuery) {
      return [];
    }

    return restaurants
      .map(restaurant => ({
        restaurant,
        score: getRestaurantMatchScore(restaurant, normalizedQuery),
      }))
      .filter(entry => entry.score > 0)
      .sort((left, right) => {
        if (right.score !== left.score) {
          return right.score - left.score;
        }
        return (
          Number(right.restaurant.is_open) - Number(left.restaurant.is_open)
        );
      })
      .map(entry => entry.restaurant)
      .slice(0, 8);
  }, [hasActiveQuery, normalizedQuery, restaurants]);

  const matchingDishes = useMemo(() => {
    if (!hasActiveQuery) {
      return [];
    }

    return searchableDishResults
      .map(result => ({
        ...result,
        matchScore: getDishMatchScore(result, normalizedQuery),
      }))
      .filter(result => result.matchScore > 0)
      .sort((left, right) => {
        if (right.matchScore !== left.matchScore) {
          return right.matchScore - left.matchScore;
        }
        if (left.item.is_available !== right.item.is_available) {
          return (
            Number(right.item.is_available) - Number(left.item.is_available)
          );
        }
        if (left.source !== right.source) {
          return left.source === 'recommendation' ? -1 : 1;
        }
        return (
          Number(right.item.is_bestseller) - Number(left.item.is_bestseller)
        );
      })
      .slice(0, 10);
  }, [hasActiveQuery, normalizedQuery, searchableDishResults]);

  const matchingCuisines = useMemo(() => {
    if (!hasActiveQuery) {
      return [];
    }

    return cuisineCatalog.filter(cuisine =>
      normalizeText(cuisine).includes(normalizedQuery),
    );
  }, [cuisineCatalog, hasActiveQuery, normalizedQuery]);

  const popularPickResults = useMemo(
    () =>
      matchingDishes
        .filter(
          result =>
            result.source === 'recommendation' ||
            result.item.is_bestseller ||
            result.item.is_new,
        )
        .slice(0, 4),
    [matchingDishes],
  );

  const discoveryTrendingResults = useMemo(() => {
    const seenItemIds = new Set<string>();
    const rows: SearchDishResult[] = [];

    searchableDishResults.forEach(result => {
      if (seenItemIds.has(result.item.id)) {
        return;
      }
      if (
        result.source === 'recommendation' ||
        result.item.is_bestseller ||
        result.item.is_new
      ) {
        seenItemIds.add(result.item.id);
        rows.push(result);
      }
    });

    return rows.slice(0, 6);
  }, [searchableDishResults]);

  const visiblePopularSearches = useMemo(
    () =>
      showAllPopularSearches
        ? [...POPULAR_SEARCHES]
        : POPULAR_SEARCHES.slice(0, 4),
    [showAllPopularSearches],
  );

  const visibleCuisines = useMemo(
    () => (showAllCuisines ? cuisineCatalog : cuisineCatalog.slice(0, 6)),
    [cuisineCatalog, showAllCuisines],
  );

  const visibleRecentSearches = useMemo(
    () => (showAllRecentSearches ? recentSearches : recentSearches.slice(0, 4)),
    [recentSearches, showAllRecentSearches],
  );

  const candidateRestaurantIds = useMemo(() => {
    if (!debouncedMenuQuery) {
      return [];
    }

    const scoredMatches = restaurants
      .map(restaurant => ({
        restaurantId: restaurant.id,
        score: getRestaurantMatchScore(
          restaurant,
          normalizeText(debouncedMenuQuery),
        ),
      }))
      .filter(entry => entry.score > 0)
      .sort((left, right) => right.score - left.score)
      .map(entry => entry.restaurantId);

    if (scoredMatches.length > 0) {
      return scoredMatches.slice(0, 4);
    }

    return restaurants
      .filter(restaurant => restaurant.is_open)
      .slice(0, 3)
      .map(restaurant => restaurant.id);
  }, [debouncedMenuQuery, restaurants]);

  const ensureRestaurantMenus = useCallback(
    async (restaurantIds: string[], options?: { silent?: boolean }) => {
      const idsToFetch = restaurantIds.filter(restaurantId => {
        if (menuItemsByRestaurantRef.current[restaurantId]) {
          return false;
        }
        if (inFlightRestaurantIdsRef.current.has(restaurantId)) {
          return false;
        }
        return true;
      });

      if (idsToFetch.length === 0) {
        return;
      }

      idsToFetch.forEach(restaurantId =>
        inFlightRestaurantIdsRef.current.add(restaurantId),
      );

      const generation = ++menuFetchGenerationRef.current;
      if (!options?.silent) {
        setMenuSearchLoading(true);
      }

      try {
        const results = await Promise.all(
          idsToFetch.map(async restaurantId => ({
            restaurantId,
            items: await api.getMenuItems(restaurantId, token),
          })),
        );

        setMenuItemsByRestaurant(current => {
          const next = { ...current };
          let changed = false;
          results.forEach(({ restaurantId, items }) => {
            if (next[restaurantId] !== items) {
              next[restaurantId] = items;
              changed = true;
            }
          });
          return changed ? next : current;
        });
      } catch (error) {
        pushToast(
          'Dish search unavailable',
          error instanceof Error
            ? error.message
            : 'We could not load dishes for these restaurants right now.',
          'error',
        );
      } finally {
        idsToFetch.forEach(restaurantId =>
          inFlightRestaurantIdsRef.current.delete(restaurantId),
        );
        if (!options?.silent && generation === menuFetchGenerationRef.current) {
          setMenuSearchLoading(false);
        }
      }
    },
    [pushToast, token],
  );

  useEffect(() => {
    const recommendedRestaurantIds = uniqueStrings(
      recommendations.map(item => item.restaurant_id),
    ).slice(0, 2);

    if (recommendedRestaurantIds.length > 0) {
      void ensureRestaurantMenus(recommendedRestaurantIds, { silent: true });
    }
  }, [ensureRestaurantMenus, recommendations]);

  useEffect(() => {
    if (!debouncedMenuQuery) {
      setMenuSearchLoading(false);
      return;
    }
    if (candidateRestaurantIds.length === 0) {
      return;
    }

    void ensureRestaurantMenus(candidateRestaurantIds);
  }, [candidateRestaurantIds, debouncedMenuQuery, ensureRestaurantMenus]);

  const handleApplySearchTerm = useCallback(
    async (value: string) => {
      setQuery(value);
      await commitSearch(value);
    },
    [commitSearch],
  );

  const handleOpenRestaurant = useCallback(
    async (restaurant: Restaurant) => {
      if (query.trim()) {
        await commitSearch(query);
      }
      navigation.navigate('Restaurant', {
        restaurantId: restaurant.id,
        restaurantName: restaurant.name,
      });
    },
    [commitSearch, navigation, query],
  );

  const handleOpenRestaurantById = useCallback(
    async (restaurantId: string, restaurantName: string) => {
      if (query.trim()) {
        await commitSearch(query);
      }
      navigation.navigate('Restaurant', { restaurantId, restaurantName });
    },
    [commitSearch, navigation, query],
  );

  const handleOpenDish = useCallback(
    async (result: SearchDishResult) => {
      if (query.trim()) {
        await commitSearch(query);
      }
      navigation.navigate('MenuItemDetail', {
        itemId: result.item.id,
        restaurantId: result.restaurantId,
        restaurantName: result.restaurantName,
      });
    },
    [commitSearch, navigation, query],
  );

  const handleAddDishToCart = useCallback(
    (result: SearchDishResult) => {
      if (isCustomizableMenuItem(result.item)) {
        void handleOpenDish(result);
        return;
      }
      void requestAddToCart(
        result.item,
        result.restaurantId,
        result.restaurantName,
      );
    },
    [handleOpenDish, requestAddToCart],
  );

  const handleToggleDishFavorite = useCallback(
    (result: SearchDishResult) => {
      if (!token) {
        pushToast(
          'Login to save favorites',
          'Favorites are synced for signed-in customers.',
          'info',
        );
        navigation.navigate('Login');
        return;
      }

      void toggleFavorite({ menuItemId: result.item.id })
        .then(nextFavorite => {
          pushToast(
            nextFavorite ? 'Saved to favorites' : 'Removed from favorites',
            nextFavorite
              ? `${result.item.name} is now in your favorites.`
              : `${result.item.name} was removed from favorites.`,
            'success',
          );
        })
        .catch(error => {
          if (
            error instanceof ApiError &&
            (error.status === 401 || error.status === 403)
          ) {
            navigation.navigate('Login');
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

  const totalResultCount =
    matchingRestaurants.length +
    matchingDishes.length +
    matchingCuisines.length;

  // `!appConfigResolved` holds the skeleton for the same reason HomeScreen
  // does: rendering results before the app mode is known is what leaks other
  // restaurants into a single-restaurant build. Reaching this screen normally
  // requires passing HomeScreen's gate, so this is defence in depth for a deep
  // link that opens search directly.
  if (loading || !appConfigResolved) {
    return (
      <SafeAreaView edges={['top']} style={styles.safeArea}>
        <SearchScreenSkeleton />
      </SafeAreaView>
    );
  }

  if (screenError && restaurants.length === 0) {
    return (
      <SafeAreaView edges={['top']} style={styles.safeArea}>
        <View style={styles.errorWrap}>
          <View style={styles.feedbackCard}>
            <Text style={styles.feedbackTitle}>Search is taking a break</Text>
            <Text style={styles.feedbackText}>{screenError}</Text>
            <Pressable
              onPress={() => {
                void loadSearchFeed();
              }}
              style={styles.primaryActionButton}
            >
              <Text style={styles.primaryActionText}>Retry</Text>
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} style={styles.safeArea}>
      <View style={styles.headerShell}>
        <View
          style={[
            styles.searchBar,
            inputFocused ? styles.searchBarFocused : null,
          ]}
        >
          <Pressable onPress={navigation.goBack} style={styles.backButton}>
            <Icon color={theme.colors.text} name="arrow-back" size={20} />
          </Pressable>
          <Icon color={theme.colors.hint} name="search-outline" size={18} />
          <TextInput
            autoCapitalize="none"
            autoCorrect={false}
            blurOnSubmit={false}
            onBlur={() => setInputFocused(false)}
            onChangeText={setQuery}
            onFocus={() => setInputFocused(true)}
            onSubmitEditing={() => {
              void commitSearch(query);
            }}
            placeholder="Search for restaurants, dishes, cuisines…"
            placeholderTextColor={theme.colors.hint}
            returnKeyType="search"
            selectionColor={theme.colors.primary}
            style={styles.searchInput}
            value={query}
          />
          {query.length > 0 ? (
            <Pressable onPress={() => setQuery('')} style={styles.clearButton}>
              <Icon color={theme.colors.hint} name="close-circle" size={18} />
            </Pressable>
          ) : null}
        </View>
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            onRefresh={() => {
              void loadSearchFeed(true);
            }}
            refreshing={refreshing}
            tintColor={theme.colors.primary}
          />
        }
        showsVerticalScrollIndicator={false}
      >
        {!hasActiveQuery ? (
          <>
            <View style={styles.discoveryHero}>
              <View style={styles.discoveryBadge}>
                <Icon
                  color={theme.colors.primary}
                  name="sparkles-outline"
                  size={14}
                />
                <Text style={styles.discoveryBadgeText}>Food discovery</Text>
              </View>
              <Text style={styles.discoveryTitle}>
                Discover something delicious
              </Text>
              <Text style={styles.discoverySubtitle}>
                Jump into quick cravings, personalized dish picks, and popular
                restaurants without wading through tag walls.
              </Text>
              <ScrollView
                contentContainerStyle={styles.inlineHorizontalChipRow}
                horizontal
                showsHorizontalScrollIndicator={false}
              >
                {searchSuggestions.slice(0, 3).map(label => (
                  <SearchChip
                    key={label}
                    label={label}
                    onPress={() => {
                      void handleApplySearchTerm(label);
                    }}
                    tone="accent"
                  />
                ))}
              </ScrollView>
            </View>

            <View style={styles.sectionBlock}>
              <SectionHeader
                actionLabel={
                  POPULAR_SEARCHES.length > 4
                    ? showAllPopularSearches
                      ? 'Show less'
                      : 'See all'
                    : undefined
                }
                onActionPress={
                  POPULAR_SEARCHES.length > 4
                    ? () => setShowAllPopularSearches(current => !current)
                    : undefined
                }
                subtitle="Quick one-tap cravings."
                title="Quick actions"
              />
              <ScrollView
                contentContainerStyle={styles.inlineHorizontalChipRow}
                horizontal
                showsHorizontalScrollIndicator={false}
              >
                {visiblePopularSearches.map(label => (
                  <SearchChip
                    key={label}
                    label={label}
                    onPress={() => {
                      void handleApplySearchTerm(label);
                    }}
                  />
                ))}
              </ScrollView>
              {showAllPopularSearches && POPULAR_SEARCHES.length > 4 ? (
                <View style={styles.discoveryChipWrap}>
                  {POPULAR_SEARCHES.slice(4).map(label => (
                    <SearchChip
                      key={`expanded-popular-${label}`}
                      label={label}
                      onPress={() => {
                        void handleApplySearchTerm(label);
                      }}
                    />
                  ))}
                </View>
              ) : null}
            </View>

            {featuredRecommendationResults.length > 0 ? (
              <View style={styles.sectionBlock}>
                <SectionHeader
                  rightLabel={`${Math.min(
                    featuredRecommendationResults.length,
                    6,
                  )} picks`}
                  subtitle="Personalized dish ideas ready for faster checkout."
                  title="Recommended for you"
                />
                <ScrollView
                  contentContainerStyle={styles.horizontalRail}
                  horizontal
                  showsHorizontalScrollIndicator={false}
                >
                  {featuredRecommendationResults.map(result => (
                    <DiscoveryDishCarouselCard
                      badgeLabel="For you"
                      key={result.item.id}
                      onAddToCart={() => handleAddDishToCart(result)}
                      onOpenDish={() => {
                        void handleOpenDish(result);
                      }}
                      result={result}
                    />
                  ))}
                </ScrollView>
              </View>
            ) : null}

            {discoveryRestaurants.length > 0 ? (
              <View style={styles.sectionBlock}>
                <SectionHeader
                  rightLabel={`${discoveryRestaurants.length} places`}
                  subtitle="Open restaurants first, then narrow down from there."
                  title="Popular restaurants"
                />
                <ScrollView
                  contentContainerStyle={styles.horizontalRail}
                  horizontal
                  showsHorizontalScrollIndicator={false}
                >
                  {discoveryRestaurants.map(restaurant => (
                    <RestaurantCard
                      key={restaurant.id}
                      onPress={() => {
                        void handleOpenRestaurant(restaurant);
                      }}
                      restaurant={restaurant}
                      variant="compact"
                    />
                  ))}
                </ScrollView>
              </View>
            ) : null}

            {discoveryTrendingResults.length > 0 ? (
              <View style={styles.sectionBlock}>
                <SectionHeader
                  subtitle="Image-first trending dishes customers are already opening."
                  title="Trending dishes"
                />
                <ScrollView
                  contentContainerStyle={styles.horizontalRail}
                  horizontal
                  showsHorizontalScrollIndicator={false}
                >
                  {discoveryTrendingResults.map(result => (
                    <DiscoveryDishCarouselCard
                      badgeLabel={
                        result.item.is_bestseller ? 'Trending' : 'Popular'
                      }
                      key={`trending-${result.item.id}`}
                      onAddToCart={() => handleAddDishToCart(result)}
                      onOpenDish={() => {
                        void handleOpenDish(result);
                      }}
                      result={result}
                    />
                  ))}
                </ScrollView>
              </View>
            ) : null}

            <View style={styles.sectionBlock}>
              <SectionHeader
                actionLabel={
                  cuisineCatalog.length > 6
                    ? showAllCuisines
                      ? 'Show less'
                      : 'See all'
                    : undefined
                }
                onActionPress={
                  cuisineCatalog.length > 6
                    ? () => setShowAllCuisines(current => !current)
                    : undefined
                }
                subtitle="Compact cuisine shortcuts for broader discovery."
                title="Popular cuisines"
              />
              <ScrollView
                contentContainerStyle={styles.inlineHorizontalChipRow}
                horizontal
                showsHorizontalScrollIndicator={false}
              >
                {visibleCuisines.map(label => (
                  <SearchChip
                    icon="restaurant-outline"
                    key={label}
                    label={label}
                    onPress={() => {
                      void handleApplySearchTerm(label);
                    }}
                  />
                ))}
              </ScrollView>
              {showAllCuisines && cuisineCatalog.length > 6 ? (
                <View style={styles.discoveryChipWrap}>
                  {cuisineCatalog.slice(6).map(label => (
                    <SearchChip
                      icon="restaurant-outline"
                      key={`expanded-cuisine-${label}`}
                      label={label}
                      onPress={() => {
                        void handleApplySearchTerm(label);
                      }}
                    />
                  ))}
                </View>
              ) : null}
            </View>

            {recentSearches.length > 0 ? (
              <View style={styles.sectionBlock}>
                <SectionHeader
                  actionLabel={
                    recentSearches.length > 4
                      ? showAllRecentSearches
                        ? 'Show less'
                        : 'See all'
                      : undefined
                  }
                  onActionPress={
                    recentSearches.length > 4
                      ? () => setShowAllRecentSearches(current => !current)
                      : undefined
                  }
                  subtitle="Return to something you already searched for."
                  title="Recent searches"
                />
                <ScrollView
                  contentContainerStyle={styles.inlineHorizontalChipRow}
                  horizontal
                  showsHorizontalScrollIndicator={false}
                >
                  {visibleRecentSearches.map(label => (
                    <SearchChip
                      icon="time-outline"
                      key={label}
                      label={label}
                      onPress={() => {
                        void handleApplySearchTerm(label);
                      }}
                    />
                  ))}
                </ScrollView>
                {showAllRecentSearches && recentSearches.length > 4 ? (
                  <View style={styles.discoveryChipWrap}>
                    {recentSearches.slice(4).map(label => (
                      <SearchChip
                        icon="time-outline"
                        key={`expanded-recent-${label}`}
                        label={label}
                        onPress={() => {
                          void handleApplySearchTerm(label);
                        }}
                      />
                    ))}
                  </View>
                ) : null}
              </View>
            ) : null}

            {featuredRecommendationResults.length === 0 &&
            discoveryRestaurants.length === 0 &&
            discoveryTrendingResults.length === 0 ? (
              <View style={styles.emptyDiscoveryCard}>
                <Text style={styles.emptyDiscoveryTitle}>
                  Start with a craving
                </Text>
                <Text style={styles.emptyDiscoveryText}>
                  Use quick actions, explore cuisines, or update taste
                  preferences to unlock stronger recommendations here.
                </Text>
              </View>
            ) : null}
          </>
        ) : (
          <>
            <View style={styles.resultsSummaryCard}>
              <View style={styles.resultsSummaryCopy}>
                <Text style={styles.resultsEyebrow}>Search results</Text>
                <HighlightedText
                  highlightStyle={styles.resultsHighlight}
                  query={normalizedQuery}
                  style={styles.resultsHeadline}
                  text={`Results for “${query.trim()}”`}
                />
                <Text style={styles.resultsSummaryText}>
                  {totalResultCount} matches across restaurants, dishes, and
                  cuisines
                </Text>
              </View>
              {menuSearchLoading ? (
                <View style={styles.loadingPill}>
                  <ActivityIndicator
                    color={theme.colors.primary}
                    size="small"
                  />
                  <Text style={styles.loadingPillText}>Searching dishes</Text>
                </View>
              ) : null}
            </View>

            {matchingRestaurants.length > 0 ? (
              <View style={styles.sectionBlock}>
                <SectionHeader
                  rightLabel={`${matchingRestaurants.length}`}
                  subtitle="Restaurants whose name, city, or cuisine match your search."
                  title="Restaurants"
                />
                <View style={styles.resultsColumn}>
                  {matchingRestaurants.map(restaurant => (
                    <RestaurantResultCard
                      key={restaurant.id}
                      onPress={() => {
                        void handleOpenRestaurant(restaurant);
                      }}
                      query={normalizedQuery}
                      restaurant={restaurant}
                    />
                  ))}
                </View>
              </View>
            ) : null}

            <View style={styles.sectionBlock}>
              <SectionHeader
                rightLabel={`${matchingDishes.length}`}
                subtitle="Matching dishes across recommendations and restaurant menus."
                title="Dishes"
              />
              {matchingDishes.length > 0 ? (
                <View style={styles.resultsColumn}>
                  {matchingDishes.map(result => (
                    <DishResultCard
                      favoritePending={isFavoritePending(result.item.id)}
                      isFavorite={
                        favoritesHydrated
                          ? isFavorite(result.item.id)
                          : result.item.is_favorite
                      }
                      key={result.item.id}
                      onAddToCart={() => handleAddDishToCart(result)}
                      onOpenDish={() => {
                        void handleOpenDish(result);
                      }}
                      onOpenRestaurant={() => {
                        const restaurant = restaurantsById[result.restaurantId];
                        if (restaurant) {
                          void handleOpenRestaurant(restaurant);
                          return;
                        }
                        void handleOpenRestaurantById(
                          result.restaurantId,
                          result.restaurantName,
                        );
                      }}
                      onToggleFavorite={() => handleToggleDishFavorite(result)}
                      query={normalizedQuery}
                      result={result}
                    />
                  ))}
                </View>
              ) : menuSearchLoading ? (
                <View style={styles.inlineLoaderCard}>
                  <ActivityIndicator color={theme.colors.primary} />
                  <Text style={styles.inlineLoaderText}>
                    Looking through dish names and restaurant menus…
                  </Text>
                </View>
              ) : (
                <View style={styles.inlineEmptyCard}>
                  <Text style={styles.inlineEmptyTitle}>
                    No dish matches yet
                  </Text>
                  <Text style={styles.inlineEmptyText}>
                    Try a broader dish name, cuisine, or restaurant keyword.
                  </Text>
                </View>
              )}
            </View>

            {matchingCuisines.length > 0 ? (
              <View style={styles.sectionBlock}>
                <SectionHeader
                  rightLabel={`${matchingCuisines.length}`}
                  subtitle="Cuisine and category ideas you can pivot to instantly."
                  title="Cuisines"
                />
                <View style={styles.resultsColumn}>
                  {matchingCuisines.map(cuisine => (
                    <CuisineCard
                      key={cuisine}
                      label={cuisine}
                      onPress={() => {
                        void handleApplySearchTerm(cuisine);
                      }}
                      query={normalizedQuery}
                    />
                  ))}
                </View>
              </View>
            ) : null}

            {popularPickResults.length > 0 ? (
              <View style={styles.sectionBlock}>
                <SectionHeader
                  subtitle="Extra high-signal results from recommendations and popular dishes."
                  title="Popular picks"
                />
                <View style={styles.popularPickGrid}>
                  {popularPickResults.map(result => (
                    <PopularPickMiniCard
                      key={result.item.id}
                      onPress={() => {
                        void handleOpenDish(result);
                      }}
                      result={result}
                    />
                  ))}
                </View>
              </View>
            ) : null}

            {totalResultCount === 0 && !menuSearchLoading ? (
              <View style={styles.emptyResultCard}>
                <Text style={styles.emptyResultTitle}>
                  No matches for that search
                </Text>
                <Text style={styles.emptyResultText}>
                  Try a dish name like “momos”, a cuisine like “Chinese”, or a
                  restaurant keyword instead.
                </Text>
                <View style={styles.emptyResultActions}>
                  {searchSuggestions.slice(0, 4).map(value => (
                    <SearchChip
                      key={value}
                      label={value}
                      onPress={() => {
                        void handleApplySearchTerm(value);
                      }}
                    />
                  ))}
                </View>
              </View>
            ) : null}
          </>
        )}
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
    headerShell: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 10,
      paddingBottom: 8,
      backgroundColor: theme.colors.background,
    },
    searchBar: {
      minHeight: 56,
      borderRadius: 20,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      paddingHorizontal: 14,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.05,
      shadowOffset: { width: 0, height: 6 },
      shadowRadius: 14,
      elevation: 2,
    },
    searchBarFocused: {
      borderColor: theme.colors.primary,
      shadowOpacity: 0.12,
    },
    backButton: {
      width: 34,
      height: 34,
      borderRadius: 17,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surface,
    },
    searchInput: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 15,
      paddingVertical: 0,
    },
    clearButton: {
      width: 28,
      height: 28,
      alignItems: 'center',
      justifyContent: 'center',
    },
    content: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 8,
      paddingBottom: 136,
      gap: 16,
    },
    discoveryHero: {
      borderRadius: 28,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : theme.colors.surfaceAlt,
      padding: 18,
      gap: 10,
      borderWidth: 1,
      borderColor: theme.colors.border,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.06,
      shadowOffset: { width: 0, height: 10 },
      shadowRadius: 18,
      elevation: 3,
    },
    discoveryBadge: {
      alignSelf: 'flex-start',
      minHeight: 30,
      borderRadius: 999,
      paddingHorizontal: 10,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    discoveryBadgeText: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
    },
    discoveryTitle: {
      color: theme.colors.text,
      fontSize: 28,
      lineHeight: 34,
      fontWeight: '900',
      letterSpacing: -0.8,
    },
    discoverySubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 19,
    },
    sectionBlock: {
      gap: 10,
    },
    sectionHeader: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'flex-end',
      gap: 12,
    },
    sectionHeaderCopy: {
      flex: 1,
      gap: 4,
    },
    sectionTitle: {
      color: theme.colors.text,
      fontSize: 19,
      fontWeight: '800',
      letterSpacing: -0.4,
    },
    sectionSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    sectionMeta: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
    },
    sectionAction: {
      paddingVertical: 6,
    },
    sectionActionText: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
    },
    horizontalRail: {
      paddingRight: 6,
      gap: 12,
    },
    inlineHorizontalChipRow: {
      paddingRight: 6,
      gap: 8,
    },
    discoveryChipWrap: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 8,
    },
    discoveryChip: {
      minHeight: 38,
      borderRadius: 999,
      paddingHorizontal: 12,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 7,
    },
    discoveryChipAccent: {
      minHeight: 38,
      borderRadius: 999,
      paddingHorizontal: 12,
      backgroundColor: theme.colors.primarySoft,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.chipBorder : 'transparent',
      flexDirection: 'row',
      alignItems: 'center',
      gap: 7,
    },
    discoveryChipPressed: {
      opacity: 0.92,
    },
    discoveryChipText: {
      color: theme.colors.text,
      fontSize: 12,
      fontWeight: '700',
    },
    discoveryChipTextAccent: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
    },
    discoveryDishCard: {
      width: 212,
      borderRadius: 20,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      overflow: 'hidden',
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.05,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 2,
    },
    discoveryDishImageWrap: {
      width: '100%',
      height: 118,
      backgroundColor: theme.colors.surfaceAlt,
      position: 'relative',
    },
    discoveryDishImage: {
      width: '100%',
      height: '100%',
    },
    discoveryDishBadge: {
      position: 'absolute',
      top: 10,
      left: 10,
      borderRadius: 999,
      paddingHorizontal: 10,
      paddingVertical: 5,
      backgroundColor:
        theme.mode === 'dark' ? 'rgba(8, 10, 14, 0.72)' : 'rgba(20,24,38,0.68)',
    },
    discoveryDishBadgeText: {
      color: theme.colors.white,
      fontSize: 10,
      fontWeight: '800',
    },
    discoveryDishBody: {
      padding: 12,
      gap: 7,
    },
    discoveryDishTitleRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    discoveryDishTitle: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
      letterSpacing: -0.25,
    },
    discoveryDishMeta: {
      color: theme.colors.secondaryText,
      fontSize: 11,
      fontWeight: '600',
    },
    discoveryDishChipRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 6,
    },
    discoveryMiniChip: {
      minHeight: 24,
      borderRadius: 999,
      paddingHorizontal: 8,
      backgroundColor: theme.colors.surface,
      borderWidth: 1,
      borderColor: theme.colors.border,
      alignItems: 'center',
      justifyContent: 'center',
    },
    discoveryMiniChipAccent: {
      minHeight: 24,
      borderRadius: 999,
      paddingHorizontal: 8,
      backgroundColor: theme.colors.primarySoft,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.chipBorder : 'transparent',
      alignItems: 'center',
      justifyContent: 'center',
    },
    discoveryMiniChipText: {
      color: theme.colors.text,
      fontSize: 10,
      fontWeight: '700',
    },
    discoveryMiniChipTextAccent: {
      color: theme.colors.primary,
      fontSize: 10,
      fontWeight: '800',
    },
    discoveryDishFooter: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10,
    },
    discoveryDishPrice: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    discoveryAddButton: {
      minWidth: 74,
      minHeight: 34,
      borderRadius: 12,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      paddingHorizontal: 12,
    },
    discoveryAddButtonText: {
      color: theme.colors.white,
      fontSize: 12,
      fontWeight: '800',
    },
    resultsSummaryCard: {
      borderRadius: 24,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 16,
      gap: 10,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.05,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 2,
    },
    resultsSummaryCopy: {
      gap: 4,
    },
    resultsEyebrow: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '800',
      textTransform: 'uppercase',
      letterSpacing: 0.8,
    },
    resultsHeadline: {
      color: theme.colors.text,
      fontSize: 24,
      lineHeight: 30,
      fontWeight: '900',
      letterSpacing: -0.6,
    },
    resultsHighlight: {
      color: theme.colors.primary,
    },
    resultsSummaryText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    loadingPill: {
      alignSelf: 'flex-start',
      minHeight: 34,
      borderRadius: 999,
      paddingHorizontal: 12,
      backgroundColor: theme.colors.surface,
      borderWidth: 1,
      borderColor: theme.colors.border,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
    },
    loadingPillText: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '700',
    },
    resultsColumn: {
      gap: 12,
    },
    restaurantCard: {
      borderRadius: 22,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 12,
      flexDirection: 'row',
      gap: 12,
      alignItems: 'center',
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.05,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 2,
    },
    restaurantImage: {
      width: 78,
      height: 78,
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceAlt,
    },
    restaurantCardCopy: {
      flex: 1,
      gap: 6,
    },
    restaurantCardTopRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10,
    },
    restaurantCardTitle: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
      letterSpacing: -0.3,
    },
    restaurantCardMeta: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    restaurantBadgeRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 8,
    },
    inlineMetaBadge: {
      minHeight: 28,
      borderRadius: 999,
      paddingHorizontal: 10,
      backgroundColor: theme.colors.surface,
      borderWidth: 1,
      borderColor: theme.colors.border,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    inlineMetaBadgeText: {
      color: theme.colors.text,
      fontSize: 11,
      fontWeight: '700',
    },
    restaurantActionWrap: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 3,
      paddingLeft: 6,
    },
    restaurantActionText: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
    },
    statusPill: {
      minHeight: 24,
      borderRadius: 999,
      paddingHorizontal: 8,
      borderWidth: 1,
      alignItems: 'center',
      justifyContent: 'center',
    },
    statusPillOpen: {
      backgroundColor: theme.colors.successSoft,
      borderColor:
        theme.mode === 'dark' ? 'rgba(72, 196, 121, 0.22)' : '#9ED6A6',
    },
    statusPillClosed: {
      backgroundColor: theme.colors.dangerSoft,
      borderColor:
        theme.mode === 'dark' ? 'rgba(203, 32, 45, 0.24)' : '#F2C2C2',
    },
    statusPillText: {
      fontSize: 10,
      fontWeight: '800',
    },
    statusPillTextOpen: {
      color: theme.colors.success,
    },
    statusPillTextClosed: {
      color: theme.colors.deepRed,
    },
    dishCard: {
      borderRadius: 22,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 12,
      flexDirection: 'row',
      gap: 12,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.05,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 2,
    },
    dishImage: {
      width: 78,
      height: 78,
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceAlt,
    },
    dishCardCopy: {
      flex: 1,
      gap: 6,
    },
    dishCardTopRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      gap: 8,
    },
    dishTitleWrap: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingTop: 2,
    },
    vegDot: {
      width: 8,
      height: 8,
      borderRadius: 4,
    },
    dishTitle: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 15,
      lineHeight: 19,
      fontWeight: '800',
      letterSpacing: -0.2,
    },
    resultHighlight: {
      color: theme.colors.primary,
      fontWeight: '900',
    },
    dishRestaurantRow: {
      alignSelf: 'flex-start',
    },
    dishRestaurant: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      fontWeight: '700',
    },
    dishDescription: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    dishCardBottomRow: {
      flexDirection: 'row',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      gap: 12,
    },
    dishMetaStack: {
      flex: 1,
      gap: 6,
    },
    dishPrice: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    dishBadgeRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 6,
    },
    tinyBadge: {
      minHeight: 24,
      borderRadius: 999,
      paddingHorizontal: 8,
      backgroundColor: theme.colors.surface,
      borderWidth: 1,
      borderColor: theme.colors.border,
      alignItems: 'center',
      justifyContent: 'center',
    },
    tinyBadgeAccent: {
      minHeight: 24,
      borderRadius: 999,
      paddingHorizontal: 8,
      backgroundColor: theme.colors.primarySoft,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.chipBorder : 'transparent',
      alignItems: 'center',
      justifyContent: 'center',
    },
    tinyBadgeText: {
      color: theme.colors.text,
      fontSize: 10,
      fontWeight: '700',
    },
    tinyBadgeTextAccent: {
      color: theme.colors.primary,
      fontSize: 10,
      fontWeight: '800',
    },
    addButton: {
      minWidth: 84,
      minHeight: 36,
      borderRadius: 14,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      paddingHorizontal: 12,
    },
    addButtonDisabled: {
      backgroundColor: theme.colors.card,
    },
    addButtonText: {
      color: theme.colors.white,
      fontSize: 12,
      fontWeight: '800',
    },
    addButtonTextDisabled: {
      color: theme.colors.disabledText,
    },
    cuisineCard: {
      borderRadius: 18,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      paddingHorizontal: 14,
      paddingVertical: 14,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
    },
    cuisineIconWrap: {
      width: 38,
      height: 38,
      borderRadius: 19,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    cuisineCopy: {
      flex: 1,
      gap: 3,
    },
    cuisineTitle: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
    },
    cuisineMeta: {
      color: theme.colors.secondaryText,
      fontSize: 12,
    },
    cuisineHighlight: {
      color: theme.colors.primary,
    },
    popularPickGrid: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 10,
    },
    popularPickCard: {
      width: '48%',
      borderRadius: 18,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 14,
      gap: 6,
    },
    popularPickTitle: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    popularPickMeta: {
      color: theme.colors.secondaryText,
      fontSize: 11,
    },
    popularPickPrice: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
    },
    inlineLoaderCard: {
      borderRadius: 18,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 16,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
    },
    inlineLoaderText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
      flex: 1,
    },
    inlineEmptyCard: {
      borderRadius: 18,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 16,
      gap: 6,
    },
    inlineEmptyTitle: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
    },
    inlineEmptyText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    emptyResultCard: {
      borderRadius: 24,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 18,
      gap: 10,
    },
    emptyResultTitle: {
      color: theme.colors.text,
      fontSize: 18,
      fontWeight: '800',
    },
    emptyResultText: {
      color: theme.colors.secondaryText,
      lineHeight: 20,
    },
    emptyResultActions: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 10,
      marginTop: 4,
    },
    emptyDiscoveryCard: {
      borderRadius: 22,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 16,
      gap: 6,
    },
    emptyDiscoveryTitle: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
    },
    emptyDiscoveryText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    errorWrap: {
      flex: 1,
      padding: theme.spacing.screen,
      justifyContent: 'center',
    },
    feedbackCard: {
      borderRadius: 24,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 20,
      gap: 10,
    },
    feedbackTitle: {
      color: theme.colors.text,
      fontSize: 20,
      fontWeight: '800',
    },
    feedbackText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 20,
    },
    primaryActionButton: {
      alignSelf: 'flex-start',
      minHeight: 44,
      borderRadius: 14,
      paddingHorizontal: 16,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: 4,
    },
    primaryActionText: {
      color: theme.colors.white,
      fontSize: 13,
      fontWeight: '800',
    },
    discoverySkeletonRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      gap: 10,
    },
    cardPressed: {
      opacity: 0.95,
      transform: [{ scale: 0.995 }],
    },
  });
