import React, { memo } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text } from 'react-native';
import { radius, useTheme } from '@/theme';
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
// A forward arrow on every step but the last, which gets a done-tick instead.
const AdvanceButtonComponent = ({ order, pending, onPress, size = 'md', testID }: AdvanceButtonProps) => {
  const theme = useTheme();
  const next = nextStatus(order.status);
  const label = advanceLabel(order);
  if (!next || !label) {
    return null;
  }
  const background = theme.status[next];
  const ink = inkOn(background);
  const finishing = next === 'DELIVERED';
  const iconSize = size === 'lg' ? 24 : 20;
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
        { backgroundColor: background },
        pending && styles.pending,
        pressed && !pending && styles.pressed,
      ]}>
      {pending ? (
        <ActivityIndicator color={ink} />
      ) : (
        <>
          {finishing ? <Icon name="checkmark-done" size={iconSize} color={ink} /> : null}
          <Text style={[styles.label, size === 'lg' && styles.labelLarge, { color: ink }]}>{label}</Text>
          {finishing ? null : <Icon name="arrow-forward" size={iconSize} color={ink} />}
        </>
      )}
    </Pressable>
  );
};

export const AdvanceButton = memo(AdvanceButtonComponent);

const styles = StyleSheet.create({
  button: {
    minHeight: 54,
    borderRadius: radius.md,
    paddingHorizontal: 18,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
  },
  large: { minHeight: 64, borderRadius: radius.lg },
  pending: { opacity: 0.75 },
  pressed: { opacity: 0.85, transform: [{ scale: 0.985 }] },
  label: { fontSize: 17, fontWeight: '800', letterSpacing: 0.2 },
  labelLarge: { fontSize: 20 },
});
