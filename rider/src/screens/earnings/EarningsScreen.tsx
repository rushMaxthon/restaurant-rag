import React, { useCallback, useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, {
  FadeInDown,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withSpring,
} from 'react-native-reanimated';
import { useFocusEffect } from '@react-navigation/native';
import Svg, {
  Circle,
  Defs,
  LinearGradient,
  Rect,
  Stop,
} from 'react-native-svg';

import { AnimatedAmount } from '@components/ui/AnimatedAmount';
import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { Screen } from '@components/ui/Screen';
import { Skeleton } from '@components/ui/Skeleton';
import { ApiError } from '@/services/http';
import { useApi } from '@/store/SessionProvider';
import type { Earnings } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, motion } from '@theme/tokens';
import { rupees, weekday } from '@utils/format';

const CHART_HEIGHT = 140;

function Bar({
  ratio,
  index,
  highlight,
  label,
  amount,
}: {
  ratio: number;
  index: number;
  highlight: boolean;
  label: string;
  amount: string;
}) {
  const { colors } = useTheme();
  const h = useSharedValue(0);
  useEffect(() => {
    h.value = withDelay(
      60 * index,
      withSpring(Math.max(ratio, 0.03) * CHART_HEIGHT, motion.springSoft),
    );
  }, [ratio, index, h]);
  const style = useAnimatedStyle(() => ({ height: h.value }));
  return (
    <View style={styles.barCol} accessibilityLabel={`${label}: ${amount}`}>
      <View style={styles.barTrack}>
        <Animated.View
          style={[
            styles.bar,
            {
              backgroundColor: highlight ? colors.primary : colors.primarySoft,
            },
            style,
          ]}
        />
      </View>
      <AppText variant="micro" tone={highlight ? 'primary' : 'muted'}>
        {label.toUpperCase()}
      </AppText>
    </View>
  );
}

