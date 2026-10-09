import React, { useCallback, useMemo, useState } from 'react';
import { RefreshControl, StyleSheet, View } from 'react-native';
import { FlashList } from '@shopify/flash-list';
import { useFocusEffect } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { Skeleton } from '@components/ui/Skeleton';
import { ApiError } from '@/services/http';
import { useApi } from '@/store/SessionProvider';
import type { Earnings, Trip } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';
import { clockTime, km, rupees } from '@utils/format';
import { dayHeaderIndices, groupByDay, type HistoryRow } from '@utils/history';
import { endLabel } from '@utils/tripTimeline';
import { useNav } from '@navigation/types';

function TripRow({ trip }: { trip: Trip }) {
  const { colors } = useTheme();
  const nav = useNav();
  const end = endLabel(trip.end_reason);
  const dot = {
    success: colors.success,
    warning: colors.warning,
    danger: colors.danger,
    neutral: colors.textFaint,
  }[end.tone];
  const delivered = end.tone === 'success';
  return (
    // No entering animation on a recycled FlashList cell: Reanimated's layout
    // animation left the cell measured wrong (a gap above, taps falling through).
    <View>
      <Card
        style={styles.card}
        onPress={() => nav.navigate('TripDetail', { trip })}
      >
        <View
          style={[styles.dot, { backgroundColor: dot }]}
          accessibilityLabel={end.label}
        />
        <View style={styles.flex}>
          <AppText variant="bodyStrong" numberOfLines={1}>
            {trip.pickup.name}
          </AppText>
          <AppText variant="caption" tone="muted" numberOfLines={1}>
            {/* A delivery that did not happen says so where the eye already is. */}
            {delivered ? '' : `${end.label} · `}
            {trip.ended_at ? clockTime(trip.ended_at) : trip.order_code} · to{' '}
            {trip.drop.name} · {km(trip.distance_km)}
          </AppText>
        </View>
        <AppText
          variant="bodyStrong"
          tone={Number(trip.earning) > 0 ? 'success' : 'muted'}
        >
          {rupees(trip.earning)}
        </AppText>
        <Icon name="chevron-forward" size={16} color={colors.textFaint} />
      </Card>
    </View>
  );
}

/** A day's heading: what the rider made that day, at a glance. */
function DayHeader({
  row,
}: {
  row: Extract<HistoryRow, { kind: 'day' }>;
}) {
  const { colors } = useTheme();
  // Opaque: it sticks to the top while the day's trips scroll under it.
  return (
    <View style={[styles.day, { backgroundColor: colors.bg }]}>
      <AppText variant="label" tone="muted" style={styles.flex}>
        {row.label.toUpperCase()} · {row.count}
      </AppText>
      <AppText variant="label" tone="success">
        {rupees(row.total)}
      </AppText>
    </View>
  );
}

/** This week at a glance, above the list: the question History is opened for. */
function WeekSummary({ week }: { week: Earnings | null }) {
  const { colors } = useTheme();
  return (
    <Card tone="alt" style={styles.summary}>
      <Icon name="calendar-outline" size={20} color={colors.primary} />
      <AppText variant="label" tone="muted" style={styles.flex}>
        LAST 7 DAYS
      </AppText>
      {week ? (
        <AppText variant="bodyStrong">
          {week.period_trips}{' '}
          {week.period_trips === 1 ? 'delivery' : 'deliveries'} ·{' '}
          <AppText variant="bodyStrong" tone="success">
            {rupees(week.period_total)}
          </AppText>
        </AppText>
      ) : (
        <Skeleton width={120} height={18} />
      )}
    </Card>
  );
}

/** Every finished delivery, newest first, loading more as the rider scrolls. */
export function HistoryScreen() {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const api = useApi();
  const [items, setItems] = useState<Trip[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [more, setMore] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  const [week, setWeek] = useState<Earnings | null>(null);
  const rows = useMemo(() => groupByDay(items ?? []), [items]);
  const sticky = useMemo(() => dayHeaderIndices(rows), [rows]);

  const loadFirst = useCallback(async () => {
    try {
      const [page, seven] = await Promise.all([
        api.history(),
        // The summary is a nicety: a failure leaves it out, not the list.
        api.earnings(7).catch(() => null),
      ]);
      setItems(page);
      setWeek(seven);
      setMore(page.length === 20);
      setError(null);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : 'Could not load your deliveries.',
      );
    }
  }, [api]);

  useFocusEffect(
    useCallback(() => {
      void loadFirst();
    }, [loadFirst]),
  );

  const loadMore = useCallback(async () => {
    const last = items?.[items.length - 1];
    if (!more || loadingMore || !last?.ended_at) return;
    setLoadingMore(true);
    try {
      const page = await api.history(last.ended_at);
      setItems(prev => [...(prev ?? []), ...page]);
      setMore(page.length === 20);
    } catch {
      // try again on the next scroll
    } finally {
      setLoadingMore(false);
    }
  }, [api, items, more, loadingMore]);

  return (
    <View
      style={[
        styles.root,
        { backgroundColor: colors.bg, paddingTop: insets.top + space.md },
      ]}
    >
      <View style={styles.header}>
        <AppText variant="title">History</AppText>
        <WeekSummary week={week} />
      </View>
      {items === null ? (
        <View style={styles.skeletons}>
          {[0, 1, 2, 3].map(i => (
            <Skeleton key={i} height={64} round={20} />
          ))}
        </View>
      ) : (
        <FlashList
          data={rows}
          keyExtractor={r => r.key}
          getItemType={r => r.kind}
          stickyHeaderIndices={sticky}
          renderItem={({ item }) =>
            item.kind === 'day' ? (
              <DayHeader row={item} />
            ) : (
              <TripRow trip={item.trip} />
            )
          }
          // Rows pad themselves: FlashList draws the pinned day heading
          // outside the content padding, so it would sit wider than the cards.
          contentContainerStyle={{ paddingBottom: 120 }}
          onEndReached={loadMore}
          onEndReachedThreshold={0.5}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={async () => {
                setRefreshing(true);
                await loadFirst();
                setRefreshing(false);
              }}
              tintColor={colors.primary}
              colors={[colors.primary]}
              progressBackgroundColor={colors.surface}
            />
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <View
                style={[
                  styles.emptyIcon,
                  { backgroundColor: colors.surfaceAlt },
                ]}
              >
                <Icon
                  name="receipt-outline"
                  size={34}
                  color={colors.textMuted}
                />
              </View>
              <AppText variant="heading" align="center">
                No deliveries yet
              </AppText>
              <AppText tone="muted" align="center">
                {error ??
                  'Go online from Home to start. Every trip you finish shows up here.'}
              </AppText>
            </View>
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  flex: { flex: 1 },
  header: {
    paddingHorizontal: space.lg,
    marginBottom: space.sm,
    gap: space.md,
  },
  summary: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingVertical: space.md,
  },
  skeletons: { paddingHorizontal: space.lg, gap: space.md },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingVertical: space.md,
    marginBottom: space.sm,
    marginHorizontal: space.lg,
  },
  dot: { width: 10, height: 10, borderRadius: 5 },
  day: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingTop: space.md,
    paddingBottom: space.sm,
    paddingHorizontal: space.lg + space.xs,
  },
  empty: {
    alignItems: 'center',
    gap: space.sm,
    paddingTop: space.huge,
    paddingHorizontal: space.xl,
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
