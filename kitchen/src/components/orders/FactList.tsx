import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';

export interface Fact {
  label: string;
  value: React.ReactNode;
}

// Label / value rows for an order's particulars.
export const FactList = ({ facts }: { facts: Fact[] }) => {
  const { colors } = useTheme();
  return (
    <View>
      {facts.map((fact, index) => (
        <View
          key={fact.label}
          style={[
            styles.row,
            index > 0 && { borderTopColor: colors.border, borderTopWidth: StyleSheet.hairlineWidth },
          ]}>
          <Text style={[styles.label, { color: colors.textMuted }]}>{fact.label}</Text>
          {typeof fact.value === 'string' ? (
            <Text style={[styles.value, { color: colors.text }]}>{fact.value}</Text>
          ) : (
            <View style={styles.valueNode}>{fact.value}</View>
          )}
        </View>
      ))}
    </View>
  );
};

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 16,
    paddingVertical: 12,
    minHeight: 48,
  },
  label: { fontSize: 15, fontWeight: '600' },
  value: { fontSize: 16, fontWeight: '700', textAlign: 'right', flexShrink: 1 },
  valueNode: { flexShrink: 1, alignItems: 'flex-end' },
});
