import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';
import { BOARD_COLUMNS } from '@/data/boardColumns';
import type { LiveStatus } from '@/types/app';
import { formatWait } from '@utils/board';
import type { BoardMetrics } from '@utils/metrics';

interface MetricsStripProps {
  counts: Record<LiveStatus, number>;
  metrics: BoardMetrics;
  // Phones show the stage counts on the tabs already; only the two derived
  // numbers are left to show here.
  showStageCounts: boolean;
}

// Counted from the tickets on screen, never fetched — so a number can never
// disagree with the column beneath it.
export const MetricsStrip = ({ counts, metrics, showStageCounts }: MetricsStripProps) => {
  const theme = useTheme();
  const { colors } = theme;
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={styles.strip}
      contentContainerStyle={styles.row}>
      {showStageCounts
        ? BOARD_COLUMNS.map(column => (
            <Tile
              key={column.status}
              label={column.title}
              value={String(counts[column.status])}
              accent={theme.status[column.status]}
            />
          ))
        : null}
      {/* Coloured only when non-zero: a permanently red tile stops being read
          within a shift. */}
      <Tile
        label="Overdue"
        value={String(metrics.overdue)}
        tone={metrics.overdue > 0 ? colors.danger : undefined}
        background={metrics.overdue > 0 ? colors.dangerSoft : undefined}
      />
      {/* "Wait", not "prep": counted from when the customer ordered. */}
      <Tile
        label="Median wait"
        value={metrics.medianWait === null ? '—' : formatWait(metrics.medianWait)}
      />
    </ScrollView>
  );
};

const Tile = ({
  label,
  value,
  accent,
  tone,
  background,
}: {
  label: string;
  value: string;
  accent?: string;
  tone?: string;
  background?: string;
}) => {
  const { colors } = useTheme();
  return (
    <View
      accessible
      accessibilityLabel={`${label}: ${value}`}
      style={[
        styles.tile,
        { backgroundColor: background ?? colors.surface, borderColor: colors.border },
      ]}>
      <View style={styles.labelRow}>
        {accent ? <View style={[styles.dot, { backgroundColor: accent }]} /> : null}
        <Text style={[styles.label, { color: tone ?? colors.textMuted }]}>{label}</Text>
      </View>
      <Text style={[styles.value, { color: tone ?? colors.text }]}>{value}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  // A horizontal ScrollView otherwise grows to fill the column it sits in.
  strip: { flexGrow: 0 },
  row: { gap: 10, paddingHorizontal: 16, paddingVertical: 12 },
  tile: {
    minWidth: 112,
    borderRadius: 14,
    borderWidth: 1,
    paddingHorizontal: 14,
    paddingVertical: 10,
    gap: 2,
  },
  labelRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  label: { fontSize: 13, fontWeight: '700' },
  value: { fontSize: 24, fontWeight: '900', fontVariant: ['tabular-nums'] },
});
