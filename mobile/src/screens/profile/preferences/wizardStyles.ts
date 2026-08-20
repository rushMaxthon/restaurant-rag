import { StyleSheet } from 'react-native';
import { lightTheme, type AppTheme } from '@/theme';

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    screen: {
      flex: 1,
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 8,
      gap: 14,
    },
    topSection: {
      gap: 10,
    },
    progressMetaRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    progressLabel: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    skipButton: {
      paddingVertical: 6,
      paddingHorizontal: 10,
    },
    skipButtonText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      fontWeight: '700',
    },
    progressTrack: {
      height: 8,
      borderRadius: 999,
      backgroundColor: theme.colors.border,
      overflow: 'hidden',
    },
    progressFill: {
      height: '100%',
      borderRadius: 999,
      backgroundColor: theme.colors.primary,
    },
    heroCard: {
      borderRadius: 24,
      backgroundColor: theme.colors.surfaceAlt,
      padding: 18,
      overflow: 'hidden',
      gap: 10,
    },
    heroGlowPrimary: {
      position: 'absolute',
      top: -42,
      right: -34,
      width: 156,
      height: 156,
      borderRadius: 78,
      backgroundColor: 'rgba(255, 126, 62, 0.14)',
    },
    heroGlowSecondary: {
      position: 'absolute',
      bottom: -50,
      left: -34,
      width: 122,
      height: 122,
      borderRadius: 61,
      backgroundColor: 'rgba(255, 126, 62, 0.1)',
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
      fontSize: 30,
      lineHeight: 34,
      fontWeight: '900',
      letterSpacing: -0.9,
    },
    heroSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 22,
    },
    stepContentWrap: {
      flexGrow: 1,
      paddingBottom: 8,
    },
    stepCard: {
      flex: 1,
      borderRadius: 22,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 18,
      minHeight: 280,
    },
    stepInner: {
      gap: 14,
    },
    stepTitle: {
      color: theme.colors.text,
      fontSize: 24,
      lineHeight: 28,
      fontWeight: '900',
      letterSpacing: -0.5,
    },
    stepDescription: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 22,
    },
    optionGrid: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 10,
      paddingTop: 6,
    },
    chip: {
      borderRadius: 999,
      borderWidth: 1,
      overflow: 'hidden',
    },
    chipPressable: {
      paddingHorizontal: 14,
      paddingVertical: 9,
    },
    chipText: {
      fontSize: 13,
      fontWeight: '800',
    },
    footerBar: {
      paddingTop: 6,
    },
    footerButtons: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
    },
    backButtonPlaceholder: {
      flex: 1,
    },
    backButton: {
      flex: 1,
      minHeight: 52,
      borderRadius: 16,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
    },
    backButtonText: {
      color: theme.colors.secondaryText,
      fontSize: 15,
      fontWeight: '800',
    },
    nextButton: {
      flex: 1.35,
      minHeight: 52,
      borderRadius: 16,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primary,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.16,
      shadowRadius: 12,
      shadowOffset: { width: 0, height: 8 },
      elevation: 3,
    },
    nextButtonDisabled: {
      opacity: 0.72,
    },
    nextButtonText: {
      color: theme.colors.white,
      fontSize: 15,
      fontWeight: '900',
    },
  });

export const styles = createStyles(lightTheme);
