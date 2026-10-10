import React, { useCallback, useEffect, useRef, useState } from 'react';
import { BackHandler, StyleSheet, Vibration, View } from 'react-native';
import Animated, { FadeIn, FadeInDown } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { ConfirmDialog } from '@components/ui/ConfirmDialog';
import { Card } from '@components/ui/Card';
import { CountdownRing } from '@components/ui/CountdownRing';
import { Icon } from '@components/ui/Icon';
import { Pill } from '@components/ui/Pill';
import { useI18n } from '@/i18n';
import { useReadyLabel } from '@hooks/useReadyLabel';
import { useNav } from '@navigation/types';
import { ApiError } from '@/services/http';
import { useRider } from '@/store/RiderProvider';
import { useApi } from '@/store/SessionProvider';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, motion } from '@theme/tokens';
import { distance, km } from '@utils/format';
import { jobMinutes } from '@utils/geo';
import { haptic } from '@utils/haptics';
import { earningLabel } from '@utils/pay';

/** Ring, ring, pause - repeated until the rider answers or time runs out. */
const RING = [0, 400, 200, 400, 900];

/**
 * A new order, full screen, impossible to miss: what it pays first and
 * biggest, then how far, then where. The ring is the server's own deadline;
 * when it runs out (or the server withdraws the offer) the screen closes.
 */
export function OfferScreen() {
  const { colors } = useTheme();
  const { t, plural } = useI18n();
  const insets = useSafeAreaInsets();
  const nav = useNav();
  const api = useApi();
  const { offer, clearOffer, setTrip, refreshMe } = useRider();
  const [busy, setBusy] = useState<'accept' | 'decline' | null>(null);
  const [askDecline, setAskDecline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shown] = useState(offer);
  const ready = useReadyLabel(shown?.ready_at);

  useEffect(() => {
    Vibration.vibrate(RING, true);
    haptic('heavy');
    return () => Vibration.cancel();
  }, []);

  // Android back is a decline by another name: asked the same way, never a
  // silent dismissal that leaves the order ringing for nobody.
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (busy === null) setAskDecline(true);
      return true;
    });
    return () => sub.remove();
  }, [busy]);

  // Withdrawn or taken elsewhere while on screen: close.
  useEffect(() => {
    if (shown && !offer && busy === null) nav.goBack();
  }, [offer, shown, busy, nav]);

  // Closing a moment after "taken by someone else": cleared if the screen
  // goes first (the offer can be withdrawn and the screen closed meanwhile).
  const closeLater = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (closeLater.current) clearTimeout(closeLater.current);
    },
    [],
  );

  const close = useCallback(() => {
    Vibration.cancel();
    clearOffer();
    if (nav.canGoBack()) nav.goBack();
  }, [clearOffer, nav]);

  const accept = useCallback(async () => {
    if (!shown) return;
    Vibration.cancel();
    setBusy('accept');
    setError(null);
    try {
      const trip = await api.accept(shown.id);
      haptic('success');
      setTrip(trip);
      clearOffer();
      void refreshMe();
      nav.replace('Trip');
    } catch (e) {
      haptic('error');
      setError(e instanceof ApiError ? e.message : t('trip.couldNotAccept'));
      setBusy(null);
      if (e instanceof ApiError && (e.status === 409 || e.status === 404))
        closeLater.current = setTimeout(close, 1400);
    }
  }, [api, shown, setTrip, clearOffer, refreshMe, nav, close, t]);

  const decline = useCallback(async () => {
    if (!shown) return;
    setBusy('decline');
    try {
      await api.decline(shown.id);
    } catch {
      // the offer expires on its own anyway
    }
    close();
  }, [api, shown, close]);

  if (!shown) return null;
  const expiresAt = new Date(shown.expires_at).getTime();

  return (
    <View
      style={[
        styles.root,
        {
          backgroundColor: colors.bg,
          paddingTop: insets.top + space.lg,
          paddingBottom: insets.bottom + space.lg,
        },
      ]}
    >
      <Animated.View entering={FadeIn.duration(250)} style={styles.top}>
        <Pill label={t('trip.newOrder')} tone="primary" icon="flash" />
        <AppText variant="caption" tone="muted">
          {plural('common.items', shown.item_count)}
        </AppText>
      </Animated.View>

      <View style={styles.body}>
        <Animated.View
          entering={FadeIn.duration(motion.slow)}
          style={styles.ring}
        >
          <CountdownRing
            expiresAt={expiresAt}
            totalMs={shown.total_seconds * 1000}
            size={128}
            onExpire={close}
          />
        </Animated.View>

        <Animated.View
          entering={FadeInDown.delay(80).duration(motion.base)}
          style={[styles.earn, { backgroundColor: colors.successSoft }]}
        >
          <AppText variant="micro" tone="success" align="center">
            {t('trip.youEarn')}
          </AppText>
          <AppText
            style={[styles.amount, { color: colors.text }]}
            align="center"
          >
            {earningLabel(shown.earning_estimate, t('money.priceLater'))}
          </AppText>
          <View style={styles.chips}>
            <Pill
              label={t('trip.toPickup', {
                distance: distance(shown.pickup_distance_m),
              })}
              icon="bicycle"
            />
            <Pill
              label={t('trip.tripKm', { km: km(shown.trip_distance_km) })}
              icon="navigate"
            />
            <Pill
              label={t('common.minAway', {
                n: jobMinutes(shown.pickup_distance_m, shown.trip_distance_km),
              })}
              icon="time"
            />
            {ready ? <Pill label={ready} icon="restaurant" /> : null}
          </View>
        </Animated.View>

        <Animated.View entering={FadeInDown.delay(160).duration(motion.base)}>
          <Card style={styles.route}>
            <Stop
              icon="restaurant"
              color={colors.primary}
              title={shown.restaurant_name}
              subtitle={shown.pickup_address}
              label={t('trip.pickUp')}
            />
            <View style={[styles.connector, { borderColor: colors.border }]} />
            <Stop
              icon="home"
              color={colors.success}
              title={shown.drop_area || t('trip.customer')}
              subtitle={t('trip.addressAfterAccept')}
              label={t('trip.deliverTo')}
            />
          </Card>
        </Animated.View>
      </View>

      {error ? (
        <AppText
          variant="label"
          tone="danger"
          align="center"
          style={styles.error}
        >
          {error}
        </AppText>
      ) : null}
      <Animated.View entering={FadeInDown.delay(220)} style={styles.actions}>
        <Button
          kind="secondary"
          label={t('trip.decline')}
          style={styles.decline}
          loading={busy === 'decline'}
          // Asked first: one thumb on the wrong side of the screen gave the
          // order away, and there is no taking it back from here.
          onPress={() => setAskDecline(true)}
        />
        <Button
          kind="success"
          label={t('trip.acceptOrder')}
          icon="checkmark-circle"
          style={styles.accept}
          loading={busy === 'accept'}
          onPress={accept}
          testID="offer-accept"
        />
      </Animated.View>
      <ConfirmDialog
        open={askDecline}
        tone="danger"
        icon="close-circle"
        title={t('confirm.decline.title')}
        message={t('confirm.decline.body')}
        confirmLabel={t('confirm.decline.yes')}
        cancelLabel={t('confirm.decline.no')}
        busy={busy === 'decline'}
        onCancel={() => setAskDecline(false)}
        onConfirm={() => {
          setAskDecline(false);
          void decline();
        }}
      />
    </View>
  );
}

