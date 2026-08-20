import React, { useCallback, useMemo, useRef, useState } from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import {
  useFocusEffect,
  useNavigation,
  useRoute,
  type RouteProp,
} from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import { RestaurantCard } from '@components/RestaurantCard';
import { SkeletonBlock } from '@components/SkeletonBlock';
import {
  useAppActions,
  useSelectedLocation,
  useSession,
} from '@hooks/useAppStore';
import { api } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { RootStackParamList } from '@/navigation/navigationTypes';
import type { Restaurant } from '@/types/app';

type RestaurantFilter = 'all' | 'open' | 'closed';

const FILTER_OPTIONS: Array<{ key: RestaurantFilter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'open', label: 'Open now' },
  { key: 'closed', label: 'Closed' },
];

function normalizeText(value: string | null | undefined): string {
  return (value ?? '').trim().toLowerCase();
}

function ScreenSkeleton(): React.JSX.Element {
  const styles = useThemedStyles(createStyles);

  return (
    <ScrollView
      contentContainerStyle={styles.loadingContent}
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.heroCard}>
        <SkeletonBlock height={24} width="42%" />
        <SkeletonBlock height={14} width="74%" />
        <SkeletonBlock height={14} width="58%" />
      </View>

      <SkeletonBlock borderRadius={18} height={52} />

      <View style={styles.loadingFilterRow}>
        <SkeletonBlock borderRadius={999} height={36} width={70} />
        <SkeletonBlock borderRadius={999} height={36} width={96} />
        <SkeletonBlock borderRadius={999} height={36} width={82} />
      </View>

      {Array.from({ length: 4 }).map((_, index) => (
        <SkeletonBlock
          key={`restaurant-skeleton-${index}`}
          borderRadius={20}
          height={258}
        />
      ))}
    </ScrollView>
  );
}

