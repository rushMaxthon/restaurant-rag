import React, { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { IconButton } from '@components/ui/IconButton';
import { Pill } from '@components/ui/Pill';
import { Screen } from '@components/ui/Screen';
import type { RootStackParamList } from '@navigation/types';
import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space } from '@theme/tokens';
import { clockTime, dayLabel, km, rupees } from '@utils/format';
import { endLabel, tripTimeline } from '@utils/tripTimeline';

function localDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(
    2,
    '0',
  )}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * One finished delivery, in full: when each moment happened, where it went,
 * what was carried and what it paid. Answers the question a rider brings to
 * the manager - "why did this one pay less?" - from the timeline alone.
 */
export function TripDetailScreen({
  navigation,
  route,
}: NativeStackScreenProps<RootStackParamList, 'TripDetail'>) {
  const { colors } = useTheme();
  const { trip } = route.params;
  const end = endLabel(trip.end_reason);
  const rows = tripTimeline(trip);
  const when = trip.ended_at ?? trip.accepted_at;
  // Folded: a finished trip's items are rarely the question.
  const [itemsOpen, setItemsOpen] = useState(false);

  return (
    <Screen scroll contentStyle={styles.content}>
      <View style={styles.header}>
        <IconButton
          icon="chevron-back"
          label="Back"
          onPress={() => navigation.goBack()}
        />
        <View style={styles.flex}>
          <AppText variant="heading">{trip.order_code}</AppText>
          <AppText variant="caption" tone="muted">
            {dayLabel(localDate(when))} · {clockTime(when)}
          </AppText>
        </View>
        <Pill label={end.label} tone={end.tone} dot />
      </View>

      <Animated.View entering={FadeInDown.duration(motion.base)}>
        <Card tone="alt" style={styles.pay}>
          <View style={styles.flex}>
            <AppText variant="micro" tone="muted">
              YOU EARNED
            </AppText>
            <AppText
              variant="money"
              tone={Number(trip.earning) > 0 ? 'success' : 'muted'}
            >
              {rupees(trip.earning)}
            </AppText>
          </View>
          <View style={[styles.divider, { backgroundColor: colors.border }]} />
          <View>
            <AppText variant="micro" tone="muted">
              DISTANCE
            </AppText>
            <AppText variant="heading">{km(trip.distance_km)}</AppText>
          </View>
        </Card>
      </Animated.View>

      <Animated.View entering={FadeInDown.delay(60).duration(motion.base)}>
        <Card>
          <AppText variant="label" tone="muted">
            TIMELINE
          </AppText>
          <View style={styles.timeline}>
            {rows.map((row, i) => (
              <View key={row.label} style={styles.moment}>
                <View style={styles.rail}>
                  <View
                    style={[
                      styles.dot,
                      {
                        backgroundColor: row.done
                          ? colors.primary
                          : colors.surfaceAlt,
                        borderColor: row.done ? colors.primary : colors.border,
                      },
                    ]}
                  />
                  {i < rows.length - 1 ? (
                    <View
                      style={[
                        styles.bar,
                        {
                          backgroundColor: rows[i + 1]?.done
                            ? colors.primary
                            : colors.border,
                        },
                      ]}
                    />
                  ) : null}
                </View>
                <View
                  style={[
                    styles.momentText,
                    i < rows.length - 1 && styles.momentGap,
                  ]}
                >
                  <AppText
                    variant="body"
                    tone={row.done ? 'default' : 'faint'}
                    style={styles.flex}
                    numberOfLines={1}
                  >
                    {row.label}
                  </AppText>
                  <AppText variant="label" tone={row.at ? 'muted' : 'faint'}>
                    {row.at ? clockTime(row.at) : 'Did not happen'}
                  </AppText>
                </View>
              </View>
            ))}
          </View>
        </Card>
      </Animated.View>

      <Animated.View entering={FadeInDown.delay(120).duration(motion.base)}>
        <Card style={styles.stops}>
          <Stop
            icon="restaurant"
            color={colors.primary}
            label="Picked up from"
            name={trip.pickup.name}
            address={trip.pickup.address}
          />
          <View style={[styles.connector, { borderColor: colors.border }]} />
          <Stop
            icon="home"
            color={colors.success}
            label={
              trip.end_reason === 'DELIVERED' ? 'Delivered to' : 'Was going to'
            }
            name={trip.drop.name}
            address={trip.drop.address}
          />
        </Card>
      </Animated.View>

      {trip.items.length > 0 ? (
        <Animated.View entering={FadeInDown.delay(180).duration(motion.base)}>
          <Card>
            <Pressable
              onPress={() => setItemsOpen(o => !o)}
              accessibilityRole="button"
              accessibilityState={{ expanded: itemsOpen }}
              hitSlop={8}
              style={styles.itemsHead}
            >
              <Icon name="bag-handle" size={20} color={colors.primary} />
              <AppText variant="bodyStrong" style={styles.flex}>
                {trip.item_count} item{trip.item_count === 1 ? '' : 's'}
              </AppText>
              <Icon
                name={itemsOpen ? 'chevron-up' : 'chevron-down'}
                size={18}
                color={colors.textMuted}
              />
            </Pressable>
            {itemsOpen &&
              trip.items.map((item, i) => (
              <View
                key={`${item.name}-${i}`}
                style={[
                  styles.item,
                  { borderTopColor: colors.border },
                  i === 0 && styles.firstItem,
                ]}
              >
                <View
                  style={[styles.qty, { backgroundColor: colors.primarySoft }]}
                >
                  <AppText variant="label" tone="primary">
                    {item.quantity}×
                  </AppText>
                </View>
                <AppText
                  variant="bodyStrong"
                  style={styles.flex}
                  numberOfLines={2}
                >
                  {item.name}
                </AppText>
              </View>
            ))}
          </Card>
        </Animated.View>
      ) : null}
    </Screen>
  );
}

