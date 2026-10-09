import React, { useEffect, useRef } from 'react';
import { Pressable, StyleSheet, TextInput, View, type TextInputInstance } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withSequence, withTiming } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { useI18n } from '@/i18n';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';

/**
 * Four boxes over one hidden input, so the number pad, paste and backspace
 * all just work. `shakeKey` changing shakes the row (a wrong code).
 */
export function OtpInput({
  value,
  onChange,
  shakeKey,
  error,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  shakeKey?: number;
  error?: boolean;
  disabled?: boolean;
}) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const input = useRef<TextInputInstance>(null);
  const shake = useSharedValue(0);

  useEffect(() => {
    if (!shakeKey) return;
    shake.value = withSequence(
      withTiming(-10, { duration: 50 }),
      withTiming(10, { duration: 50 }),
      withTiming(-8, { duration: 50 }),
      withTiming(8, { duration: 50 }),
      withTiming(0, { duration: 50 }),
    );
  }, [shakeKey, shake]);

  const row = useAnimatedStyle(() => ({ transform: [{ translateX: shake.value }] }));

  return (
    <Pressable accessibilityLabel={t('trip.otpA11y')} onPress={() => input.current?.focus()} disabled={disabled}>
      <Animated.View style={[styles.row, row]}>
        {[0, 1, 2, 3].map(i => {
          const char = value[i] ?? '';
          const active = !disabled && i === Math.min(value.length, 3);
          return (
            <View
              key={i}
              style={[
                styles.box,
                {
                  backgroundColor: colors.surfaceAlt,
                  borderColor: error ? colors.danger : active ? colors.primary : char ? colors.text : colors.border,
                },
              ]}
            >
              <AppText variant="display">{char}</AppText>
            </View>
          );
        })}
      </Animated.View>
      <TextInput
        ref={input}
        value={value}
        onChangeText={text => onChange(text.replace(/\D/g, '').slice(0, 4))}
        keyboardType="number-pad"
        maxLength={4}
        editable={!disabled}
        autoComplete="one-time-code"
        style={styles.hidden}
        caretHidden
      />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', justifyContent: 'center', gap: space.md },
  box: { width: 60, height: 68, borderRadius: radius.lg, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  hidden: { position: 'absolute', opacity: 0, width: 1, height: 1 },
});
