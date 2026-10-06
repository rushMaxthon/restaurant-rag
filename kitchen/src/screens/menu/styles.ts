import { StyleSheet } from 'react-native';
import { radius, space, type AppTheme } from '@/theme';

export const createStyles = ({ colors }: AppTheme) =>
  StyleSheet.create({
    // The list stays a readable width on a tablet.
    column: { width: '100%', maxWidth: 820, alignSelf: 'center' },
    content: { paddingHorizontal: space.lg, paddingBottom: space.xxxl, flexGrow: 1 },

    header: { flexDirection: 'row', alignItems: 'flex-start', gap: space.md, paddingTop: space.lg },
    headerText: { flex: 1, gap: 2 },
    overline: { fontSize: 12, fontWeight: '800', letterSpacing: 1, textTransform: 'uppercase', color: colors.accent },
    title: { fontSize: 30, fontWeight: '800', letterSpacing: -0.4, color: colors.text },
    subtitle: { fontSize: 14, fontWeight: '500', color: colors.textMuted, marginTop: 2 },
    branchButton: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 2,
      height: 40,
      paddingHorizontal: 8,
      borderRadius: radius.md,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.surface,
    },

    stats: { flexDirection: 'row', gap: space.sm, marginTop: space.lg },
    stat: {
      flex: 1,
      borderRadius: radius.md,
      borderWidth: 1,
      paddingHorizontal: space.md,
      paddingVertical: 10,
      gap: 2,
    },
    statValue: { fontSize: 20, fontWeight: '900', fontVariant: ['tabular-nums'] },
    statLabel: { fontSize: 12, fontWeight: '600' },

    searchCard: {
      marginTop: space.md,
      backgroundColor: colors.surface,
      borderColor: colors.border,
      borderWidth: 1,
      borderRadius: radius.lg,
      padding: space.md,
      gap: space.md,
    },
    chips: { gap: 8, alignItems: 'center', paddingRight: space.sm },
    chip: { height: 38, borderRadius: radius.md, borderWidth: 1, paddingHorizontal: 16, justifyContent: 'center' },
    chipText: { fontSize: 14, fontWeight: '700' },

    sectionHead: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: space.sm,
      paddingTop: space.xl,
      paddingBottom: space.sm,
      paddingHorizontal: 2,
      backgroundColor: colors.background,
    },
    sectionTitle: { fontSize: 17, fontWeight: '800', color: colors.text },
    sectionCount: { flex: 1, fontSize: 13, fontWeight: '600', color: colors.textMuted },

    // One white card per section; each row is a slice of it.
    group: {
      backgroundColor: colors.surface,
      borderLeftWidth: 1,
      borderRightWidth: 1,
      borderColor: colors.border,
      overflow: 'hidden',
    },
    groupFirst: { borderTopWidth: 1, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg },
    groupLast: { borderBottomWidth: 1, borderBottomLeftRadius: radius.lg, borderBottomRightRadius: radius.lg },
    skeletons: { gap: 8, paddingTop: space.lg },
  });
