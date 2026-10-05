import React, { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { radius, useTheme } from '@/theme';
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
// stage's count always visible. The selected stage takes its own colour as
// an underline and count, so the tab matches the tickets' action buttons.
const StageTabsComponent = ({ value, onChange, counts, late, arrived }: StageTabsProps) => {
  const theme = useTheme();
  const { colors } = theme;
  return (
    <View
      accessibilityRole="tablist"
      style={[styles.bar, { backgroundColor: colors.surface, borderColor: colors.border }]}>
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
              active && { backgroundColor: colors.surfaceMuted },
              arrived[column.status] && !active && [styles.arrived, { borderColor: colors.accent }],
            ]}>
            <View style={styles.countRow}>
              <View style={[styles.count, { backgroundColor: active ? stageColor : colors.surfaceMuted }]}>
                <Text style={[styles.countText, { color: active ? inkOn(stageColor) : colors.text }]}>
                  {counts[column.status]}
                </Text>
              </View>
              {late[column.status] ? (
                <View style={[styles.lateDot, { backgroundColor: colors.danger }]} />
              ) : null}
            </View>
            <Text
              numberOfLines={1}
              style={[styles.title, { color: active ? colors.text : colors.textMuted }]}>
              {column.title}
            </Text>
            <View style={[styles.underline, active ? { backgroundColor: stageColor } : styles.underlineIdle]} />
          </Pressable>
        );
      })}
    </View>
  );
};

export const StageTabs = memo(StageTabsComponent);

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: 4,
    gap: 4,
  },
  tab: {
    flex: 1,
    minHeight: 64,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    paddingTop: 8,
    paddingHorizontal: 2,
    overflow: 'hidden',
  },
  arrived: { borderWidth: 2 },
  countRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  count: { minWidth: 30, borderRadius: radius.sm, paddingHorizontal: 8, paddingVertical: 2, alignItems: 'center' },
  countText: { fontSize: 15, fontWeight: '900', fontVariant: ['tabular-nums'] },
  lateDot: { width: 8, height: 8, borderRadius: 4 },
  title: { fontSize: 13, fontWeight: '800' },
  underline: { alignSelf: 'stretch', height: 3, borderRadius: 2, marginHorizontal: 10, marginTop: 2 },
  underlineIdle: { backgroundColor: 'transparent' },
});
