import React, { useCallback, useContext, useMemo, useState } from 'react';
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import type { ListRenderItem } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { BottomTabBarHeightContext } from '@react-navigation/bottom-tabs';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import { SkeletonBlock } from '@components/SkeletonBlock';
import { useAppActions, useSession } from '@hooks/useAppStore';
import { api, formatCurrency, formatDateTime } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { RootStackParamList } from '@/navigation/AppNavigator';
import type { Order } from '@/types/app';

function getStatusTone(theme: AppTheme, status: Order['status']) {
  if (status === 'DELIVERED') {
    return {
      bg: theme.colors.successSoft,
      fg: theme.colors.success,
      label: 'Delivered',
    };
  }

  // A card order that was never paid. It is not in the kitchen queue, so it is
  // deliberately called out rather than shown as a normal live order.
  if (status === 'PAYMENT_PENDING') {
    return {
      bg: theme.colors.primarySoft,
      fg: theme.colors.primary,
      label: 'Payment pending',
    };
  }

  if (status === 'CANCELLED') {
    return {
      bg: theme.colors.card,
      fg: theme.colors.hint,
      label: 'Cancelled',
    };
  }

  if (status === 'PREPARING' || status === 'OUT_FOR_DELIVERY') {
    return {
      bg: theme.colors.warningSoft,
      fg: theme.colors.warning,
      label: status === 'PREPARING' ? 'Preparing' : 'On the way',
    };
  }

  return {
    bg: theme.colors.card,
    fg: theme.colors.secondaryText,
    label: status.replaceAll('_', ' '),
  };
}

function OrdersHero({ title, subtitle }: { title: string; subtitle: string }) {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  return (
    <View style={styles.heroCard}>
      <View style={styles.heroGlowPrimary} />
      <View style={styles.heroGlowSecondary} />
      <View style={styles.heroBadge}>
        <Icon color={theme.colors.primary} name="receipt-outline" size={15} />
        <Text style={styles.heroBadgeText}>Orders</Text>
      </View>
      <Text style={styles.heroTitle}>{title}</Text>
      <Text style={styles.heroSubtitle}>{subtitle}</Text>
    </View>
  );
}

function FeedbackCard({
  icon,
  title,
  text,
  buttonLabel,
  onPress,
}: {
  icon: string;
  title: string;
  text: string;
  buttonLabel: string;
  onPress: () => void;
}) {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  return (
    <View style={styles.feedbackCard}>
      <View style={styles.feedbackIcon}>
        <Icon color={theme.colors.primary} name={icon} size={20} />
      </View>
      <Text style={styles.feedbackTitle}>{title}</Text>
      <Text style={styles.feedbackText}>{text}</Text>
      <Pressable onPress={onPress} style={styles.primaryButton}>
        <Text style={styles.primaryButtonText}>{buttonLabel}</Text>
      </Pressable>
    </View>
  );
}

