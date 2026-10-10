import React, { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { useI18n } from '@/i18n';
import { useApi } from '@/store/SessionProvider';
import type { Earnings, RiderMe } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, motion } from '@theme/tokens';
import { rupees } from '@utils/format';
import { rateCard } from '@utils/pay';

/**
 * Home's lower half: the week so far and what a delivery pays. Both answer
 * the questions a rider asks between orders - "how am I doing?" and "is this
 * order worth it?" - instead of leaving the screen empty while they wait.
 */
export function HomeInsights({ me }: { me: RiderMe | null }) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const api = useApi();
  const nav = useNavigation<{ navigate: (route: 'Earnings') => void }>();
  const [week, setWeek] = useState<Earnings | null>(null);

  useFocusEffect(
    useCallback(() => {
      api
        .earnings(7)
        .then(setWeek)
        .catch(() => undefined);
    }, [api]),
  );

  const average =
    week && week.period_trips > 0
      ? Number(week.period_total) / week.period_trips
      : null;
  // The admin's rate card, folded to one line until tapped.
  const card = me?.pay?.slabs?.length ? rateCard(me.pay) : null;
  const [ratesOpen, setRatesOpen] = useState(false);

  return (
    <View style={styles.wrap}>
      <Animated.View entering={FadeInDown.delay(220).duration(motion.base)}>
        <Card onPress={() => nav.navigate('Earnings')} style={styles.week}>
          <View style={styles.weekHead}>
            <View
              style={[styles.badge, { backgroundColor: colors.successSoft }]}
            >
              <Icon name="trending-up" size={18} color={colors.success} />
            </View>
            <AppText variant="label" tone="muted" style={styles.flex}>
              {t('money.thisWeek')}
            </AppText>
            <Icon name="chevron-forward" size={18} color={colors.textFaint} />
          </View>
          <View style={styles.stats}>
            <Stat
              label={t('money.earned')}
              value={week ? rupees(week.period_total) : '—'}
            />
            <View style={[styles.rule, { backgroundColor: colors.border }]} />
            <Stat
              label={t('money.deliveries')}
              value={week ? String(week.period_trips) : '—'}
            />
            <View style={[styles.rule, { backgroundColor: colors.border }]} />
            <Stat
              label={t('money.perDelivery')}
              value={average != null ? rupees(Math.round(average)) : '—'}
            />
          </View>
        </Card>
      </Animated.View>

      {card ? (
        <Animated.View entering={FadeInDown.delay(280).duration(motion.base)}>
          <Card tone="alt" onPress={() => setRatesOpen(open => !open)}>
            <View style={styles.pay}>
              <View
                style={[styles.badge, { backgroundColor: colors.primarySoft }]}
              >
                <Icon name="cash-outline" size={18} color={colors.primary} />
              </View>
              <View style={styles.flex}>
                <AppText variant="bodyStrong">{t('money.howYouEarn')}</AppText>
                <AppText variant="caption" tone="muted">
                  {t('money.payRule', {
                    lowest: rupees(card.lowest),
                    highest: rupees(card.highest),
                    lastKm: String(card.lastKm),
                    incentive: rupees(card.incentive),
                  })}
                </AppText>
              </View>
              <Icon
                name={ratesOpen ? 'chevron-up' : 'chevron-down'}
                size={18}
                color={colors.textFaint}
              />
            </View>
            {ratesOpen ? (
              <View style={[styles.rates, { borderColor: colors.border }]}>
                {card.rows.map((row, i) => (
                  <View key={row.to} style={styles.rateRow}>
                    <AppText variant="caption" style={styles.flex}>
                      {i === 0
                        ? t('money.rateUpTo', { to: String(row.to) })
                        : t('money.rateRange', {
                            from: String(row.from),
                            to: String(row.to),
                          })}
                    </AppText>
                    <AppText variant="bodyStrong" tone="success">
                      {rupees(row.amount)}
                    </AppText>
                  </View>
                ))}
                <View style={styles.rateRow}>
                  <AppText variant="caption" style={styles.flex}>
                    {t('money.rateAbove', { km: String(card.lastKm) })}
                  </AppText>
                  <AppText variant="caption" tone="muted">
                    {t('money.priceLater')}
                  </AppText>
                </View>
                {card.incentive > 0 ? (
                  <AppText variant="caption" tone="success">
                    {t('money.incentiveNote', {
                      incentive: rupees(card.incentive),
                    })}
                  </AppText>
                ) : null}
                <AppText variant="caption" tone="muted">
                  {t('money.ownBike')}
                </AppText>
              </View>
            ) : null}
          </Card>
        </Animated.View>
      ) : null}
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <AppText variant="heading" numberOfLines={1}>
        {value}
      </AppText>
      {/* One line, shrunk to fit: a longer word in Hindi or Gujarati wrapped
          and lost its second half in this narrow column. */}
      <AppText
        variant="caption"
        tone="muted"
        align="center"
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.75}
      >
        {label}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: space.lg },
  flex: { flex: 1 },
  week: { borderRadius: radius.xl },
  weekHead: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  badge: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stats: { flexDirection: 'row', alignItems: 'center', marginTop: space.lg },
  stat: { flex: 1, alignItems: 'center', gap: 2 },
  rule: { width: 1, height: 32 },
  pay: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  rates: {
    marginTop: space.md,
    paddingTop: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    gap: space.sm,
  },
  rateRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
});
