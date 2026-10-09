import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View, type ViewStyle } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withSpring } from 'react-native-reanimated';

import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space, touch } from '@theme/tokens';
import { AppText } from './AppText';
import { Icon, type IconName } from './Icon';
import { haptic } from '@utils/haptics';

type Kind = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success';

export type ButtonProps = {
  label: string;
  onPress?: () => void;
  kind?: Kind;
  icon?: IconName;
  loading?: boolean;
  /** House rule: a disabled button says WHY, beside it, never just greys out. */
  disabledReason?: string | null;
  size?: 'md' | 'lg';
  style?: ViewStyle;
  testID?: string;
};

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

export function Button({ label, onPress, kind = 'primary', icon, loading, disabledReason, size = 'lg', style, testID }: ButtonProps) {
  const { colors } = useTheme();
  const scale = useSharedValue(1);
  const disabled = Boolean(disabledReason) || Boolean(loading);

  const palette = {
    primary: { bg: colors.primary, fg: colors.onPrimary, border: colors.primary },
    secondary: { bg: colors.surfaceAlt, fg: colors.text, border: colors.border },
    ghost: { bg: 'transparent', fg: colors.primary, border: 'transparent' },
    danger: { bg: colors.dangerSoft, fg: colors.danger, border: colors.dangerSoft },
    success: { bg: colors.success, fg: colors.onSuccess, border: colors.success },
  }[kind];

  const animated = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));

  return (
    <View style={style}>
      <AnimatedPressable
        testID={testID}
        accessibilityRole="button"
        accessibilityState={{ disabled, busy: Boolean(loading) }}
        accessibilityHint={disabledReason ?? undefined}
        disabled={disabled}
        onPressIn={() => {
          scale.value = withSpring(0.97, motion.springSnappy);
        }}
        onPressOut={() => {
          scale.value = withSpring(1, motion.springSnappy);
        }}
        onPress={() => {
          haptic('light');
          onPress?.();
        }}
        style={[
          styles.base,
          { minHeight: size === 'lg' ? touch.large : touch.min, backgroundColor: palette.bg, borderColor: palette.border },
          disabled && styles.disabled,
          animated,
        ]}
      >
        {loading ? (
          <ActivityIndicator color={palette.fg} />
        ) : (
          <View style={styles.row}>
            {icon ? <Icon name={icon} size={20} color={palette.fg} /> : null}
            <AppText variant="bodyStrong" style={{ color: palette.fg }}>
              {label}
            </AppText>
          </View>
        )}
      </AnimatedPressable>
      {disabledReason ? (
        <AppText variant="caption" tone="muted" align="center" style={styles.reason}>
          {disabledReason}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  base: {
    borderRadius: radius.lg,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.xl,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  disabled: { opacity: 0.5 },
  reason: { marginTop: space.xs },
});
