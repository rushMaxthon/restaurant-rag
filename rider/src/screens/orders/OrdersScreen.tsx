import React, { useCallback, useMemo, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { OpenOrderCard } from '@components/OpenOrderCard';
import { ShiftCard } from '@components/home/ShiftCard';
import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { Screen } from '@components/ui/Screen';
import { useNav } from '@navigation/types';
import { useShiftToggle } from '@hooks/useShiftToggle';
import { useTakeOrder } from '@hooks/useTakeOrder';
import { useTour } from '@/guide/useTour';
import { useRider } from '@/store/RiderProvider';
import { useTheme } from '@theme/ThemeProvider';
import { motion, space } from '@theme/tokens';
import { rankOrders } from '@utils/homeOrders';

/**
 * The Orders board: every order waiting near the rider, any time - online
 * or not, mid-trip or not - including one they missed. Our riders get the
 * whole window before a courier is booked (backend `offers.open_orders`), and
 * this tab is how they use it. Looking is open to everyone; Take needs the
 * rider online and free, and the server checks that on every tap.
 */
export function OrdersScreen() {
  const { colors } = useTheme();
  const nav = useNav();
  const { trip, openOrders, refreshOpenOrders } = useRider();
  const shift = useShiftToggle();
  // The same order as Home's preview: the first card here is the first there.
  const ranked = useMemo(() => rankOrders(openOrders), [openOrders]);
  const { take, taking, error, blockedFor } = useTakeOrder();
  const [refreshing, setRefreshing] = useState(false);
  useTour('orders', openOrders.length > 0);

  // Fresh on every visit, not just on the next poll.
  useFocusEffect(
    useCallback(() => {
      void refreshOpenOrders();
    }, [refreshOpenOrders]),
  );

  return (
    <Screen
      scroll
      tabbed
      refreshing={refreshing}
      onRefresh={async () => {
        setRefreshing(true);
        await refreshOpenOrders();
        setRefreshing(false);
      }}
      contentStyle={styles.content}
    >
      <Animated.View
        entering={FadeInDown.duration(motion.base)}
        style={styles.header}
      >
        <AppText variant="title" style={styles.flex}>
          Orders
        </AppText>
        {openOrders.length > 0 ? (
          <AppText variant="label" tone="muted">
            {openOrders.length} waiting
          </AppText>
        ) : null}
      </Animated.View>

      {/* Where the rider stands: on a delivery, or the same shift strip as Home
          - an offline rider goes online right here, not via Home. */}
      {trip ? (
        <Card
          onPress={() => nav.navigate('Trip')}
          style={[styles.status, { borderColor: colors.primary }]}
        >
          <Icon name="bicycle" size={20} color={colors.primary} />
          <View style={styles.flex}>
            <AppText variant="bodyStrong">You're on a delivery</AppText>
            <AppText variant="caption" tone="muted">
              Finish it to take another
            </AppText>
          </View>
          <AppText variant="label" tone="primary">
            Continue
          </AppText>
          <Icon name="chevron-forward" size={16} color={colors.primary} />
        </Card>
      ) : (
        <ShiftCard
          strip
          guide={false}
          online={shift.online}
          onChange={shift.toggle}
          busy={shift.busy}
          disabledReason={shift.disabledReason}
          error={shift.error}
          offlineHint="Go online to take orders"
        />
      )}

      {error ? (
        <AppText variant="label" tone="danger">
          {error}
        </AppText>
      ) : null}

      {openOrders.length === 0 ? (
        <View style={styles.empty}>
          <View
            style={[styles.emptyIcon, { backgroundColor: colors.surfaceAlt }]}
          >
            <Icon name="receipt-outline" size={26} color={colors.textMuted} />
          </View>
          <AppText variant="bodyStrong" align="center">
            No orders waiting
          </AppText>
          <AppText variant="caption" tone="muted" align="center">
            New ones appear the moment a kitchen accepts. A missed order stays
            here until a courier is booked.
          </AppText>
        </View>
      ) : (
        ranked.map((order, index) => (
          <Animated.View
            key={order.order_id}
            entering={FadeInDown.delay(Math.min(index, 6) * 40).duration(
              motion.base,
            )}
          >
            <OpenOrderCard
              order={order}
              taking={taking === order.order_id}
              blockedReason={blockedFor(order)}
              onTake={() => void take(order)}
              guide={index === 0}
            />
          </Animated.View>
        ))
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { gap: space.md },
  header: { flexDirection: 'row', alignItems: 'baseline', gap: space.md },
  flex: { flex: 1 },
  status: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  empty: {
    alignItems: 'center',
    gap: space.xs,
    paddingTop: space.xl,
    paddingHorizontal: space.xl,
  },
  emptyIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.sm,
  },
});
