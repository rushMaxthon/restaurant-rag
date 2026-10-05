import React, { memo } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { radius, space, useTheme } from '@/theme';
import { BOARD_COLUMNS } from '@/data/boardColumns';
import type { LiveStatus } from '@/types/app';
import { Icon, type IconName } from '@components/Icon';
import { formatWait } from '@utils/board';
import type { BoardMetrics } from '@utils/metrics';

interface MetricsStripProps {
  counts: Record<LiveStatus, number>;
  metrics: BoardMetrics;
}

// The numbers above a tablet board, as ONE segmented strip rather than a row
// of loose tiles: they are read together, left to right, like the columns
// under them. Counted from the tickets on screen, never fetched — so a number
// can never disagree with the column beneath it.
const MetricsStripComponent = ({ counts, metrics }: MetricsStripProps) => {
  const theme = useTheme();
  const { colors } = theme;
  const overdue = metrics.overdue > 0;
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={styles.strip}
      contentContainerStyle={styles.content}>
      <View style={[styles.group, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        {BOARD_COLUMNS.map((column, index) => (
          <Segment
            key={column.status}
            first={index === 0}
            label={column.title}
            value={String(counts[column.status])}
            dot={theme.status[column.status]}
          />
        ))}
      </View>
      {/* Coloured only when non-zero: a permanently red tile stops being read
          within a shift. */}
      <View
        style={[
          styles.group,
          {
            backgroundColor: overdue ? colors.dangerSoft : colors.surface,
            borderColor: overdue ? colors.danger : colors.border,
          },
        ]}>
        <Segment
          first
          label="Overdue"
          value={String(metrics.overdue)}
          icon="flame"
          tone={overdue ? colors.danger : undefined}
        />
      </View>
      {/* "Wait", not "prep": counted from when the customer ordered. */}
      <View style={[styles.group, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <Segment
          first
          label="Median wait"
          value={metrics.medianWait === null ? '—' : formatWait(metrics.medianWait)}
          icon="timer-outline"
        />
      </View>
    </ScrollView>
  );
};

export const MetricsStrip = memo(MetricsStripComponent);

const Segment = ({
  label,
  value,
  dot,
  icon,
  tone,
  first,
}: {
  label: string;
  value: string;
  dot?: string;
  icon?: IconName;
  tone?: string;
  first: boolean;
}) => {
  const { colors } = useTheme();
  return (
    <View
      accessible
      accessibilityLabel={`${label}: ${value}`}
      style={[styles.segment, !first && { borderLeftColor: colors.border, borderLeftWidth: StyleSheet.hairlineWidth }]}>
      <View style={styles.labelRow}>
        {dot ? <View style={[styles.dot, { backgroundColor: dot }]} /> : null}
        {icon ? <Icon name={icon} size={14} color={tone ?? colors.textMuted} /> : null}
        <Text style={[styles.label, { color: tone ?? colors.textMuted }]}>{label}</Text>
      </View>
      <Text style={[styles.value, { color: tone ?? colors.text }]}>{value}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  // A horizontal ScrollView otherwise grows to fill the column it sits in.
  strip: { flexGrow: 0 },
  content: { gap: space.md, paddingHorizontal: space.lg, paddingVertical: space.md },
  group: { flexDirection: 'row', borderRadius: radius.lg, borderWidth: 1, overflow: 'hidden' },
  segment: { minWidth: 104, paddingHorizontal: space.lg, paddingVertical: 10, gap: 2 },
  labelRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  label: { fontSize: 13, fontWeight: '700' },
  value: { fontSize: 26, fontWeight: '900', fontVariant: ['tabular-nums'] },
});
