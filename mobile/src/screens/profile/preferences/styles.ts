import { StyleSheet } from 'react-native';
import { lightTheme, type AppTheme } from '@/theme';

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
      backgroundColor: 'rgba(255, 126, 62, 0.14)',
    },
    heroGlowSecondary: {
      position: 'absolute',
      bottom: -52,
      left: -40,
      width: 136,
      height: 136,
      borderRadius: 68,
      backgroundColor: 'rgba(255, 126, 62, 0.1)',
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

export const styles = createStyles(lightTheme);
