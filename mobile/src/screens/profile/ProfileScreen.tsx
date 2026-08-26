import React, { useCallback, useMemo, useState } from 'react';
import {
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type ListRenderItem,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { useBottomTabBarHeight } from '@react-navigation/bottom-tabs';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import {
  ProfileRow,
  type ProfileRowProps as SectionItem,
} from './components/ProfileRow';
import { useAppActions, usePreferences, useSession } from '@hooks/useAppStore';
import { api, formatCurrency, formatDateTime } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { Order, ProfileSummary } from '@/types/app';
import type { RootStackParamList } from '@/navigation/AppNavigator';

type ProfileStackNav = NativeStackNavigationProp<RootStackParamList>;

function ProfileHero({ children }: { children?: React.ReactNode }) {
  const styles = useThemedStyles(createStyles);
  return (
    <View style={styles.heroCard}>
      <View style={styles.heroGlowPrimary} />
      <View style={styles.heroGlowSecondary} />
      {children}
    </View>
  );
}

export function ProfileScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation = useNavigation<ProfileStackNav>();
  const tabBarHeight = useBottomTabBarHeight();
  const { user, token } = useSession();
  const { preferences } = usePreferences();
  const { updateUser, logout, pushToast } = useAppActions();
  const [profileSummary, setProfileSummary] = useState<ProfileSummary | null>(
    null,
  );
  const [loading, setLoading] = useState(Boolean(token));
  const [refreshing, setRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loadProfile = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!token) {
        setProfileSummary(null);
        setErrorMessage(null);
        setLoading(false);
        setRefreshing(false);
        return;
      }

      if (options?.silent) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      try {
        const summary = await api.getProfileSummary(token);
        setProfileSummary(summary);
        setErrorMessage(null);
        updateUser(summary.user);
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : 'Unable to load profile data.';
        setErrorMessage(message);
        pushToast('Profile unavailable', message, 'error');
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [pushToast, token, updateUser],
  );

  const preferencesSummary = useMemo(() => {
    const resolvedPreferences = profileSummary?.preferences ?? preferences;
    if (!resolvedPreferences) {
      return 'Set cuisines, spice, and budget preferences';
    }

    const parts = [
      resolvedPreferences.cuisines.slice(0, 2).join(', '),
      resolvedPreferences.diet === 'VEG'
        ? 'Veg'
        : resolvedPreferences.diet === 'NON_VEG'
        ? 'Non-Veg'
        : '',
      resolvedPreferences.budget === 'LOW'
        ? 'Low budget'
        : resolvedPreferences.budget === 'MID'
        ? 'Mid budget'
        : resolvedPreferences.budget === 'HIGH'
        ? 'High budget'
        : '',
    ].filter(Boolean);

    return parts.length > 0
      ? parts.join(' • ')
      : 'Set cuisines, spice, and budget preferences';
  }, [preferences, profileSummary?.preferences]);

  useFocusEffect(
    useCallback(() => {
      if (!token) {
        setProfileSummary(null);
        setErrorMessage(null);
        setLoading(false);
        return;
      }

      void loadProfile();
    }, [loadProfile, token]),
  );

  const resolvedUser = profileSummary?.user ?? user;
  const stats = profileSummary?.stats;
  const recentOrders = profileSummary?.recent_orders.slice(0, 3) ?? [];

  // Hoisted out of the JSX: as an inline prop this row was rebuilt on
  // every render of the surrounding component.
  const renderRecentOrder = useCallback<ListRenderItem<Order>>(
    ({ item }) => (
      <Pressable
        onPress={() => navigation.navigate('OrderDetail', { orderId: item.id })}
        style={styles.orderRow}
      >
        <View style={styles.orderIcon}>
          <Icon
            color={theme.colors.primary}
            name="bag-handle-outline"
            size={18}
          />
        </View>
        <View style={styles.orderCopy}>
          <Text style={styles.orderRestaurant}>{item.restaurant.name}</Text>
          <Text style={styles.orderMeta}>{formatDateTime(item.placed_at)}</Text>
        </View>
        <View style={styles.orderRight}>
          <Text style={styles.orderAmount}>
            {formatCurrency(item.total_amount)}
          </Text>
          <Text style={styles.orderStatus}>
            {item.status.replaceAll('_', ' ')}
          </Text>
        </View>
      </Pressable>
    ),
    [navigation, styles, theme],
  );

  const initials = useMemo(() => {
    if (!resolvedUser?.full_name) {
      return 'RR';
    }
    return resolvedUser.full_name
      .split(/\s+/)
      .map(part => part[0]?.toUpperCase())
      .filter(Boolean)
      .slice(0, 2)
      .join('');
  }, [resolvedUser?.full_name]);

  const profileStatus = useMemo(() => {
    if (stats && stats.total_orders > 0) {
      return `${stats.total_orders} order${
        stats.total_orders === 1 ? '' : 's'
      } placed • ${stats.delivered_orders} delivered`;
    }
    if (profileSummary?.preferences ?? preferences) {
      return 'Taste profile ready for smarter recommendations';
    }
    return 'Set your food preferences for smarter picks';
  }, [preferences, profileSummary?.preferences, stats]);

  if (!resolvedUser) {
    return (
      <SafeAreaView edges={['top']} style={styles.safeArea}>
        <View
          style={[
            styles.loggedOutWrap,
            { paddingBottom: Math.max(tabBarHeight + 12, 88) },
          ]}
        >
          <ProfileHero>
            <View style={styles.heroHeaderRow}>
              <View style={styles.heroBadge}>
                <Icon
                  color={theme.colors.primary}
                  name="person-circle-outline"
                  size={14}
                />
                <Text style={styles.heroBadgeText}>Profile</Text>
              </View>
            </View>
            <Text style={styles.name}>Keep your food world in one place.</Text>
            <Text style={styles.heroSubtitle}>
              Login to track orders, saved places, and personalized
              recommendations.
            </Text>
          </ProfileHero>
          <View style={styles.loggedOutCard}>
            <View style={styles.loggedOutFeatureIcon}>
              <Icon
                color={theme.colors.primary}
                name="person-circle-outline"
                size={20}
              />
            </View>
            <Text style={styles.loggedOutFeatureTitle}>
              Your profile is waiting.
            </Text>
            <Text style={styles.loggedOutFeatureText}>
              Login to see your orders, saved addresses, delivery progress, and
              reorder options.
            </Text>
            <Pressable
              onPress={() => navigation.navigate('Login')}
              style={styles.primaryButtonCompact}
            >
              <Text style={styles.primaryButtonText}>Login</Text>
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
    );
  }

  const detailSections: SectionItem[] = [
    {
      title: 'User Details',
      subtitle: 'View and update your name, contact info, and default address',
      icon: 'person-outline',
      onPress: () => navigation.navigate('ProfileDetails'),
    },
    {
      title: 'Saved Addresses',
      subtitle:
        resolvedUser.default_address ??
        'Add delivery locations for faster checkout',
      icon: 'location-outline',
      onPress: () => navigation.navigate('SavedAddresses'),
    },
    {
      title: 'User Preferences',
      subtitle: preferencesSummary,
      icon: 'sparkles-outline',
      onPress: () => navigation.navigate('UserPreferences', { mode: 'edit' }),
    },
    {
      title: 'Favorites',
      subtitle: stats
        ? `${stats.favorites_count} saved dish${
            stats.favorites_count === 1 ? '' : 'es'
          } synced across web and mobile`
        : 'Saved dishes synced across web and mobile',
      icon: 'heart-outline',
      onPress: () => navigation.navigate('Favorites'),
    },
  ];

  const settingsSections: SectionItem[] = [
    {
      title: 'Notifications',
      subtitle: 'Manage alerts for offers, delivery, and updates',
      icon: 'notifications-outline',
      onPress: () => navigation.navigate('NotificationSettings'),
    },
    {
      title: 'Privacy',
      subtitle: 'Control data usage and account visibility preferences',
      icon: 'lock-closed-outline',
      onPress: () => navigation.navigate('Privacy'),
    },
    {
      title: 'Appearance',
      subtitle: 'Review the current visual mode used in the app',
      icon: 'color-palette-outline',
      onPress: () => navigation.navigate('Appearance'),
    },
  ];

  const supportSections: SectionItem[] = [
    {
      title: 'Help & Support',
      subtitle: 'Get help with payments, deliveries, and your AI assistant',
      icon: 'help-buoy-outline',
      onPress: () => navigation.navigate('HelpSupport'),
    },
  ];

  return (
    <SafeAreaView edges={['top']} style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={[styles.content, { paddingBottom: 10 }]}
        refreshControl={
          token ? (
            <RefreshControl
              onRefresh={() => {
                void loadProfile({ silent: true });
              }}
              refreshing={refreshing}
              tintColor={theme.colors.primary}
            />
          ) : undefined
        }
        showsVerticalScrollIndicator={false}
      >
        <ProfileHero>
          <View style={styles.heroHeaderRow}>
            <View style={styles.heroBadge}>
              <Icon
                color={theme.colors.primary}
                name="person-circle-outline"
                size={14}
              />
              <Text style={styles.heroBadgeText}>Profile</Text>
            </View>
            <Pressable
              onPress={() => navigation.navigate('ProfileDetails')}
              style={styles.editButton}
            >
              <Icon
                color={theme.colors.primary}
                name="create-outline"
                size={15}
              />
              <Text style={styles.editButtonText}>Edit Profile</Text>
            </Pressable>
          </View>
          <View style={styles.heroIdentityRow}>
            <View style={styles.avatar}>
              <Text style={styles.avatarText}>{initials}</Text>
            </View>
            <View style={styles.heroCopy}>
              <Text numberOfLines={1} style={styles.name}>
                {resolvedUser.full_name}
              </Text>
              <Text numberOfLines={1} style={styles.meta}>
                {resolvedUser.email}
              </Text>
              <Text numberOfLines={2} style={styles.heroSubtitle}>
                {profileStatus}
              </Text>
            </View>
          </View>
        </ProfileHero>

        <View style={styles.summaryRow}>
          <View style={styles.summaryChip}>
            <Text style={styles.summaryValue}>
              {stats?.total_orders ?? '—'}
            </Text>
            <Text style={styles.summaryLabel}>Total orders</Text>
          </View>
          <View style={styles.summaryChip}>
            <Text style={styles.summaryValue}>
              {stats?.delivered_orders ?? '—'}
            </Text>
            <Text style={styles.summaryLabel}>Delivered</Text>
          </View>
          <View style={styles.summaryChip}>
            <Text style={styles.summaryValue}>
              {stats?.saved_places ?? '—'}
            </Text>
            <Text style={styles.summaryLabel}>Saved places</Text>
          </View>
        </View>

        {errorMessage ? (
          <View style={styles.inlineStatusCard}>
            <Text style={styles.inlineStatusTitle}>Profile sync delayed</Text>
            <Text style={styles.inlineStatusText}>{errorMessage}</Text>
            <Pressable
              onPress={() => {
                void loadProfile({ silent: true });
              }}
              style={styles.inlineStatusButton}
            >
              <Text style={styles.inlineStatusButtonText}>
                {refreshing ? 'Refreshing...' : 'Try again'}
              </Text>
            </Pressable>
          </View>
        ) : null}

        <View style={styles.sectionCard}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionHeading}>Account</Text>
            <Text style={styles.sectionHelper}>
              Everything about your profile in one place.
            </Text>
          </View>
          {detailSections.map(item => (
            <ProfileRow key={item.title} {...item} />
          ))}
        </View>

        <View style={styles.sectionCard}>
          <View style={styles.sectionHeaderRow}>
            <View>
              <Text style={styles.sectionHeading}>Order History</Text>
              <Text style={styles.sectionHelper}>
                Your latest food orders and totals.
              </Text>
            </View>
            <Pressable onPress={() => navigation.navigate('OrderList')}>
              <Text style={styles.sectionLink}>View all</Text>
            </Pressable>
          </View>
          {loading && recentOrders.length === 0 ? (
            <View style={styles.emptyCard}>
              <Text style={styles.emptyTitle}>Loading your profile</Text>
              <Text style={styles.emptyText}>
                We are pulling your latest orders, favorites, and saved details.
              </Text>
            </View>
          ) : recentOrders.length > 0 ? (
            <FlatList
              data={recentOrders}
              keyExtractor={item => item.id}
              renderItem={renderRecentOrder}
              scrollEnabled={false}
            />
          ) : (
            <View style={styles.emptyCard}>
              <Text style={styles.emptyTitle}>No orders yet</Text>
              <Text style={styles.emptyText}>
                Your delivered and in-progress orders will show up here once you
                place one.
              </Text>
              <Pressable
                onPress={() =>
                  navigation.navigate('MainTabs', { screen: 'Home' })
                }
                style={styles.emptyAction}
              >
                <Text style={styles.emptyActionText}>Browse restaurants</Text>
              </Pressable>
            </View>
          )}
        </View>

        <View style={styles.sectionCard}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionHeading}>Settings</Text>
            <Text style={styles.sectionHelper}>
              Adjust alerts, privacy, and app appearance.
            </Text>
          </View>
          {settingsSections.map(item => (
            <ProfileRow key={item.title} {...item} />
          ))}
        </View>

        <View style={styles.sectionCard}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionHeading}>Support</Text>
            <Text style={styles.sectionHelper}>
              Need help? Reach us anytime.
            </Text>
          </View>
          {supportSections.map(item => (
            <ProfileRow key={item.title} {...item} />
          ))}
        </View>

        <Pressable onPress={logout} style={styles.logoutButton}>
          <Icon color={theme.colors.white} name="log-out-outline" size={18} />
          <Text style={styles.logoutText}>Logout</Text>
        </Pressable>
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
    content: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 8,
      gap: 14,
    },
    heroCard: {
      borderRadius: 22,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceRaised : theme.tone('#FFF4EC'),
      paddingHorizontal: 15,
      paddingVertical: 13,
      gap: 10,
      overflow: 'hidden',
      position: 'relative',
      borderWidth: 1,
      borderColor: theme.colors.border,
      shadowColor: theme.colors.shadow,
      shadowOpacity: theme.mode === 'dark' ? 0.18 : 0.08,
      shadowOffset: { width: 0, height: 10 },
      shadowRadius: 20,
      elevation: 4,
    },
    heroGlowPrimary: {
      position: 'absolute',
      width: 180,
      height: 180,
      borderRadius: 90,
      top: -56,
      right: -20,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.primaryTint(0.08)
          : theme.primaryTint(0.12),
    },
    heroGlowSecondary: {
      position: 'absolute',
      width: 120,
      height: 120,
      borderRadius: 60,
      bottom: -48,
      left: -24,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.primaryTint(0.06)
          : theme.tone('rgba(255,189,153,0.34)'),
    },
    heroHeaderRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10,
    },
    heroBadge: {
      minHeight: 26,
      borderRadius: 13,
      paddingHorizontal: 9,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : 'rgba(255,255,255,0.72)',
      borderWidth: 1,
      borderColor: theme.colors.border,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 5,
    },
    heroBadgeText: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '800',
    },
    heroIdentityRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
    },
    avatar: {
      width: 54,
      height: 54,
      borderRadius: 27,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 2,
      borderColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : 'rgba(255,255,255,0.7)',
    },
    avatarText: {
      color: theme.colors.white,
      fontSize: 19,
      fontWeight: '900',
    },
    heroCopy: {
      flex: 1,
      minWidth: 0,
      gap: 2,
    },
    editButton: {
      minHeight: 34,
      borderRadius: 13,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : 'rgba(255,255,255,0.72)',
      borderWidth: 1,
      borderColor: theme.colors.border,
      paddingHorizontal: 9,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 5,
    },
    editButtonText: {
      color: theme.colors.primary,
      fontSize: 13,
      fontWeight: '700',
    },
    name: {
      color: theme.colors.text,
      fontSize: 22,
      fontWeight: '900',
      lineHeight: 27,
    },
    heroSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 17,
      maxWidth: '100%',
    },
    meta: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 16,
    },
    summaryRow: {
      flexDirection: 'row',
      gap: 10,
    },
    summaryChip: {
      flex: 1,
      borderRadius: 18,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      paddingVertical: 12,
      paddingHorizontal: 12,
      gap: 3,
    },
    summaryValue: {
      color: theme.colors.text,
      fontSize: 18,
      fontWeight: '800',
    },
    summaryLabel: {
      color: theme.colors.secondaryText,
      fontSize: 12,
    },
    inlineStatusCard: {
      borderRadius: 18,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 14,
      gap: 8,
    },
    inlineStatusTitle: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    inlineStatusText: {
      color: theme.colors.secondaryText,
      lineHeight: 19,
    },
    inlineStatusButton: {
      alignSelf: 'flex-start',
      borderRadius: 14,
      backgroundColor: theme.colors.primarySoft,
      paddingHorizontal: 12,
      paddingVertical: 8,
    },
    inlineStatusButtonText: {
      color: theme.colors.primary,
      fontWeight: '800',
    },
    sectionCard: {
      borderRadius: 26,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 16,
      gap: 8,
      borderWidth: 1,
      borderColor: theme.colors.border,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.06,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 4,
    },
    sectionHeader: {
      gap: 4,
      marginBottom: 6,
    },
    sectionHeaderRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      gap: 12,
      marginBottom: 6,
    },
    sectionHeading: {
      color: theme.colors.text,
      fontSize: 19,
      fontWeight: '800',
    },
    sectionHelper: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 18,
    },
    sectionLink: {
      color: theme.colors.primary,
      fontWeight: '800',
    },
    sectionRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      paddingVertical: 12,
    },
    sectionIcon: {
      width: 40,
      height: 40,
      borderRadius: 20,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    sectionCopy: {
      flex: 1,
      gap: 2,
    },
    sectionTitle: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    sectionSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    orderRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      paddingVertical: 12,
    },
    orderIcon: {
      width: 42,
      height: 42,
      borderRadius: 21,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    orderCopy: {
      flex: 1,
      gap: 3,
    },
    orderRestaurant: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    orderMeta: {
      color: theme.colors.secondaryText,
      fontSize: 12,
    },
    orderRight: {
      alignItems: 'flex-end',
      gap: 2,
    },
    orderAmount: {
      color: theme.colors.text,
      fontWeight: '800',
    },
    orderStatus: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '800',
      textTransform: 'capitalize',
    },
    emptyCard: {
      borderRadius: 20,
      backgroundColor: theme.colors.cream,
      padding: 16,
      gap: 8,
    },
    emptyTitle: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
    },
    emptyText: {
      color: theme.colors.secondaryText,
      lineHeight: 19,
    },
    emptyAction: {
      alignSelf: 'flex-start',
      borderRadius: 14,
      backgroundColor: theme.colors.primary,
      paddingHorizontal: 14,
      paddingVertical: 10,
      marginTop: 4,
    },
    emptyActionText: {
      color: theme.colors.white,
      fontWeight: '800',
    },
    logoutButton: {
      minHeight: 52,
      borderRadius: 18,
      backgroundColor: theme.colors.primary,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 8,
    },
    logoutText: {
      color: theme.colors.white,
      fontWeight: '800',
      fontSize: 15,
    },
    loggedOutWrap: {
      flex: 1,
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 12,
      gap: 12,
    },
    loggedOutCard: {
      borderRadius: 20,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 18,
      gap: 10,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.05,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 14,
      elevation: 3,
    },
    loggedOutFeatureIcon: {
      width: 44,
      height: 44,
      borderRadius: 22,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: 4,
    },
    loggedOutFeatureTitle: {
      color: theme.colors.text,
      fontSize: 22,
      fontWeight: '900',
      lineHeight: 28,
    },
    loggedOutFeatureText: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 22,
    },
    primaryButton: {
      minHeight: 50,
      borderRadius: 16,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: 8,
    },
    primaryButtonText: {
      color: theme.colors.white,
      fontWeight: '800',
    },
    primaryButtonCompact: {
      marginTop: 4,
      alignSelf: 'flex-start',
      minHeight: 46,
      borderRadius: 23,
      paddingHorizontal: 22,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
  });
