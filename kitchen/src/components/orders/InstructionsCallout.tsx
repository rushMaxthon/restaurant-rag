import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { radius, useTheme } from '@/theme';
import { Icon } from '@components/Icon';

// The order's one free-text note. Allergies live here, so it is never
// truncated and never styled as small print: an amber rail, a label, the
// customer's words in full.
export const InstructionsCallout = ({ text }: { text: string }) => {
  const { colors } = useTheme();
  return (
    <View
      accessible
      accessibilityLabel={`Special instructions: ${text}`}
      style={[styles.box, { backgroundColor: colors.warningSoft, borderLeftColor: colors.warning }]}>
      <View style={styles.head}>
        <Icon name="warning" size={15} color={colors.warning} />
        <Text style={[styles.label, { color: colors.warning }]}>NOTE FROM CUSTOMER</Text>
      </View>
      <Text style={[styles.text, { color: colors.text }]}>{text}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  box: {
    borderLeftWidth: 4,
    borderRadius: radius.md,
    paddingVertical: 10,
    paddingHorizontal: 12,
    gap: 4,
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  label: { fontSize: 11, fontWeight: '900', letterSpacing: 0.6 },
  text: { fontSize: 15, fontWeight: '700', lineHeight: 21 },
});
