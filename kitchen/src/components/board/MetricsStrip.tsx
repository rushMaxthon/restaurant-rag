import React, { memo } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { radius, space, useTheme } from '@/theme';
import { formatWait } from '@utils/board';
import type { BoardMetrics } from '@utils/metrics';

// Three numbers that span every stage: what is late, how long people are
// waiting, and how many orders leave with a rider. Each stage's own count is
// on the stage tabs (phone) or the column headers (tablet). Counted from the
// tickets on screen, never fetched, so they cannot disagree with the board.
const MetricsStripComponent = ({ metrics }: { metrics: BoardMetrics }) => {
  const { colors } = useTheme();
  const overdue = metrics.overdue > 0;
  return (
    <View style={styles.row}>
      {/* Tinted only when non-zero: a permanently red card stops being read. */}
      <Card
        label="Overdue"
        value={String(metrics.overdue)}
        ink={overdue ? colors.danger : undefined}
        soft={overdue ? colors.dangerSoft : undefined}
      />
      {/* "Wait", not "prep": counted from when the customer ordered. */}
      <Card
        label="Median wait"
        value={metrics.medianWait === null ? '—' : formatWait(metrics.medianWait).replace(/^(\d+)m$/, '$1 min')}
      />
      <Card label="Deliveries" value={String(metrics.deliveries)} />
    </View>
  );
};

export const MetricsStrip = memo(MetricsStripComponent);

const Card = ({ label, value, ink, soft }: { label: string; value: string; ink?: string; soft?: string }) => {
  const { colors } = useTheme();
  return (
    <View
      accessible
      accessibilityLabel={`${label}: ${value}`}
      style={[styles.card, { backgroundColor: soft ?? colors.surface, borderColor: ink ?? colors.border }]}>
      <Text numberOfLines={1} style={[styles.value, { color: ink ?? colors.text }]}>
        {value}
      </Text>
      <Text numberOfLines={1} style={[styles.label, { color: ink ?? colors.textMuted }]}>
        {label}
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: space.sm },
  card: { flex: 1, minWidth: 0, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: space.md, paddingVertical: 10, gap: 2 },
  value: { fontSize: 18, fontWeight: '900', fontVariant: ['tabular-nums'] },
  label: { fontSize: 12, fontWeight: '600' },
});
