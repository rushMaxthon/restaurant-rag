import { StyleSheet } from 'react-native';
import type { AppTheme } from '@/theme';

// At or above this the board is four columns side by side (a landscape
// tablet). Below it, one stage at a time behind tabs.
export const COLUMNS_MIN_WIDTH = 900;
// Between this and COLUMNS_MIN_WIDTH (a portrait tablet, a big phone on its
// side) the tabbed list lays tickets out two across.
export const TWO_UP_MIN_WIDTH = 600;

export const createStyles = ({ colors }: AppTheme) =>
  StyleSheet.create({
    screen: { flex: 1, backgroundColor: colors.background },
    toolbar: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      paddingHorizontal: 16,
      paddingBottom: 8,
    },
    search: { width: 260 },
    searchCompact: { flex: 1 },
    chips: { flex: 1 },
    columns: { flex: 1, flexDirection: 'row', gap: 12, paddingHorizontal: 12, paddingBottom: 8 },
    column: {
      flex: 1,
      backgroundColor: colors.surfaceMuted,
      borderRadius: 20,
      overflow: 'hidden',
    },
    columnHead: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      paddingHorizontal: 16,
      paddingTop: 14,
      paddingBottom: 2,
    },
    columnBar: { width: 4, height: 20, borderRadius: 2 },
    columnTitle: { flex: 1, fontSize: 17, fontWeight: '800', color: colors.text },
    columnCount: { fontSize: 17, fontWeight: '900', color: colors.textMuted, fontVariant: ['tabular-nums'] },
    tabs: { paddingHorizontal: 12, paddingTop: 12 },
    phoneTools: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      paddingHorizontal: 12,
      paddingTop: 10,
    },
    summary: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 14,
      paddingHorizontal: 16,
      paddingTop: 8,
    },
    summaryText: { fontSize: 14, fontWeight: '700', color: colors.textMuted },
    summaryAlert: { color: colors.danger },
    list: { flex: 1 },
  });
