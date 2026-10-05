import React, { forwardRef, useState } from 'react';
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from 'react-native';
import { useTheme } from '@/theme';

interface AuthFieldProps extends Omit<TextInputProps, 'style' | 'secureTextEntry'> {
  label: string;
  error?: string;
  // Renders a Show/Hide toggle and masks the value until it is pressed.
  secret?: boolean;
}

export const AuthField = forwardRef<TextInput, AuthFieldProps>(
  ({ label, error, secret = false, onFocus, onBlur, ...inputProps }, ref) => {
    const { colors } = useTheme();
    const [focused, setFocused] = useState(false);
    const [revealed, setRevealed] = useState(false);

    const borderColor = error
      ? colors.danger
      : focused
        ? colors.accent
        : colors.border;

    return (
      <View style={styles.field}>
        <Text style={[styles.label, { color: colors.text }]}>{label}</Text>
        <View
          style={[
            styles.inputRow,
            { borderColor, backgroundColor: colors.inputBackground },
            focused && styles.inputRowFocused,
          ]}>
          <TextInput
            ref={ref}
            {...inputProps}
            secureTextEntry={secret && !revealed}
            placeholderTextColor={colors.textMuted}
            selectionColor={colors.accent}
            accessibilityLabel={label}
            onFocus={event => {
              setFocused(true);
              onFocus?.(event);
            }}
            onBlur={event => {
              setFocused(false);
              onBlur?.(event);
            }}
            style={[styles.input, { color: colors.text }]}
          />
          {secret ? (
            <Pressable
              onPress={() => setRevealed(value => !value)}
              hitSlop={12}
              accessibilityRole="button"
              accessibilityLabel={revealed ? 'Hide password' : 'Show password'}
              style={styles.toggle}>
              <Text style={[styles.toggleText, { color: colors.accent }]}>
                {revealed ? 'Hide' : 'Show'}
              </Text>
            </Pressable>
          ) : null}
        </View>
        {error ? (
          <Text style={[styles.error, { color: colors.danger }]}>{error}</Text>
        ) : null}
      </View>
    );
  },
);

const styles = StyleSheet.create({
  field: { gap: 8 },
  label: { fontSize: 15, fontWeight: '600' },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    // 56pt: tapped by someone in gloves or with wet hands, often mid-shift.
    minHeight: 56,
    borderWidth: 1.5,
    borderRadius: 12,
    paddingHorizontal: 16,
  },
  inputRowFocused: { borderWidth: 2 },
  input: { flex: 1, fontSize: 17, paddingVertical: 14 },
  toggle: { paddingLeft: 12, paddingVertical: 8 },
  toggleText: { fontSize: 15, fontWeight: '700' },
  error: { fontSize: 14, fontWeight: '500' },
});
