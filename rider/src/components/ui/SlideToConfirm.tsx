import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View, type LayoutChangeEvent } from 'react-native';
import { GestureDetector, usePanGesture } from 'react-native-gesture-handler';
import Animated, {
  interpolate,
  Extrapolation,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import { scheduleOnRN } from 'react-native-worklets';

import { useI18n } from '@/i18n';
import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space, touch } from '@theme/tokens';
import { haptic } from '@utils/haptics';
import { AppText } from './AppText';
import { Icon, type IconName } from './Icon';

export type SlideToConfirmProps = {
  label: string;
  onConfirm: () => void;
  /** Shown on the knob after the slide completes, until `resetKey` changes. */
  busy?: boolean;
  /** Change it (e.g. to the next trip step) to bring the knob home. */
  resetKey?: string | number;
  tone?: 'primary' | 'success';
  icon?: IconName;
  /** House rule: a control that cannot be used says why, beside it. */
  disabledReason?: string | null;
  testID?: string;
};

const KNOB = touch.large;
const PAD = 4;
/** Past this share of the track a release confirms; short of it, springs back. */
export const CONFIRM_AT = 0.85;

/**
 * "Slide to pick up" / "Slide to deliver".
 *
 * A slide rather than a tap because these two actions move real food and
 * real money: a tap fires from a pocket or a bump on the road, a deliberate
 * slide does not. The whole gesture runs on the UI thread (gesture handler +
 * Reanimated worklets), so the knob tracks the thumb at 60 fps even while the
 * JS thread is busy with a network call or a location batch - which is
 * exactly when a rider is using it.
 */
export function SlideToConfirm({
  label,
  onConfirm,
  busy = false,
  resetKey,
  tone = 'primary',
  icon = 'arrow-forward',
  disabledReason,
  testID,
}: SlideToConfirmProps) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const accent = tone === 'success' ? colors.success : colors.primary;
  const onAccent = tone === 'success' ? colors.onSuccess : colors.onPrimary;
  const disabled = Boolean(disabledReason);

  const x = useSharedValue(0);
  const maxX = useSharedValue(0);
  const armed = useSharedValue(false);
  const done = useSharedValue(false);
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    // A new step (or a failed request) brings the knob home.
    done.value = false;
    armed.value = false;
    x.value = withSpring(0, motion.spring);
    setConfirmed(false);
  }, [resetKey, done, armed, x]);

  const onLayout = useCallback(
    (e: LayoutChangeEvent) => {
      maxX.value = Math.max(0, e.nativeEvent.layout.width - KNOB - PAD * 2);
    },
    [maxX],
  );

  const fire = useCallback(() => {
    setConfirmed(true);
    haptic('success');
    onConfirm();
  }, [onConfirm]);

  const gesture = usePanGesture({
    enabled: !disabled && !confirmed,
    activeOffsetX: [-8, 8],
    failOffsetY: [-24, 24],
    onUpdate: e => {
      'worklet';
      if (done.value) return;
      const next = Math.min(Math.max(e.translationX, 0), maxX.value);
      x.value = next;
      const isArmed = next >= maxX.value * CONFIRM_AT;
      if (isArmed !== armed.value) {
        armed.value = isArmed;
        scheduleOnRN(haptic, 'tick');
      }
    },
    onDeactivate: () => {
      'worklet';
      if (done.value) return;
      if (maxX.value > 0 && x.value >= maxX.value * CONFIRM_AT) {
        done.value = true;
        x.value = withSpring(maxX.value, motion.springSnappy);
        scheduleOnRN(fire);
      } else {
        armed.value = false;
        x.value = withSpring(0, motion.spring);
      }
    },
  });

  const knobStyle = useAnimatedStyle(() => ({ transform: [{ translateX: x.value }] }));
  const fillStyle = useAnimatedStyle(() => ({ width: x.value + KNOB + PAD }));
  const labelStyle = useAnimatedStyle(() => ({
    opacity: interpolate(x.value, [0, Math.max(maxX.value * 0.6, 1)], [1, 0], Extrapolation.CLAMP),
    transform: [{ translateX: interpolate(x.value, [0, Math.max(maxX.value, 1)], [0, 24], Extrapolation.CLAMP) }],
  }));
  const chevronStyle = useAnimatedStyle(() => ({
    opacity: withTiming(armed.value ? 0 : 1, { duration: motion.fast }),
  }));

  return (
    <View>
      <GestureDetector gesture={gesture}>
        <View
          testID={testID}
          accessible
          accessibilityRole="adjustable"
          accessibilityLabel={label}
          accessibilityHint={disabledReason ?? t('trip.slideHint')}
          accessibilityState={{ disabled, busy }}
          accessibilityActions={[{ name: 'activate', label }]}
          onAccessibilityAction={() => !disabled && !confirmed && fire()}
          onLayout={onLayout}
          style={[styles.track, { backgroundColor: colors.surfaceAlt, borderColor: colors.border }, disabled && styles.disabled]}
        >
          <Animated.View style={[styles.fill, { backgroundColor: accent }, fillStyle]} />
          <Animated.View style={[styles.labelWrap, labelStyle]} pointerEvents="none">
            <AppText variant="bodyStrong" tone="default">
              {label}
            </AppText>
            <Animated.View style={chevronStyle}>
              <Icon name="chevron-forward" size={18} color={colors.textFaint} />
            </Animated.View>
          </Animated.View>
          <Animated.View style={[styles.knob, { backgroundColor: accent }, knobStyle]}>
            {busy ? <ActivityIndicator color={onAccent} /> : <Icon name={confirmed ? 'checkmark' : icon} size={26} color={onAccent} />}
          </Animated.View>
        </View>
      </GestureDetector>
      {disabledReason ? (
        <AppText variant="caption" tone="muted" align="center" style={styles.reason}>
          {disabledReason}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  track: {
    height: KNOB + PAD * 2,
    borderRadius: radius.pill,
    borderWidth: 1,
    justifyContent: 'center',
    overflow: 'hidden',
  },
  fill: { position: 'absolute', left: 0, top: 0, bottom: 0, borderRadius: radius.pill, opacity: 0.22 },
  labelWrap: {
    position: 'absolute',
    left: KNOB + PAD * 2,
    right: space.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.xs,
  },
  knob: {
    position: 'absolute',
    left: PAD,
    width: KNOB,
    height: KNOB,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  disabled: { opacity: 0.5 },
  reason: { marginTop: space.xs },
});
