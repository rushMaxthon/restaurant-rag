import React, { forwardRef, useState } from 'react';
import { translate } from '@/i18n/translate';
import { Pressable, StyleSheet, TextInput, View, type TextInputInstance, type TextInputProps } from 'react-native';
import Animated, { interpolateColor, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';

import { useTheme } from '@theme/ThemeProvider';
import { font, motion, radius, space, touch } from '@theme/tokens';
import { AppText } from './AppText';
import { Icon, type IconName } from './Icon';

type Props = TextInputProps & {
  label: string;
  icon?: IconName;
  error?: string | null;
  prefix?: string;
  secure?: boolean;
};

/**
 * Label above, icon inside, the border lights up in the accent on focus and
 * turns red with the error written beneath - never a red border with no words.
 */
export const TextField = forwardRef<TextInputInstance, Props>(function TextField(
  { label, icon, error, prefix, secure, style, onFocus, onBlur, ...rest },
  ref,
) {
  const { colors } = useTheme();
  const focus = useSharedValue(0);
  const [hidden, setHidden] = useState(Boolean(secure));
  const animated = useAnimatedStyle(() => ({
    borderColor: error
      ? colors.danger
      : interpolateColor(focus.value, [0, 1], [colors.border, colors.primary]),
    backgroundColor: interpolateColor(focus.value, [0, 1], [colors.surfaceAlt, colors.surface]),
  }));

  return (
    <View style={style}>
      <AppText variant="label" tone="muted" style={styles.label}>
        {label}
      </AppText>
      <Animated.View style={[styles.box, animated]}>
        {icon ? <Icon name={icon} size={20} color={colors.textMuted} /> : null}
        {prefix ? (
          <AppText variant="bodyStrong" tone="muted">
            {prefix}
          </AppText>
        ) : null}
        <TextInput
          ref={ref}
          placeholderTextColor={colors.textFaint}
          selectionColor={colors.primary}
          secureTextEntry={hidden}
          style={[styles.input, { color: colors.text }]}
          onFocus={e => {
            focus.value = withTiming(1, { duration: motion.fast });
            onFocus?.(e);
          }}
          onBlur={e => {
            focus.value = withTiming(0, { duration: motion.fast });
            onBlur?.(e);
          }}
          {...rest}
        />
        {secure ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={
              hidden
                ? translate('common.showPassword')
                : translate('common.hidePassword')
            }
            hitSlop={10}
            onPress={() => setHidden(h => !h)}
          >
            <Icon name={hidden ? 'eye-outline' : 'eye-off-outline'} size={20} color={colors.textMuted} />
          </Pressable>
        ) : null}
      </Animated.View>
      {error ? (
        <AppText variant="caption" tone="danger" style={styles.error}>
          {error}
        </AppText>
      ) : null}
    </View>
  );
});

const styles = StyleSheet.create({
  label: { marginBottom: space.xs + 2 },
  box: {
    minHeight: touch.large,
    borderRadius: radius.lg,
    borderWidth: 1.5,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingHorizontal: space.lg,
  },
  input: { flex: 1, fontFamily: font.semibold, fontSize: 17, paddingVertical: space.md },
  error: { marginTop: space.xs },
});
