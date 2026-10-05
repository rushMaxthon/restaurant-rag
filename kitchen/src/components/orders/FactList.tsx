import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { space, useTheme } from '@/theme';
import { Icon, type IconName } from '@components/Icon';

export interface Fact {
  label: string;
  value: React.ReactNode;
  icon: IconName;
  // Draws the row's value in the warning colour — a scheduled time, say.
  emphasis?: boolean;
}

// Label / value rows for an order's particulars, each led by its icon so the
// list can be scanned without reading the labels.
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
          <View style={[styles.icon, { backgroundColor: colors.surfaceMuted }]}>
            <Icon name={fact.icon} size={17} color={fact.emphasis ? colors.warning : colors.textMuted} />
          </View>
          <Text style={[styles.label, { color: colors.textMuted }]}>{fact.label}</Text>
          {typeof fact.value === 'string' ? (
            <Text
              style={[styles.value, { color: fact.emphasis ? colors.warning : colors.text }]}>
              {fact.value}
            </Text>
          ) : (
            <View style={styles.valueNode}>{fact.value}</View>
          )}
        </View>
      ))}
    </View>
  );
};

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: 11, minHeight: 52 },
  icon: { width: 32, height: 32, borderRadius: 9, alignItems: 'center', justifyContent: 'center' },
  label: { flex: 1, fontSize: 15, fontWeight: '600' },
  value: { fontSize: 16, fontWeight: '800', textAlign: 'right', flexShrink: 1 },
  valueNode: { flexShrink: 1, alignItems: 'flex-end' },
});
