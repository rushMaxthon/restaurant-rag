import React from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, { FadeIn } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Icon, type IconName } from '@components/ui/Icon';
import { useI18n, type Key } from '@/i18n';
import type { ApplicationStatus } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';

type Tone = 'primary' | 'warning' | 'danger' | 'success';

const LOOK: Record<
  ApplicationStatus,
  { tone: Tone; icon: IconName; title: Key; body: Key }
> = {
  DRAFT: {
    tone: 'primary',
    icon: 'create-outline',
    title: 'onboarding.home.draftTitle',
    body: 'onboarding.home.draftBody',
  },
  SUBMITTED: {
    tone: 'primary',
    icon: 'hourglass-outline',
    title: 'onboarding.home.reviewTitle',
    body: 'onboarding.home.reviewBody',
  },
  CHANGES_NEEDED: {
    tone: 'warning',
    icon: 'alert-circle',
    title: 'onboarding.home.changesTitle',
    body: 'onboarding.home.changesBody',
  },
  REJECTED: {
    tone: 'danger',
    icon: 'close-circle',
    title: 'onboarding.home.rejectedTitle',
    body: 'onboarding.home.rejectedBody',
  },
  APPROVED: {
    tone: 'success',
    icon: 'checkmark-circle',
    title: 'onboarding.home.approvedTitle',
    body: 'onboarding.home.approvedBody',
  },
};

/**
 * Where the application stands, in one tinted card at the top of the status
 * screen. Amber for "needs you", red only for the final no - and that one
 * carries the admin's reason, because "not approved" alone sends a rider to
 * the support line to ask why.
 */
export function StatusBanner({
  status,
  finalReason,
}: {
  status: ApplicationStatus;
  finalReason?: string;
}) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const look = LOOK[status];
  const ink = {
    primary: colors.primary,
    warning: colors.warning,
    danger: colors.danger,
    success: colors.success,
  }[look.tone];
  const soft = {
    primary: colors.primarySoft,
    warning: colors.warningSoft,
    danger: colors.dangerSoft,
    success: colors.successSoft,
  }[look.tone];
  const reason = status === 'REJECTED' && finalReason ? finalReason : null;

  return (
    <Animated.View
      entering={FadeIn.duration(300)}
      accessibilityRole="summary"
      style={[styles.card, { backgroundColor: soft, borderColor: ink }]}
    >
      <View style={[styles.icon, { backgroundColor: ink }]}>
        <Icon name={look.icon} size={22} color={colors.bg} />
      </View>
      <View style={styles.text}>
        <AppText variant="heading">{t(look.title)}</AppText>
        {reason ? <AppText variant="bodyStrong">{reason}</AppText> : null}
        <AppText variant="label" tone="muted">
          {t(look.body)}
        </AppText>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    gap: space.md,
    padding: space.lg,
    borderRadius: radius.xl,
    borderWidth: 1,
  },
  icon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  text: { flex: 1, gap: space.xs },
});
