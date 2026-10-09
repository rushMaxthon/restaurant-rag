import React from 'react';
import { useI18n } from '@/i18n';
import { StyleSheet, View } from 'react-native';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { GuideTarget } from '@/guide/GuideProvider';
import { TARGETS } from '@/guide/tours';
import type { OpenOrder } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';
import { distance, km, rupees } from '@utils/format';
import { minutesLeftLabel } from '@utils/openOrders';
import { useReadyLabel } from '@hooks/useReadyLabel';

/**
 * One order on the board, in three short lines: where from and what it pays,
 * where to, then how far and how long before a courier gets it, and when the
 * food will be ready when the restaurant has said. An order in
 * its last minute gets an amber edge - it is now or never. `blockedReason`
 * disables Take and says why; the button never just goes grey.
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
  const { colors } = useTheme();
  const { t, plural } = useI18n();
  const lastMinute = order.minutes_left <= 1;
  const ready = useReadyLabel(order.ready_at);
  const take = (
    <Button
      kind="success"
      size="md"
      icon="checkmark-circle"
      label={t('orders.take')}
      loading={taking}
      disabledReason={blockedReason ?? undefined}
      onPress={onTake}
    />
  );
  return (
    <Card
      style={[styles.card, lastMinute && { borderColor: colors.warning }]}
    >
      {order.missed ? (
        <View style={styles.meta}>
          <Icon name="alarm" size={14} color={colors.warning} />
          <AppText variant="caption" style={{ color: colors.warning }}>
            {t('orders.missed')}
          </AppText>
        </View>
      ) : null}
      <View style={styles.row}>
        <View style={styles.flex}>
          <AppText variant="bodyStrong" numberOfLines={1}>
            {order.restaurant_name}
          </AppText>
          <AppText variant="caption" tone="muted" numberOfLines={1}>
            {t('orders.to', {
              place: order.drop_area || t('orders.theCustomer'),
            })}{' '}
            · {plural('common.items', order.item_count)}
          </AppText>
        </View>
        <AppText variant="heading" tone="success">
          {rupees(order.earning_estimate)}
        </AppText>
      </View>
      <View style={styles.metaRow}>
        <Meta
          icon="bicycle"
          label={t('common.away', {
            distance: distance(order.pickup_distance_m),
          })}
        />
        <Meta
          icon="navigate"
          label={t('orders.trip', { distance: km(order.trip_distance_km) })}
        />
        <Meta
          icon="time"
          label={minutesLeftLabel(order.minutes_left)}
          color={lastMinute ? colors.warning : undefined}
        />
        {ready ? <Meta icon="restaurant" label={ready} /> : null}
      </View>
      {guide ? <GuideTarget id={TARGETS.ordersTake}>{take}</GuideTarget> : take}
    </Card>
  );
}

function Meta({
  icon,
  label,
  color,
}: {
  icon: IconName;
  label: string;
  color?: string;
}) {
  const { colors } = useTheme();
  return (
    <View style={styles.meta}>
      <Icon name={icon} size={14} color={color ?? colors.textMuted} />
      <AppText
        variant="label"
        tone={color ? undefined : 'muted'}
        style={color ? { color } : undefined}
      >
        {label}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { gap: space.md, borderRadius: radius.xl },
  flex: { flex: 1 },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  metaRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    columnGap: space.lg,
    rowGap: space.xs,
  },
  meta: { flexDirection: 'row', alignItems: 'center', gap: space.xs },
});