/** What I earned today, this week, and what is still to be paid to me. */
export function EarningsScreen() {
  const { colors } = useTheme();
  const api = useApi();
  const [data, setData] = useState<Earnings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.earnings(7));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not load earnings.');
    }
  }, [api]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const max = Math.max(1, ...(data?.days.map(d => Number(d.amount)) ?? [1]));

  return (
    <Screen
      scroll
      tabbed
      refreshing={refreshing}
      onRefresh={async () => {
        setRefreshing(true);
        await load();
        setRefreshing(false);
      }}
      contentStyle={styles.content}
    >
      <Animated.View entering={FadeInDown.duration(350)}>
        <AppText variant="title">Earnings</AppText>
        <AppText tone="muted">Last 7 days</AppText>
      </Animated.View>

      <Animated.View entering={FadeInDown.delay(60).duration(motion.base)}>
        <View style={styles.hero}>
          {/* A warm gradient with a soft highlight: the one place money is the hero. */}
          <Svg
            style={StyleSheet.absoluteFill}
            preserveAspectRatio="none"
            viewBox="0 0 100 100"
          >
            <Defs>
              <LinearGradient id="earn" x1="0" y1="0" x2="1" y2="1">
                <Stop offset="0" stopColor="#FF7A3D" />
                <Stop offset="1" stopColor={colors.primaryPressed} />
              </LinearGradient>
            </Defs>
            <Rect x="0" y="0" width="100" height="100" fill="url(#earn)" />
            <Circle cx="92" cy="8" r="38" fill="#FFFFFF" opacity={0.08} />
          </Svg>
          <AppText variant="micro" style={styles.heroLabel}>
            THIS WEEK
          </AppText>
          {data ? (
            <AnimatedAmount
              value={Number(data.period_total)}
              style={styles.heroAmount}
            />
          ) : (
            <Skeleton width={160} height={40} style={styles.gapSm} />
          )}
          <View style={styles.heroRow}>
            <HeroStat
              label="Deliveries"
              value={data ? String(data.period_trips) : '—'}
            />
            <HeroStat label="Today" value={data ? rupees(data.today) : '—'} />
            <HeroStat
              label="Per delivery"
              value={
                data && data.period_trips > 0
                  ? rupees(
                      Math.round(Number(data.period_total) / data.period_trips),
                    )
                  : '—'
              }
            />
          </View>
        </View>
      </Animated.View>

      <Animated.View entering={FadeInDown.delay(120).duration(motion.base)}>
        <Card>
          <AppText variant="label" tone="muted">
            DAILY
          </AppText>
          <View style={styles.chart}>
            {(
              data?.days ??
              Array.from({ length: 7 }, (_, i) => ({
                date: `${i}`,
                trips: 0,
                amount: '0',
              }))
            ).map((d, i, all) => (
              <Bar
                key={d.date}
                index={i}
                ratio={Number(d.amount) / max}
                highlight={i === all.length - 1}
                label={data ? weekday(d.date) : ''}
                amount={rupees(d.amount)}
              />
            ))}
          </View>
        </Card>
      </Animated.View>

      <Animated.View
        entering={FadeInDown.delay(180).duration(motion.base)}
        style={styles.row}
      >
        <Card style={styles.half}>
          <Icon name="hourglass-outline" size={22} color={colors.warning} />
          <AppText variant="micro" tone="muted" style={styles.gapSm}>
            TO BE PAID
          </AppText>
          <AppText variant="heading">
            {data ? rupees(data.unpaid) : '—'}
          </AppText>
        </Card>
        <Card style={styles.half}>
          <Icon
            name="checkmark-done-circle-outline"
            size={22}
            color={colors.success}
          />
          <AppText variant="micro" tone="muted" style={styles.gapSm}>
            PAID SO FAR
          </AppText>
          <AppText variant="heading">
            {data ? rupees(data.paid_total) : '—'}
          </AppText>
        </Card>
      </Animated.View>

      <Card tone="alt" style={styles.info}>
        <Icon
          name="information-circle-outline"
          size={20}
          color={colors.textMuted}
        />
        <AppText variant="caption" tone="muted" style={styles.flex}>
          Payouts are sent to your bank by the platform. Each delivery pays a
          base amount plus a rate per km.
        </AppText>
      </Card>

      {error ? (
        <AppText variant="label" tone="danger" align="center">
          {error}
        </AppText>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { gap: space.lg },
  flex: { flex: 1 },
  hero: {
    borderRadius: radius.xxl,
    padding: space.xl,
    gap: space.xs,
    overflow: 'hidden',
  },
  heroLabel: { color: '#FFFFFF', opacity: 0.85 },
  heroAmount: { fontSize: 40, lineHeight: 48, color: '#FFFFFF' },
  heroRow: { flexDirection: 'row', marginTop: space.lg, gap: space.md },
  heroStat: {
    flex: 1,
    backgroundColor: 'rgba(255,255,255,0.14)',
    borderRadius: radius.md,
    paddingVertical: space.sm,
    alignItems: 'center',
  },
  heroValue: { color: '#FFFFFF' },
  heroCaption: { color: '#FFFFFF', opacity: 0.8 },
  chart: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
    marginTop: space.lg,
  },
  barCol: { alignItems: 'center', gap: space.xs, flex: 1 },
  barTrack: { height: CHART_HEIGHT, justifyContent: 'flex-end' },
  bar: { width: 22, borderRadius: 8 },
  row: { flexDirection: 'row', gap: space.md },
  half: { flex: 1 },
  info: { flexDirection: 'row', gap: space.sm, alignItems: 'center' },
  gapSm: { marginTop: space.sm },
});

function HeroStat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.heroStat}>
      <AppText variant="bodyStrong" style={styles.heroValue} numberOfLines={1}>
        {value}
      </AppText>
      <AppText variant="caption" style={styles.heroCaption}>
        {label}
      </AppText>
    </View>
  );
}
