import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import Animated, {
  FadeInDown,
  LinearTransition,
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
import { Segmented } from '@components/ui/Segmented';
import { Skeleton } from '@components/ui/Skeleton';
import { GuideTarget } from '@/guide/GuideProvider';
import { TARGETS } from '@/guide/tours';
import { useTour } from '@/guide/useTour';
import { ApiError } from '@/services/http';
import { useApi } from '@/store/SessionProvider';
import type { Earnings, Payout } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, motion } from '@theme/tokens';
import {
  PERIODS,
  periodFor,
  heroLine,
  showsChart,
  type PeriodKey,
} from '@utils/earningsPeriod';
import { rupees, weekday } from '@utils/format';
import { dateLabel } from '@utils/history';

const CHART_HEIGHT = 90;
const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

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
      40 * index,
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
      {label ? (
        <AppText variant="micro" tone={highlight ? 'primary' : 'muted'}>
          {label}
        </AppText>
      ) : null}
    </View>
  );
}

function localDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(
    2,
    '0',
  )}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * What I earned today, this week or this month, what is still to be paid,
 * and every payment that has reached me - the record a rider checks their
 * bank statement against.
 */
export function EarningsScreen() {
  const { colors } = useTheme();
  const api = useApi();
  const [periodKey, setPeriodKey] = useState<PeriodKey>('week');
  const period = periodFor(periodKey);
  const [data, setData] = useState<Earnings | null>(null);
  const [payouts, setPayouts] = useState<Payout[] | null>(null);
  const [payoutsFailed, setPayoutsFailed] = useState(false);
  // Two period taps in a row start two requests; only the latest may land.
  const request = useRef(0);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  // The bar the rider tapped; untouched, the latest day.
  const [picked, setPicked] = useState<number | null>(null);
  const [chartWidth, setChartWidth] = useState(0);
  // Which period `data` belongs to. A switch keeps the old numbers, dimmed,
  // until the new ones land - and if they never do, the error says so at the
  // top, instead of skeletons that look like loading forever.
  const [dataDays, setDataDays] = useState<number | null>(null);
  useTour('earnings', data !== null);

  const load = useCallback(async () => {
    const mine = ++request.current;
    try {
      const [earnings, paid] = await Promise.all([
        api.earnings(period.days),
        api.payouts().catch(() => null),
      ]);
      if (mine !== request.current) return;
      setData(earnings);
      setDataDays(period.days);
      setPayouts(paid ?? []);
      setPayoutsFailed(paid === null);
      setError(null);
    } catch (e) {
      if (mine !== request.current) return;
      setError(e instanceof ApiError ? e.message : 'Could not load earnings.');
    }
  }, [api, period.days]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const max = Math.max(1, ...(data?.days.map(d => Number(d.amount)) ?? [1]));
  const month = period.days > 7;
  const stale = data !== null && dataDays !== period.days;
  const pickedDay = data?.days[picked ?? data.days.length - 1] ?? null;

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
      </Animated.View>

      <Segmented
        options={PERIODS}
        value={periodKey}
        onChange={key => {
          setPeriodKey(key);
          setPicked(null);
        }}
      />

      {error ? (
        <Card tone="alt" style={styles.errorCard}>
          <Icon name="cloud-offline-outline" size={20} color={colors.danger} />
          <AppText variant="label" style={styles.flex}>
            {error} Pull down to try again.
          </AppText>
        </Card>
      ) : null}

      <Animated.View
        entering={FadeInDown.delay(60).duration(motion.base)}
        layout={LinearTransition}
      >
        <View style={[styles.hero, stale && styles.stale]}>
          {/* A warm gradient with a soft highlight: the one place money is the hero. */}
          <Svg
            style={StyleSheet.absoluteFill}
            preserveAspectRatio="none"
            viewBox="0 0 100 100"
          >
            <Defs>
              <LinearGradient id="earn" x1="0" y1="0" x2="1" y2="1">
                <Stop offset="0" stopColor={colors.primary} />
                <Stop offset="1" stopColor={colors.primaryPressed} />
              </LinearGradient>
            </Defs>
            <Rect x="0" y="0" width="100" height="100" fill="url(#earn)" />
            <Circle cx="92" cy="8" r="38" fill={colors.onPrimary} opacity={0.08} />
          </Svg>
          <AppText variant="micro" style={[styles.heroLabel, { color: colors.onPrimary }]}>
            {period.heroLabel}
          </AppText>
          {data ? (
            <AnimatedAmount
              value={Number(data.period_total)}
              style={[styles.heroAmount, { color: colors.onPrimary }]}
            />
          ) : (
            <Skeleton width={160} height={40} style={styles.gapSm} />
          )}
          <AppText
            variant="bodyStrong"
            style={[styles.heroCaption, { color: colors.onPrimary }]}
          >
            {data ? heroLine(data.period_trips, data.period_total) : ' '}
          </AppText>
        </View>
      </Animated.View>

      {showsChart(periodKey) ? (
        <Animated.View
          entering={FadeInDown.delay(120).duration(motion.base)}
          layout={LinearTransition}
        >
          <Card style={stale && styles.stale}>
            <View style={styles.chartHead}>
              <AppText variant="label" tone="muted" style={styles.flex}>
                DAILY
              </AppText>
              {pickedDay ? (
                <AppText variant="label">
                  {dateLabel(pickedDay.date)} ·{' '}
                  <AppText variant="label" tone="success">
                    {rupees(pickedDay.amount)}
                  </AppText>
                </AppText>
              ) : null}
            </View>
            {/* One touch area across the whole chart, the day picked from where
                the finger lands: thirty bars are ~8 dp each, far too narrow to
                be buttons of their own. */}
            <Pressable
              style={styles.chart}
              onLayout={e => setChartWidth(e.nativeEvent.layout.width)}
              onPress={e => {
                const n = data?.days.length ?? 0;
                if (n === 0 || chartWidth === 0) return;
                const i = Math.floor((e.nativeEvent.locationX / chartWidth) * n);
                setPicked(Math.max(0, Math.min(n - 1, i)));
              }}
              accessibilityRole="adjustable"
              accessibilityLabel="Daily earnings chart. Tap a day to see its amount."
            >
              {(
                data?.days ??
                Array.from({ length: period.days }, (_, i) => ({
                  date: `${i}`,
                  trips: 0,
                  amount: '0',
                }))
              ).map((d, i, all) => (
                <Bar
                  key={d.date}
                  index={i}
                  ratio={Number(d.amount) / max}
                  highlight={i === (picked ?? all.length - 1)}
                  // A month has no room for 30 labels: every fifth day, and the last.
                  label={!data || month ? '' : weekday(d.date).toUpperCase()}
                  amount={rupees(d.amount)}
                />
              ))}
            </Pressable>
            {month && data ? (
              // Thirty columns have no room for thirty labels: one every five days.
              <View style={styles.monthLabels}>
                {data.days
                  .filter((_, i) => i % 5 === 0)
                  .map(d => (
                    <AppText
                      key={d.date}
                      variant="micro"
                      tone="muted"
                      style={styles.monthLabel}
                    >
                      {Number(d.date.slice(-2))}{' '}
                      {MONTHS[Number(d.date.slice(5, 7)) - 1]}
                    </AppText>
                  ))}
              </View>
            ) : null}
          </Card>
        </Animated.View>
      ) : null}

      <Animated.View
        entering={FadeInDown.delay(180).duration(motion.base)}
        layout={LinearTransition}
      >
        <Card style={styles.row}>
          <GuideTarget id={TARGETS.earningsUnpaid} style={styles.half}>
            <View style={styles.payHead}>
              <Icon name="hourglass-outline" size={16} color={colors.warning} />
              <AppText variant="micro" tone="muted">
                TO BE PAID
              </AppText>
            </View>
            <AppText variant="heading" style={styles.gapXs}>
              {data ? rupees(data.unpaid) : '—'}
            </AppText>
          </GuideTarget>
          <View style={[styles.split, { backgroundColor: colors.border }]} />
          <View style={styles.half}>
            <View style={styles.payHead}>
              <Icon
                name="checkmark-done-circle-outline"
                size={16}
                color={colors.success}
              />
              <AppText variant="micro" tone="muted">
                PAID SO FAR
              </AppText>
            </View>
            <AppText variant="heading" style={styles.gapXs}>
              {data ? rupees(data.paid_total) : '—'}
            </AppText>
          </View>
        </Card>
      </Animated.View>

      {/* Payments received */}
      <Animated.View
        entering={FadeInDown.delay(240).duration(motion.base)}
        layout={LinearTransition}
      >
        <Card style={styles.payments}>
          <View style={styles.paymentsHead}>
            <Icon name="card-outline" size={18} color={colors.success} />
            <AppText variant="bodyStrong" style={styles.flex}>
              Payments to your bank
            </AppText>
          </View>
          {payouts === null ? (
            <Skeleton height={56} round={radius.md} />
          ) : payoutsFailed ? (
            <View
              style={[styles.emptyPay, { backgroundColor: colors.surfaceAlt }]}
            >
              <AppText variant="label" align="center">
                Couldn't load payments
              </AppText>
              <AppText variant="caption" tone="muted" align="center">
                Pull down to try again.
              </AppText>
            </View>
          ) : payouts.length === 0 ? (
            <View
              style={[styles.emptyPay, { backgroundColor: colors.surfaceAlt }]}
            >
              <AppText variant="label" align="center">
                Nothing paid yet
              </AppText>
              <AppText variant="caption" tone="muted" align="center">
                {data && Number(data.unpaid) > 0
                  ? `${rupees(
                      data.unpaid,
                    )} is due to you. It arrives after the platform pays out.`
                  : 'Each delivery you finish adds to what is due to you.'}
              </AppText>
            </View>
          ) : (
            payouts.map((p, i) => (
              <View
                key={p.id}
                style={[
                  styles.payRow,
                  { borderTopColor: colors.border },
                  i === 0 && styles.firstPay,
                ]}
              >
                <View style={styles.flex}>
                  <AppText variant="bodyStrong">
                    {dateLabel(localDate(p.paid_at))} · {p.trips} deliver
                    {p.trips === 1 ? 'y' : 'ies'}
                  </AppText>
                  <AppText variant="caption" tone="muted" numberOfLines={1}>
                    {p.reference ? `Ref ${p.reference}` : 'Bank transfer'}
                  </AppText>
                </View>
                <AppText variant="heading" tone="success">
                  {rupees(p.amount)}
                </AppText>
              </View>
            ))
          )}
        </Card>
      </Animated.View>

      <Card tone="alt" style={styles.info}>
        <Icon
          name="information-circle-outline"
          size={20}
          color={colors.textMuted}
        />
        <AppText variant="caption" tone="muted" style={styles.flex}>
          Base + a rate per km, never under the minimum. Rates are on Home.
        </AppText>
      </Card>

    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { gap: space.md },
  flex: { flex: 1 },
  hero: {
    borderRadius: radius.xxl,
    padding: space.lg,
    paddingHorizontal: space.xl,
    gap: space.xxs,
    overflow: 'hidden',
  },
  heroLabel: { opacity: 0.85 },
  heroAmount: { fontSize: 36, lineHeight: 44 },
  heroCaption: { opacity: 0.85 },
  stale: { opacity: 0.45 },
  errorCard: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  chart: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
    marginTop: space.md,
    gap: 2,
  },
  barCol: { alignItems: 'center', gap: space.xs, flex: 1 },
  barTrack: {
    height: CHART_HEIGHT,
    justifyContent: 'flex-end',
    alignSelf: 'stretch',
    alignItems: 'center',
  },
  bar: { width: '70%', maxWidth: 22, minWidth: 4, borderRadius: 8 },
  monthLabels: { flexDirection: 'row', marginTop: space.xs },
  monthLabel: { flex: 1 },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.lg },
  split: { width: 1, alignSelf: 'stretch' },
  payHead: { flexDirection: 'row', alignItems: 'center', gap: space.xs },
  chartHead: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  gapXs: { marginTop: space.xs },
  half: { flex: 1 },
  payments: { gap: space.md },
  paymentsHead: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  emptyPay: { padding: space.md, borderRadius: radius.md, gap: space.xxs },
  payRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingTop: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  firstPay: { borderTopWidth: 0, paddingTop: 0 },
  info: { flexDirection: 'row', gap: space.sm, alignItems: 'center' },
  gapSm: { marginTop: space.sm },
});

