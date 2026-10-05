import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';
import type { KitchenOrder } from '@/types/app';
import { Icon } from '@components/Icon';
import { clockTime, customerName, isScheduled } from '@utils/board';

// Delivery or pickup, who it is for, and when it is booked — the line under
// an order code. No address and no phone number: a cook needs neither, and
// an address is somebody's home on a screen on a wall.
export const OrderMeta = ({
  order,
  branchName,
}: {
  order: KitchenOrder;
  branchName?: string | null;
}) => {
  const { colors } = useTheme();
  const isDelivery = order.fulfillment_type === 'DELIVERY';
  const who = customerName(order);
  return (
    <View style={styles.row}>
      <View style={styles.item}>
        <Icon
          name={isDelivery ? 'bicycle' : 'bag-handle-outline'}
          size={16}
          color={colors.textMuted}
        />
        <Text style={[styles.text, { color: colors.text }]}>
          {isDelivery ? 'Delivery' : 'Pickup'}
        </Text>
      </View>
      {who ? (
        <Text numberOfLines={1} style={[styles.text, styles.who, { color: colors.textMuted }]}>
          {who}
        </Text>
      ) : null}
      {isScheduled(order) ? (
        <View style={styles.item}>
          <Icon name="calendar-outline" size={15} color={colors.warning} />
          <Text style={[styles.text, styles.scheduled, { color: colors.warning }]}>
            {clockTime(order.scheduled_at)}
          </Text>
        </View>
      ) : null}
      {branchName ? (
        <View style={styles.item}>
          <Icon name="location-outline" size={15} color={colors.textMuted} />
          <Text style={[styles.text, { color: colors.textMuted }]}>{branchName}</Text>
        </View>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', columnGap: 12, rowGap: 4 },
  item: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  text: { fontSize: 14, fontWeight: '600' },
  who: { flexShrink: 1, maxWidth: '60%' },
  scheduled: { fontWeight: '800' },
});
