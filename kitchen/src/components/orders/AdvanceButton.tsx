import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text } from 'react-native';
import { useTheme } from '@/theme';
import type { KitchenOrder } from '@/types/app';
import { inkOn } from '@/themePalette';
import { Icon } from '@components/Icon';
import { advanceLabel, nextStatus } from '@utils/board';

interface AdvanceButtonProps {
  order: KitchenOrder;
  pending: boolean;
  onPress: () => void;
  size?: 'md' | 'lg';
  testID?: string;
}

// The one action on a live order. Filled with the colour of the column the
// order is about to move INTO — Accept is amber like Accepted, Start cooking
// is orange like Cooking — so the button previews where the ticket will go.
export const AdvanceButton = ({
  order,
  pending,
  onPress,
  size = 'md',
  testID,
}: AdvanceButtonProps) => {
  const theme = useTheme();
  const next = nextStatus(order.status);
  const label = advanceLabel(order);
  if (!next || !label) {
    return null;
  }
  const background = theme.status[next];
  const ink = inkOn(background);
  const finishing = next === 'DELIVERED';
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={pending}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ busy: pending, disabled: pending }}
      style={({ pressed }) => [
        styles.button,
        size === 'lg' && styles.large,
        { backgroundColor: background, opacity: pending ? 0.75 : pressed ? 0.85 : 1 },
        pressed && styles.pressed,
      ]}>
      {pending ? (
        <ActivityIndicator color={ink} />
      ) : (
        <>
          {finishing ? <Icon name="checkmark-done" size={size === 'lg' ? 24 : 20} color={ink} /> : null}
          <Text style={[styles.label, size === 'lg' && styles.labelLarge, { color: ink }]}>
            {label}
          </Text>
        </>
      )}
    </Pressable>
  );
};

const styles = StyleSheet.create({
  button: {
    minHeight: 52,
    borderRadius: 14,
    paddingHorizontal: 18,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  large: { minHeight: 64, borderRadius: 16 },
  pressed: { transform: [{ scale: 0.98 }] },
  label: { fontSize: 17, fontWeight: '800' },
  labelLarge: { fontSize: 20 },
});
