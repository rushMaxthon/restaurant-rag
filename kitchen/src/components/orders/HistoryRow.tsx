import React, { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { radius, space, useTheme } from '@/theme';
import type { KitchenOrder } from '@/types/app';
import { Icon } from '@components/Icon';
import { OrderMeta } from '@components/orders/OrderMeta';
import { itemCount, orderCode } from '@utils/board';
import { completedLabel } from '@utils/history';

interface HistoryRowProps {
  order: KitchenOrder;
  now: Date;
  branchName: string | null;
  onOpen: (order: KitchenOrder) => void;
}

// One finished order in the completed list. Memoised: a poll that brings
// back the same orders reuses them (utils/reconcile), so an idle list
// re-renders no rows at all.
const HistoryRowComponent = ({ order, now, branchName, onOpen }: HistoryRowProps) => {
  const theme = useTheme();
  const { colors } = theme;
  const isDelivery = order.fulfillment_type === 'DELIVERY';
  const done = theme.status.DELIVERED;
  return (
    <Pressable
      testID={`history-row-${order.id}`}
      onPress={() => onOpen(order)}
      accessibilityRole="button"
      accessibilityLabel={`${orderCode(order)}, completed ${completedLabel(order.completed_at, now)}, ${itemCount(order.items)}`}
      style={({ pressed }) => [
        styles.row,
        { backgroundColor: colors.surface, borderColor: colors.border },
        pressed && styles.pressed,
      ]}>
      <View style={[styles.tile, { backgroundColor: colors.accentSoft }]}>
        <Icon name={isDelivery ? 'bicycle' : 'bag-handle-outline'} size={22} color={done} />
      </View>
      <View style={styles.main}>
        <View style={styles.top}>
          <Text style={[styles.code, { color: colors.text }]}>{orderCode(order)}</Text>
          <View style={styles.time}>
            <Icon name="checkmark-done" size={14} color={colors.accent} />
            <Text style={[styles.timeText, { color: colors.textMuted }]}>
              {completedLabel(order.completed_at, now)}
            </Text>
          </View>
        </View>
        <OrderMeta order={order} branchName={branchName} />
      </View>
      <View style={[styles.count, { backgroundColor: colors.surfaceMuted }]}>
        <Text style={[styles.countText, { color: colors.text }]}>{itemCount(order.items)}</Text>
      </View>
      <Icon name="chevron-forward" size={20} color={colors.textMuted} />
    </Pressable>
  );
};

export const HistoryRow = memo(HistoryRowComponent);

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    borderWidth: 1,
    borderRadius: radius.lg,
    paddingHorizontal: space.lg,
    paddingVertical: 14,
    minHeight: 84,
  },
  pressed: { opacity: 0.7 },
  tile: { width: 46, height: 46, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  main: { flex: 1, gap: 6, minWidth: 0 },
  top: { flexDirection: 'row', alignItems: 'center', gap: 10, flexWrap: 'wrap' },
  code: { fontSize: 18, fontWeight: '900', letterSpacing: 0.4, fontVariant: ['tabular-nums'] },
  time: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  timeText: { fontSize: 13, fontWeight: '700' },
  count: { borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 4 },
  countText: { fontSize: 13, fontWeight: '800' },
});
