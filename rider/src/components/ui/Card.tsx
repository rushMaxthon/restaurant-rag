import React from 'react';
import { Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withSpring } from 'react-native-reanimated';

import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space } from '@theme/tokens';

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

/**
 * The app's one card: surface, hairline border, large radius, no shadow.
 * Flat on purpose - shadows in scrolling lists are expensive on a cheap
 * Android, and the border already separates. Pressable cards dip slightly.
 */
export function Card({
  children,
  style,
  onPress,
  padded = true,
  tone = 'surface',
  testID,
}: {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  onPress?: () => void;
  padded?: boolean;
  tone?: 'surface' | 'alt' | 'primary' | 'success';
  testID?: string;
}) {
  const { colors } = useTheme();
  const scale = useSharedValue(1);
  const animated = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));
  const bg = {
    surface: colors.surface,
    alt: colors.surfaceAlt,
    primary: colors.primarySoft,
    success: colors.successSoft,
  }[tone];
  const border = tone === 'primary' ? colors.primary : tone === 'success' ? colors.success : colors.border;
  const base = [styles.card, padded && styles.padded, { backgroundColor: bg, borderColor: border }, style];

  if (!onPress) {
    return (
      <View testID={testID} style={base}>
        {children}
      </View>
    );
  }
  return (
    <AnimatedPressable
      testID={testID}
      accessibilityRole="button"
      onPress={onPress}
      onPressIn={() => (scale.value = withSpring(0.98, motion.springSnappy))}
      onPressOut={() => (scale.value = withSpring(1, motion.springSnappy))}
      style={[base, animated]}
    >
      {children}
    </AnimatedPressable>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: radius.xl, borderWidth: StyleSheet.hairlineWidth * 2 },
  padded: { padding: space.lg },
});
