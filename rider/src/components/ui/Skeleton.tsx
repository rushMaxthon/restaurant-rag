import React, { useEffect } from 'react';
import { type DimensionValue, type ViewStyle } from 'react-native';
import Animated, {
  Easing,
  interpolateColor,
  makeMutable,
  useAnimatedStyle,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import { useTheme } from '@theme/ThemeProvider';
import { radius } from '@theme/tokens';

/**
 * ONE pulse shared by every placeholder on screen - the kitchen app's lesson:
 * a loop per skeleton is costly on a cheap phone, and separate loops drift
 * out of step and shimmer unevenly.
 */
const pulse = makeMutable(0);
let started = false;
function ensurePulse() {
  if (started) {
    return;
  }
  started = true;
  pulse.value = withRepeat(withTiming(1, { duration: 900, easing: Easing.inOut(Easing.quad) }), -1, true);
}

export type SkeletonProps = {
  width?: DimensionValue;
  height?: number;
  round?: number;
  style?: ViewStyle;
};

export function Skeleton({ width = '100%', height = 16, round = radius.sm, style }: SkeletonProps) {
  const { colors } = useTheme();
  useEffect(ensurePulse, []);
  const base = colors.skeleton;
  const sheen = colors.skeletonSheen;
  const animated = useAnimatedStyle(() => ({
    backgroundColor: interpolateColor(pulse.value, [0, 1], [base, sheen]),
  }));
  return <Animated.View accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={[{ width, height, borderRadius: round }, animated, style]} />;
}
