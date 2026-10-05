import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';
import { Icon } from '@components/Icon';

// The order's one free-text note. Allergies live here, so it is never
// truncated and never styled as small print.
export const InstructionsCallout = ({ text }: { text: string }) => {
  const { colors } = useTheme();
  return (
    <View
      accessible
      accessibilityLabel={`Special instructions: ${text}`}
      style={[styles.box, { backgroundColor: colors.warningSoft, borderColor: colors.warning }]}>
      <Icon name="warning" size={18} color={colors.warning} />
      <Text style={[styles.text, { color: colors.text }]}>{text}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  box: {
    flexDirection: 'row',
    gap: 10,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    alignItems: 'flex-start',
  },
  text: { flex: 1, fontSize: 15, fontWeight: '600', lineHeight: 21 },
});
