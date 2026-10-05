import React, { memo } from 'react';
import { Pressable, StyleSheet, Text } from 'react-native';
import { radius, useTheme } from '@/theme';
import { Icon, type IconName } from '@components/Icon';

interface IconButtonProps {
  icon: IconName;
  accessibilityLabel: string;
  onPress: () => void;
  // Shown beside the icon on wide layouts; icon-only when absent.
  label?: string;
  active?: boolean;
  testID?: string;
}

const IconButtonComponent = ({
  icon,
  accessibilityLabel,
  onPress,
  label,
  active = false,
  testID,
}: IconButtonProps) => {
  const { colors } = useTheme();
  const foreground = active ? colors.accent : colors.text;
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      hitSlop={6}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ selected: active }}
      style={({ pressed }) => [
        styles.button,
        label ? styles.withLabel : null,
        {
          backgroundColor: active ? colors.accentSoft : colors.surfaceMuted,
          borderColor: active ? colors.accent : colors.border,
        },
        pressed && styles.pressed,
      ]}>
      <Icon name={icon} size={22} color={foreground} />
      {label ? <Text style={[styles.label, { color: foreground }]}>{label}</Text> : null}
    </Pressable>
  );
};

export const IconButton = memo(IconButtonComponent);

const styles = StyleSheet.create({
  button: {
    minWidth: 48,
    height: 48,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 8,
  },
  withLabel: { paddingHorizontal: 16 },
  pressed: { opacity: 0.7 },
  label: { fontSize: 15, fontWeight: '700' },
});
