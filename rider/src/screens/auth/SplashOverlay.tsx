import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, {
  Easing,
  FadeOut,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { BrandMark } from '@components/ui/BrandMark';
import { useI18n } from '@/i18n';
import { useTheme } from '@theme/ThemeProvider';
import { space, motion } from '@theme/tokens';

const MIN_VISIBLE_MS = 1100;

/**
 * The first second: the mark springs in, the name rises under it, three dots
 * breathe while the saved session is read. Held for a minimum so a fast
 * restore does not flash, then fades away over whatever screen is ready.
 */
export function SplashOverlay({ ready }: { ready: boolean }) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const [minElapsed, setMinElapsed] = useState(false);
  const scale = useSharedValue(0.6);
  const lift = useSharedValue(16);
  const fade = useSharedValue(0);
  const pulse = useSharedValue(0);

  useEffect(() => {
    scale.value = withSpring(1, motion.springSoft);
    lift.value = withDelay(180, withSpring(0, motion.springSoft));
    fade.value = withDelay(180, withTiming(1, { duration: 420 }));
    pulse.value = withDelay(
      500,
      withRepeat(
        withSequence(
          withTiming(1, { duration: 600, easing: Easing.inOut(Easing.quad) }),
          withTiming(0, { duration: 600 }),
        ),
        -1,
      ),
    );
    const timer = setTimeout(() => setMinElapsed(true), MIN_VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [scale, lift, fade, pulse]);

  const mark = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));
  const words = useAnimatedStyle(() => ({
    opacity: fade.value,
    transform: [{ translateY: lift.value }],
  }));
  const dots = useAnimatedStyle(() => ({ opacity: 0.35 + pulse.value * 0.65 }));

  if (ready && minElapsed) return null;

  return (
    <Animated.View
      exiting={FadeOut.duration(320)}
      style={[
        StyleSheet.absoluteFill,
        styles.root,
        { backgroundColor: colors.bg },
      ]}
    >
      <Animated.View style={mark}>
        <BrandMark size={96} />
      </Animated.View>
      <Animated.View style={[styles.words, words]}>
        <AppText variant="display" align="center">
          Foodie{' '}
          <AppText variant="display" tone="primary">
            Rider
          </AppText>
        </AppText>
        <AppText tone="muted" align="center">
          {t('account.splash.tagline')}
        </AppText>
      </Animated.View>
      <Animated.View style={[styles.dots, dots]}>
        {[0, 1, 2].map(i => (
          <View
            key={i}
            style={[styles.dot, { backgroundColor: colors.primary }]}
          />
        ))}
      </Animated.View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  root: { alignItems: 'center', justifyContent: 'center', zIndex: 10 },
  words: { marginTop: space.xl, gap: space.xs },
  dots: {
    position: 'absolute',
    bottom: 72,
    flexDirection: 'row',
    gap: space.sm,
  },
  dot: { width: 8, height: 8, borderRadius: 4 },
});
