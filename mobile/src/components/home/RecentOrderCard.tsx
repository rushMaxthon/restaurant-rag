import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { formatCurrency } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { Order } from '@/types/app';

interface RecentOrderCardProps {
  order: Order;
  /** Receives the order, so a list can share one stable handler. */
  onPress: (order: Order) => void;
}

function RecentOrderCardComponent({
  order,
  onPress,
}: RecentOrderCardProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const handlePress = React.useCallback(() => onPress(order), [onPress, order]);
  const leadItem = order.items[0];
  const extraItems = Math.max(order.items.length - 1, 0);

  return (
    <Pressable
      onPress={handlePress}
      style={({ pressed }) => [
        styles.card,
        pressed ? styles.cardPressed : null,
      ]}
    >
      <View style={styles.iconWrap}>
        <Icon color={theme.colors.primary} name="bag-handle" size={16} />
      </View>
      <View style={styles.body}>
        <Text numberOfLines={1} style={styles.title}>
          {order.restaurant.name}
        </Text>
        <Text numberOfLines={1} style={styles.subtitle}>
          {leadItem
            ? `${leadItem.item_name_snapshot}${
                extraItems > 0 ? ` + ${extraItems} more` : ''
              }`
            : 'Recent order'}
        </Text>
        <View style={styles.metaRow}>
          <Text style={styles.meta}>{order.status.replaceAll('_', ' ')}</Text>
          <Text style={styles.dot}>•</Text>
          <Text style={styles.meta}>{formatCurrency(order.total_amount)}</Text>
        </View>
      </View>
      <Icon color={theme.colors.hint} name="chevron-forward" size={18} />
    </Pressable>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    card: {
      borderRadius: 16,
      backgroundColor: theme.colors.surfaceRaised,
      paddingHorizontal: 14,
      paddingVertical: 12,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      borderWidth: 1,
      borderColor: theme.colors.border,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.05,
      shadowOffset: { width: 0, height: 6 },
      shadowRadius: 12,
      elevation: 2,
    },
    cardPressed: {
      opacity: 0.95,
    },
    iconWrap: {
      width: 38,
      height: 38,
      borderRadius: 19,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    body: {
      flex: 1,
      gap: 3,
    },
    title: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
    },
    subtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
    },
    metaRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 5,
    },
    meta: {
      color: theme.colors.text,
      fontSize: 11,
      fontWeight: '700',
    },
    dot: {
      color: theme.colors.hint,
      fontSize: 11,
    },
  });


/**
 * Memoized: these cards sit in lists whose parent re-renders on unrelated
 * state changes, and none of them depend on anything but their props.
 */
export const RecentOrderCard = React.memo(RecentOrderCardComponent);
