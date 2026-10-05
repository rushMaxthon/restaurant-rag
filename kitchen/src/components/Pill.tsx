import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Icon, type IconName } from '@components/Icon';

interface PillProps {
  label: string;
  color: string;
  background: string;
  icon?: IconName;
  size?: 'sm' | 'md';
}

export const Pill = ({ label, color, background, icon, size = 'sm' }: PillProps) => (
  <View style={[styles.pill, size === 'md' && styles.md, { backgroundColor: background }]}>
    {icon ? <Icon name={icon} size={size === 'md' ? 16 : 13} color={color} /> : null}
    <Text style={[styles.text, size === 'md' && styles.textMd, { color }]}>{label}</Text>
  </View>
);

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
    alignSelf: 'flex-start',
  },
  md: { paddingHorizontal: 12, paddingVertical: 6 },
  text: { fontSize: 12, fontWeight: '800', letterSpacing: 0.3 },
  textMd: { fontSize: 14 },
});
