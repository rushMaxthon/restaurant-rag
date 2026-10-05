import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';
import type { RealtimeStatus } from '@/types/app';

export type FreshnessState = 'live' | 'polling' | 'stale';

// Three honest states. "Live" only when a push can actually arrive;
// "Polling" when the board is fresh only as of the next poll (socket down or
// realtime off on the server); "Not updating" when REST itself is failing —
// which outranks everything, because then nothing on screen is current.
export const freshnessOf = (realtime: RealtimeStatus | null, stale: boolean): FreshnessState =>
  stale ? 'stale' : realtime === 'live' ? 'live' : 'polling';

export const FRESHNESS_LABEL: Record<FreshnessState, string> = {
  live: 'Live',
  polling: 'Polling',
  stale: 'Not updating',
};

export const LiveIndicator = ({ state }: { state: FreshnessState }) => {
  const { colors } = useTheme();
  const color =
    state === 'live' ? colors.accent : state === 'stale' ? colors.danger : colors.warning;
  const background =
    state === 'live' ? colors.accentSoft : state === 'stale' ? colors.dangerSoft : colors.warningSoft;
  return (
    <View
      accessible
      accessibilityLabel={`Board status: ${FRESHNESS_LABEL[state]}`}
      style={[styles.pill, { backgroundColor: background }]}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={[styles.text, { color }]}>{FRESHNESS_LABEL[state]}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderRadius: 999,
    paddingHorizontal: 12,
    height: 32,
  },
  dot: { width: 8, height: 8, borderRadius: 4 },
  text: { fontSize: 13, fontWeight: '800' },
});
