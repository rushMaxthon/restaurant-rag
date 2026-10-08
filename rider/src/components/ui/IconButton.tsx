import React from 'react';
import { Pressable, StyleSheet } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withSpring } from 'react-native-reanimated';

import { useTheme } from '@theme/ThemeProvider';
import { motion, touch } from '@theme/tokens';
import { haptic } from '@utils/haptics';
import { Icon, type IconName } from './Icon';

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

export function IconButton({
  icon,
  onPress,
  label,
  tone = 'neutral',
  size = touch.min,
}: {
  icon: IconName;
  onPress: () => void;
  /** Read aloud by TalkBack: an icon alone says nothing. */
  label: string;
  tone?: 'neutral' | 'primary' | 'success' | 'danger';
  size?: number;
}) {
  const { colors } = useTheme();
  const scale = useSharedValue(1);
  const animated = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));
  const palette = {
    neutral: { bg: colors.surfaceAlt, fg: colors.text },
    primary: { bg: colors.primarySoft, fg: colors.primary },
    success: { bg: colors.successSoft, fg: colors.success },
    danger: { bg: colors.dangerSoft, fg: colors.danger },
  }[tone];
  return (
    <AnimatedPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={6}
      onPressIn={() => (scale.value = withSpring(0.9, motion.springSnappy))}
      onPressOut={() => (scale.value = withSpring(1, motion.springSnappy))}
      onPress={() => {
        haptic('light');
        onPress();
      }}
      style={[styles.btn, { width: size, height: size, borderRadius: size / 2, backgroundColor: palette.bg }, animated]}
    >
      <Icon name={icon} size={size * 0.45} color={palette.fg} />
    </AnimatedPressable>
  );
}

const styles = StyleSheet.create({ btn: { alignItems: 'center', justifyContent: 'center' } });
