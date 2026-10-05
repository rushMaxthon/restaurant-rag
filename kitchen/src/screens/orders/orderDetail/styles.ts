import { StyleSheet } from 'react-native';
import type { AppTheme } from '@/theme';

// Items on the left, particulars and the action on the right.
export const TWO_PANE_MIN_WIDTH = 768;

export const createStyles = ({ colors }: AppTheme) =>
  StyleSheet.create({
    flex: { flex: 1 },
    scroll: { padding: 16, gap: 16, paddingBottom: 32 },
    panes: { flex: 1, flexDirection: 'row', gap: 16, padding: 16 },
    paneMain: { flex: 3 },
    paneSide: { flex: 2, gap: 16 },
    paneScroll: { gap: 16, paddingBottom: 24 },
    card: {
      backgroundColor: colors.surface,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: 20,
      padding: 18,
      gap: 14,
    },
    hero: { flexDirection: 'row', alignItems: 'center', gap: 12 },
    heroText: { flex: 1, gap: 6 },
    code: { fontSize: 30, fontWeight: '900', letterSpacing: 0.5, color: colors.text },
    waitBox: { alignItems: 'flex-end' },
    waitLabel: { fontSize: 13, fontWeight: '700', color: colors.textMuted },
    waitValue: { fontSize: 34, fontWeight: '900', fontVariant: ['tabular-nums'] },
    sectionTitle: { fontSize: 17, fontWeight: '800', color: colors.text },
    banner: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      borderRadius: 14,
      padding: 14,
    },
    bannerText: { flex: 1, fontSize: 15, fontWeight: '700', lineHeight: 21 },
    actionBar: {
      borderTopWidth: StyleSheet.hairlineWidth,
      borderTopColor: colors.border,
      backgroundColor: colors.surface,
      paddingHorizontal: 16,
      paddingTop: 12,
      paddingBottom: 12,
      gap: 10,
    },
    // On a tablet the action sits at the foot of the side pane as a card,
    // not as a full-width strip.
    actionCard: {
      borderRadius: 20,
      overflow: 'hidden',
      borderWidth: 1,
      borderColor: colors.border,
    },
    actionError: {
      fontSize: 14,
      fontWeight: '600',
      color: colors.danger,
      backgroundColor: colors.dangerSoft,
      borderRadius: 10,
      padding: 10,
    },
  });
