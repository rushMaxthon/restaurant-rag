import React from 'react';
import { StyleSheet, View } from 'react-native';
import { radius, space, useTheme } from '@/theme';
import { Skeleton } from '@components/Skeleton';

// A placeholder shaped like the ticket it stands in for — code and wait,
// a meta line, two dishes, the action — so the first load does not jump
// when the real tickets replace it.
export const TicketSkeleton = () => {
  const { colors } = useTheme();
  return (
    <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      <View style={styles.row}>
        <Skeleton height={22} width="45%" radius={6} />
        <Skeleton height={22} width={52} radius={6} />
      </View>
      <Skeleton height={14} width="60%" radius={6} />
      <View style={styles.line}>
        <Skeleton height={30} width={30} radius={8} />
        <Skeleton height={16} width="55%" radius={6} />
      </View>
      <View style={styles.line}>
        <Skeleton height={30} width={30} radius={8} />
        <Skeleton height={16} width="40%" radius={6} />
      </View>
      <Skeleton height={54} radius={radius.md} />
    </View>
  );
};

const styles = StyleSheet.create({
  card: { borderRadius: radius.xl, borderWidth: 1, padding: space.lg, gap: 14 },
  row: { flexDirection: 'row', justifyContent: 'space-between' },
  line: { flexDirection: 'row', alignItems: 'center', gap: 12 },
});
