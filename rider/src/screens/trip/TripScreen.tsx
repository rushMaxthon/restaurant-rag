import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  Keyboard,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
  type ScrollViewInstance,
} from 'react-native';
import Animated, {
  FadeIn,
  FadeInDown,
  FadeOut,
  LinearTransition,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { OtpInput } from '@components/trip/OtpInput';
import { ProblemSheet } from '@components/trip/ProblemSheet';
import { StepProgress } from '@components/trip/StepProgress';
import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { ConfirmDialog } from '@components/ui/ConfirmDialog';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { IconButton } from '@components/ui/IconButton';
import { Pill } from '@components/ui/Pill';
import { SlideToConfirm } from '@components/ui/SlideToConfirm';
import { useRiderLocation } from '@components/ShiftKeeper';
import { GuideTarget } from '@/guide/GuideProvider';
import { TARGETS } from '@/guide/tours';
import { useTour } from '@/guide/useTour';
import { useKeyboardHeight } from '@hooks/useKeyboardHeight';
import { useReadyLabel } from '@hooks/useReadyLabel';
import { useTripAction } from '@hooks/useTripAction';
import { nextSlide } from '@utils/tripSteps';
import { useI18n } from '@/i18n';
import { useNav } from '@navigation/types';
import { useRider } from '@/store/RiderProvider';
import type { Trip, TripStop } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, motion } from '@theme/tokens';
import { km, rupees } from '@utils/format';
import { awayLabel, metresBetween } from '@utils/geo';
import { haptic } from '@utils/haptics';
import { call, openNavigation } from '@utils/links';

