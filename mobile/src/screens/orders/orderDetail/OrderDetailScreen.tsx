import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  LayoutAnimation,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  UIManager,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import { OrderStepper } from '@components/OrderStepper';
import { SkeletonBlock } from '@components/SkeletonBlock';
import { useAppActions, useSession } from '@hooks/useAppStore';
import { api, formatCurrency, formatDateTime } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { RootStackParamList } from '@/navigation/AppNavigator';
import type { Order } from '@/types/app';

function getStatusTone(theme: AppTheme, status: Order['status']) {
  if (status === 'PAYMENT_PENDING') {
    return {
      bg: theme.colors.primarySoft,
      fg: theme.colors.primary,
      title: 'Waiting for payment',
      subtitle:
        'This order is saved but not paid yet. The kitchen starts once the payment is confirmed.',
      icon: 'card-outline',
    };
  }

  if (status === 'CANCELLED') {
    return {
      bg: theme.colors.card,
      fg: theme.colors.hint,
      title: 'Order cancelled',
      subtitle: 'This order was cancelled and will not be prepared.',
      icon: 'close-circle-outline',
    };
  }

  if (status === 'DELIVERED') {
    return {
      bg: theme.colors.successSoft,
      fg: theme.colors.success,
      title: 'Delivered successfully',
      subtitle:
        'Your order has reached you. You can rate it or reorder anytime.',
      icon: 'checkmark-circle',
    };
  }

  if (status === 'OUT_FOR_DELIVERY') {
    return {
      bg: theme.colors.warningSoft,
      fg: theme.colors.warning,
      title: 'Out for delivery',
      subtitle: 'Your rider is on the way with your order.',
      icon: 'bicycle-outline',
    };
  }

  if (status === 'PREPARING') {
    return {
      bg: theme.colors.warningSoft,
      fg: theme.colors.warning,
      title: 'Kitchen is preparing your order',
      subtitle: 'Your food is being cooked and packed right now.',
      icon: 'restaurant-outline',
    };
  }

  if (status === 'ACCEPTED') {
    return {
      bg: theme.colors.primarySoft,
      fg: theme.colors.primary,
      title: 'Restaurant accepted your order',
      subtitle: 'The kitchen has received your request and will start shortly.',
      icon: 'checkmark-done-outline',
    };
  }

  return {
    bg: theme.colors.card,
    fg: theme.colors.secondaryText,
    title: 'Order placed',
    subtitle:
      'Your order has been received and is waiting for restaurant confirmation.',
    icon: 'bag-handle-outline',
  };
}

