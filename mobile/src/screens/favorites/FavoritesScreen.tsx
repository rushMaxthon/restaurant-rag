import React, { useCallback, useMemo, useRef, useState } from 'react';
import type { ListRenderItem } from 'react-native';
import {
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { FavoriteIconButton } from '@components/FavoriteIconButton';
import {
  useAppActions,
  useFavoritesState,
  useSession,
} from '@hooks/useAppStore';
import { ApiError, api, formatCurrency, placeholderImage } from '@services/api';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { FavoriteItem } from '@/types/app';
import type { RootStackParamList } from '@/navigation/AppNavigator';
import { isCustomizableMenuItem } from '@utils/menuItemCustomization';

type FavoritesNavigation = NativeStackNavigationProp<RootStackParamList>;

export function FavoritesScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation = useNavigation<FavoritesNavigation>();
  const { token } = useSession();
  const { favoriteVersion, favoritesHydrated } = useFavoritesState();
  const {
    addToCart,
    requestAddToCart,
    isFavorite,
    isFavoritePending,
    pushToast,
    toggleFavorite,
  } = useAppActions();
  const [items, setItems] = useState<FavoriteItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastLoadSignatureRef = useRef<string | null>(null);

  const loadFavorites = useCallback(
    async (isRefresh = false) => {
      if (!token) {
        setItems([]);
        setError(null);
        setLoading(false);
        setRefreshing(false);
        return;
      }

      if (isRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      try {
        const rows = await api.getFavorites(token);
        setItems(rows);
        setError(null);
      } catch (nextError) {
        const message =
          nextError instanceof Error
            ? nextError.message
            : 'Unable to load favorites right now.';
        setError(message);
        if (
          nextError instanceof ApiError &&
          (nextError.status === 401 || nextError.status === 403)
        ) {
          navigation.navigate('Login', { redirectTo: { screen: 'Favorites' } });
        }
      } finally {
        if (isRefresh) {
          setRefreshing(false);
        } else {
          setLoading(false);
        }
      }
    },
    [navigation, token],
  );

  // Refetches on focus only when the session or the favorites set actually
  // changed since the last load. Toggling from this screen already updates the
  // store optimistically and is reflected by the `visibleItems` filter below,
  // so a tap no longer round-trips the whole list.
  useFocusEffect(
    useCallback(() => {
      const loadSignature = `${token ?? 'anon'}:${favoriteVersion}`;
      if (lastLoadSignatureRef.current === loadSignature) {
        return;
      }
      lastLoadSignatureRef.current = loadSignature;
      void loadFavorites();
    }, [favoriteVersion, loadFavorites, token]),
  );

  // Hoisted out of the JSX so the row body is not rebuilt on every render.
  const renderFavorite = useCallback<ListRenderItem<FavoriteItem>>(
    ({ item }) => {
      const unavailable = !item.is_orderable;
      return (
        <View style={styles.card}>
          <Pressable
            onPress={() =>
              navigation.navigate('MenuItemDetail', {
                itemId: item.id,
                restaurantId: item.restaurant_id,
                restaurantName: item.restaurant_name,
              })
            }
            style={styles.imageWrap}
          >
            <Image
              source={{
                uri: item.image_url ?? placeholderImage(item.name),
              }}
              style={styles.image}
            />
          </Pressable>
          <View style={styles.cardBody}>
            <View style={styles.cardTop}>
              <View style={styles.cardCopy}>
                <Text style={styles.cardTitle}>{item.name}</Text>
                <Pressable
                  onPress={() =>
                    navigation.navigate('Restaurant', {
                      restaurantId: item.restaurant_id,
                      restaurantName: item.restaurant_name,
                    })
                  }
                >
                  <Text style={styles.cardRestaurant}>
                    {item.restaurant_name}
                  </Text>
                </Pressable>
              </View>
              <FavoriteIconButton
                active
                disabled={isFavoritePending(item.id)}
                onPress={() => {
                  void toggleFavorite({
                    menuItemId: item.id,
                    shouldFavorite: false,
                  })
                    .then(() => {
                      pushToast(
                        'Removed from favorites',
                        `${item.name} was removed.`,
                        'info',
                      );
                    })
                    .catch(nextError => {
                      if (
                        nextError instanceof ApiError &&
                        (nextError.status === 401 || nextError.status === 403)
                      ) {
                        navigation.navigate('Login', {
                          redirectTo: { screen: 'Favorites' },
                        });
                      }
                      pushToast(
                        'Favorites unavailable',
                        nextError instanceof Error
                          ? nextError.message
                          : 'Unable to update favorites right now.',
                        'error',
                      );
                    });
                }}
              />
            </View>
            <View style={styles.badges}>
              <View
                style={[
                  styles.dot,
                  {
                    backgroundColor: item.is_veg
                      ? theme.colors.offer
                      : theme.colors.deepRed,
                  },
                ]}
              />
              <Text style={styles.badgeText}>{item.category}</Text>
              {unavailable ? (
                <Text style={styles.badgeMuted}>Unavailable</Text>
              ) : null}
            </View>
            <Text numberOfLines={2} style={styles.description}>
              {item.description ??
                'Saved for the next time this craving shows up.'}
            </Text>
            <View style={styles.footer}>
              <View>
                <Text style={styles.price}>{formatCurrency(item.price)}</Text>
                <Text style={styles.statusText}>
                  {unavailable ? 'Currently unavailable' : 'Ready to order'}
                </Text>
              </View>
              <Pressable
                disabled={unavailable}
                onPress={() => {
                  if (isCustomizableMenuItem(item)) {
                    navigation.navigate('MenuItemDetail', {
                      itemId: item.id,
                      restaurantId: item.restaurant_id,
                      restaurantName: item.restaurant_name,
                    });
                    return;
                  }
                  void requestAddToCart(
                    item,
                    item.restaurant_id,
                    item.restaurant_name,
                  );
                }}
                style={[
                  styles.primaryButtonSmall,
                  unavailable ? styles.primaryButtonDisabled : null,
                ]}
              >
                <Text style={styles.primaryButtonText}>
                  {unavailable ? 'Unavailable' : 'Add to cart'}
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      );
    },
    [
      isFavoritePending,
      navigation,
      pushToast,
      requestAddToCart,
      styles,
      theme,
      toggleFavorite,
    ],
  );
  const visibleItems = useMemo(
    () =>
      favoritesHydrated ? items.filter(item => isFavorite(item.id)) : items,
    [favoritesHydrated, isFavorite, items],
  );

  if (!token) {
    return (
      <SafeAreaView edges={['left', 'right', 'bottom']} style={styles.safeArea}>
        <View style={styles.emptyState}>
          <Text style={styles.emptyTitle}>Login to view favorites</Text>
          <Text style={styles.emptyText}>
            Save dishes on the home screen or restaurant menu and keep them
            synced here.
          </Text>
          <Pressable
            onPress={() => navigation.navigate('Login')}
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonText}>Login</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['left', 'right', 'bottom']} style={styles.safeArea}>
      <View style={styles.header}>
        <Text style={styles.title}>Favorites</Text>
        <Text style={styles.subtitle}>
          Your saved dishes across web and mobile.
        </Text>
      </View>
      {loading ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyText}>Loading favorites…</Text>
        </View>
      ) : error ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyTitle}>We couldn’t load favorites.</Text>
          <Text style={styles.emptyText}>{error}</Text>
          <Pressable
            onPress={() => void loadFavorites()}
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonText}>Retry</Text>
          </Pressable>
        </View>
      ) : visibleItems.length === 0 ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyTitle}>No favorites yet</Text>
          <Text style={styles.emptyText}>
            Tap the heart on any dish card to keep it handy for your next order.
          </Text>
        </View>
      ) : (
        <FlatList
          contentContainerStyle={styles.listContent}
          data={visibleItems}
          keyExtractor={item => item.id}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              tintColor={theme.colors.primary}
              onRefresh={() => void loadFavorites(true)}
            />
          }
          renderItem={renderFavorite}
        />
      )}
    </SafeAreaView>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    header: {
      paddingHorizontal: 20,
      paddingTop: 12,
      paddingBottom: 8,
    },
    title: {
      color: theme.colors.text,
      fontSize: 26,
      fontWeight: '800',
    },
    subtitle: {
      marginTop: 4,
      color: theme.colors.secondaryText,
      fontSize: 14,
    },
    listContent: {
      padding: 20,
      gap: 14,
    },
    card: {
      flexDirection: 'row',
      gap: 14,
      padding: 14,
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceRaised,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.08,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 3,
    },
    imageWrap: {
      width: 92,
    },
    image: {
      width: 92,
      height: 92,
      borderRadius: 14,
      backgroundColor: theme.colors.card,
    },
    cardBody: {
      flex: 1,
      gap: 8,
    },
    cardTop: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      gap: 12,
    },
    cardCopy: {
      flex: 1,
      gap: 3,
    },
    cardTitle: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
    },
    cardRestaurant: {
      color: theme.colors.primary,
      fontSize: 13,
      fontWeight: '700',
    },
    badges: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
    },
    dot: {
      width: 10,
      height: 10,
      borderRadius: 5,
    },
    badgeText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      fontWeight: '700',
    },
    badgeMuted: {
      color: theme.colors.deepRed,
      fontSize: 12,
      fontWeight: '700',
    },
    description: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 18,
    },
    footer: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
    },
    price: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    statusText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      marginTop: 2,
    },
    emptyState: {
      flex: 1,
      paddingHorizontal: 24,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 12,
    },
    emptyTitle: {
      color: theme.colors.text,
      fontSize: 22,
      fontWeight: '800',
      textAlign: 'center',
    },
    emptyText: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      textAlign: 'center',
      lineHeight: 20,
    },
    primaryButton: {
      minHeight: 44,
      paddingHorizontal: 18,
      borderRadius: 14,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    primaryButtonSmall: {
      minHeight: 40,
      paddingHorizontal: 14,
      borderRadius: 12,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    primaryButtonDisabled: {
      backgroundColor: theme.colors.surfaceAlt,
    },
    primaryButtonText: {
      color: theme.colors.white,
      fontSize: 13,
      fontWeight: '800',
    },
  });

const styles = createStyles(theme);
