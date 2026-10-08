import React, { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { Pill } from '@components/ui/Pill';
import { useNav } from '@navigation/types';
import { ApiError } from '@/services/http';
import { useRider } from '@/store/RiderProvider';
import { useApi } from '@/store/SessionProvider';
import type { OpenOrder } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space } from '@theme/tokens';
import { distance, km, rupees } from '@utils/format';
import { haptic } from '@utils/haptics';
import { claimErrorMessage, minutesLeftLabel } from '@utils/openOrders';

/** Often enough that a list a few seconds old rarely offers food someone took. */
const POLL_MS = 8000;

/**
 * Orders nearby that nobody has taken yet - including one whose offer this
 * rider missed. Our riders get the whole window before a courier is booked
 * (backend `offers.open_orders`), and this list is how they use it.
 * First come, first served: the server decides, and a loser is told plainly.
 */
export function OpenOrders() {
  const { colors } = useTheme();
  const api = useApi();
  const nav = useNav();
  const { me, trip, setTrip, refreshMe } = useRider();
  const [orders, setOrders] = useState<OpenOrder[]>([]);
  const [taking, setTaking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const free = me?.status === 'ONLINE' && !trip;

  const load = useCallback(async () => {
    try {
      setOrders(await api.openOrders());
    } catch {
      // the next poll tries again
    }
  }, [api]);

  useFocusEffect(
    useCallback(() => {
      if (!free) {
        setOrders([]);
        return undefined;
      }
      void load();
      const id = setInterval(load, POLL_MS);
      return () => clearInterval(id);
    }, [free, load]),
  );

  const take = async (order: OpenOrder) => {
    setTaking(order.order_id);
    setError(null);
    try {
      const started = await api.claim(order.order_id);
      haptic('success');
      setTrip(started);
      void refreshMe();
      nav.navigate('Trip');
    } catch (e) {
      haptic('error');
      setError(
        claimErrorMessage(
          e instanceof ApiError && typeof e.detail === 'string'
            ? e.detail
            : undefined,
        ),
      );
      void load();
    } finally {
      setTaking(null);
    }
  };

  if (!free || orders.length === 0) return null;

  return (
    <Animated.View
      entering={FadeInDown.duration(motion.base)}
      style={styles.wrap}
    >
      <View style={styles.head}>
        <View style={[styles.badge, { backgroundColor: colors.primarySoft }]}>
          <Icon name="flash" size={16} color={colors.primary} />
        </View>
        <View style={styles.flex}>
          <AppText variant="bodyStrong">Open orders · {orders.length}</AppText>
          <AppText variant="caption" tone="muted">
            Take one before it goes to a courier
          </AppText>
        </View>
      </View>

      {error ? (
        <AppText variant="label" tone="danger">
          {error}
        </AppText>
      ) : null}

      {orders.map(order => (
        <Card key={order.order_id} style={styles.card}>
          <View style={styles.row}>
            <View style={styles.flex}>
              <AppText variant="bodyStrong" numberOfLines={1}>
                {order.restaurant_name}
              </AppText>
              <AppText variant="caption" tone="muted" numberOfLines={1}>
                to {order.drop_area || 'the customer'} · {order.item_count} item
                {order.item_count === 1 ? '' : 's'}
              </AppText>
            </View>
            <AppText variant="heading" tone="success">
              {rupees(order.earning_estimate)}
            </AppText>
          </View>
          <View style={styles.chips}>
            <Pill
              icon="bicycle"
              label={`${distance(order.pickup_distance_m)} away`}
            />
            <Pill
              icon="navigate"
              label={`${km(order.trip_distance_km)} trip`}
            />
            <Pill
              icon="time"
              tone={order.minutes_left <= 1 ? 'warning' : 'neutral'}
              label={minutesLeftLabel(order.minutes_left)}
            />
          </View>
          <Button
            kind="success"
            size="md"
            icon="checkmark-circle"
            label="Take order"
            loading={taking === order.order_id}
            onPress={() => void take(order)}
          />
        </Card>
      ))}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: space.md },
  flex: { flex: 1 },
  head: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  badge: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  card: { gap: space.md, borderRadius: radius.xl },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
});
