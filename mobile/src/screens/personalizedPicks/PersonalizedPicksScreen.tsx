import React, {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  Animated,
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
  type ListRenderItem,
  type ViewToken,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import { FavoriteIconButton } from '@components/FavoriteIconButton';
import { SkeletonBlock } from '@components/SkeletonBlock';
import {
  useAppActions,
  useFavoritesState,
  usePreferences,
  useSelectedLocation,
  useSession,
} from '@hooks/useAppStore';
import { ApiError, api, formatCurrency, placeholderImage } from '@services/api';
import { checkAuthAndRedirect } from '@utils/authRedirect';
import { isCustomizableMenuItem } from '@utils/menuItemCustomization';
import { buildLocationKey, buildPreferencesKey } from '@utils/preferencesKey';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type {
  Order,
  PersonalizedRecommendationContext,
  RecommendationItem,
} from '@/types/app';
import type { RootStackParamList } from '@/navigation/navigationTypes';

type Props = NativeStackScreenProps<RootStackParamList, 'PersonalizedPicks'>;

type PersonalizedFilter =
  | 'ALL'
  | 'VEG'
  | 'NON_VEG'
  | 'POPULAR'
  | 'RECENTLY_ORDERED';

const FILTER_OPTIONS: Array<{
  id: PersonalizedFilter;
  label: string;
}> = [
  { id: 'ALL', label: 'All' },
  { id: 'VEG', label: 'Veg' },
  { id: 'NON_VEG', label: 'Non-Veg' },
  { id: 'POPULAR', label: 'Popular' },
  { id: 'RECENTLY_ORDERED', label: 'Recently Ordered' },
];

function trackPersonalizedPickEvent(
  eventName:
    | 'See All Opened'
    | 'Personalized Pick Viewed'
    | 'Item Clicked'
    | 'Add to Cart'
    | 'Favorite Toggled'
    | 'Filter Selected',
  payload: Record<string, unknown> = {},
): void {
  console.info('[personalized-picks]', eventName, payload);
}

function PersonalizedPicksLoading(): React.JSX.Element {
  const styles = useThemedStyles(createStyles);

  return (
    <View style={styles.loadingContainer}>
      <SkeletonBlock borderRadius={18} height={34} width="46%" />
      <SkeletonBlock borderRadius={12} height={16} width="72%" />
      <View style={styles.infoSkeletonCard}>
        <SkeletonBlock borderRadius={12} height={18} width="42%" />
        <SkeletonBlock borderRadius={10} height={14} width="82%" />
        <SkeletonBlock borderRadius={10} height={14} width="64%" />
      </View>
      <View style={styles.filterSkeletonRow}>
        {FILTER_OPTIONS.map(option => (
          <SkeletonBlock
            key={option.id}
            borderRadius={999}
            height={36}
            width={option.label === 'Recently Ordered' ? 142 : 84}
          />
        ))}
      </View>
      <View style={styles.gridSkeleton}>
        {Array.from({ length: 6 }).map((_, index) => (
          <View key={index} style={styles.gridSkeletonCard}>
            <SkeletonBlock borderRadius={22} height={176} />
          </View>
        ))}
      </View>
    </View>
  );
}

const PersonalizedPickCard = memo(function PersonalizedPickCard({
  cardWidth,
  favoritePending,
  isFavorite,
  item,
  onAddToCart,
  onPress,
  onToggleFavorite,
}: {
  cardWidth: number;
  favoritePending: boolean;
  isFavorite: boolean;
  item: RecommendationItem;
  onAddToCart: (item: RecommendationItem) => void;
  onPress: (item: RecommendationItem) => void;
  onToggleFavorite: (item: RecommendationItem) => void;
}): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const matchPercent = Math.max(1, Math.round(item.score * 100));
  const priceLabel =
    item.price_label ?? formatCurrency(item.display_price ?? item.price);
  const isAvailable = item.is_available !== false;
  const categoryLabel = item.category || 'Recommended';
  const recommendedLabel = item.ai_badge || 'Recommended';
  const supportingReason = item.ai_reason || item.recommendation_reason;
  const locationLabel =
    item.preferred_location_name ?? item.restaurant_location.branch_name;

  return (
    <View style={[styles.cardShell, { width: cardWidth }]}>
      <Pressable
        onPress={() => onPress(item)}
        style={({ pressed }) => [
          styles.card,
          pressed ? styles.cardPressed : null,
        ]}
      >
        <View style={styles.cardImageWrap}>
          <Image
            source={{ uri: item.image_url ?? placeholderImage(item.name) }}
            style={styles.cardImage}
          />
          <View style={styles.recommendedBadge}>
            <Text style={styles.recommendedBadgeText}>{recommendedLabel}</Text>
          </View>
          <View style={styles.favoriteButtonWrap}>
            <FavoriteIconButton
              active={isFavorite}
              disabled={favoritePending}
              onPress={() => onToggleFavorite(item)}
            />
          </View>
        </View>

        <View style={styles.cardBody}>
          <View style={styles.cardTopRow}>
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
            <View style={styles.categoryPill}>
              <Text numberOfLines={1} style={styles.categoryPillText}>
                {categoryLabel}
              </Text>
            </View>
          </View>

          <Text numberOfLines={2} style={styles.cardTitle}>
            {item.name}
          </Text>
          <Text numberOfLines={1} style={styles.cardRestaurant}>
            {item.restaurant.name}
          </Text>
          <Text numberOfLines={1} style={styles.cardLocation}>
            {locationLabel}
          </Text>
          {supportingReason ? (
            <Text numberOfLines={2} style={styles.cardReason}>
              {supportingReason}
            </Text>
          ) : null}

          <View style={styles.cardFooter}>
            <View style={styles.priceColumn}>
              <Text style={styles.priceText}>{priceLabel}</Text>
              <Text style={styles.matchText}>{matchPercent}% match</Text>
            </View>
            <Pressable
              disabled={!isAvailable}
              onPress={() => onAddToCart(item)}
              style={[
                styles.addButton,
                !isAvailable ? styles.addButtonDisabled : null,
              ]}
            >
              <Text
                style={[
                  styles.addButtonText,
                  !isAvailable ? styles.addButtonTextDisabled : null,
                ]}
              >
                {isAvailable ? 'Add' : 'Sold out'}
              </Text>
            </Pressable>
          </View>
        </View>
      </Pressable>
    </View>
  );
});

