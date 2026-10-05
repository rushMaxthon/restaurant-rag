import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';
import { BOARD_COLUMNS } from '@/data/boardColumns';
import type { LiveStatus } from '@/types/app';
import { inkOn } from '@/themePalette';

interface StageTabsProps {
  value: LiveStatus;
  onChange: (status: LiveStatus) => void;
  counts: Record<LiveStatus, number>;
  // A stage holding at least one late ticket gets a red dot, so a phone
  // showing "Cooking" still says that something in "New" is overdue.
  late: Record<LiveStatus, boolean>;
  // A stage that just received an order the cook is not looking at.
  arrived: Record<LiveStatus, boolean>;
}

// The phone's replacement for four columns: one stage at a time, with every
// stage's count always visible.
export const StageTabs = ({ value, onChange, counts, late, arrived }: StageTabsProps) => {
  const theme = useTheme();
  const { colors } = theme;
  return (
    <View
      accessibilityRole="tablist"
      style={[styles.bar, { backgroundColor: colors.surfaceMuted }]}>
      {BOARD_COLUMNS.map(column => {
        const active = column.status === value;
        const stageColor = theme.status[column.status];
        return (
          <Pressable
            key={column.status}
            testID={`stage-${column.status}`}
            onPress={() => onChange(column.status)}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            accessibilityLabel={`${column.title}, ${counts[column.status]} orders${
              late[column.status] ? ', some overdue' : ''
            }`}
            style={[
              styles.tab,
              active && [styles.active, { backgroundColor: colors.surface }],
              arrived[column.status] && !active && [styles.arrived, { borderColor: colors.accent }],
            ]}>
            <Text
              numberOfLines={1}
              style={[styles.title, { color: active ? colors.text : colors.textMuted }]}>
              {column.title}
            </Text>
            <View style={[styles.count, { backgroundColor: active ? stageColor : colors.border }]}>
              <Text style={[styles.countText, { color: active ? inkOn(stageColor) : colors.text }]}>
                {counts[column.status]}
              </Text>
            </View>
            {late[column.status] ? (
              <View style={[styles.lateDot, { backgroundColor: colors.danger, borderColor: colors.surfaceMuted }]} />
            ) : null}
          </Pressable>
        );
      })}
    </View>
  );
};

const styles = StyleSheet.create({
  bar: { flexDirection: 'row', borderRadius: 16, padding: 4, gap: 4 },
  tab: {
    flex: 1,
    minHeight: 56,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    paddingHorizontal: 4,
  },
  active: {
    shadowColor: '#000',
    shadowOpacity: 0.08,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  arrived: { borderWidth: 2 },
  title: { fontSize: 13, fontWeight: '800' },
  count: { minWidth: 28, borderRadius: 10, paddingHorizontal: 8, paddingVertical: 1, alignItems: 'center' },
  countText: { fontSize: 14, fontWeight: '900', fontVariant: ['tabular-nums'] },
  lateDot: {
    position: 'absolute',
    top: 6,
    right: 8,
    width: 12,
    height: 12,
    borderRadius: 6,
    borderWidth: 2,
  },
});
