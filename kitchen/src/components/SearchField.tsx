import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { radius, useTheme } from '@/theme';
import { Icon } from '@components/Icon';

interface SearchFieldProps {
  value: string;
  onChangeText: (value: string) => void;
  placeholder: string;
  accessibilityLabel: string;
  busy?: boolean;
  // GET /orders caps `search` at 120 characters and answers 422 past it.
  maxLength?: number;
  testID?: string;
}

export const SearchField = ({
  value,
  onChangeText,
  placeholder,
  accessibilityLabel,
  busy = false,
  maxLength = 120,
  testID,
}: SearchFieldProps) => {
  const { colors } = useTheme();
  return (
    <View
      style={[
        styles.field,
        { backgroundColor: colors.surface, borderColor: value ? colors.accent : colors.border },
      ]}>
      <Icon name="search" size={19} color={value ? colors.accent : colors.textMuted} />
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.textMuted}
        accessibilityLabel={accessibilityLabel}
        maxLength={maxLength}
        autoCapitalize="characters"
        autoCorrect={false}
        returnKeyType="search"
        selectionColor={colors.accent}
        style={[styles.input, { color: colors.text }]}
      />
      {busy ? <ActivityIndicator size="small" color={colors.textMuted} /> : null}
      {value ? (
        <Pressable
          onPress={() => onChangeText('')}
          hitSlop={12}
          accessibilityRole="button"
          accessibilityLabel="Clear search">
          <Icon name="close-circle" size={20} color={colors.textMuted} />
        </Pressable>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  field: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: 48,
    borderRadius: radius.md,
    borderWidth: 1.5,
    paddingHorizontal: 14,
  },
  input: { flex: 1, fontSize: 16, paddingVertical: 10, fontWeight: '700', letterSpacing: 0.4 },
});
