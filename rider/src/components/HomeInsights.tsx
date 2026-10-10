import React, { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { useI18n } from '@/i18n';
import { useApi } from '@/store/SessionProvider';
import type { Earnings } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, motion } from '@theme/tokens';
import { rupees } from '@utils/format';

/**
 * Home's lower half: the week so far - "how am I doing?" - instead of leaving
 * the screen empty while the rider waits. The rate card was here and was
 * taken off Home on the owner's call (2026-10-10).
 */
export function HomeInsights() {
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
});
