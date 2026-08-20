import React, { type PropsWithChildren } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';

interface AuthScreenLayoutProps extends PropsWithChildren {
  eyebrow: string;
  title: string;
  subtitle: string;
  footerPrompt: string;
  footerActionLabel: string;
  onFooterAction: () => void;
  errorMessage?: string | null;
}

export function AuthScreenLayout({
  eyebrow,
  title,
  subtitle,
  footerPrompt,
  footerActionLabel,
  onFooterAction,
  errorMessage,
  children,
}: AuthScreenLayoutProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.flex}
      >
        <ScrollView
          bounces={false}
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.panel}>
            <View style={styles.brand}>
              <View style={styles.brandMark}>
                <Text style={styles.brandMarkText}>RR</Text>
              </View>
              <View style={styles.brandCopy}>
                <Text style={styles.brandTitle}>Restaurant RAG</Text>
                <Text style={styles.brandSubtitle}>
                  Smarter cravings, faster checkout
                </Text>
              </View>
            </View>

            <View style={styles.header}>
              <Text style={styles.eyebrow}>{eyebrow}</Text>
              <Text style={styles.title}>{title}</Text>
              <Text style={styles.subtitle}>{subtitle}</Text>
            </View>

            {errorMessage ? (
              <View style={styles.alert}>
                <Text style={styles.alertText}>{errorMessage}</Text>
              </View>
            ) : null}

            <View style={styles.formStack}>{children}</View>

            <View style={styles.switchRow}>
              <Text style={styles.switchPrompt}>{footerPrompt}</Text>
              <Pressable onPress={onFooterAction}>
                <Text style={styles.switchAction}>{footerActionLabel}</Text>
              </Pressable>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    flex: {
      flex: 1,
    },
    content: {
      flexGrow: 1,
      paddingHorizontal: 20,
      paddingVertical: 20,
      justifyContent: 'center',
    },
    panel: {
      borderRadius: 28,
      padding: 22,
      gap: 18,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.08,
      shadowOffset: { width: 0, height: 10 },
      shadowRadius: 24,
      elevation: 4,
    },
    brand: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
    },
    brandMark: {
      width: 48,
      height: 48,
      borderRadius: 16,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primary,
    },
    brandMarkText: {
      color: theme.colors.white,
      fontSize: 18,
      fontWeight: '900',
    },
    brandCopy: {
      gap: 2,
    },
    brandTitle: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    brandSubtitle: {
      color: theme.colors.hint,
      fontSize: 11,
    },
    header: {
      gap: 8,
    },
    eyebrow: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '800',
      letterSpacing: 1,
      textTransform: 'uppercase',
    },
    title: {
      color: theme.colors.text,
      fontSize: 29,
      lineHeight: 32,
      fontWeight: '800',
      letterSpacing: -0.9,
    },
    subtitle: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 21,
    },
    alert: {
      borderRadius: 16,
      paddingHorizontal: 14,
      paddingVertical: 12,
      backgroundColor: theme.colors.dangerSoft,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? 'rgba(203,32,45,0.26)' : 'rgba(203,32,45,0.14)',
    },
    alertText: {
      color: theme.colors.deepRed,
      fontSize: 13,
      lineHeight: 19,
      fontWeight: '700',
    },
    formStack: {
      gap: 12,
    },
    switchRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      flexWrap: 'wrap',
      marginTop: 2,
    },
    switchPrompt: {
      color: theme.colors.secondaryText,
      fontSize: 13,
    },
    switchAction: {
      color: theme.colors.primary,
      fontSize: 13,
      fontWeight: '800',
    },
  });

const styles = createStyles(theme);