function PersonalizedPicksEmptyState({
  onBrowseRestaurants,
}: {
  onBrowseRestaurants: () => void;
}): React.JSX.Element {
  const styles = useThemedStyles(createStyles);

  return (
    <View style={styles.emptyState}>
      <View style={styles.emptyIconWrap}>
        <Icon color={theme.colors.primary} name="sparkles-outline" size={24} />
      </View>
      <Text style={styles.emptyTitle}>No recommendations yet</Text>
      <Text style={styles.emptyText}>
        Start exploring menus and placing orders to unlock personalized picks.
      </Text>
      <Pressable onPress={onBrowseRestaurants} style={styles.emptyCta}>
        <Text style={styles.emptyCtaText}>Browse Restaurants</Text>
        <Icon color={theme.colors.onPrimary} name="arrow-forward" size={16} />
      </Pressable>
    </View>
  );
}

export function PersonalizedPicksScreen({
  navigation,
  route,
}: Props): React.JSX.Element {
  const styles = useThemedStyles(createStyles);
  const { width } = useWindowDimensions();
  const { token } = useSession();
  const { preferences } = usePreferences();
  const { favoritesHydrated } = useFavoritesState();
  const selectedLocation = useSelectedLocation();
  const {
    isFavorite,
    isFavoritePending,
    pushToast,
    requestAddToCart,
    toggleFavorite,
  } = useAppActions();
  const initialRecommendations = route.params?.initialRecommendations ?? [];
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>(
    initialRecommendations,
  );
  const [recommendationContext, setRecommendationContext] =
    useState<PersonalizedRecommendationContext | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(initialRecommendations.length === 0);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedFilter, setSelectedFilter] =
    useState<PersonalizedFilter>('ALL');
  const fadeAnim = useRef(
    new Animated.Value(initialRecommendations.length > 0 ? 1 : 0),
  ).current;
  const viewedRecommendationIdsRef = useRef<Set<string>>(new Set());
  // Ref instead of `recommendations.length` in the loader's dependency array,
  // which used to change this callback's identity after each load and fetch
  // the three endpoints a second time.
  const hasRecommendationsRef = useRef(initialRecommendations.length > 0);
  const preferencesRef = useRef(preferences);
  const selectedLocationRef = useRef(selectedLocation);
  const preferencesKey = useMemo(
    () => buildPreferencesKey(preferences),
    [preferences],
  );
  const locationKey = useMemo(
    () => buildLocationKey(selectedLocation),
    [selectedLocation],
  );

  useEffect(() => {
    preferencesRef.current = preferences;
    selectedLocationRef.current = selectedLocation;
  }, [preferences, selectedLocation]);

  const recentOrderNames = useMemo(() => {
    const names = new Set<string>();
    for (const order of orders) {
      for (const item of order.items) {
        names.add(item.item_name_snapshot.trim().toLowerCase());
      }
    }
    return names;
  }, [orders]);

  const filteredRecommendations = useMemo(() => {
    return recommendations.filter(item => {
      switch (selectedFilter) {
        case 'VEG':
          return item.is_veg;
        case 'NON_VEG':
          return !item.is_veg;
        case 'POPULAR':
          return item.is_bestseller || Number(item.popularity_score) >= 80;
        case 'RECENTLY_ORDERED':
          return recentOrderNames.has(item.name.trim().toLowerCase());
        case 'ALL':
        default:
          return true;
      }
    });
  }, [recentOrderNames, recommendations, selectedFilter]);

  const cardWidth = useMemo(() => {
    const horizontalPadding = width >= 768 ? 40 : 32;
    const interCardGap = 14;
    return Math.max(
      158,
      Math.floor((width - horizontalPadding - interCardGap) / 2),
    );
  }, [width]);

  const loadRecommendations = useCallback(
    async (mode: 'initial' | 'refresh' = 'initial') => {
      if (mode === 'refresh') {
        setRefreshing(true);
      } else if (!hasRecommendationsRef.current) {
        setLoading(true);
      }

      try {
        const [recommendationRows, recommendationContextRow, orderRows] =
          await Promise.all([
            api.getRecommendationsForContext({
              token,
              preferences: preferencesRef.current,
              dedupeMultiLocation: true,
              selectedLocation: selectedLocationRef.current,
            }),
            token
              ? api
                  .getPersonalizedRecommendationContext(token)
                  .catch(() => null)
              : Promise.resolve(null),
            token ? api.getOrders(token).catch(() => []) : Promise.resolve([]),
          ]);
        hasRecommendationsRef.current = recommendationRows.length > 0;
        setRecommendations(recommendationRows);
        setRecommendationContext(recommendationContextRow);
        setOrders(orderRows);

        fadeAnim.setValue(0);
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 260,
          useNativeDriver: true,
        }).start();
      } catch (error) {
        pushToast(
          'Recommendations unavailable',
          error instanceof Error
            ? error.message
            : 'Unable to load personalized picks right now.',
          'error',
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    // The request bodies are read from refs, so these two keys are what makes
    // the loader re-run when the preference or location *content* changes -
    // deliberately, in place of the objects themselves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fadeAnim, locationKey, preferencesKey, pushToast, token],
  );

  useEffect(() => {
    trackPersonalizedPickEvent('See All Opened', {
      initial_count: initialRecommendations.length,
    });
  }, [initialRecommendations.length]);

  useEffect(() => {
    void loadRecommendations('initial');
  }, [loadRecommendations]);

  const handleOpenRecommendation = useCallback(
    (item: RecommendationItem) => {
      trackPersonalizedPickEvent('Item Clicked', {
        item_id: item.id,
        restaurant_id: item.restaurant_id,
      });

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

  const handleAddToCart = useCallback(
    (item: RecommendationItem) => {
      trackPersonalizedPickEvent('Add to Cart', {
        item_id: item.id,
        restaurant_id: item.restaurant_id,
      });

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

  const handleToggleFavorite = useCallback(
    (item: RecommendationItem) => {
      if (
        !checkAuthAndRedirect({
          token,
          navigation,
          pushToast,
          redirectTo: { screen: 'PersonalizedPicks' },
        })
      ) {
        return;
      }

      void toggleFavorite({ menuItemId: item.id })
        .then(nextFavorite => {
          trackPersonalizedPickEvent('Favorite Toggled', {
            item_id: item.id,
            is_favorite: nextFavorite,
          });
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
              redirectTo: { screen: 'PersonalizedPicks' },
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

  const onViewableItemsChanged = useRef(
    ({
      viewableItems,
    }: {
      viewableItems: Array<ViewToken<RecommendationItem>>;
    }) => {
      for (const entry of viewableItems) {
        if (!entry.isViewable || !entry.item) {
          continue;
        }
        if (viewedRecommendationIdsRef.current.has(entry.item.id)) {
          continue;
        }
        viewedRecommendationIdsRef.current.add(entry.item.id);
        trackPersonalizedPickEvent('Personalized Pick Viewed', {
          item_id: entry.item.id,
          restaurant_id: entry.item.restaurant_id,
          score: entry.item.score,
        });
      }
    },
  ).current;

  const renderRecommendationCard = useCallback<
    ListRenderItem<RecommendationItem>
  >(
    ({ item }) => (
      <PersonalizedPickCard
        cardWidth={cardWidth}
        favoritePending={isFavoritePending(item.id)}
        isFavorite={favoritesHydrated ? isFavorite(item.id) : item.is_favorite}
        item={item}
        onAddToCart={handleAddToCart}
        onPress={handleOpenRecommendation}
        onToggleFavorite={handleToggleFavorite}
      />
    ),
    [
      cardWidth,
      favoritesHydrated,
      handleAddToCart,
      handleOpenRecommendation,
      handleToggleFavorite,
      isFavorite,
      isFavoritePending,
    ],
  );

  const handleSelectFilter = useCallback((filterId: PersonalizedFilter) => {
    setSelectedFilter(filterId);
    trackPersonalizedPickEvent('Filter Selected', {
      filter: filterId,
    });
  }, []);

  const collectionTitle =
    recommendationContext?.ai_collection_title?.trim() || 'Personalized Picks';
  const collectionInsight =
    recommendationContext?.ai_insight?.trim() ||
    'Based on your preferences, favorites, and ordering patterns.';

  if (loading) {
    return (
      <SafeAreaView edges={['left', 'right']} style={styles.safeArea}>
        <View style={styles.screen}>
          <PersonalizedPicksLoading />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['left', 'right']} style={styles.safeArea}>
      <Animated.View style={[styles.screen, { opacity: fadeAnim }]}>
        <FlatList
          ListEmptyComponent={
            <PersonalizedPicksEmptyState
              onBrowseRestaurants={() => navigation.navigate('Restaurants')}
            />
          }
          ListHeaderComponent={
            <View style={styles.headerBlock}>
              <Text style={styles.title}>{collectionTitle}</Text>
              <Text style={styles.subtitle}>
                Handpicked recommendations based on your tastes
              </Text>

              <View style={styles.explainerCard}>
                <Text style={styles.explainerEyebrow}>
                  {'\u2728'} Recommendations made for you
                </Text>
                <Text style={styles.explainerText}>{collectionInsight}</Text>
              </View>

              <FlatList
                contentContainerStyle={styles.filterList}
                data={FILTER_OPTIONS}
                horizontal
                keyExtractor={item => item.id}
                renderItem={({ item }) => {
                  const selected = selectedFilter === item.id;
                  return (
                    <Pressable
                      onPress={() => handleSelectFilter(item.id)}
                      style={[
                        styles.filterChip,
                        selected ? styles.filterChipActive : null,
                      ]}
                    >
                      <Text
                        style={[
                          styles.filterChipText,
                          selected ? styles.filterChipTextActive : null,
                        ]}
                      >
                        {item.label}
                      </Text>
                    </Pressable>
                  );
                }}
                showsHorizontalScrollIndicator={false}
              />
            </View>
          }
          columnWrapperStyle={styles.gridRow}
          contentContainerStyle={styles.listContent}
          data={filteredRecommendations}
          keyExtractor={item => item.id}
          numColumns={2}
          onViewableItemsChanged={onViewableItemsChanged}
          refreshControl={
            <RefreshControl
              onRefresh={() => void loadRecommendations('refresh')}
              refreshing={refreshing}
              tintColor={theme.colors.primary}
            />
          }
          renderItem={renderRecommendationCard}
          showsVerticalScrollIndicator={false}
          viewabilityConfig={{
            itemVisiblePercentThreshold: 55,
          }}
        />
      </Animated.View>
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
    loadingContainer: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: theme.spacing.lg,
      gap: 12,
    },
    infoSkeletonCard: {
      marginTop: 8,
      borderRadius: 22,
      backgroundColor: theme.colors.surface,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 16,
      gap: 10,
    },
    filterSkeletonRow: {
      flexDirection: 'row',
      gap: 10,
      marginTop: 4,
    },
    gridSkeleton: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      marginHorizontal: -7,
      marginTop: 8,
    },
    gridSkeletonCard: {
      width: '50%',
      paddingHorizontal: 7,
      marginBottom: 14,
    },
    listContent: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: theme.spacing.lg,
      paddingBottom: theme.spacing.section * 2,
      flexGrow: 1,
    },
    headerBlock: {
      marginBottom: theme.spacing.lg,
    },
    title: {
      fontSize: 30,
      lineHeight: 36,
      fontWeight: '800',
      color: theme.colors.text,
      letterSpacing: -0.7,
    },
    subtitle: {
      marginTop: 8,
      fontSize: 16,
      lineHeight: 23,
      color: theme.colors.secondaryText,
    },
    explainerCard: {
      marginTop: 18,
      borderRadius: 24,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark'
          ? 'rgba(255,255,255,0.05)'
          : theme.colors.chipBorder,
      backgroundColor:
        theme.mode === 'dark' ? 'rgba(255,122,69,0.10)' : 'rgba(255,82,0,0.06)',
      padding: 16,
      gap: 6,
    },
    explainerEyebrow: {
      fontSize: 14,
      fontWeight: '800',
      color: theme.colors.primary,
      letterSpacing: 0.2,
    },
    explainerText: {
      fontSize: 14,
      lineHeight: 20,
      color: theme.colors.secondaryText,
    },
    filterList: {
      paddingTop: 16,
      paddingBottom: 2,
      gap: 10,
    },
    filterChip: {
      borderRadius: 999,
      paddingHorizontal: 14,
      paddingVertical: 10,
      borderWidth: 1,
      borderColor: theme.colors.chipBorder,
      backgroundColor: theme.colors.chip,
    },
    filterChipActive: {
      backgroundColor: theme.colors.primary,
      borderColor: theme.colors.primary,
    },
    filterChipText: {
      fontSize: 13,
      fontWeight: '700',
      color: theme.colors.secondaryText,
    },
    filterChipTextActive: {
      color: theme.colors.onPrimary,
    },
    gridRow: {
      justifyContent: 'space-between',
    },
    cardShell: {
      marginBottom: 14,
    },
    card: {
      flex: 1,
      borderRadius: 24,
      overflow: 'hidden',
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? 'rgba(255,255,255,0.05)' : theme.colors.border,
      shadowColor: theme.colors.shadow,
      shadowOpacity: theme.mode === 'dark' ? 0.2 : 0.08,
      shadowOffset: { width: 0, height: 10 },
      shadowRadius: 20,
      elevation: 4,
    },
    cardPressed: {
      transform: [{ scale: 0.988 }],
    },
    cardImageWrap: {
      height: 132,
      backgroundColor: theme.colors.surfaceAlt,
      position: 'relative',
    },
    cardImage: {
      width: '100%',
      height: '100%',
    },
    recommendedBadge: {
      position: 'absolute',
      left: 10,
      top: 10,
      borderRadius: 999,
      paddingHorizontal: 10,
      paddingVertical: 6,
      backgroundColor:
        theme.mode === 'dark'
          ? 'rgba(10,12,18,0.62)'
          : 'rgba(255,255,255,0.90)',
    },
    recommendedBadgeText: {
      fontSize: 10,
      fontWeight: '800',
      color: theme.colors.text,
    },
    favoriteButtonWrap: {
      position: 'absolute',
      right: 10,
      top: 10,
    },
    cardBody: {
      padding: 12,
    },
    cardTopRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      marginBottom: 10,
    },
    vegDot: {
      width: 10,
      height: 10,
      borderRadius: 5,
    },
    categoryPill: {
      borderRadius: 999,
      paddingHorizontal: 9,
      paddingVertical: 5,
      backgroundColor: theme.colors.primarySoft,
    },
    categoryPillText: {
      fontSize: 10.5,
      fontWeight: '700',
      color: theme.colors.primary,
    },
    cardTitle: {
      fontSize: 16,
      lineHeight: 21,
      fontWeight: '800',
      color: theme.colors.text,
      minHeight: 42,
    },
    cardRestaurant: {
      marginTop: 6,
      fontSize: 13,
      fontWeight: '700',
      color: theme.colors.secondaryText,
    },
    cardLocation: {
      marginTop: 2,
      fontSize: 12,
      color: theme.colors.hint,
    },
    cardReason: {
      marginTop: 6,
      fontSize: 12.5,
      lineHeight: 18,
      color:
        theme.mode === 'dark'
          ? 'rgba(240,244,255,0.78)'
          : theme.colors.secondaryText,
      minHeight: 36,
    },
    cardFooter: {
      marginTop: 12,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10,
    },
    priceColumn: {
      flex: 1,
    },
    priceText: {
      fontSize: 15,
      fontWeight: '800',
      color: theme.colors.text,
    },
    matchText: {
      marginTop: 2,
      fontSize: 11.5,
      color: theme.colors.offer,
      fontWeight: '700',
    },
    addButton: {
      minWidth: 66,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 14,
      paddingHorizontal: 14,
      paddingVertical: 10,
      backgroundColor: theme.colors.primary,
    },
    addButtonDisabled: {
      backgroundColor: theme.colors.divider,
    },
    addButtonText: {
      fontSize: 13,
      fontWeight: '800',
      color: theme.colors.onPrimary,
    },
    addButtonTextDisabled: {
      color: theme.colors.disabledText,
    },
    emptyState: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: 48,
      paddingHorizontal: 28,
    },
    emptyIconWrap: {
      width: 64,
      height: 64,
      borderRadius: 32,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primarySoft,
      marginBottom: 16,
    },
    emptyTitle: {
      fontSize: 22,
      fontWeight: '800',
      color: theme.colors.text,
      textAlign: 'center',
    },
    emptyText: {
      marginTop: 8,
      fontSize: 15,
      lineHeight: 22,
      color: theme.colors.secondaryText,
      textAlign: 'center',
    },
    emptyCta: {
      marginTop: 18,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      borderRadius: 999,
      backgroundColor: theme.colors.primary,
      paddingHorizontal: 18,
      paddingVertical: 12,
    },
    emptyCtaText: {
      fontSize: 14,
      fontWeight: '800',
      color: theme.colors.onPrimary,
    },
  });

const styles = createStyles(theme);
