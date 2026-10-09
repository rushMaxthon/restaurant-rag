import React, { useCallback, useState } from 'react';
import { useI18n, type Key } from '@/i18n';
import { StyleSheet, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import Animated, {
  FadeIn,
  FadeInDown,
  FadeOut,
  LinearTransition,
} from 'react-native-reanimated';

import { HomeInsights } from '@components/HomeInsights';
import { NearbyOrders } from '@components/home/NearbyOrders';
import { ShiftCard } from '@components/home/ShiftCard';
import { useRiderLocation } from '@components/ShiftKeeper';
import { AnimatedAmount } from '@components/ui/AnimatedAmount';
import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { Pill } from '@components/ui/Pill';
import { Screen } from '@components/ui/Screen';
import { Skeleton } from '@components/ui/Skeleton';
import { GuideTarget } from '@/guide/GuideProvider';
import { TARGETS } from '@/guide/tours';
import { useTour } from '@/guide/useTour';
import { usePermissions } from '@hooks/usePermissions';
import { useShiftToggle } from '@hooks/useShiftToggle';
import { gateReason } from '@utils/permissions';
import { useNav } from '@navigation/types';
import { useRider } from '@/store/RiderProvider';
import { useSignedInUser } from '@/store/SessionProvider';
import type { Trip } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { space, motion } from '@theme/tokens';
import { greeting, initials } from '@utils/format';

const STEP_LABEL: Record<Trip['step'], Key> = {
  to_pickup: 'home.step.toPickup',
  at_pickup: 'home.step.atPickup',
  to_drop: 'home.step.toDrop',
  at_drop: 'home.step.atDrop',
  done: 'home.step.done',
};

export function HomeScreen() {
  const { colors } = useTheme();
  const { t } = useI18n();
  const nav = useNav();
  const user = useSignedInUser();
  const { me, trip, loading, refreshMe, refreshTrip, error } = useRider();
  const permissions = usePermissions();
  // Back from the Permissions screen or the phone's settings: read again, so
  // the "Finish setting up" note and the toggle agree with the phone.
  const refreshPermissions = permissions.refresh;
  useFocusEffect(
    useCallback(() => {
      void refreshPermissions();
    }, [refreshPermissions]),
  );
  const location = useRiderLocation();
  const shift = useShiftToggle();
  const [refreshing, setRefreshing] = useState(false);
  const online = shift.online;
  useTour('home', me !== null && !trip);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([refreshMe(), refreshTrip()]);
    setRefreshing(false);
  }, [refreshMe, refreshTrip]);

  return (
    <Screen
      scroll
      tabbed
      refreshing={refreshing}
      onRefresh={onRefresh}
      contentStyle={styles.content}
    >
      {/* Header */}
      <Animated.View entering={FadeInDown.duration(400)} style={styles.header}>
        <View style={[styles.avatar, { backgroundColor: colors.primarySoft }]}>
          <AppText variant="heading" tone="primary">
            {initials(me?.full_name ?? user?.full_name ?? 'R')}
          </AppText>
        </View>
        <View style={styles.flex}>
          <AppText variant="caption" tone="muted">
            {greeting()}
          </AppText>
          <AppText variant="heading" numberOfLines={1}>
            {me?.full_name ?? user?.full_name ?? t('common.rider')}
          </AppText>
        </View>
      </Animated.View>

      {/* Active trip */}
      {trip ? (
        <Animated.View
          entering={FadeIn.duration(300)}
          exiting={FadeOut}
          layout={LinearTransition}
        >
          <Card
            tone="primary"
            onPress={() => nav.navigate('Trip')}
            testID="active-trip"
          >
            <View style={styles.rowBetween}>
              <Pill
                label={t(STEP_LABEL[trip.step])}
                tone="primary"
                icon="navigate"
              />
              <AppText variant="label" tone="muted">
                {trip.order_code}
              </AppText>
            </View>
            <View style={styles.route}>
              <RouteLine colors={colors} />
              <View style={styles.flexGap}>
                <View>
                  <AppText variant="caption" tone="muted">
                    {t('home.pickUp')}
                  </AppText>
                  <AppText variant="bodyStrong" numberOfLines={1}>
                    {trip.pickup.name}
                  </AppText>
                </View>
                <View>
                  <AppText variant="caption" tone="muted">
                    {t('home.deliverTo')}
                  </AppText>
                  <AppText variant="bodyStrong" numberOfLines={1}>
                    {trip.drop.name} · {trip.drop.address}
                  </AppText>
                </View>
              </View>
            </View>
            <Button
              label={t('home.continueDelivery')}
              icon="arrow-forward"
              onPress={() => nav.navigate('Trip')}
            />
          </Card>
        </Animated.View>
      ) : null}

      {/* Shift: a strip while online, the screen's big action while offline. */}
      {!trip ? (
        <ShiftCard
          online={online}
          onChange={shift.toggle}
          busy={shift.busy}
          disabledReason={shift.disabledReason}
          error={shift.error}
        />
      ) : null}

      {/* Orders waiting nearby, takeable from here: what an online rider is looking for. */}
      {online && !trip ? (
        <NearbyOrders
          onSeeAll={() => nav.navigate('Main', { screen: 'Orders' })}
        />
      ) : null}

      {/* Today */}
      <Animated.View entering={FadeInDown.delay(120).duration(motion.base)}>
        <GuideTarget id={TARGETS.homeToday}>
          <Card tone="alt" style={styles.today}>
            <View style={styles.flex}>
              <AppText variant="micro" tone="muted">
                {t('home.todayEarnings')}
              </AppText>
              {loading && !me ? (
                <Skeleton width={120} height={30} style={styles.gapXs} />
              ) : (
                <AnimatedAmount
                  value={Number(me?.today_earnings ?? 0)}
                  style={styles.gapXs}
                />
              )}
            </View>
            <View
              style={[styles.divider, { backgroundColor: colors.border }]}
            />
            <View style={styles.tripsBox}>
              <AppText variant="micro" tone="muted">
                {t('home.trips')}
              </AppText>
              <AppText variant="money" style={styles.gapXs}>
                {me?.today_trips ?? 0}
              </AppText>
            </View>
          </Card>
        </GuideTarget>
      </Animated.View>

      {/* The week so far and what a delivery pays: useful between orders. */}
      {!trip ? <HomeInsights me={me} /> : null}

      {/* Status notes */}
      {permissions.state && !permissions.ready ? (
        <Card onPress={() => nav.navigate('Permissions')} style={styles.note}>
          <Icon name="warning" size={22} color={colors.warning} />
          <View style={styles.flex}>
            <AppText variant="bodyStrong">{t('home.finishSetup')}</AppText>
            <AppText variant="caption" tone="muted">
              {t('home.setupReason', {
                reason: gateReason(permissions.state) ?? '',
              })}
            </AppText>
          </View>
          <Icon name="chevron-forward" size={20} color={colors.textFaint} />
        </Card>
      ) : null}
      {me && !me.fleet_enabled ? (
        <Card style={styles.note}>
          <Icon name="information-circle" size={22} color={colors.primary} />
          <View style={styles.flex}>
            <AppText variant="bodyStrong">{t('home.practiceMode')}</AppText>
            <AppText variant="caption" tone="muted">
              {t('home.practiceModeBody')}
            </AppText>
          </View>
        </Card>
      ) : null}
      {online && location.error ? (
        <Card style={styles.note}>
          <Icon name="location-outline" size={22} color={colors.danger} />
          <View style={styles.flex}>
            <AppText variant="bodyStrong">{t('home.noLocation')}</AppText>
            <AppText variant="caption" tone="muted">
              {t('home.noLocationBody', { reason: location.error })}
            </AppText>
          </View>
        </Card>
      ) : null}
      {error && !me ? (
        <Card style={styles.note}>
          <Icon name="cloud-offline-outline" size={22} color={colors.danger} />
          <View style={styles.flex}>
            <AppText variant="bodyStrong">{t('home.noServer')}</AppText>
            <AppText variant="caption" tone="muted">
              {error}
            </AppText>
          </View>
        </Card>
      ) : null}
    </Screen>
  );
}

function RouteLine({
  colors,
}: {
  colors: { primary: string; success: string; border: string };
}) {
  return (
    <View style={styles.routeLine}>
      <View style={[styles.routeDot, { backgroundColor: colors.primary }]} />
      <View style={[styles.routeBar, { backgroundColor: colors.border }]} />
      <View style={[styles.routeDot, { backgroundColor: colors.success }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  content: { gap: space.lg },
  flex: { flex: 1 },
  flexGap: { flex: 1, justifyContent: 'space-between', gap: space.md },
  header: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  today: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: space.xl,
  },
  divider: { width: 1, alignSelf: 'stretch', marginHorizontal: space.lg },
  tripsBox: { minWidth: 72 },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  route: { flexDirection: 'row', gap: space.md, marginVertical: space.lg },
  routeLine: { alignItems: 'center', paddingVertical: 6 },
  routeDot: { width: 10, height: 10, borderRadius: 5 },
  routeBar: { width: 2, flex: 1, marginVertical: 4, borderRadius: 1 },
  note: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  gapXs: { marginTop: space.xs },
});
