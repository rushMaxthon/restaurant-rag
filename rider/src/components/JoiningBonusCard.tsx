import React, { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { useI18n } from '@/i18n';
import { useApi } from '@/store/SessionProvider';
import type { ReferralProgress } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';
import { rupees } from '@utils/format';
import { daysLeft, progressFraction } from '@utils/referral';

/**
 * The rider's own joining bonus while they work towards it, and once it is
 * earned. Nothing at all for a rider who joined without a code.
 */
export function JoiningBonusCard() {
  const api = useApi();
  const { t } = useI18n();
  const { colors } = useTheme();
  const [mine, setMine] = useState<ReferralProgress | null>(null);

  useFocusEffect(
    useCallback(() => {
      api
        .referral()
        .then(r => setMine(r.joined_with))
        .catch(() => undefined);
    }, [api]),
  );

  if (!mine || (mine.status !== 'IN_PROGRESS' && mine.status !== 'EARNED'))
    return null;
  const earned = mine.status === 'EARNED';
  return (
    <Card tone="alt" style={styles.card}>
      <View
        style={[
          styles.badge,
          {
            backgroundColor: earned ? colors.successSoft : colors.primarySoft,
          },
        ]}
      >
        <Icon
          name="gift-outline"
          size={18}
          color={earned ? colors.success : colors.primary}
        />
      </View>
      <View style={styles.flex}>
        <AppText variant="bodyStrong">
          {t('referral.joinTitle', { amount: rupees(mine.amount) })}
        </AppText>
        <AppText variant="caption" tone={earned ? 'success' : 'muted'}>
          {earned
            ? t('referral.joinEarned')
            : t('referral.joinBody', {
                done: Math.min(mine.delivered, mine.required),
                n: mine.required,
                days: daysLeft(mine.deadline) ?? 0,
              })}
        </AppText>
        {!earned ? (
          <View style={[styles.track, { backgroundColor: colors.border }]}>
            <View
              style={[
                styles.bar,
                {
                  width: `${progressFraction(mine) * 100}%`,
                  backgroundColor: colors.primary,
                },
              ]}
            />
          </View>
        ) : null}
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  badge: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
  },
  flex: { flex: 1, gap: space.xs },
  track: {
    height: 5,
    borderRadius: 3,
    overflow: 'hidden',
    marginTop: space.xs,
  },
  bar: { height: 5 },
});