function Stop({
  icon,
  color,
  label,
  name,
  address,
}: {
  icon: 'restaurant' | 'home';
  color: string;
  label: string;
  name: string;
  address: string;
}) {
  const { colors } = useTheme();
  return (
    <View style={styles.stop}>
      <View style={[styles.stopIcon, { backgroundColor: colors.surfaceAlt }]}>
        <Icon name={icon} size={20} color={color} />
      </View>
      <View style={styles.flex}>
        <AppText variant="caption" tone="muted">
          {label}
        </AppText>
        <AppText variant="bodyStrong">{name}</AppText>
        <AppText variant="caption" tone="muted">
          {address}
        </AppText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { gap: space.md },
  itemsHead: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  flex: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  pay: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: space.lg,
    borderRadius: radius.xxl,
  },
  divider: { width: 1, alignSelf: 'stretch', marginHorizontal: space.lg },
  timeline: { marginTop: space.md },
  moment: { flexDirection: 'row', gap: space.md },
  rail: { alignItems: 'center', width: 12 },
  dot: { width: 10, height: 10, borderRadius: 5, borderWidth: 2, marginTop: 7 },
  bar: { width: 2, flex: 1, marginVertical: 2 },
  momentText: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    minHeight: 24,
  },
  momentGap: { paddingBottom: space.md },
  stops: { gap: space.xs },
  stop: { flexDirection: 'row', gap: space.md, alignItems: 'center' },
  stopIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  connector: {
    height: 18,
    marginLeft: 21,
    borderLeftWidth: 2,
    borderStyle: 'dashed',
  },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingVertical: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  firstItem: { borderTopWidth: 0, marginTop: space.sm },
  qty: {
    minWidth: 40,
    paddingHorizontal: space.sm,
    paddingVertical: space.xs,
    borderRadius: radius.sm,
    alignItems: 'center',
  },
});
