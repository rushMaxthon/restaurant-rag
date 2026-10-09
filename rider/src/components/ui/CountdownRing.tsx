import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, { cancelAnimation, Easing, useAnimatedProps, useSharedValue, withTiming } from 'react-native-reanimated';
import Svg, { Circle } from 'react-native-svg';

import { useI18n } from '@/i18n';
import { useTheme } from '@theme/ThemeProvider';
import { secondsLeft } from '@utils/time';
import { AppText } from './AppText';

const AnimatedCircle = Animated.createAnimatedComponent(Circle);

export type CountdownRingProps = {
  /** Epoch ms when the offer stops being acceptable - the SERVER's clock decides. */
  expiresAt: number;
  /** The whole window, so the ring starts at the right length mid-way through. */
  totalMs: number;
  size?: number;
  onExpire?: () => void;
};

/**
 * The shrinking ring on a new-order alert.
 *
 * The ring is a single UI-thread timing animation from now to `expiresAt`, so
 * it never stutters; the number in the middle is JS state, refreshed four
 * times a second so it never skips a digit. Amber in the last ten seconds:
 * urgency a rider can see without reading.
 */
export function CountdownRing({ expiresAt, totalMs, size = 120, onExpire }: CountdownRingProps) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const stroke = 8;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const progress = useSharedValue(1);
  const [left, setLeft] = useState(() => secondsLeft(expiresAt, Date.now()));
  const expireRef = useRef(onExpire);
  expireRef.current = onExpire;

  useEffect(() => {
    const remaining = Math.max(0, expiresAt - Date.now());
    progress.value = Math.min(1, remaining / Math.max(totalMs, 1));
    progress.value = withTiming(0, { duration: remaining, easing: Easing.linear });
    let fired = false;
    const timer = setInterval(() => {
      const s = secondsLeft(expiresAt, Date.now());
      setLeft(s);
      if (s === 0 && !fired) {
        fired = true;
        clearInterval(timer);
        expireRef.current?.();
      }
    }, 250);
    return () => {
      clearInterval(timer);
      cancelAnimation(progress);
    };
  }, [expiresAt, totalMs, progress]);

  const animatedProps = useAnimatedProps(() => ({
    strokeDashoffset: circumference * (1 - progress.value),
  }));

  const urgent = left <= 10;

  return (
    <View
      style={{ width: size, height: size }}
      accessible
      accessibilityRole="timer"
      accessibilityLabel={t('trip.secondsLeftA11y', { n: left })}
    >
      <Svg width={size} height={size} style={styles.svg}>
        <Circle cx={size / 2} cy={size / 2} r={r} stroke={colors.surfaceAlt} strokeWidth={stroke} fill="none" />
        <AnimatedCircle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={urgent ? colors.warning : colors.primary}
          strokeWidth={stroke}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={`${circumference} ${circumference}`}
          animatedProps={animatedProps}
        />
      </Svg>
      <View style={styles.center}>
        <AppText variant="display" tone={urgent ? 'warning' : 'default'}>
          {left}
        </AppText>
        <AppText variant="micro" tone="muted">
          {t('trip.seconds')}
        </AppText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  svg: { transform: [{ rotate: '-90deg' }] },
  center: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, alignItems: 'center', justifyContent: 'center' },
});
