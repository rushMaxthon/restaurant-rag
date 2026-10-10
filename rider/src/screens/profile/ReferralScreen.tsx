import React, { useCallback, useState } from 'react';
import { Share, StyleSheet, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { Illustration } from '@components/illustrations/Illustration';
import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { IconButton } from '@components/ui/IconButton';
import { Pill } from '@components/ui/Pill';
import { Screen } from '@components/ui/Screen';
import { useI18n, type Key } from '@/i18n';
import { useNav } from '@navigation/types';
import { useApi } from '@/store/SessionProvider';
import type { ReferralProgress, RiderReferral } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space } from '@theme/tokens';
import { rupees } from '@utils/format';
import { daysLeft, progressFraction, shareMessage } from '@utils/referral';

const TONE: Record<
  ReferralProgress['status'],
  'neutral' | 'warning' | 'success' | 'danger'
> = {
  WAITING: 'neutral',
  IN_PROGRESS: 'warning',
  EARNED: 'success',
  EXPIRED: 'neutral',
  CANCELLED: 'danger',
};

const HOW: Key[] = ['referral.how1', 'referral.how2', 'referral.how3'];

/**
 * Refer & earn (backend `fleet/referral.py`): the rider's code with Share,
 * today's terms in three lines, what referrals have earned, and each friend's
 * progress. React Native's own share sheet - it offers Copy too, so no
 * clipboard library.
 */
export function ReferralScreen() {
  const nav = useNav();
  const api = useApi();
  const { t } = useI18n();
  const { colors } = useTheme();
  const [data, setData] = useState<RiderReferral | null>(null);
  const [error, setError] = useState<string | null>(null);

  useFocusEffect(
    useCallback(() => {
      api
        .referral()
        .then(next => {
          setData(next);
          setError(null);
        })
        .catch((e: Error) => setError(e.message));
    }, [api]),
  );

  const terms = data?.terms;
  const share = () => {
    if (!data?.code || !terms) return;
    void Share.share({
      message: shareMessage(data.code, terms, (key, vars) =>
        t(key as Key, vars),
      ),
    });
  };

  return (
    <Screen scroll contentStyle={styles.content}>
      <View style={styles.header}>
        <IconButton
          icon="chevron-back"
          label={t('common.back')}
          onPress={() => nav.goBack()}
        />
        <AppText variant="heading">{t('referral.title')}</AppText>
      </View>

      <Illustration name="approved" width={220} style={styles.center} />

      {error ? (
        <AppText tone="danger" align="center">
          {error}
        </AppText>
      ) : null}

      {data && terms ? (
        <Animated.View
          entering={FadeInDown.duration(motion.base)}
          style={styles.gap}
        >
          <AppText tone="muted" align="center">
            {t('referral.lead', {
              n: terms.deliveries_required,
              days: terms.days_allowed,
              referrer: rupees(terms.referrer_amount),
              joiner: rupees(terms.joiner_amount),
            })}
          </AppText>

          {data.code ? (
            <Card style={styles.codeCard}>
              <AppText variant="micro" tone="muted" align="center">
                {t('referral.yourCode')}
              </AppText>
              <AppText
                variant="display"
                align="center"
                selectable
                accessibilityLabel={data.code.split('').join(' ')}
              >
                {data.code}
              </AppText>
              <Button
                label={t('referral.share')}
                icon="share-social"
                onPress={share}
                disabledReason={data.enabled ? undefined : t('referral.off')}
              />
            </Card>
          ) : null}

          <Card style={styles.gapSm}>
            {HOW.map((key, i) => (
              <View key={key} style={styles.howRow}>
                <View
                  style={[styles.step, { backgroundColor: colors.primarySoft }]}
                >
                  <AppText variant="label" tone="primary">
                    {i + 1}
                  </AppText>
                </View>
                <AppText style={styles.flex}>
                  {t(key, {
                    n: terms.deliveries_required,
                    days: terms.days_allowed,
                  })}
                </AppText>
              </View>
            ))}
          </Card>

          <Card style={styles.row}>
            <AppText style={styles.flex}>{t('referral.earned')}</AppText>
            <AppText variant="heading" tone="success">
              {rupees(data.earned_total)}
            </AppText>
          </Card>

          <AppText variant="micro" tone="muted">
            {t('referral.yours')}
          </AppText>
          {data.referrals.length === 0 ? (
            <AppText tone="muted">{t('referral.none')}</AppText>
          ) : (
            data.referrals.map((r, i) => {
              const left = daysLeft(r.deadline);
              return (
                <Card key={`${r.name}-${i}`} style={styles.gapSm}>
                  <View style={styles.row}>
                    <AppText variant="bodyStrong" style={styles.flex}>
                      {r.name}
                    </AppText>
                    <Pill
                      label={t(`referral.status.${r.status}` as Key)}
                      tone={TONE[r.status]}
                    />
                  </View>
                  <View
                    style={[styles.track, { backgroundColor: colors.border }]}
                  >
                    <View
                      style={[
                        styles.bar,
                        {
                          width: `${progressFraction(r) * 100}%`,
                          backgroundColor: colors.primary,
                        },
                      ]}
                    />
                  </View>
                  <AppText variant="caption" tone="muted">
                    {t('referral.progress', {
                      done: Math.min(r.delivered, r.required),
                      n: r.required,
                    })}
                    {r.status === 'IN_PROGRESS' && left !== null
                      ? ` · ${t('referral.daysLeft', { days: left })}`
                      : ''}
                    {` · ${rupees(r.amount)}`}
                  </AppText>
                </Card>
              );
            })
          )}
        </Animated.View>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { gap: space.lg },
  header: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  center: { alignSelf: 'center' },
  gap: { gap: space.md },
  gapSm: { gap: space.sm },
  codeCard: { gap: space.md, paddingVertical: space.xl },
  howRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  step: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  flex: { flex: 1 },
  track: { height: 6, borderRadius: radius.pill, overflow: 'hidden' },
  bar: { height: 6 },
});
