import React from 'react';
import { Pressable, StyleSheet, Text } from 'react-native';
import { useTheme } from '@/theme';
import { Icon, type IconName } from '@components/Icon';

interface IconButtonProps {
  icon: IconName;
  accessibilityLabel: string;
  onPress: () => void;
  // Shown beside the icon on wide layouts; icon-only when absent.
  label?: string;
  active?: boolean;
  tone?: 'default' | 'danger';
  testID?: string;
}

export const IconButton = ({
  icon,
  accessibilityLabel,
  onPress,
  label,
  active = false,
  tone = 'default',
  testID,
}: IconButtonProps) => {
  const { colors } = useTheme();
  const foreground = tone === 'danger' ? colors.danger : active ? colors.accent : colors.text;
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      hitSlop={8}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ selected: active }}
      style={({ pressed }) => [
        styles.button,
        label ? styles.withLabel : null,
        {
          backgroundColor: active ? colors.accentSoft : colors.surfaceMuted,
          opacity: pressed ? 0.7 : 1,
        },
      ]}>
      <Icon name={icon} size={22} color={foreground} />
      {label ? <Text style={[styles.label, { color: foreground }]}>{label}</Text> : null}
    </Pressable>
  );
};

const styles = StyleSheet.create({
  button: {
    minWidth: 48,
    height: 48,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 8,
  },
  withLabel: { paddingHorizontal: 16 },
  label: { fontSize: 15, fontWeight: '700' },
});
