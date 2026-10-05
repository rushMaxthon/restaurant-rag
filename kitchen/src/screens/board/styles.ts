import { StyleSheet } from 'react-native';
import { radius, space, type AppTheme } from '@/theme';

// At or above this the board is four columns side by side (a landscape
// tablet). Below it, one stage at a time behind tabs.
export const COLUMNS_MIN_WIDTH = 900;
// Between this and COLUMNS_MIN_WIDTH (a portrait tablet, a big phone on its
// side) the tabbed list lays tickets out two across.
export const TWO_UP_MIN_WIDTH = 600;

export const createStyles = ({ colors }: AppTheme) =>
  StyleSheet.create({
    toolbar: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: space.md,
      paddingHorizontal: space.lg,
      paddingBottom: space.md,
    },
    search: { width: 280 },
    searchCompact: { flex: 1 },
    chips: { flex: 1 },
    columns: {
      flex: 1,
      flexDirection: 'row',
      gap: space.md,
      paddingHorizontal: space.md,
      paddingBottom: space.sm,
    },
    column: {
      flex: 1,
      backgroundColor: colors.surfaceMuted,
      borderRadius: radius.xl,
      overflow: 'hidden',
    },
    columnHead: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: space.sm,
      paddingHorizontal: space.lg,
      paddingTop: 14,
      paddingBottom: 2,
    },
    columnDot: { width: 10, height: 10, borderRadius: 5 },
    columnTitle: { flex: 1, fontSize: 17, fontWeight: '800', color: colors.text },
    columnCount: {
      minWidth: 32,
      borderRadius: radius.sm,
      paddingHorizontal: 8,
      paddingVertical: 2,
      alignItems: 'center',
    },
    columnCountText: { fontSize: 15, fontWeight: '900', fontVariant: ['tabular-nums'] },
    tabs: { paddingHorizontal: space.md, paddingTop: space.md },
    phoneTools: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: space.sm,
      paddingHorizontal: space.md,
      paddingTop: space.md,
    },
    summary: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: space.sm,
      paddingHorizontal: space.md,
      paddingTop: space.md,
    },
    summaryPill: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      borderRadius: radius.pill,
      borderWidth: 1,
      paddingHorizontal: 12,
      paddingVertical: 6,
    },
    summaryText: { fontSize: 13, fontWeight: '800', fontVariant: ['tabular-nums'] },
    list: { flex: 1 },
  });
