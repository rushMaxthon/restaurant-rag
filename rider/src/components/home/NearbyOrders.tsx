import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import Animated, {
  FadeInDown,
  LinearTransition,
} from 'react-native-reanimated';

import { OpenOrderCard } from '@components/OpenOrderCard';
import { AppText } from '@components/ui/AppText';
import { Icon } from '@components/ui/Icon';
import { useTakeOrder } from '@hooks/useTakeOrder';
import { useRider } from '@/store/RiderProvider';
import { useTheme } from '@theme/ThemeProvider';
import { motion, space } from '@theme/tokens';
import { homePreview } from '@utils/homeOrders';

/**
 * The orders waiting nearby, on Home, with Take on each - the thing an
 * online rider between deliveries is actually looking for. The nearest few
 * (`homePreview`); the whole board is one tap away on the Orders tab.
 * While nothing is waiting it says so in one line rather than leaving a gap.
 */
export function NearbyOrders({ onSeeAll }: { onSeeAll: () => void }) {
  const { colors } = useTheme();
  const { openOrders } = useRider();
  const { take, taking, error, blockedFor } = useTakeOrder();
  const { shown, more } = homePreview(openOrders);

  return (
    <View style={styles.wrap}>
      <View style={styles.head}>
        <AppText variant="label" tone="muted" style={styles.flex}>
          {shown.length > 0
            ? `WAITING NEAR YOU · ${openOrders.length}`
            : 'WAITING NEAR YOU'}
        </AppText>
        {openOrders.length > 0 ? (
          <Pressable
            onPress={onSeeAll}
            hitSlop={12}
            accessibilityRole="link"
            style={styles.link}
          >
            <AppText variant="label" tone="primary">
              {more > 0 ? `See all ${openOrders.length}` : 'Orders tab'}
            </AppText>
            <Icon name="chevron-forward" size={16} color={colors.primary} />
          </Pressable>
        ) : null}
      </View>

      {shown.length === 0 ? (
        <AppText variant="caption" tone="muted">
          No orders waiting right now. A new one rings the moment it's yours.
        </AppText>
      ) : (
        shown.map((order, i) => (
          <Animated.View
            key={order.order_id}
            entering={FadeInDown.delay(i * 40).duration(motion.base)}
            layout={LinearTransition}
          >
            <OpenOrderCard
              order={order}
              taking={taking === order.order_id}
              blockedReason={blockedFor(order)}
              onTake={() => void take(order)}
            />
          </Animated.View>
        ))
      )}

      {error ? (
        <AppText variant="label" tone="danger">
          {error}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: space.md },
  flex: { flex: 1 },
  head: { flexDirection: 'row', alignItems: 'center', minHeight: 24 },
  link: { flexDirection: 'row', alignItems: 'center', gap: 2 },
});