export function RestaurantsScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation =
    useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const route = useRoute<RouteProp<RootStackParamList, 'Restaurants'>>();
  const { token } = useSession();
  const selectedLocation = useSelectedLocation();
  const { pushToast } = useAppActions();
  const seededRestaurants = useMemo(
    () => route.params?.initialRestaurants ?? [],
    [route.params?.initialRestaurants],
  );
  const [restaurants, setRestaurants] =
    useState<Restaurant[]>(seededRestaurants);
  const [loading, setLoading] = useState(seededRestaurants.length === 0);
  const [refreshing, setRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState<RestaurantFilter>('all');
  // Tracked in a ref rather than read from state: `restaurants.length` in the
  // dependency array below changed this callback's identity after every load,
  // which re-armed the focus effect and fetched the list a second time.
  const hasRestaurantsRef = useRef(seededRestaurants.length > 0);

  const loadRestaurants = useCallback(
    async (mode: 'initial' | 'refresh' = 'initial') => {
      setErrorMessage(null);
      if (mode === 'refresh') {
        setRefreshing(true);
      } else if (!hasRestaurantsRef.current) {
        setLoading(true);
      }

      try {
        const rows = await api.getRestaurants(token);
        hasRestaurantsRef.current = rows.length > 0;
        setRestaurants(rows);
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : 'Unable to load restaurants right now.';
        if (!hasRestaurantsRef.current) {
          setErrorMessage(message);
          pushToast('Restaurants unavailable', message, 'error');
        }
      } finally {
        if (mode === 'refresh') {
          setRefreshing(false);
        } else {
          setLoading(false);
        }
      }
    },
    [pushToast, token],
  );

  useFocusEffect(
    useCallback(() => {
      void loadRestaurants('initial');
    }, [loadRestaurants]),
  );

  const filteredRestaurants = useMemo(() => {
    const query = normalizeText(searchQuery);

    return [...restaurants]
      .filter(restaurant => {
        if (activeFilter === 'open' && !restaurant.is_open) {
          return false;
        }

        if (activeFilter === 'closed' && restaurant.is_open) {
          return false;
        }

        if (!query) {
          return true;
        }

        const haystack = [
          restaurant.name,
          restaurant.cuisine_type,
          restaurant.city,
        ]
          .join(' ')
          .toLowerCase();

        return haystack.includes(query);
      })
      .sort(
        (left, right) =>
          Number(right.is_open) - Number(left.is_open) ||
          left.name.localeCompare(right.name),
      );
  }, [activeFilter, restaurants, searchQuery]);

  const locationLabel =
    selectedLocation?.city ??
    selectedLocation?.address.split(',')[0]?.trim() ??
    'All available areas';

  const renderRestaurant = ({ item }: { item: Restaurant }) => (
    <RestaurantCard
      onPress={() =>
        navigation.navigate('Restaurant', {
          restaurantId: item.id,
          restaurantName: item.name,
        })
      }
      restaurant={item}
    />
  );

  if (loading) {
    return (
      <SafeAreaView edges={['bottom']} style={styles.safeArea}>
        <ScreenSkeleton />
      </SafeAreaView>
    );
  }

  if (errorMessage && restaurants.length === 0) {
    return (
      <SafeAreaView edges={['bottom']} style={styles.safeArea}>
        <View style={styles.feedbackWrap}>
          <View style={styles.feedbackCard}>
            <Text style={styles.feedbackTitle}>Restaurants unavailable</Text>
            <Text style={styles.feedbackText}>{errorMessage}</Text>
            <Pressable
              onPress={() => {
                void loadRestaurants('initial');
              }}
              style={styles.retryButton}
            >
              <Text style={styles.retryButtonText}>Retry</Text>
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <FlatList
        contentContainerStyle={styles.content}
        data={filteredRestaurants}
        keyExtractor={item => item.id}
        ListEmptyComponent={
          <View style={styles.emptyCard}>
            <View style={styles.emptyIconWrap}>
              <Icon
                color={theme.colors.primary}
                name="storefront-outline"
                size={28}
              />
            </View>
            <Text style={styles.emptyTitle}>No restaurants matched</Text>
            <Text style={styles.emptyText}>
              Try a different search or switch the filter to see more places.
            </Text>
          </View>
        }
        ListHeaderComponent={
          <View style={styles.headerWrap}>
            <View style={styles.heroCard}>
              <View style={styles.heroGlowPrimary} />
              <View style={styles.heroGlowSecondary} />
              <Text style={styles.heroTitle}>Restaurants</Text>
              <Text style={styles.heroSubtitle}>
                Browse every available restaurant without the Home screen limit.
              </Text>
              <Text style={styles.heroMeta}>
                {filteredRestaurants.length}{' '}
                {filteredRestaurants.length === 1
                  ? 'restaurant'
                  : 'restaurants'}{' '}
                • {locationLabel}
              </Text>
            </View>

            <View style={styles.searchBar}>
              <Icon color={theme.colors.hint} name="search-outline" size={18} />
              <TextInput
                onChangeText={setSearchQuery}
                placeholder="Search restaurants or cuisines"
                placeholderTextColor={theme.colors.hint}
                style={styles.searchInput}
                value={searchQuery}
              />
              {searchQuery.length > 0 ? (
                <Pressable
                  hitSlop={8}
                  onPress={() => setSearchQuery('')}
                  style={styles.clearSearchButton}
                >
                  <Icon
                    color={theme.colors.hint}
                    name="close-circle"
                    size={18}
                  />
                </Pressable>
              ) : null}
            </View>

            <ScrollView
              contentContainerStyle={styles.filterRail}
              horizontal
              showsHorizontalScrollIndicator={false}
            >
              {FILTER_OPTIONS.map(option => (
                <Pressable
                  key={option.key}
                  onPress={() => setActiveFilter(option.key)}
                  style={[
                    styles.filterChip,
                    activeFilter === option.key
                      ? styles.filterChipActive
                      : null,
                  ]}
                >
                  <Text
                    style={[
                      styles.filterChipText,
                      activeFilter === option.key
                        ? styles.filterChipTextActive
                        : null,
                    ]}
                  >
                    {option.label}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        }
        refreshControl={
          <RefreshControl
            onRefresh={() => {
              void loadRestaurants('refresh');
            }}
            refreshing={refreshing}
            tintColor={theme.colors.primary}
          />
        }
        renderItem={renderRestaurant}
        showsVerticalScrollIndicator={false}
      />
    </SafeAreaView>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    loadingContent: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 12,
      paddingBottom: 28,
      gap: 14,
    },
    loadingFilterRow: {
      flexDirection: 'row',
      gap: 8,
    },
    content: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 12,
      paddingBottom: 28,
    },
    headerWrap: {
      gap: 14,
      marginBottom: 12,
    },
    heroCard: {
      borderRadius: 24,
      padding: 18,
      gap: 8,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : theme.colors.surface,
      borderWidth: 1,
      borderColor: theme.colors.border,
      overflow: 'hidden',
    },
    heroGlowPrimary: {
      position: 'absolute',
      top: -28,
      right: -20,
      width: 104,
      height: 104,
      borderRadius: 52,
      backgroundColor: theme.colors.primarySoft,
      opacity: theme.mode === 'dark' ? 0.2 : 0.75,
    },
    heroGlowSecondary: {
      position: 'absolute',
      bottom: -26,
      left: -18,
      width: 84,
      height: 84,
      borderRadius: 42,
      backgroundColor: theme.colors.infoSoft,
      opacity: theme.mode === 'dark' ? 0.14 : 0.45,
    },
    heroTitle: {
      color: theme.colors.text,
      fontSize: 28,
      lineHeight: 34,
      fontWeight: '900',
      letterSpacing: -0.7,
    },
    heroSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 19,
      maxWidth: '88%',
    },
    heroMeta: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    searchBar: {
      minHeight: 52,
      borderRadius: 18,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      paddingHorizontal: 14,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
    },
    searchInput: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 14,
      paddingVertical: 0,
    },
    clearSearchButton: {
      width: 28,
      height: 28,
      alignItems: 'center',
      justifyContent: 'center',
    },
    filterRail: {
      gap: 8,
      paddingRight: 8,
    },
    filterChip: {
      minHeight: 36,
      borderRadius: 999,
      paddingHorizontal: 14,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    filterChipActive: {
      backgroundColor: theme.colors.primarySoft,
      borderColor:
        theme.mode === 'dark' ? theme.colors.chipBorder : 'transparent',
    },
    filterChipText: {
      color: theme.colors.text,
      fontSize: 12,
      fontWeight: '700',
    },
    filterChipTextActive: {
      color: theme.colors.primary,
      fontWeight: '800',
    },
    feedbackWrap: {
      flex: 1,
      paddingHorizontal: theme.spacing.screen,
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
      fontSize: 18,
      fontWeight: '800',
    },
    feedbackText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 20,
    },
    retryButton: {
      alignSelf: 'flex-start',
      minHeight: 42,
      borderRadius: 14,
      paddingHorizontal: 16,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primary,
      marginTop: 4,
    },
    retryButtonText: {
      color: theme.colors.white,
      fontSize: 13,
      fontWeight: '800',
    },
    emptyCard: {
      borderRadius: 24,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 22,
      gap: 10,
      alignItems: 'flex-start',
      marginTop: 8,
    },
    emptyIconWrap: {
      width: 56,
      height: 56,
      borderRadius: 28,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primarySoft,
    },
    emptyTitle: {
      color: theme.colors.text,
      fontSize: 18,
      fontWeight: '800',
    },
    emptyText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 20,
    },
  });
