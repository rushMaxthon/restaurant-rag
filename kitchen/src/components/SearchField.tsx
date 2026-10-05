import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { useTheme } from '@/theme';
import { Icon } from '@components/Icon';

interface SearchFieldProps {
  value: string;
  onChangeText: (value: string) => void;
  placeholder: string;
  accessibilityLabel: string;
  busy?: boolean;
  testID?: string;
}

export const SearchField = ({
  value,
  onChangeText,
  placeholder,
  accessibilityLabel,
  busy = false,
  testID,
}: SearchFieldProps) => {
  const { colors } = useTheme();
  return (
    <View
      style={[styles.field, { backgroundColor: colors.surfaceMuted, borderColor: colors.border }]}>
      <Icon name="search" size={18} color={colors.textMuted} />
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.textMuted}
        accessibilityLabel={accessibilityLabel}
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
    borderRadius: 14,
    borderWidth: 1,
    paddingHorizontal: 14,
  },
  input: { flex: 1, fontSize: 16, paddingVertical: 10, fontWeight: '600' },
});
