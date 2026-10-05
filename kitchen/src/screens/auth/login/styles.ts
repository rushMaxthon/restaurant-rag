import { StyleSheet } from 'react-native';
import type { AppTheme } from '@/theme';

// Below this the brand panel stacks above the form; at or above it (any
// tablet, and a phone in landscape) the two sit side by side.
export const WIDE_LAYOUT_MIN_WIDTH = 768;

export const createStyles = ({ colors }: AppTheme) =>
  StyleSheet.create({
    flex: { flex: 1 },
    scroll: { flexGrow: 1 },
    page: { flex: 1, padding: 16, gap: 16 },
    pageWide: { flexDirection: 'row', padding: 24, gap: 24 },

    brand: {
      backgroundColor: colors.surface,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: 20,
      padding: 24,
      gap: 16,
    },
    brandWide: { flex: 1, justifyContent: 'center', padding: 40, gap: 24 },
    // On a phone the brand is a header row, not a card, so the form is the
    // first thing on screen rather than something to scroll to.
    brandCompact: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 14,
      paddingTop: 8,
      paddingHorizontal: 4,
    },
    mark: {
      width: 56,
      height: 56,
      borderRadius: 16,
      backgroundColor: colors.accent,
      alignItems: 'center',
      justifyContent: 'center',
    },
    markCompact: { width: 44, height: 44, borderRadius: 12 },
    markText: { color: colors.onAccent, fontSize: 28, fontWeight: '800' },
    markTextCompact: { fontSize: 22 },
    brandTitle: { color: colors.text, fontSize: 30, fontWeight: '800' },
    brandTitleWide: { fontSize: 40 },
    brandTitleCompact: { fontSize: 24 },
    brandLead: { color: colors.textMuted, fontSize: 17, lineHeight: 25 },
    chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
    chip: { borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8 },
    chipText: { fontSize: 14, fontWeight: '700' },

    formColumn: { justifyContent: 'center' },
    formColumnWide: { flex: 1, alignItems: 'center' },
    card: {
      width: '100%',
      maxWidth: 460,
      alignSelf: 'center',
      backgroundColor: colors.surface,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: 20,
      padding: 24,
      gap: 20,
    },
    heading: { color: colors.text, fontSize: 26, fontWeight: '800' },
    subheading: { color: colors.textMuted, fontSize: 16, lineHeight: 23, marginTop: 6 },
    banner: {
      backgroundColor: colors.dangerSoft,
      borderColor: colors.danger,
      borderWidth: 1,
      borderRadius: 12,
      padding: 14,
    },
    notice: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      backgroundColor: colors.warningSoft,
      borderColor: colors.warning,
      borderWidth: 1,
      borderRadius: 12,
      padding: 14,
    },
    noticeText: { flex: 1, color: colors.text, fontSize: 15, fontWeight: '600', lineHeight: 21 },
    bannerText: { color: colors.danger, fontSize: 15, fontWeight: '600', lineHeight: 21 },
    footnote: { color: colors.textMuted, fontSize: 14, lineHeight: 20, textAlign: 'center' },
  });