function DetailSection({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  const styles = useThemedStyles(createStyles);
  return (
    <View style={styles.sectionCard}>
      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>{title}</Text>
        {subtitle ? (
          <Text style={styles.sectionSubtitle}>{subtitle}</Text>
        ) : null}
      </View>
      {children}
    </View>
  );
}

export function OrderDetailScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation =
    useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const route = useRoute();
  const { orderId } = route.params as RootStackParamList['OrderDetail'];
  const { token } = useSession();
  const { pushToast } = useAppActions();
  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(Boolean(token));
  const [error, setError] = useState<string | null>(null);
  const [trackingExpanded, setTrackingExpanded] = useState(false);

  useEffect(() => {
    if (
      Platform.OS === 'android' &&
      UIManager.setLayoutAnimationEnabledExperimental
    ) {
      UIManager.setLayoutAnimationEnabledExperimental(true);
    }
  }, []);

  const loadOrder = useCallback(async () => {
    if (!token) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await api.getOrder(token, orderId);
      setOrder(response);
    } catch (nextError) {
      const message =
        nextError instanceof Error
          ? nextError.message
          : 'Unable to load this order right now.';
      setError(message);
      pushToast('Order unavailable', message, 'error');
    } finally {
      setLoading(false);
    }
  }, [orderId, pushToast, token]);

  useEffect(() => {
    void loadOrder();
  }, [loadOrder]);

  const shortId = useMemo(
    () => `#${orderId.replaceAll('-', '').slice(-8).toUpperCase()}`,
    [orderId],
  );

  if (!token) {
    return (
      <SafeAreaView edges={['bottom']} style={styles.safeArea}>
        <View style={styles.feedbackCard}>
          <Text style={styles.feedbackTitle}>Login to view this order</Text>
          <Text style={styles.feedbackText}>
            Order details, tracking, and bill breakdown are available after
            login.
          </Text>
          <Pressable
            onPress={() =>
              navigation.navigate('Login', {
                redirectTo: { screen: 'OrderList' },
              })
            }
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonText}>Login</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  if (loading) {
    return (
      <SafeAreaView edges={['bottom']} style={styles.safeArea}>
        <ScrollView
          contentContainerStyle={styles.content}
          showsVerticalScrollIndicator={false}
        >
          <SkeletonBlock height={152} />
          <SkeletonBlock height={224} />
          <SkeletonBlock height={118} />
          <SkeletonBlock height={180} />
          <SkeletonBlock height={144} />
        </ScrollView>
      </SafeAreaView>
    );
  }

  if (error || !order) {
    return (
      <SafeAreaView edges={['bottom']} style={styles.safeArea}>
        <View style={styles.feedbackCard}>
          <Text style={styles.feedbackTitle}>We couldn’t load this order</Text>
          <Text style={styles.feedbackText}>
            {error ?? 'The order may no longer be available.'}
          </Text>
          <Pressable
            onPress={() => void loadOrder()}
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonText}>Retry</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  const statusTone = getStatusTone(theme, order.status);
  const canRate = order.status === 'DELIVERED';
  const collapsedTrackingLabel = order.status.replaceAll('_', ' ');

  const toggleTrackingExpanded = () => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setTrackingExpanded(current => !current);
  };

  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.heroCard}>
          <View style={styles.heroGlowPrimary} />
          <View style={styles.heroGlowSecondary} />

          <View style={styles.heroTopRow}>
            <View style={styles.orderMetaBlock}>
              <Text style={styles.orderCode}>{shortId}</Text>
              <Text style={styles.orderDate}>
                {formatDateTime(order.placed_at)}
              </Text>
            </View>
            <View
              style={[
                styles.heroStatusPill,
                { backgroundColor: statusTone.bg },
              ]}
            >
              <Text style={[styles.heroStatusText, { color: statusTone.fg }]}>
                {order.status.replaceAll('_', ' ')}
              </Text>
            </View>
          </View>

          <View style={styles.heroBodyRow}>
            <View
              style={[
                styles.heroStatusIcon,
                { backgroundColor: theme.colors.surfaceRaised },
              ]}
            >
              <Icon color={statusTone.fg} name={statusTone.icon} size={22} />
            </View>
            <View style={styles.heroCopy}>
              <Text style={styles.heroTitle}>{statusTone.title}</Text>
              <Text style={styles.heroSubtitle}>{statusTone.subtitle}</Text>
            </View>
          </View>

          {order.status === 'PAYMENT_PENDING' ? (
            <Pressable
              onPress={() =>
                navigation.navigate('Payment', { retryOrderId: order.id })
              }
              style={styles.completePaymentButton}
            >
              <Icon color={theme.colors.white} name="card-outline" size={15} />
              <Text style={styles.completePaymentText}>Complete payment</Text>
            </Pressable>
          ) : null}
        </View>

        <View style={styles.sectionCard}>
          <Pressable
            onPress={toggleTrackingExpanded}
            style={styles.accordionHeader}
          >
            <View style={styles.accordionCopy}>
              <Text style={styles.sectionTitle}>Order tracking</Text>
              <Text style={styles.accordionStatusText}>
                Order Tracking • {collapsedTrackingLabel}
              </Text>
            </View>
            <View style={styles.accordionIconWrap}>
              <Icon
                color={theme.colors.text}
                name={trackingExpanded ? 'chevron-up' : 'chevron-down'}
                size={18}
              />
            </View>
          </Pressable>

          {trackingExpanded ? (
            <View style={styles.accordionBody}>
              <Text style={styles.sectionSubtitle}>
                Live progress across the full delivery lifecycle.
              </Text>
              <OrderStepper status={order.status} />
              {!canRate ? (
                <View style={styles.activeStatusCard}>
                  <Icon
                    color={theme.colors.primary}
                    name="time-outline"
                    size={18}
                  />
                  <Text style={styles.activeStatusText}>
                    Current status: {collapsedTrackingLabel}.
                  </Text>
                </View>
              ) : null}
            </View>
          ) : null}
        </View>

        <DetailSection
          subtitle="Restaurant details linked to this order."
          title="Restaurant info"
        >
          <View style={styles.infoRow}>
            <View style={styles.infoAvatar}>
              <Text style={styles.infoAvatarText}>
                {order.restaurant.name.slice(0, 2).toUpperCase()}
              </Text>
            </View>
            <View style={styles.infoCopy}>
              <Text style={styles.infoTitle}>{order.restaurant.name}</Text>
              <Text style={styles.infoSubtitle}>
                {order.restaurant.cuisine_type}
              </Text>
              <Text style={styles.infoSubtitle}>
                {order.restaurant.address_line_1}
              </Text>
              <Text style={styles.infoSubtitle}>{order.restaurant.city}</Text>
            </View>
          </View>
        </DetailSection>

        <DetailSection
          subtitle="Delivery destination saved with this checkout."
          title="Delivery details"
        >
          <View style={styles.deliveryRow}>
            <View style={styles.deliveryIcon}>
              <Icon
                color={theme.colors.primary}
                name="location-outline"
                size={18}
              />
            </View>
            <View style={styles.deliveryCopy}>
              <Text style={styles.deliveryTitle}>Delivering to</Text>
              <Text style={styles.deliveryText}>{order.delivery_address}</Text>
            </View>
          </View>
        </DetailSection>

        <DetailSection
          subtitle={`${order.items.length} item${
            order.items.length === 1 ? '' : 's'
          } in this order.`}
          title="Ordered items"
        >
          <View style={styles.itemsList}>
            {order.items.map((item, index) => (
              <View
                key={item.id}
                style={[
                  styles.itemRow,
                  index === order.items.length - 1 ? styles.itemRowLast : null,
                ]}
              >
                <View style={styles.itemQuantityBubble}>
                  <Text style={styles.itemQuantityText}>{item.quantity}x</Text>
                </View>
                <View style={styles.itemCopy}>
                  <Text style={styles.itemName}>{item.item_name_snapshot}</Text>
                  <Text style={styles.itemMeta}>
                    {formatCurrency(item.unit_price)} each
                  </Text>
                </View>
                <Text style={styles.itemTotal}>
                  {formatCurrency(item.total_price)}
                </Text>
              </View>
            ))}
          </View>
        </DetailSection>

        <DetailSection
          subtitle="A compact bill breakdown for this checkout."
          title="Bill summary"
        >
          <View style={styles.summaryRow}>
            <Text style={styles.summaryLabel}>Items total</Text>
            <Text style={styles.summaryValue}>
              {formatCurrency(order.subtotal)}
            </Text>
          </View>
          <View style={styles.summaryRow}>
            <Text style={styles.summaryLabel}>Delivery charge</Text>
            <Text style={styles.summaryValue}>
              {formatCurrency(order.delivery_fee)}
            </Text>
          </View>
          <View style={styles.summaryRow}>
            <Text style={styles.summaryLabel}>Taxes and fees</Text>
            <Text style={styles.summaryValue}>
              {formatCurrency(order.tax_amount)}
            </Text>
          </View>
          {Number(order.discount_amount) > 0 ? (
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Discount</Text>
              <Text style={[styles.summaryValue, styles.discountValue]}>
                -{formatCurrency(order.discount_amount)}
              </Text>
            </View>
          ) : null}
          <View style={styles.summaryDivider} />
          <View style={styles.totalCard}>
            <Text style={styles.totalEyebrow}>Grand total</Text>
            <Text style={styles.totalValue}>
              {formatCurrency(order.total_amount)}
            </Text>
          </View>
        </DetailSection>

        <DetailSection
          subtitle={
            canRate
              ? 'Share feedback or place the same order again.'
              : 'You can keep an eye on this order or browse the restaurant again.'
          }
          title={canRate ? 'Actions' : 'Current status'}
        >
          {canRate ? (
            <View style={styles.actionsRow}>
              <Pressable
                onPress={() =>
                  navigation.navigate('Restaurant', {
                    restaurantId: order.restaurant_id,
                    restaurantName: order.restaurant.name,
                  })
                }
                style={styles.secondaryButton}
              >
                <Text style={styles.secondaryButtonText}>Reorder</Text>
              </Pressable>
              <Pressable
                onPress={() =>
                  pushToast(
                    'Reorder',
                    'Quick reorder shortcuts can be added here next if you want that flow.',
                    'info',
                  )
                }
                style={styles.primaryButton}
              >
                <Text style={styles.primaryButtonText}>Reorder help</Text>
              </Pressable>
            </View>
          ) : (
            <View style={styles.statusInfoRow}>
              <View style={styles.statusInfoIcon}>
                <Icon
                  color={theme.colors.warning}
                  name="sparkles-outline"
                  size={18}
                />
              </View>
              <View style={styles.statusInfoCopy}>
                <Text style={styles.statusInfoTitle}>{statusTone.title}</Text>
                <Text style={styles.statusInfoText}>{statusTone.subtitle}</Text>
              </View>
            </View>
          )}
        </DetailSection>
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
      paddingTop: theme.spacing.stackTop,
      gap: 12,
    },
    heroCard: {
      borderRadius: 24,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceRaised : theme.tone('#FFF4EC'),
      paddingHorizontal: 18,
      paddingVertical: 18,
      gap: 14,
      overflow: 'hidden',
      position: 'relative',
      borderWidth: 1,
      borderColor: theme.colors.border,
      shadowColor: theme.colors.shadow,
      shadowOpacity: theme.mode === 'dark' ? 0.16 : 0.08,
      shadowOffset: { width: 0, height: 10 },
      shadowRadius: 20,
      elevation: 4,
    },
    heroGlowPrimary: {
      position: 'absolute',
      right: -30,
      top: -40,
      width: 170,
      height: 170,
      borderRadius: 85,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.primaryTint(0.08)
          : theme.primaryTint(0.10),
    },
    heroGlowSecondary: {
      position: 'absolute',
      left: -24,
      bottom: -44,
      width: 128,
      height: 128,
      borderRadius: 64,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.primaryTint(0.06)
          : theme.tone('rgba(255, 189, 153, 0.32)'),
    },
    heroTopRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      gap: 12,
    },
    orderMetaBlock: {
      gap: 4,
    },
    orderCode: {
      color: theme.colors.primary,
      fontSize: 13,
      fontWeight: '900',
      letterSpacing: 0.3,
    },
    orderDate: {
      color: theme.colors.secondaryText,
      fontSize: 12,
    },
    heroStatusPill: {
      borderRadius: 999,
      paddingHorizontal: 10,
      paddingVertical: 6,
      borderWidth: 1,
      borderColor: theme.mode === 'dark' ? theme.colors.border : 'transparent',
    },
    heroStatusText: {
      fontSize: 11,
      fontWeight: '900',
      textTransform: 'uppercase',
    },
    heroBodyRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 12,
    },
    heroStatusIcon: {
      width: 44,
      height: 44,
      borderRadius: 22,
      alignItems: 'center',
      justifyContent: 'center',
    },
    heroCopy: {
      flex: 1,
      gap: 4,
    },
    completePaymentButton: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 7,
      marginTop: 12,
      minHeight: 44,
      borderRadius: 14,
      backgroundColor: theme.colors.primary,
    },
    completePaymentText: {
      color: theme.colors.white,
      fontSize: 14,
      fontWeight: '800',
    },
    heroTitle: {
      color: theme.colors.text,
      fontSize: 22,
      lineHeight: 28,
      fontWeight: '900',
    },
    heroSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 20,
    },
    sectionCard: {
      borderRadius: 20,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 16,
      gap: 12,
      shadowColor: theme.colors.shadow,
      shadowOpacity: theme.mode === 'dark' ? 0.14 : 0.05,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 3,
    },
    accordionHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
    },
    accordionCopy: {
      flex: 1,
      gap: 3,
    },
    accordionStatusText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    accordionIconWrap: {
      width: 32,
      height: 32,
      borderRadius: 16,
      backgroundColor: theme.colors.surfaceAlt,
      alignItems: 'center',
      justifyContent: 'center',
    },
    accordionBody: {
      gap: 12,
    },
    sectionHeader: {
      gap: 3,
    },
    sectionTitle: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
    },
    sectionSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    activeStatusCard: {
      marginTop: 2,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      borderRadius: 14,
      backgroundColor: theme.colors.primarySoft,
      paddingHorizontal: 12,
      paddingVertical: 10,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.chipBorder : 'transparent',
    },
    activeStatusText: {
      flex: 1,
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '700',
    },
    infoRow: {
      flexDirection: 'row',
      gap: 12,
      alignItems: 'flex-start',
    },
    infoAvatar: {
      width: 48,
      height: 48,
      borderRadius: 16,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.chipBorder : 'transparent',
    },
    infoAvatarText: {
      color: theme.colors.primary,
      fontSize: 14,
      fontWeight: '900',
    },
    infoCopy: {
      flex: 1,
      gap: 3,
    },
    infoTitle: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    infoSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    deliveryRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 10,
    },
    deliveryIcon: {
      width: 38,
      height: 38,
      borderRadius: 14,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.chipBorder : 'transparent',
    },
    deliveryCopy: {
      flex: 1,
      gap: 3,
    },
    deliveryTitle: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    deliveryText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    itemsList: {
      gap: 0,
    },
    itemRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10,
      paddingVertical: 10,
      borderBottomWidth: 1,
      borderBottomColor: theme.colors.divider,
    },
    itemRowLast: {
      paddingBottom: 0,
      borderBottomWidth: 0,
    },
    itemQuantityBubble: {
      minWidth: 34,
      height: 34,
      paddingHorizontal: 8,
      borderRadius: 17,
      backgroundColor: theme.colors.surfaceAlt,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    itemQuantityText: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '900',
    },
    itemCopy: {
      flex: 1,
      gap: 2,
    },
    itemName: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '700',
    },
    itemMeta: {
      color: theme.colors.secondaryText,
      fontSize: 12,
    },
    itemTotal: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    summaryRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      gap: 12,
    },
    summaryLabel: {
      color: theme.colors.secondaryText,
      fontSize: 13,
    },
    summaryValue: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '700',
    },
    discountValue: {
      color: theme.colors.success,
    },
    summaryDivider: {
      height: 1,
      backgroundColor: theme.colors.divider,
      marginTop: 2,
      marginBottom: 2,
    },
    totalCard: {
      borderRadius: 16,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : theme.colors.surfaceAlt,
      paddingHorizontal: 14,
      paddingVertical: 14,
      gap: 4,
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    totalEyebrow: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      fontWeight: '700',
    },
    totalValue: {
      color: theme.colors.text,
      fontSize: 22,
      fontWeight: '900',
    },
    actionsRow: {
      flexDirection: 'row',
      gap: 10,
    },
    statusInfoRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 10,
      borderRadius: 16,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : theme.colors.surfaceAlt,
      paddingHorizontal: 12,
      paddingVertical: 12,
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    statusInfoIcon: {
      width: 36,
      height: 36,
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceRaised,
      alignItems: 'center',
      justifyContent: 'center',
    },
    statusInfoCopy: {
      flex: 1,
      gap: 3,
    },
    statusInfoTitle: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    statusInfoText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    primaryButton: {
      flex: 1,
      minHeight: 48,
      borderRadius: 15,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      paddingHorizontal: 16,
    },
    primaryButtonText: {
      color: theme.colors.white,
      fontSize: 13,
      fontWeight: '800',
    },
    secondaryButton: {
      flex: 1,
      minHeight: 48,
      borderRadius: 15,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      alignItems: 'center',
      justifyContent: 'center',
      paddingHorizontal: 16,
    },
    secondaryButtonText: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    feedbackCard: {
      margin: theme.spacing.screen,
      borderRadius: 22,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : theme.colors.surfaceRaised,
      padding: 18,
      gap: 8,
      alignItems: 'flex-start',
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    feedbackTitle: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
    },
    feedbackText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 20,
    },
  });