function Stop({
  icon,
  color,
  title,
  subtitle,
  label,
}: {
  icon: 'restaurant' | 'home';
  color: string;
  title: string;
  subtitle: string;
  label: string;
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
        <AppText variant="bodyStrong" numberOfLines={1}>
          {title}
        </AppText>
        <AppText variant="caption" tone="muted" numberOfLines={2}>
          {subtitle}
        </AppText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, paddingHorizontal: space.lg },
  flex: { flex: 1 },
  top: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  // Sat at the bottom, over the buttons: the rider reads what it pays and
  // where it goes right where their thumb already is.
  body: { flex: 1, justifyContent: 'flex-end', paddingVertical: space.lg },
  ring: { alignItems: 'center' },
  earn: {
    alignItems: 'center',
    marginTop: space.xl,
    gap: space.xs,
    paddingVertical: space.lg,
    paddingHorizontal: space.md,
    borderRadius: radius.xxl,
  },
  amount: {
    fontFamily: 'PlusJakartaSans-ExtraBold',
    fontSize: 52,
    lineHeight: 60,
    letterSpacing: -1,
  },
  chips: {
    flexDirection: 'row',
    gap: space.sm,
    marginTop: space.sm,
    flexWrap: 'wrap',
    justifyContent: 'center',
  },
  route: { marginTop: space.lg, gap: space.xs, borderRadius: radius.xxl },
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
  actions: { flexDirection: 'row', gap: space.md },
  decline: { flex: 1 },
  accept: { flex: 2 },
  error: { marginBottom: space.md },
});
