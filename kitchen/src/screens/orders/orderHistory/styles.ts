import { StyleSheet } from 'react-native';
import { space, type, type AppTheme } from '@/theme';

export const createStyles = ({ colors }: AppTheme) =>
  StyleSheet.create({
    searchRow: {
      paddingHorizontal: space.lg,
      paddingTop: space.md,
      paddingBottom: space.xs,
      width: '100%',
      maxWidth: 760,
      alignSelf: 'center',
    },
    content: { padding: space.lg, paddingBottom: space.xxxl, flexGrow: 1 },
    // Rows stay a readable width on a tablet instead of stretching edge to edge.
    constrained: { width: '100%', maxWidth: 760, alignSelf: 'center' },
    summary: { ...type.overline, color: colors.textMuted, marginBottom: space.md },
    separator: { height: 10 },
    footer: { paddingVertical: space.xl, alignItems: 'center' },
    footerText: { ...type.caption, color: colors.textMuted },
    skeletons: { gap: 10 },
  });
