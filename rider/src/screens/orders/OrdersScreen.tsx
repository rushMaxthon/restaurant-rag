import React, { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { OpenOrderCard } from '@components/OpenOrderCard';
import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { Screen } from '@components/ui/Screen';
import { useNav } from '@navigation/types';
import { useTakeOrder } from '@hooks/useTakeOrder';
import { useTour } from '@/guide/useTour';
import { useRider } from '@/store/RiderProvider';
import { useTheme } from '@theme/ThemeProvider';
import { motion, space } from '@theme/tokens';

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
  const { me, trip, openOrders, refreshOpenOrders } = useRider();
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
      <Animated.View entering={FadeInDown.duration(motion.base)}>
        <AppText variant="title">Orders</AppText>
        <AppText tone="muted">Every order waiting near you</AppText>
      </Animated.View>

      {trip ? (
        <Card onPress={() => nav.navigate('Trip')} style={styles.status}>
          <Icon name="bicycle" size={22} color={colors.primary} />
          <View style={styles.flex}>
            <AppText variant="bodyStrong">You are on a delivery</AppText>
            <AppText variant="caption" tone="muted">
              Finish it to take another. Tap to continue.
            </AppText>
          </View>
          <Icon name="chevron-forward" size={18} color={colors.textFaint} />
        </Card>
      ) : me?.status !== 'ONLINE' ? (
        <Card
          onPress={() => nav.navigate('Main', { screen: 'Home' })}
          style={styles.status}
        >
          <Icon name="moon" size={22} color={colors.textMuted} />
          <View style={styles.flex}>
            <AppText variant="bodyStrong">You are offline</AppText>
            <AppText variant="caption" tone="muted">
              Go online on Home to take these.
            </AppText>
          </View>
          <Icon name="chevron-forward" size={18} color={colors.textFaint} />
        </Card>
      ) : null}

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
            <Icon name="receipt-outline" size={34} color={colors.textMuted} />
          </View>
          <AppText variant="heading" align="center">
            No orders waiting
          </AppText>
          <AppText tone="muted" align="center">
            New ones appear here the moment a kitchen accepts. Missed an order?
            It stays here until a courier is booked.
          </AppText>
        </View>
      ) : (
        openOrders.map((order, index) => (
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
  content: { gap: space.lg },
  flex: { flex: 1 },
  status: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  empty: {
    alignItems: 'center',
    gap: space.sm,
    paddingTop: space.xxl,
    paddingHorizontal: space.lg,
  },
  emptyIcon: {
    width: 80,
    height: 80,
    borderRadius: 40,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.sm,
  },
});
