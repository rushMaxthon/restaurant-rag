import React, { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { radius, useTheme } from '@/theme';
import { BOARD_COLUMNS } from '@/data/boardColumns';
import type { LiveStatus } from '@/types/app';

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

// The phone's replacement for four columns: a segmented control, one stage
// at a time, with every stage's count always visible. The selected segment
// is raised and its count filled.
const StageTabsComponent = ({ value, onChange, counts, late, arrived }: StageTabsProps) => {
  const { colors } = useTheme();
  return (
    <View accessibilityRole="tablist" style={[styles.bar, { backgroundColor: colors.surfaceMuted, borderColor: colors.border }]}>
      {BOARD_COLUMNS.map(column => {
        const active = column.status === value;
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
            <View style={styles.countRow}>
              <View style={[styles.count, { backgroundColor: active ? colors.accent : colors.surface }]}>
                <Text style={[styles.countText, { color: active ? colors.onAccent : colors.text }]}>
                  {counts[column.status]}
                </Text>
              </View>
              {late[column.status] ? <View style={[styles.lateDot, { backgroundColor: colors.danger }]} /> : null}
            </View>
            <Text numberOfLines={1} style={[styles.title, { color: active ? colors.text : colors.textMuted }]}>
              {column.title}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
};

export const StageTabs = memo(StageTabsComponent);

const styles = StyleSheet.create({
  bar: { flexDirection: 'row', borderRadius: radius.lg, borderWidth: 1, padding: 4, gap: 4 },
  tab: {
    flex: 1,
    minHeight: 60,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    paddingHorizontal: 2,
  },
  active: {
    shadowColor: '#000',
    shadowOpacity: 0.08,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 1 },
    elevation: 2,
  },
  arrived: { borderWidth: 2 },
  countRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  count: { minWidth: 26, borderRadius: radius.sm, paddingHorizontal: 7, paddingVertical: 2, alignItems: 'center' },
  countText: { fontSize: 14, fontWeight: '900', fontVariant: ['tabular-nums'] },
  lateDot: { width: 8, height: 8, borderRadius: 4 },
  title: { fontSize: 13, fontWeight: '700' },
});
