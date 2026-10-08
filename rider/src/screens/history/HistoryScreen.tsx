import React, { useCallback, useState } from 'react';
import { RefreshControl, StyleSheet, View } from 'react-native';
import { FlashList } from '@shopify/flash-list';
import { useFocusEffect } from '@react-navigation/native';
import Animated, { FadeInDown } from 'react-native-reanimated';
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

const END_LABEL: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' }> = {
  DELIVERED: { label: 'Delivered', tone: 'success' },
  CUSTOMER_UNAVAILABLE: { label: 'Customer away', tone: 'warning' },
  CANCELLED_BEFORE_PICKUP: { label: 'Cancelled', tone: 'danger' },
  CANCELLED_AFTER_PICKUP: { label: 'Cancelled', tone: 'danger' },
  REASSIGNED: { label: 'Reassigned', tone: 'neutral' },
};

function TripRow({ trip, index }: { trip: Trip; index: number }) {
  const { colors } = useTheme();
  const end = END_LABEL[trip.end_reason ?? ''] ?? { label: trip.end_reason ?? 'Ended', tone: 'neutral' as const };
  const ended = trip.ended_at ? new Date(trip.ended_at) : null;
  return (
    <Animated.View entering={index < 8 ? FadeInDown.delay(index * 40).springify().damping(18) : undefined}>
      <Card style={styles.card}>
        <View style={styles.rowBetween}>
          <View style={styles.flex}>
            <AppText variant="bodyStrong" numberOfLines={1}>
              {trip.pickup.name}
            </AppText>
            <AppText variant="caption" tone="muted" numberOfLines={1}>
              to {trip.drop.name} · {km(trip.distance_km)}
            </AppText>
          </View>
          <AppText variant="heading" tone={Number(trip.earning) > 0 ? 'success' : 'muted'}>
            {rupees(trip.earning)}
          </AppText>
        </View>
        <View style={[styles.footer, { borderTopColor: colors.border }]}>
          <Pill label={end.label} tone={end.tone} dot />
          <AppText variant="caption" tone="faint">
            {trip.order_code} · {ended ? `${ended.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}, ${clockTime(trip.ended_at)}` : ''}
          </AppText>
        </View>
      </Card>
    </Animated.View>
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

  const loadFirst = useCallback(async () => {
    try {
      const page = await api.history();
      setItems(page);
      setMore(page.length === 20);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not load your deliveries.');
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
    <View style={[styles.root, { backgroundColor: colors.bg, paddingTop: insets.top + space.md }]}>
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
          data={items}
          keyExtractor={t => t.id}
          renderItem={({ item, index }) => <TripRow trip={item} index={index} />}
          contentContainerStyle={{ paddingHorizontal: space.lg, paddingBottom: 120 }}
          ItemSeparatorComponent={() => <View style={{ height: space.md }} />}
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
              <View style={[styles.emptyIcon, { backgroundColor: colors.surfaceAlt }]}>
                <Icon name="receipt-outline" size={34} color={colors.textMuted} />
              </View>
              <AppText variant="heading" align="center">
                No deliveries yet
              </AppText>
              <AppText tone="muted" align="center">
                {error ?? 'Go online from Home to start. Every trip you finish shows up here.'}
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
  card: { gap: space.md },
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  footer: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingTop: space.md, borderTopWidth: StyleSheet.hairlineWidth },
  empty: { alignItems: 'center', gap: space.sm, paddingTop: space.huge, paddingHorizontal: space.xl },
  emptyIcon: { width: 80, height: 80, borderRadius: 40, alignItems: 'center', justifyContent: 'center', marginBottom: space.sm },
});
