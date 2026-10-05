import { StyleSheet } from 'react-native';
import type { AppTheme } from '@/theme';

export const createStyles = ({ colors }: AppTheme) =>
  StyleSheet.create({
    scroll: { padding: 16, paddingBottom: 40, gap: 22 },
    // A settings list is read, not scanned across; it stays narrow on a tablet.
    column: { width: '100%', maxWidth: 640, alignSelf: 'center', gap: 22 },
    section: { gap: 8 },
    sectionTitle: {
      fontSize: 13,
      fontWeight: '800',
      letterSpacing: 0.6,
      textTransform: 'uppercase',
      color: colors.textMuted,
      paddingHorizontal: 4,
    },
    group: {
      backgroundColor: colors.surface,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: 18,
      overflow: 'hidden',
    },
    row: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 14,
      paddingHorizontal: 16,
      paddingVertical: 12,
      minHeight: 60,
    },
    rowDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
    rowText: { flex: 1, gap: 2, minWidth: 0 },
    rowTitle: { fontSize: 16, fontWeight: '700', color: colors.text },
    rowBody: { fontSize: 14, lineHeight: 20, color: colors.textMuted },
    footnote: { fontSize: 13, lineHeight: 19, color: colors.textMuted, paddingHorizontal: 4 },
    avatar: {
      width: 52,
      height: 52,
      borderRadius: 26,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: colors.accentSoft,
    },
    avatarText: { fontSize: 20, fontWeight: '900', color: colors.accent },
    signOut: {
      minHeight: 56,
      borderRadius: 16,
      borderWidth: 1.5,
      borderColor: colors.danger,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 10,
    },
    signOutText: { fontSize: 17, fontWeight: '800', color: colors.danger },
    testButton: {
      minHeight: 44,
      borderRadius: 12,
      paddingHorizontal: 16,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: colors.surfaceMuted,
    },
    testButtonText: { fontSize: 15, fontWeight: '800', color: colors.text },
  });
