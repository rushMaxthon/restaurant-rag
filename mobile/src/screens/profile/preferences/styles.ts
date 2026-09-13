import { StyleSheet } from 'react-native';
import { type AppTheme } from '@/theme';

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    content: {
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 12,
      paddingBottom: 28,
      gap: 18,
    },
    heroCard: {
      borderRadius: 28,
      backgroundColor: theme.colors.surfaceAlt,
      padding: 18,
      overflow: 'hidden',
      gap: 10,
    },
    heroGlowPrimary: {
      position: 'absolute',
      top: -38,
      right: -34,
      width: 168,
      height: 168,
      borderRadius: 84,
      backgroundColor: theme.tone('rgba(255, 126, 62, 0.14)'),
    },
    heroGlowSecondary: {
      position: 'absolute',
      bottom: -52,
      left: -40,
      width: 136,
      height: 136,
      borderRadius: 68,
      backgroundColor: theme.tone('rgba(255, 126, 62, 0.1)'),
    },
    topBar: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
    },
    topBarAction: {
      minWidth: 58,
      paddingVertical: 8,
      paddingHorizontal: 12,
      alignItems: 'center',
    },
    topBarActionText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      fontWeight: '700',
    },
    heroBadge: {
      alignSelf: 'flex-start',
      paddingHorizontal: 14,
      paddingVertical: 8,
      borderRadius: 999,
      backgroundColor: theme.colors.surfaceRaised,
    },
    heroBadgeText: {
      color: theme.colors.primary,
      fontSize: 13,
      fontWeight: '800',
    },
    heroTitle: {
      color: theme.colors.text,
      fontSize: 34,
      lineHeight: 38,
      fontWeight: '900',
      letterSpacing: -1,
    },
    heroSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 15,
      lineHeight: 24,
    },
    sectionCard: {
      borderRadius: 22,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 16,
      gap: 14,
    },
    sectionHeader: {
      gap: 4,
    },
    sectionTitle: {
      color: theme.colors.text,
      fontSize: 18,
      fontWeight: '800',
    },
    sectionSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 20,
    },
    freeTextRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      marginTop: 12,
    },
    freeTextInput: {
      flex: 1,
      minHeight: 44,
      borderRadius: 12,
      paddingHorizontal: 14,
      color: theme.colors.text,
      fontSize: 14,
      backgroundColor: theme.colors.input,
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    freeTextAdd: {
      minHeight: 44,
      paddingHorizontal: 16,
      borderRadius: 12,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primarySoft,
      borderWidth: 1,
      borderColor: theme.primaryTint(0.24),
    },
    freeTextAddLabel: {
      color: theme.colors.primary,
      fontSize: 13,
      fontWeight: '800',
    },
    /**
     * An answer to a question the restaurant has since hidden, or to an option
     * it withdrew. Shown rather than dropped, because it is the customer's own
     * data - and marked, so it does not read as something they can still pick.
     */
    staleNotice: {
      marginTop: 10,
      padding: 10,
      borderRadius: 10,
      backgroundColor: theme.colors.warningSoft,
    },
    staleNoticeText: {
      color: theme.colors.text,
      fontSize: 12,
      lineHeight: 17,
    },
    errorText: {
      marginTop: 8,
      color: theme.colors.deepRed,
      fontSize: 12.5,
      fontWeight: '600',
    },
    loadingWrap: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 12,
      paddingVertical: 60,
    },
    loadingText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
    },
    chipRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 10,
    },
    chip: {
      paddingHorizontal: 14,
      paddingVertical: 9,
      borderRadius: 999,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
    },
    chipActive: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primary,
    },
    chipText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      fontWeight: '700',
    },
    chipTextActive: {
      color: theme.colors.white,
    },
    footerCard: {
      borderRadius: 22,
      backgroundColor: theme.colors.cream,
      padding: 16,
      gap: 12,
    },
    footerTitle: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
    },
    footerText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 20,
    },
    buttonRow: {
      flexDirection: 'row',
      gap: 12,
      alignItems: 'center',
    },
    secondaryButton: {
      flex: 1,
      minHeight: 50,
      borderRadius: 14,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
    },
    secondaryButtonText: {
      color: theme.colors.secondaryText,
      fontSize: 15,
      fontWeight: '800',
    },
    primaryButton: {
      flex: 1.2,
      minHeight: 50,
      borderRadius: 14,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primary,
    },
    primaryButtonDisabled: {
      opacity: 0.7,
    },
    primaryButtonText: {
      color: theme.colors.white,
      fontSize: 15,
      fontWeight: '800',
    },
  });
