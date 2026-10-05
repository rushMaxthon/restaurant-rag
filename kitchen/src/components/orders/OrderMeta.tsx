import React, { memo } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';
import type { KitchenOrder } from '@/types/app';
import { Icon } from '@components/Icon';
import { clockTime, customerName, isScheduled } from '@utils/board';

// Delivery or pickup, who it is for, when it is booked and — on a board that
// spans branches — where. No address and no phone number: a cook needs
// neither, and an address is somebody's home on a screen on a wall.
const OrderMetaComponent = ({
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
      <View style={[styles.type, { backgroundColor: colors.surfaceMuted }]}>
        <Icon name={isDelivery ? 'bicycle' : 'bag-handle-outline'} size={14} color={colors.text} />
        <Text style={[styles.typeText, { color: colors.text }]}>
          {isDelivery ? 'Delivery' : 'Pickup'}
        </Text>
      </View>
      {who ? (
        <View style={styles.item}>
          <Icon name="person-outline" size={14} color={colors.textMuted} />
          <Text numberOfLines={1} style={[styles.text, styles.who, { color: colors.text }]}>
            {who}
          </Text>
        </View>
      ) : null}
      {isScheduled(order) ? (
        <View style={[styles.type, { backgroundColor: colors.warningSoft }]}>
          <Icon name="calendar-outline" size={14} color={colors.warning} />
          <Text style={[styles.typeText, { color: colors.warning }]}>
            {clockTime(order.scheduled_at)}
          </Text>
        </View>
      ) : null}
      {branchName ? (
        <View style={styles.item}>
          <Icon name="location-outline" size={14} color={colors.textMuted} />
          <Text numberOfLines={1} style={[styles.text, { color: colors.textMuted }]}>
            {branchName}
          </Text>
        </View>
      ) : null}
    </View>
  );
};

export const OrderMeta = memo(OrderMetaComponent);

const styles = StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', columnGap: 10, rowGap: 6 },
  type: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    borderRadius: 8,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  typeText: { fontSize: 13, fontWeight: '800' },
  item: { flexDirection: 'row', alignItems: 'center', gap: 4, flexShrink: 1 },
  text: { fontSize: 14, fontWeight: '600' },
  who: { flexShrink: 1 },
});