export function OrderListScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation =
    useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const tabBarHeight = useContext(BottomTabBarHeightContext) ?? 0;
  const { token } = useSession();
  const { pushToast } = useAppActions();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(Boolean(token));
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const deliveredCount = useMemo(
    () => orders.filter(order => order.status === 'DELIVERED').length,
    [orders],
  );

  // Unpaid and cancelled orders are not "active": neither is being cooked.
  const activeOrderCount = useMemo(
    () =>
      orders.filter(
        order =>
          order.status !== 'DELIVERED' &&
          order.status !== 'CANCELLED' &&
          order.status !== 'PAYMENT_PENDING',
      ).length,
    [orders],
  );

  const loadOrders = useCallback(
    async (mode: 'initial' | 'refresh' = 'initial') => {
      if (!token) {
        setOrders([]);
        setLoading(false);
        setRefreshing(false);
        return;
      }

      if (mode === 'refresh') {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      setError(null);
      try {
        const rows = await api.getOrders(token);
        setOrders(rows);
      } catch (nextError) {
        const message =
          nextError instanceof Error
            ? nextError.message
            : 'Unable to load your order history.';
        setError(message);
        pushToast('Orders unavailable', message, 'error');
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [pushToast, token],
  );

  // Both hoisted out of the JSX: as inline props they were rebuilt on
  // every render, taking the header block and every row with them.
  const listHeader = useMemo(
    () => (
      <View style={styles.headerStack}>
        <OrdersHero
          subtitle="See recent checkouts, delivery progress, and quick access to every bill."
          title="Orders that move with you."
        />
        <View style={styles.summaryRow}>
          <View style={styles.summaryChip}>
            <Text style={styles.summaryValue}>{orders.length}</Text>
            <Text style={styles.summaryLabel}>Total orders</Text>
          </View>
          <View style={styles.summaryChip}>
            <Text style={styles.summaryValue}>{activeOrderCount}</Text>
            <Text style={styles.summaryLabel}>Active</Text>
          </View>
          <View style={styles.summaryChip}>
            <Text style={styles.summaryValue}>{deliveredCount}</Text>
            <Text style={styles.summaryLabel}>Delivered</Text>
          </View>
        </View>
      </View>
    ),
    [activeOrderCount, deliveredCount, orders.length, styles],
  );

  const renderOrder = useCallback<ListRenderItem<Order>>(
    ({ item, index }) => {
      const statusTone = getStatusTone(theme, item.status);
      return (
        <Pressable
          onPress={() =>
            navigation.navigate('OrderDetail', {
              orderId: item.id,
            })
          }
          style={[
            styles.orderCard,
            index === orders.length - 1 ? styles.orderCardLast : null,
          ]}
        >
          <View style={styles.thumb}>
            <Text style={styles.thumbText}>
              {item.restaurant.name.slice(0, 2).toUpperCase()}
            </Text>
          </View>
          <View style={styles.orderCopy}>
            <View style={styles.orderTitleRow}>
              <Text numberOfLines={1} style={styles.restaurantName}>
                {item.restaurant.name}
              </Text>
              <View
                style={[styles.statusPill, { backgroundColor: statusTone.bg }]}
              >
                <Text style={[styles.statusText, { color: statusTone.fg }]}>
                  {statusTone.label}
                </Text>
              </View>
            </View>
            <Text style={styles.orderMeta}>
              {formatDateTime(item.placed_at)}
            </Text>
            <View style={styles.orderFooter}>
              <Text style={styles.itemCount}>
                {item.items.length} item{item.items.length === 1 ? '' : 's'}
              </Text>
              <Text style={styles.totalAmount}>
                {formatCurrency(item.total_amount)}
              </Text>
            </View>
            {item.status === 'PAYMENT_PENDING' ? (
              <Pressable
                onPress={() =>
                  navigation.navigate('Payment', { retryOrderId: item.id })
                }
                style={styles.completePaymentButton}
              >
                <Icon
                  color={theme.colors.primary}
                  name="card-outline"
                  size={13}
                />
                <Text style={styles.completePaymentText}>
                  Payment pending — tap to complete
                </Text>
              </Pressable>
            ) : null}
          </View>
          <Icon color={theme.colors.hint} name="chevron-forward" size={18} />
        </Pressable>
      );
    },
    [navigation, orders.length, styles, theme],
  );
  useFocusEffect(
    useCallback(() => {
      void loadOrders('initial');
    }, [loadOrders]),
  );

  if (!token) {
    return (
      <SafeAreaView edges={['top']} style={styles.safeArea}>
        <View
          style={[
            styles.loggedOutWrap,
            { paddingBottom: Math.max(tabBarHeight + 12, 88) },
          ]}
        >
          <OrdersHero
            subtitle="Your placed orders and live delivery updates will show up here in one clean timeline."
            title="Track every meal in one place."
          />
          <FeedbackCard
            buttonLabel="Login"
            icon="person-circle-outline"
            onPress={() =>
              navigation.navigate('Login', {
                redirectTo: { screen: 'OrderList' },
              })
            }
            text="Login to see your past orders, live delivery progress, and reorder options."
            title="Your order history is waiting."
          />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <FlatList
        contentContainerStyle={[styles.content, { paddingBottom: 10 }]}
        data={orders}
        initialNumToRender={8}
        keyExtractor={item => item.id}
        ListEmptyComponent={
          loading ? (
            <View style={styles.skeletonWrap}>
              <SkeletonBlock height={84} />
              <SkeletonBlock height={84} />
              <SkeletonBlock height={84} />
            </View>
          ) : error ? (
            <FeedbackCard
              buttonLabel="Retry"
              icon="refresh-outline"
              onPress={() => void loadOrders('initial')}
              text={error}
              title="We couldn’t load your orders"
            />
          ) : (
            <FeedbackCard
              buttonLabel="Browse restaurants"
              icon="bag-handle-outline"
              onPress={() =>
                navigation.navigate('MainTabs', { screen: 'Home' })
              }
              text="Once you place an order, it will show up here with live status updates and bill details."
              title="No orders yet"
            />
          )
        }
        ListHeaderComponent={listHeader}
        refreshControl={
          <RefreshControl
            onRefresh={() => void loadOrders('refresh')}
            refreshing={refreshing}
            tintColor={theme.colors.primary}
          />
        }
        removeClippedSubviews
        renderItem={renderOrder}
        showsVerticalScrollIndicator={false}
        windowSize={8}
      />
    </SafeAreaView>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    loggedOutWrap: {
      flex: 1,
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 10,
      gap: 14,
    },
    content: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 10,
      gap: 10,
    },
    headerStack: {
      gap: 10,
      marginBottom: 10,
    },
    heroCard: {
      borderRadius: 24,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : theme.tone('#FFF4EC'),
      paddingHorizontal: 16,
      paddingVertical: 15,
      overflow: 'hidden',
      gap: 8,
    },
    heroGlowPrimary: {
      position: 'absolute',
      right: -20,
      top: -38,
      width: 150,
      height: 150,
      borderRadius: 75,
      backgroundColor: theme.primaryTint(0.10),
    },
    heroGlowSecondary: {
      position: 'absolute',
      left: -28,
      bottom: -48,
      width: 120,
      height: 120,
      borderRadius: 60,
      backgroundColor: theme.tone('rgba(255, 198, 168, 0.42)'),
    },
    heroBadge: {
      alignSelf: 'flex-start',
      minHeight: 28,
      borderRadius: 14,
      paddingHorizontal: 10,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : 'rgba(255,255,255,0.7)',
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : 'rgba(255,255,255,0.55)',
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    heroBadgeText: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '800',
    },
    heroTitle: {
      color: theme.colors.text,
      fontSize: 24,
      lineHeight: 30,
      fontWeight: '900',
      maxWidth: '86%',
    },
    heroSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 20,
      maxWidth: '94%',
    },
    summaryRow: {
      flexDirection: 'row',
      gap: 8,
    },
    summaryChip: {
      flex: 1,
      borderRadius: 16,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      paddingVertical: 10,
      paddingHorizontal: 11,
      gap: 2,
    },
    summaryValue: {
      color: theme.colors.text,
      fontSize: 17,
      fontWeight: '800',
    },
    summaryLabel: {
      color: theme.colors.secondaryText,
      fontSize: 11,
    },
    skeletonWrap: {
      gap: 8,
    },
    orderCard: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      borderRadius: 16,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      paddingHorizontal: 12,
      paddingVertical: 10,
    },
    orderCardLast: {
      marginBottom: 0,
    },
    thumb: {
      width: 42,
      height: 42,
      borderRadius: 12,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    thumbText: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '900',
    },
    orderCopy: {
      flex: 1,
      gap: 3,
    },
    orderTitleRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    restaurantName: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
    },
    statusPill: {
      borderRadius: 999,
      paddingHorizontal: 8,
      paddingVertical: 3,
    },
    statusText: {
      fontSize: 10,
      fontWeight: '800',
    },
    completePaymentButton: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 5,
      marginTop: 6,
      borderRadius: 10,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : theme.primaryTint(0.22),
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : theme.colors.primarySoft,
      paddingHorizontal: 8,
      paddingVertical: 5,
    },
    completePaymentText: {
      color: theme.colors.primary,
      fontSize: 10.5,
      fontWeight: '800',
    },
    orderMeta: {
      color: theme.colors.secondaryText,
      fontSize: 11,
    },
    orderFooter: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    itemCount: {
      color: theme.colors.hint,
      fontSize: 11,
    },
    totalAmount: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    feedbackCard: {
      borderRadius: 24,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 22,
      gap: 10,
    },
    feedbackIcon: {
      width: 44,
      height: 44,
      borderRadius: 22,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    feedbackTitle: {
      color: theme.colors.text,
      fontSize: 22,
      lineHeight: 28,
      fontWeight: '900',
    },
    feedbackText: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 22,
    },
    primaryButton: {
      marginTop: 4,
      alignSelf: 'flex-start',
      minHeight: 46,
      borderRadius: 23,
      paddingHorizontal: 22,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    primaryButtonText: {
      color: theme.colors.white,
      fontSize: 17,
      fontWeight: '800',
    },
  });
