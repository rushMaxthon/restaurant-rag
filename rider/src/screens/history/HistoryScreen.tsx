import React, { useCallback, useMemo, useState } from 'react';
import { RefreshControl, StyleSheet, View } from 'react-native';
import { FlashList } from '@shopify/flash-list';
import { useFocusEffect } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { Pill } from '@components/ui/Pill';
import { Skeleton } from '@components/ui/Skeleton';
import { ApiError } from '@/services/http';
import { useApi } from '@/store/SessionProvider';
import type { Trip } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';
import { clockTime, km, rupees } from '@utils/format';
import { groupByDay, type HistoryRow } from '@utils/history';
import { endLabel } from '@utils/tripTimeline';
import { useNav } from '@navigation/types';

function TripRow({ trip }: { trip: Trip }) {
  const { colors } = useTheme();
  const nav = useNav();
  const end = endLabel(trip.end_reason);
  return (
    // No entering animation on a recycled FlashList cell: Reanimated's layout
    // animation left the cell measured wrong (a gap above, taps falling through).
    <View>
      <Card
        style={styles.card}
        onPress={() => nav.navigate('TripDetail', { trip })}
      >
        <View style={styles.rowBetween}>
          <View style={styles.flex}>
            <AppText variant="bodyStrong" numberOfLines={1}>
              {trip.pickup.name}
            </AppText>
            <AppText variant="caption" tone="muted" numberOfLines={1}>
              to {trip.drop.name} · {km(trip.distance_km)}
            </AppText>
          </View>
          <AppText
            variant="heading"
            tone={Number(trip.earning) > 0 ? 'success' : 'muted'}
          >
            {rupees(trip.earning)}
          </AppText>
        </View>
        <View style={[styles.footer, { borderTopColor: colors.border }]}>
          <Pill label={end.label} tone={end.tone} dot />
          <View style={styles.meta}>
            <AppText variant="caption" tone="faint">
              {trip.order_code}
              {trip.ended_at ? ` · ${clockTime(trip.ended_at)}` : ''}
            </AppText>
            <Icon name="chevron-forward" size={16} color={colors.textFaint} />
          </View>
        </View>
      </Card>
    </View>
  );
}

/** A day's heading: what the rider made that day, at a glance. */
function DayHeader({
  row,
  first,
}: {
  row: Extract<HistoryRow, { kind: 'day' }>;
  first: boolean;
}) {
  return (
    <View style={[styles.day, first ? null : styles.dayGap]}>
      <View style={styles.flex}>
        <AppText variant="bodyStrong">{row.label}</AppText>
        <AppText variant="caption" tone="muted">
          {row.count} {row.count === 1 ? 'delivery' : 'deliveries'}
        </AppText>
      </View>
      <AppText variant="bodyStrong" tone="success">
        {rupees(row.total)}
      </AppText>
    </View>
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

  const rows = useMemo(() => groupByDay(items ?? []), [items]);

  const loadFirst = useCallback(async () => {
    try {
      const page = await api.history();
      setItems(page);
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
        <AppText tone="muted">Your finished deliveries</AppText>
      </View>
      {items === null ? (
        <View style={styles.skeletons}>
          {[0, 1, 2, 3].map(i => (
            <Skeleton key={i} height={96} round={20} />
          ))}
        </View>
      ) : (
        <FlashList
          data={rows}
          keyExtractor={r => r.key}
          getItemType={r => r.kind}
          renderItem={({ item, index }) =>
            item.kind === 'day' ? (
              <DayHeader row={item} first={index === 0} />
            ) : (
              <TripRow trip={item.trip} />
            )
          }
          contentContainerStyle={{
            paddingHorizontal: space.lg,
            paddingBottom: 120,
          }}
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
  header: { paddingHorizontal: space.lg, marginBottom: space.lg },
  skeletons: { paddingHorizontal: space.lg, gap: space.md },
  card: { gap: space.md, marginBottom: space.md },
  day: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingBottom: space.sm,
    paddingHorizontal: space.xs,
  },
  dayGap: { marginTop: space.lg },
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  meta: { flexDirection: 'row', alignItems: 'center', gap: space.xs },
  footer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingTop: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
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
