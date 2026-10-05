import { StyleSheet } from 'react-native';
import { radius, space, type, type AppTheme } from '@/theme';

// Items on the left, particulars and the action on the right.
export const TWO_PANE_MIN_WIDTH = 768;

export const createStyles = ({ colors }: AppTheme) =>
  StyleSheet.create({
    flex: { flex: 1 },
    scroll: { padding: space.lg, gap: space.lg, paddingBottom: space.xxxl },
    panes: { flex: 1, flexDirection: 'row', gap: space.lg, padding: space.lg },
    paneMain: { flex: 3 },
    paneSide: { flex: 2, gap: space.lg },
    paneScroll: { gap: space.lg, paddingBottom: space.xxl },
    card: {
      backgroundColor: colors.surface,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: radius.xl,
      padding: space.xl,
      gap: space.lg,
      overflow: 'hidden',
    },
    // The stage's own colour along the top of the hero card.
    accent: { position: 'absolute', top: 0, left: 0, right: 0, height: 5 },
    hero: { flexDirection: 'row', alignItems: 'flex-start', gap: space.md, marginTop: 2 },
    heroText: { flex: 1, gap: space.sm },
    code: { ...type.display, color: colors.text, fontVariant: ['tabular-nums'] },
    waitBox: {
      alignItems: 'center',
      borderRadius: radius.lg,
      paddingHorizontal: space.lg,
      paddingVertical: 10,
      minWidth: 96,
    },
    waitLabel: { ...type.overline, fontSize: 11 },
    waitValue: { fontSize: 32, fontWeight: '900', fontVariant: ['tabular-nums'] },
    divider: { height: StyleSheet.hairlineWidth, backgroundColor: colors.border },
    sectionHead: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
    sectionTitle: { ...type.heading, color: colors.text, flex: 1 },
    countPill: {
      borderRadius: radius.pill,
      paddingHorizontal: 10,
      paddingVertical: 3,
      backgroundColor: colors.surfaceMuted,
    },
    countPillText: { fontSize: 13, fontWeight: '800', color: colors.text },
    banner: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      borderRadius: radius.md,
      padding: 14,
    },
    bannerText: { flex: 1, fontSize: 15, fontWeight: '700', lineHeight: 21 },
    actionBar: {
      borderTopWidth: StyleSheet.hairlineWidth,
      borderTopColor: colors.border,
      backgroundColor: colors.surface,
      paddingHorizontal: space.lg,
      paddingTop: space.md,
      paddingBottom: space.md,
      gap: 10,
    },
    // On a tablet the action sits at the foot of the side pane as a card,
    // not as a full-width strip.
    actionCard: {
      borderRadius: radius.xl,
      overflow: 'hidden',
      borderWidth: 1,
      borderColor: colors.border,
    },
    nextHint: { flexDirection: 'row', alignItems: 'center', gap: 6 },
    nextHintText: { ...type.caption, color: colors.textMuted },
    nextHintDot: { width: 8, height: 8, borderRadius: 4 },
    actionError: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 8,
      backgroundColor: colors.dangerSoft,
      borderRadius: radius.md,
      padding: space.md,
    },
    actionErrorText: { flex: 1, fontSize: 14, fontWeight: '700', color: colors.danger, lineHeight: 19 },
  });
