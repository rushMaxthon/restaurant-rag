import React, { useEffect, useRef } from 'react';
import {
  Pressable,
  StyleSheet,
  TextInput,
  View,
  type TextInputInstance,
} from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSequence,
  withTiming,
} from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { useI18n } from '@/i18n';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';

export const CODE_LENGTH = 6;

/**
 * The sign-up code: six boxes over ONE hidden input, the same build as the
 * delivery-code boxes (`trip/OtpInput`). One input is what makes paste, the
 * SMS autofill chip and backspace work with no code of ours - six inputs
 * have to pass focus between them and lose a pasted code to the first box.
 * Boxes flex so six fit a 360 dp phone with the gutters.
 */
export function CodeInput({
  value,
  onChange,
  shakeKey,
  error,
  autoFocus,
}: {
  value: string;
  onChange: (next: string) => void;
  shakeKey?: number;
  error?: boolean;
  autoFocus?: boolean;
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
      withTiming(-6, { duration: 50 }),
      withTiming(0, { duration: 50 }),
    );
  }, [shakeKey, shake]);

  const row = useAnimatedStyle(() => ({
    transform: [{ translateX: shake.value }],
  }));

  return (
    <Pressable
      accessibilityLabel={t('onboarding.code.title')}
      accessibilityValue={{ text: value }}
      onPress={() => input.current?.focus()}
    >
      <Animated.View style={[styles.row, row]}>
        {Array.from({ length: CODE_LENGTH }, (_, i) => {
          const char = value[i] ?? '';
          const active = i === Math.min(value.length, CODE_LENGTH - 1);
          return (
            <View
              key={i}
              accessibilityLabel={t('onboarding.code.digit', { n: i + 1 })}
              style={[
                styles.box,
                {
                  backgroundColor: active ? colors.surface : colors.surfaceAlt,
                  borderColor: error
                    ? colors.danger
                    : active
                    ? colors.primary
                    : char
                    ? colors.textMuted
                    : colors.border,
                },
              ]}
            >
              <AppText variant="title" maxFontSizeMultiplier={1.2}>
                {char}
              </AppText>
            </View>
          );
        })}
      </Animated.View>
      <TextInput
        ref={input}
        value={value}
        onChangeText={text =>
          onChange(text.replace(/\D/g, '').slice(0, CODE_LENGTH))
        }
        keyboardType="number-pad"
        maxLength={CODE_LENGTH}
        autoFocus={autoFocus}
        autoComplete="sms-otp"
        textContentType="oneTimeCode"
        style={styles.hidden}
        caretHidden
      />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', justifyContent: 'center', gap: space.sm },
  box: {
    flex: 1,
    maxWidth: 56,
    height: 64,
    borderRadius: radius.lg,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  hidden: { position: 'absolute', opacity: 0, width: 1, height: 1 },
});