export function TripScreen() {
  const { colors } = useTheme();
  const { t, plural } = useI18n();
  const insets = useSafeAreaInsets();
  const nav = useNav();
  const { trip, setTrip, refreshMe, refreshTrip } = useRider();
  const [otp, setOtp] = useState('');
  const [shake, setShake] = useState(0);
  const [problem, setProblem] = useState(false);
  const [askUnavailable, setAskUnavailable] = useState(false);
  // Folded to one row on the way there; open by default at the counter,
  // where the rider checks the bag against it. A tap overrides either way.
  const [itemsOpen, setItemsOpen] = useState<boolean | null>(null);
  const step = trip?.step;
  useEffect(() => setItemsOpen(null), [step]);
  const keyboard = useKeyboardHeight();
  const { lastFix } = useRiderLocation();
  const scroll = useRef<ScrollViewInstance>(null);

  // Keep the code boxes above the keys (edge-to-edge: the window does not resize).
  useEffect(() => {
    if (keyboard > 0)
      setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 50);
  }, [keyboard]);

  const onDone = useCallback(
    (next: Trip) => {
      haptic('success');
      if (next.step === 'done') {
        setTrip(null);
        void refreshMe();
        nav.replace('Delivered', {
          amount: next.earning,
          orderCode: next.order_code,
        });
        return;
      }
      setTrip(next);
    },
    [setTrip, refreshMe, nav],
  );
  const action = useTripAction(trip?.id, onDone);
  useTour('trip', trip?.step === 'to_pickup');
  useTour('otp', trip?.step === 'at_drop');

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
      const timer = setTimeout(() => nav.canGoBack() && nav.goBack(), 600);
      return () => clearTimeout(timer);
    }
  }, [trip, nav]);

  const stop: TripStop | null = useMemo(() => {
    if (!trip) return null;
    return trip.step === 'to_pickup' || trip.step === 'at_pickup'
      ? trip.pickup
      : trip.drop;
  }, [trip]);

  // When the food will be ready: shown while the rider is heading to, or
  // waiting at, the restaurant - after pickup it means nothing.
  const ready = useReadyLabel(trip?.ready_at);

  if (!trip || !stop) {
    return (
      <View style={[styles.empty, { backgroundColor: colors.bg }]}>
        <AppText tone="muted">{t('trip.ended')}</AppText>
      </View>
    );
  }

  const atRestaurant = trip.step === 'to_pickup' || trip.step === 'at_pickup';
  const showItems = itemsOpen ?? trip.step === 'at_pickup';
  const slide = nextSlide(trip.step);
  // Live, from this phone's own GPS: refreshed with every fix, no routing API.
  const heading = trip.step === 'to_pickup' || trip.step === 'to_drop';
  const away =
    heading && lastFix && stop.lat != null && stop.lng != null
      ? awayLabel(metresBetween(lastFix.lat, lastFix.lng, stop.lat, stop.lng))
      : null;
  const otpReason = trip.otp_locked
    ? t('trip.otpLocked')
    : otp.length < 4
    ? t('trip.askCode')
    : null;

  return (
    <View style={[styles.root, { backgroundColor: colors.bg }]}>
      {/* Header */}
      <View style={[styles.header, { paddingTop: insets.top + space.sm }]}>
        <IconButton
          icon="chevron-back"
          label={t('common.back')}
          onPress={() => nav.goBack()}
        />
        <View style={styles.headerText}>
          <AppText variant="heading">{trip.order_code}</AppText>
          <AppText variant="caption" tone="muted">
            {t('trip.headerMeta', {
              km: km(trip.distance_km),
              amount: rupees(trip.earning),
            })}
          </AppText>
        </View>
        <IconButton
          icon="help-circle-outline"
          label={t('trip.problemTitle')}
          onPress={() => setProblem(true)}
        />
      </View>

      <ScrollView
        ref={scroll}
        contentContainerStyle={[
          styles.scroll,
          keyboard > 0 && { paddingBottom: keyboard + space.xl },
        ]}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        <Animated.View entering={FadeInDown.duration(350)}>
          <GuideTarget id={TARGETS.tripSteps}>
            <StepProgress step={trip.step} />
          </GuideTarget>
        </Animated.View>

        {action.waitingForNetwork ? (
          <Animated.View entering={FadeIn} exiting={FadeOut}>
            <Card tone="alt" style={styles.banner}>
              <Icon name="cloud-offline" size={20} color={colors.warning} />
              <AppText variant="label" style={styles.flex}>
                {t('trip.noNetwork')}
              </AppText>
            </Card>
          </Animated.View>
        ) : null}

        {/* The current stop */}
        <Animated.View
          key={atRestaurant ? 'pickup' : 'drop'}
          entering={FadeInDown.duration(motion.base)}
          layout={LinearTransition}
        >
          <Card style={styles.stopCard}>
            <View style={styles.rowBetween}>
              <Pill
                label={
                  atRestaurant ? t('trip.pickUpFrom') : t('trip.deliverTo')
                }
                tone={atRestaurant ? 'primary' : 'success'}
                icon={atRestaurant ? 'restaurant' : 'home'}
              />
              {trip.step === 'at_pickup' || trip.step === 'at_drop' ? (
                <Pill label={t('trip.youAreHere')} tone="success" dot />
              ) : null}
            </View>
            <AppText variant="title" style={styles.gapMd}>
              {stop.name}
            </AppText>
            {atRestaurant && stop.branch && stop.branch !== stop.name ? (
              <AppText variant="label" tone="muted">
                {stop.branch}
              </AppText>
            ) : null}
            <AppText tone="muted" style={styles.gapXs}>
              {stop.address}
            </AppText>
            {atRestaurant && ready ? (
              <View
                style={[styles.away, { backgroundColor: colors.surfaceAlt }]}
              >
                <Icon name="restaurant" size={16} color={colors.text} />
                <AppText variant="label">{ready}</AppText>
              </View>
            ) : null}
            {away ? (
              <View
                style={[styles.away, { backgroundColor: colors.primarySoft }]}
              >
                <Icon name="navigate" size={16} color={colors.primary} />
                <AppText variant="label" tone="primary">
                  {away}
                </AppText>
              </View>
            ) : null}
            {!atRestaurant && stop.instructions ? (
              <Card tone="alt" style={styles.note}>
                <Icon
                  name="chatbubble-ellipses"
                  size={18}
                  color={colors.warning}
                />
                <AppText variant="label" style={styles.flex}>
                  {stop.instructions}
                </AppText>
              </Card>
            ) : null}
            <View style={styles.actionsRow}>
              <Button
                kind="secondary"
                size="md"
                icon="call"
                label={t('trip.call')}
                style={styles.flex}
                onPress={async () => {
                  const ok = await call(stop.phone);
                  if (ok && !atRestaurant && trip.step === 'at_drop')
                    action.run('call-logged');
                }}
                disabledReason={stop.phone ? null : t('trip.noPhone')}
              />
              <Button
                kind="primary"
                size="md"
                icon="navigate"
                label={t('trip.navigate')}
                style={styles.flex}
                onPress={() => openNavigation(stop.lat, stop.lng, stop.address)}
              />
            </View>
          </Card>
        </Animated.View>

        {/* What to collect */}
        {atRestaurant && trip.items.length > 0 ? (
          <Animated.View entering={FadeInDown.delay(80)}>
            <Card>
              <Pressable
                onPress={() => setItemsOpen(!showItems)}
                accessibilityRole="button"
                accessibilityState={{ expanded: showItems }}
                hitSlop={8}
                style={styles.itemsHead}
              >
                <Icon name="bag-handle" size={20} color={colors.primary} />
                <AppText variant="bodyStrong" style={styles.flex}>
                  {plural('trip.collect', trip.item_count)}
                </AppText>
                <Icon
                  name={showItems ? 'chevron-up' : 'chevron-down'}
                  size={18}
                  color={colors.textMuted}
                />
              </Pressable>
              {showItems &&
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
                      style={[
                        styles.qty,
                        { backgroundColor: colors.primarySoft },
                      ]}
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

        {/* Code + problems at the door */}
        {trip.step === 'at_drop' ? (
          <Animated.View entering={FadeInDown.duration(motion.base)}>
            <Card style={styles.otpCard}>
              <AppText variant="heading" align="center">
                {t('trip.customerCode')}
              </AppText>
              <AppText
                variant="caption"
                tone="muted"
                align="center"
                style={styles.gapXs}
              >
                {t('trip.codeWhere')}
              </AppText>
              <GuideTarget id={TARGETS.tripOtp} style={styles.gapLg}>
                <OtpInput
                  value={otp}
                  onChange={v => {
                    action.clearError();
                    setOtp(v);
                    // The fourth digit completes it: no hunting for a button under the keyboard.
                    if (v.length === 4 && !trip.otp_locked) {
                      Keyboard.dismiss();
                      action.run('delivered', v);
                    }
                  }}
                  shakeKey={shake}
                  error={action.error?.code === 'otp_wrong'}
                  disabled={trip.otp_locked}
                />
              </GuideTarget>
              {action.error?.code === 'otp_wrong' ? (
                <AppText
                  variant="label"
                  tone="danger"
                  align="center"
                  style={styles.gapSm}
                >
                  {plural('trip.wrongCode', trip.otp_attempts_left)}
                </AppText>
              ) : null}
              <Button
                kind="success"
                label={t('trip.completeDelivery')}
                icon="checkmark-done"
                style={styles.gapLg}
                loading={action.busy === 'delivered'}
                disabledReason={otpReason}
                onPress={() => action.run('delivered', otp)}
                testID="complete-delivery"
              />
              <Button
                kind="ghost"
                size="md"
                label={t('trip.notAnswering')}
                onPress={() => setProblem(true)}
              />
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
      {slide ? (
        <View
          style={[
            styles.footer,
            {
              paddingBottom: insets.bottom + space.md,
              backgroundColor: colors.bg,
              borderTopColor: colors.border,
            },
          ]}
        >
          <GuideTarget id={TARGETS.tripSlide}>
            <SlideToConfirm
              label={slide.label}
              icon={slide.icon}
              tone={slide.tone}
              busy={action.busy === slide.action}
              resetKey={trip.step}
              onConfirm={() => action.run(slide.action)}
              testID={`slide-${slide.action}`}
            />
          </GuideTarget>
        </View>
      ) : null}

      <ConfirmDialog
        open={askUnavailable}
        tone="danger"
        icon="person-remove"
        title={t('confirm.unavailable.title')}
        message={t('confirm.unavailable.body')}
        confirmLabel={t('confirm.unavailable.yes')}
        cancelLabel={t('confirm.unavailable.no')}
        busy={action.busy === 'unavailable'}
        onCancel={() => setAskUnavailable(false)}
        onConfirm={() => {
          setAskUnavailable(false);
          action.run('unavailable');
        }}
      />

      <ProblemSheet
        open={problem}
        onClose={() => setProblem(false)}
        trip={trip}
        onCustomerCalled={() => action.run('call-logged')}
        unavailableBusy={action.busy === 'unavailable'}
        onUnavailable={() => {
          // Ends the delivery: asked first, after the sheet has closed.
          setProblem(false);
          setAskUnavailable(true);
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  flex: { flex: 1 },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingHorizontal: space.lg,
    paddingBottom: space.sm,
  },
  headerText: { flex: 1 },
  scroll: { padding: space.lg, gap: space.md, paddingBottom: 140 },
  banner: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  stopCard: { borderRadius: radius.xxl },
  itemsHead: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  note: {
    flexDirection: 'row',
    gap: space.sm,
    alignItems: 'center',
    marginTop: space.md,
  },
  away: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.xs,
    alignSelf: 'flex-start',
    marginTop: space.md,
    paddingHorizontal: space.md,
    paddingVertical: space.xs + 2,
    borderRadius: radius.pill,
  },
  actionsRow: { flexDirection: 'row', gap: space.md, marginTop: space.lg },
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
  otpCard: { borderRadius: radius.xxl, paddingVertical: space.xl },
  footer: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  gapXs: { marginTop: space.xs },
  gapSm: { marginTop: space.sm },
  gapMd: { marginTop: space.md },
  gapLg: { marginTop: space.lg },
});
