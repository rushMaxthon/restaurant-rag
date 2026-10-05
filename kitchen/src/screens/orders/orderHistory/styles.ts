import { StyleSheet } from 'react-native';
import type { AppTheme } from '@/theme';

export const createStyles = ({ colors }: AppTheme) =>
  StyleSheet.create({
    searchRow: { paddingHorizontal: 16, paddingTop: 12, paddingBottom: 4 },
    content: { padding: 16, paddingBottom: 32, flexGrow: 1 },
    // Rows stay a readable width on a tablet instead of stretching edge to edge.
    constrained: { width: '100%', maxWidth: 760, alignSelf: 'center' },
    row: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 14,
      backgroundColor: colors.surface,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: 16,
      paddingHorizontal: 16,
      paddingVertical: 14,
      minHeight: 76,
    },
    rowMain: { flex: 1, gap: 4, minWidth: 0 },
    rowTop: { flexDirection: 'row', alignItems: 'baseline', gap: 10 },
    code: { fontSize: 18, fontWeight: '900', letterSpacing: 0.4, color: colors.text },
    time: { fontSize: 14, fontWeight: '700', color: colors.textMuted },
    count: { fontSize: 15, fontWeight: '800', color: colors.text },
    separator: { height: 10 },
    footer: { paddingVertical: 18, alignItems: 'center' },
    footerText: { fontSize: 14, fontWeight: '600', color: colors.textMuted },
    skeletons: { gap: 10 },
  });
