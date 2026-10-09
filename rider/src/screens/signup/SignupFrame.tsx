import React from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { IconButton } from '@components/ui/IconButton';
import { Screen } from '@components/ui/Screen';
import { useI18n } from '@/i18n';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';

/**
 * The three sign-up screens share one frame: back, an icon tile, a title and
 * one line under it, then the form. Same rhythm as the sign-in screen, so
 * moving between them reads as one flow.
 */
export function SignupFrame({
  icon,
  title,
  lead,
  onBack,
  children,
}: {
  icon: IconName;
  title: string;
  lead: string;
  onBack?: () => void;
  children: React.ReactNode;
}) {
  const { colors } = useTheme();
  const { t } = useI18n();
  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Screen scroll contentStyle={styles.content}>
        {onBack ? (
          <View style={styles.top}>
            <IconButton
              icon="arrow-back"
              label={t('common.back')}
              onPress={onBack}
            />
          </View>
        ) : null}
        <Animated.View entering={FadeInDown.duration(400)} style={styles.hero}>
          <View style={[styles.tile, { backgroundColor: colors.primarySoft }]}>
            <Icon name={icon} size={30} color={colors.primary} />
          </View>
          <AppText variant="title" accessibilityRole="header">
            {title}
          </AppText>
          <AppText tone="muted">{lead}</AppText>
        </Animated.View>
        <View style={styles.form}>{children}</View>
      </Screen>
    </KeyboardAvoidingView>
  );
}

/** A problem in words, in a red-edged card - never a red border with nothing said. */
export function ErrorCard({
  message,
  children,
}: {
  message: string;
  children?: React.ReactNode;
}) {
  const { colors } = useTheme();
  return (
    <Animated.View entering={FadeInDown.duration(200)}>
      <Card tone="alt" style={[styles.error, { borderColor: colors.danger }]}>
        <View style={styles.errorRow}>
          <Icon name="alert-circle" size={20} color={colors.danger} />
          <AppText variant="label" tone="danger" style={styles.flex}>
            {message}
          </AppText>
        </View>
        {children}
      </Card>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { flexGrow: 1 },
  top: { flexDirection: 'row', marginBottom: space.lg },
  hero: { gap: space.sm, marginBottom: space.xxl },
  tile: {
    width: 60,
    height: 60,
    borderRadius: radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.sm,
  },
  form: { gap: space.lg },
  error: { gap: space.md, paddingVertical: space.md },
  errorRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
});
