import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Keyboard, ScrollView, StyleSheet, View, type ScrollViewInstance } from 'react-native';
import Animated, { FadeIn, FadeInDown, FadeOut, LinearTransition } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { OtpInput } from '@components/trip/OtpInput';
import { StepTracker } from '@components/trip/StepTracker';
import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { IconButton } from '@components/ui/IconButton';
import { Pill } from '@components/ui/Pill';
import { SlideToConfirm } from '@components/ui/SlideToConfirm';
import { useKeyboardHeight } from '@hooks/useKeyboardHeight';
import { useTripAction } from '@hooks/useTripAction';
import { useNav } from '@navigation/types';
import { SUPPORT_PHONE } from '@/config/api';
import { useRider } from '@/store/RiderProvider';
import type { Trip, TripStop } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';
import { km, rupees } from '@utils/format';
import { haptic } from '@utils/haptics';
import { call, openNavigation } from '@utils/links';

const WAIT_MINUTES = 10;

export function TripScreen() {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const nav = useNav();
  const { trip, setTrip, refreshMe, refreshTrip } = useRider();
  const [otp, setOtp] = useState('');
  const [shake, setShake] = useState(0);
  const [showProblem, setShowProblem] = useState(false);
  const keyboard = useKeyboardHeight();
  const scroll = useRef<ScrollViewInstance>(null);

  // Keep the code boxes above the keys (edge-to-edge: the window does not resize).
  useEffect(() => {
    if (keyboard > 0) setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 50);
  }, [keyboard]);

  const onDone = useCallback(
    (next: Trip) => {
      haptic('success');
      if (next.step === 'done') {
        setTrip(null);
        void refreshMe();
        nav.replace('Delivered', { amount: next.earning, orderCode: next.order_code });
        return;
      }
      setTrip(next);
    },
    [setTrip, refreshMe, nav],
  );
  const action = useTripAction(trip?.id, onDone);

  // A wrong code: shake, clear, refresh the attempts left.
  useEffect(() => {
    if (action.error?.code === 'otp_wrong') {
      haptic('error');
      setShake(s => s + 1);
      setOtp('');
      void refreshTrip();
    }
  }, [action.error, refreshTrip]);

  useEffect(() => {
    if (!trip) {
      const t = setTimeout(() => nav.canGoBack() && nav.goBack(), 600);
      return () => clearTimeout(t);
    }
  }, [trip, nav]);

  const stop: TripStop | null = useMemo(() => {
    if (!trip) return null;
    return trip.step === 'to_pickup' || trip.step === 'at_pickup' ? trip.pickup : trip.drop;
  }, [trip]);

  if (!trip || !stop) {
    return (
      <View style={[styles.empty, { backgroundColor: colors.bg }]}>
        <AppText tone="muted">This delivery has ended.</AppText>
      </View>
    );
  }

  const atRestaurant = trip.step === 'to_pickup' || trip.step === 'at_pickup';
  const waitedMin = trip.arrived_drop_at ? (Date.now() - new Date(trip.arrived_drop_at).getTime()) / 60_000 : 0;
  const canGiveUp = waitedMin >= WAIT_MINUTES && trip.call_attempts >= 2;
  const otpReason = trip.otp_locked
    ? 'Code locked after wrong tries. Call support.'
    : otp.length < 4
      ? 'Ask the customer for their 4-digit code'
      : null;

  return (
    <View style={[styles.root, { backgroundColor: colors.bg }]}>
      {/* Header */}
      <View style={[styles.header, { paddingTop: insets.top + space.sm }]}>
        <IconButton icon="chevron-back" label="Back" onPress={() => nav.goBack()} />
        <View style={styles.headerText}>
          <AppText variant="heading">{trip.order_code}</AppText>
          <AppText variant="caption" tone="muted">
            {km(trip.distance_km)} · you earn {rupees(trip.earning)}
          </AppText>
        </View>
        <IconButton icon="headset" label="Call support" onPress={() => call(SUPPORT_PHONE)} />
      </View>

      <ScrollView
        ref={scroll}
        contentContainerStyle={[styles.scroll, keyboard > 0 && { paddingBottom: keyboard + space.xl }]}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        <Animated.View entering={FadeInDown.duration(350)}>
          <Card>
            <StepTracker step={trip.step} />
          </Card>
        </Animated.View>

        {action.waitingForNetwork ? (
          <Animated.View entering={FadeIn} exiting={FadeOut}>
            <Card tone="alt" style={styles.banner}>
              <Icon name="cloud-offline" size={20} color={colors.warning} />
              <AppText variant="label" style={styles.flex}>
                No network. Your step is saved and will be sent automatically.
              </AppText>
            </Card>
          </Animated.View>
        ) : null}

        {/* The current stop */}
        <Animated.View key={atRestaurant ? 'pickup' : 'drop'} entering={FadeInDown.springify().damping(18)} layout={LinearTransition}>
          <Card style={styles.stopCard}>
            <View style={styles.rowBetween}>
              <Pill
                label={atRestaurant ? 'Pick up from' : 'Deliver to'}
                tone={atRestaurant ? 'primary' : 'success'}
                icon={atRestaurant ? 'restaurant' : 'home'}
              />
              {trip.step === 'at_pickup' || trip.step === 'at_drop' ? <Pill label="You are here" tone="success" dot /> : null}
            </View>
            <AppText variant="title" style={styles.gapMd}>
              {stop.name}
            </AppText>
            {atRestaurant && stop.branch && stop.branch !== stop.name ? (
              <AppText variant="label" tone="muted">{stop.branch}</AppText>
            ) : null}
            <AppText tone="muted" style={styles.gapXs}>
              {stop.address}
            </AppText>
            {!atRestaurant && stop.instructions ? (
              <Card tone="alt" style={styles.note}>
                <Icon name="chatbubble-ellipses" size={18} color={colors.warning} />
                <AppText variant="label" style={styles.flex}>{stop.instructions}</AppText>
              </Card>
            ) : null}
            <View style={styles.actionsRow}>
              <Button
                kind="secondary"
                size="md"
                icon="call"
                label="Call"
                style={styles.flex}
                onPress={async () => {
                  const ok = await call(stop.phone);
                  if (ok && !atRestaurant && trip.step === 'at_drop') action.run('call-logged');
                }}
                disabledReason={stop.phone ? null : 'No phone number'}
              />
              <Button kind="primary" size="md" icon="navigate" label="Navigate" style={styles.flex} onPress={() => openNavigation(stop.lat, stop.lng, stop.address)} />
            </View>
          </Card>
        </Animated.View>

        {/* What to collect */}
        {atRestaurant && trip.items.length > 0 ? (
          <Animated.View entering={FadeInDown.delay(80)}>
            <Card>
              <AppText variant="label" tone="muted">
                COLLECT {trip.item_count} ITEM{trip.item_count === 1 ? '' : 'S'}
              </AppText>
              {trip.items.map((item, i) => (
                <View key={`${item.name}-${i}`} style={[styles.item, { borderTopColor: colors.border }, i === 0 && styles.firstItem]}>
                  <View style={[styles.qty, { backgroundColor: colors.primarySoft }]}>
                    <AppText variant="label" tone="primary">{item.quantity}×</AppText>
                  </View>
                  <AppText variant="bodyStrong" style={styles.flex} numberOfLines={2}>
                    {item.name}
                  </AppText>
                </View>
              ))}
            </Card>
          </Animated.View>
        ) : null}

        {/* Code + problems at the door */}
        {trip.step === 'at_drop' ? (
          <Animated.View entering={FadeInDown.springify().damping(18)}>
            <Card style={styles.otpCard}>
              <AppText variant="heading" align="center">Customer's code</AppText>
              <AppText variant="caption" tone="muted" align="center" style={styles.gapXs}>
                The customer sees it on their order page.
              </AppText>
              <View style={styles.gapLg}>
                <OtpInput value={otp} onChange={v => {
                    action.clearError();
                    setOtp(v);
                    // The fourth digit completes it: no hunting for a button under the keyboard.
                    if (v.length === 4 && !trip.otp_locked) {
                      Keyboard.dismiss();
                      action.run('delivered', v);
                    }
                  }} shakeKey={shake} error={action.error?.code === 'otp_wrong'} disabled={trip.otp_locked} />
              </View>
              {action.error?.code === 'otp_wrong' ? (
                <AppText variant="label" tone="danger" align="center" style={styles.gapSm}>
                  Wrong code. {trip.otp_attempts_left} {trip.otp_attempts_left === 1 ? 'try' : 'tries'} left.
                </AppText>
              ) : null}
              <Button
                kind="success"
                label="Complete delivery"
                icon="checkmark-done"
                style={styles.gapLg}
                loading={action.busy === 'delivered'}
                disabledReason={otpReason}
                onPress={() => action.run('delivered', otp)}
                testID="complete-delivery"
              />
              <Button kind="ghost" size="md" label={showProblem ? 'Hide' : 'Customer not answering?'} onPress={() => setShowProblem(p => !p)} />
              {showProblem ? (
                <Animated.View entering={FadeInDown} style={styles.problem}>
                  <AppText variant="caption" tone="muted" align="center">
                    Call the customer at least twice and wait {WAIT_MINUTES} minutes at the door. Calls made: {trip.call_attempts}.
                  </AppText>
                  <Button
                    kind="danger"
                    size="md"
                    icon="person-remove"
                    label="Customer unavailable"
                    loading={action.busy === 'unavailable'}
                    disabledReason={canGiveUp ? null : `Available after ${WAIT_MINUTES} min and 2 calls`}
                    onPress={() => action.run('unavailable')}
                  />
                </Animated.View>
              ) : null}
            </Card>
          </Animated.View>
        ) : null}

        {action.error && action.error.code !== 'otp_wrong' ? (
          <AppText variant="label" tone="danger" align="center">
            {action.error.message}
          </AppText>
        ) : null}
      </ScrollView>

      {/* The one big next step */}
      {trip.step !== 'at_drop' ? (
        <View style={[styles.footer, { paddingBottom: insets.bottom + space.md, backgroundColor: colors.bg, borderTopColor: colors.border }]}>
          {trip.step === 'to_pickup' ? (
            <SlideToConfirm label="Arrived at restaurant" icon="restaurant" busy={action.busy === 'arrived-pickup'} resetKey={trip.step} onConfirm={() => action.run('arrived-pickup')} testID="slide-arrived-pickup" />
          ) : trip.step === 'at_pickup' ? (
            <SlideToConfirm label="Picked up the order" icon="bag-check" busy={action.busy === 'picked-up'} resetKey={trip.step} onConfirm={() => action.run('picked-up')} testID="slide-picked-up" />
          ) : (
            <SlideToConfirm label="Arrived at customer" tone="success" icon="home" busy={action.busy === 'arrived-drop'} resetKey={trip.step} onConfirm={() => action.run('arrived-drop')} testID="slide-arrived-drop" />
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  flex: { flex: 1 },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingHorizontal: space.lg, paddingBottom: space.sm },
  headerText: { flex: 1 },
  scroll: { padding: space.lg, gap: space.lg, paddingBottom: 140 },
  banner: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  stopCard: { borderRadius: radius.xxl },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  note: { flexDirection: 'row', gap: space.sm, alignItems: 'center', marginTop: space.md },
  actionsRow: { flexDirection: 'row', gap: space.md, marginTop: space.lg },
  item: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: space.md, borderTopWidth: StyleSheet.hairlineWidth },
  firstItem: { borderTopWidth: 0, marginTop: space.sm },
  qty: { minWidth: 40, paddingHorizontal: space.sm, paddingVertical: space.xs, borderRadius: radius.sm, alignItems: 'center' },
  otpCard: { borderRadius: radius.xxl, paddingVertical: space.xl },
  problem: { gap: space.sm, marginTop: space.sm },
  footer: { position: 'absolute', left: 0, right: 0, bottom: 0, paddingHorizontal: space.lg, paddingTop: space.md, borderTopWidth: StyleSheet.hairlineWidth },
  gapXs: { marginTop: space.xs },
  gapSm: { marginTop: space.sm },
  gapMd: { marginTop: space.md },
  gapLg: { marginTop: space.lg },
});
