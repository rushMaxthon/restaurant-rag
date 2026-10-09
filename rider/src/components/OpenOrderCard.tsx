import React from 'react';
import { StyleSheet, View } from 'react-native';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Pill } from '@components/ui/Pill';
import { GuideTarget } from '@/guide/GuideProvider';
import { TARGETS } from '@/guide/tours';
import type { OpenOrder } from '@/types/api';
import { radius, space } from '@theme/tokens';
import { distance, km, rupees } from '@utils/format';
import { minutesLeftLabel } from '@utils/openOrders';

/**
 * One order on the board: what it pays first, then how far, then how long
 * before a courier gets it. `blockedReason` disables Take and says why -
 * the button never just goes grey.
 */
export function OpenOrderCard({
  order,
  taking,
  blockedReason,
  onTake,
  guide = false,
}: {
  order: OpenOrder;
  taking: boolean;
  blockedReason: string | null;
  onTake: () => void;
  /** The first card on the board: the one the Orders tip points at. */
  guide?: boolean;
}) {
  const take = (
    <Button
      kind="success"
      size="md"
      icon="checkmark-circle"
      label="Take order"
      loading={taking}
      disabledReason={blockedReason ?? undefined}
      onPress={onTake}
    />
  );
  return (
    <Card style={styles.card}>
      {order.missed ? (
        <View style={styles.tag}>
          <Pill
            icon="alarm"
            tone="warning"
            label="You missed this - still yours to take"
          />
        </View>
      ) : null}
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
        <Pill icon="navigate" label={`${km(order.trip_distance_km)} trip`} />
        <Pill
          icon="time"
          tone={order.minutes_left <= 1 ? 'warning' : 'neutral'}
          label={minutesLeftLabel(order.minutes_left)}
        />
      </View>
      {guide ? <GuideTarget id={TARGETS.ordersTake}>{take}</GuideTarget> : take}
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { gap: space.md, borderRadius: radius.xl },
  tag: { flexDirection: 'row' },
  flex: { flex: 1 },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
});
