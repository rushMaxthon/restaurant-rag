import React, { useCallback, useState } from 'react';
import { Linking, Pressable, Share, StyleSheet, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { Illustration } from '@components/illustrations/Illustration';
import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { IconButton } from '@components/ui/IconButton';
import { Pill } from '@components/ui/Pill';
import { Screen } from '@components/ui/Screen';
import { Segmented } from '@components/ui/Segmented';
import { useI18n, type Key } from '@/i18n';
import { useNav } from '@navigation/types';
import { useApi } from '@/store/SessionProvider';
import type { Leaderboard, ReferralProgress, RiderReferral } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space } from '@theme/tokens';
import { rupees } from '@utils/format';
import {
  daysLeft,
  progressFraction,
  shareMessage,
  stepMarkers,
  tabOf,
  whatsappUrl,
  type ReferralTab,
} from '@utils/referral';

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
const FAQ: [Key, Key][] = [
  ['referral.q1', 'referral.a1'],
  ['referral.q2', 'referral.a2'],
  ['referral.q3', 'referral.a3'],
  ['referral.q4', 'referral.a4'],
  ['referral.q5', 'referral.a5'],
];
const WHATSAPP_GREEN = '#25D366';

/**
 * Refer & earn, Swiggy-style (backend `fleet/referral.py`): the code with a
 * one-tap WhatsApp invite, Earned / Pending / Paid, the friends in three
 * tabs with a bar marked at every step, this month's leaderboard, and the
 * questions riders ask. React Native's own share sheet is the fallback - it
 * offers Copy too, so no clipboard library.
 */
export function ReferralScreen() {
  const nav = useNav();
  const api = useApi();
  const { t } = useI18n();
  const { colors } = useTheme();
  const [data, setData] = useState<RiderReferral | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<ReferralTab>('active');
  const [openFaq, setOpenFaq] = useState<number | null>(null);

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
  const message =
    data?.code && terms
      ? shareMessage(data.code, terms, (key, vars) => t(key as Key, vars))
      : '';
  const share = () => {
    if (message) void Share.share({ message });
  };
  // Straight into WhatsApp; the share sheet when it is not installed.
  const whatsapp = () => {
    if (!message) return;
    Linking.openURL(whatsappUrl(message)).catch(share);
  };
  const shown = (data?.referrals ?? []).filter(r => tabOf(r.status) === tab);
  const firstStep = terms?.steps?.[0];

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

      <Illustration name="approved" width={200} style={styles.center} />

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
            {/* The totals go with the LAST step: at the first one the
                amounts are smaller (review, 2026-10-10). */}
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
              {data.enabled ? (
                <Pressable
                  accessibilityRole="button"
                  onPress={whatsapp}
                  style={({ pressed }) => [
                    styles.whatsapp,
                    {
                      backgroundColor: WHATSAPP_GREEN,
                      opacity: pressed ? 0.85 : 1,
                    },
                  ]}
                >
                  <Icon name="logo-whatsapp" size={22} color="#FFFFFF" />
                  <AppText variant="bodyStrong" style={styles.white}>
                    {t('referral.whatsapp')}
                  </AppText>
                </Pressable>
              ) : null}
              <Button
                kind="secondary"
                size="md"
                icon="share-social"
                label={t('referral.moreOptions')}
                onPress={share}
                disabledReason={data.enabled ? undefined : t('referral.off')}
              />
            </Card>
          ) : null}

          <Card style={styles.totals}>
            <Total
              label={t('referral.totalEarned')}
              value={rupees(data.earned_total)}
            />
            <View style={[styles.rule, { backgroundColor: colors.border }]} />
            <Total
              label={t('referral.totalPending')}
              value={rupees(data.pending_total)}
              tone="warning"
            />
            <View style={[styles.rule, { backgroundColor: colors.border }]} />
            <Total
              label={t('referral.totalPaid')}
              value={rupees(data.paid_total)}
              tone="success"
            />
          </Card>

          <Card style={styles.gapSm}>
            {HOW.map((key, i) => (
              <View key={key} style={styles.row}>
                <View
                  style={[styles.step, { backgroundColor: colors.primarySoft }]}
                >
                  <AppText variant="label" tone="primary">
                    {i + 1}
                  </AppText>
                </View>
                <AppText style={styles.flex}>
                  {t(key, {
                    n: firstStep?.deliveries ?? terms.deliveries_required,
                    days: terms.days_allowed,
                  })}
                </AppText>
              </View>
            ))}
            {(terms.steps ?? []).map(s => (
              <AppText key={s.deliveries} variant="caption" tone="muted">
                {t('referral.stepLine', {
                  deliveries: s.deliveries,
                  amount: `${rupees(s.referrer_amount)} + ${rupees(
                    s.joiner_amount,
                  )}`,
                })}
              </AppText>
            ))}
          </Card>

          <AppText variant="micro" tone="muted">
            {t('referral.yours')}
          </AppText>
          <Segmented
            options={[
              { key: 'active', label: t('referral.tab.active') },
              { key: 'earned', label: t('referral.tab.earned') },
              { key: 'expired', label: t('referral.tab.expired') },
            ]}
            value={tab}
            onChange={setTab}
          />
          {data.referrals.length === 0 ? (
            <AppText tone="muted">{t('referral.none')}</AppText>
          ) : shown.length === 0 ? (
            <AppText tone="muted">{t('referral.noneInTab')}</AppText>
          ) : (
            shown.map((r, i) => <FriendCard key={`${r.name}-${i}`} r={r} />)
          )}

          {data.leaderboard ? <Board board={data.leaderboard} /> : null}

          <AppText variant="micro" tone="muted">
            {t('referral.faq')}
          </AppText>
          <Card style={styles.gapSm}>
            {FAQ.map(([q, a], i) => (
              <Pressable
                key={q}
                accessibilityRole="button"
                accessibilityState={{ expanded: openFaq === i }}
                onPress={() => setOpenFaq(openFaq === i ? null : i)}
                style={styles.faqRow}
              >
                <View style={styles.row}>
                  <AppText variant="bodyStrong" style={styles.flex}>
                    {t(q)}
                  </AppText>
                  <Icon
                    name={openFaq === i ? 'chevron-up' : 'chevron-down'}
                    size={18}
                    color={colors.textFaint}
                  />
                </View>
                {openFaq === i ? (
                  <AppText variant="caption" tone="muted">
                    {t(a, { days: terms.days_allowed })}
                  </AppText>
                ) : null}
              </Pressable>
            ))}
          </Card>
        </Animated.View>
      ) : null}
    </Screen>
  );
}

function Total({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'success' | 'warning';
}) {
  return (
    <View style={styles.total}>
      <AppText variant="heading" tone={tone} numberOfLines={1}>
        {value}
      </AppText>
      <AppText variant="caption" tone="muted" numberOfLines={1}>
        {label}
      </AppText>
    </View>
  );
}

/** One friend: status, a bar with a marker at every step, this side's step amounts. */
function FriendCard({ r }: { r: ReferralProgress }) {
  const { t } = useI18n();
  const { colors } = useTheme();
  const left = daysLeft(r.deadline);
  const markers = stepMarkers(r.steps ?? [], r.required);
  return (
    <Card style={styles.gapSm}>
      <View style={styles.row}>
        <AppText variant="bodyStrong" style={styles.flex}>
          {r.name}
        </AppText>
        <Pill
          label={t(`referral.status.${r.status}` as Key)}
          tone={TONE[r.status]}
        />
      </View>
      <View style={[styles.track, { backgroundColor: colors.border }]}>
        <View
          style={[
            styles.bar,
            {
              width: `${progressFraction(r) * 100}%`,
              backgroundColor: colors.primary,
            },
          ]}
        />
        {markers.slice(0, -1).map(at => (
          <View
            key={at}
            style={[
              styles.marker,
              { left: `${at * 100}%`, backgroundColor: colors.surface },
            ]}
          />
        ))}
      </View>
      <AppText variant="caption" tone="muted">
        {t('referral.progress', {
          done: Math.min(r.delivered, r.required),
          n: r.required,
        })}
        {r.status === 'IN_PROGRESS' && left !== null
          ? ` · ${t('referral.daysLeft', { days: left })}`
          : ''}
      </AppText>
      <View style={styles.stepRow}>
        {(r.steps ?? []).map(s => (
          <View key={s.deliveries} style={styles.stepChip}>
            <Icon
              name={s.earned ? 'checkmark-circle' : 'ellipse-outline'}
              size={14}
              color={s.earned ? colors.success : colors.textFaint}
            />
            <AppText variant="caption" tone={s.earned ? 'success' : 'muted'}>
              {t('referral.stepLine', {
                deliveries: s.deliveries,
                amount: rupees(s.amount),
              })}
            </AppText>
          </View>
        ))}
      </View>
    </Card>
  );
}

/** This month's top referrers; the rider's own row stands out. */
function Board({ board }: { board: Leaderboard }) {
  const { t } = useI18n();
  const { colors } = useTheme();
  return (
    <>
      <AppText variant="micro" tone="muted">
        {t('referral.board')}
      </AppText>
      <Card style={styles.gapSm}>
        {board.top.map(row => (
          <View
            key={`${row.rank}-${row.name}`}
            style={[
              styles.row,
              styles.boardRow,
              row.me ? { backgroundColor: colors.primarySoft } : null,
            ]}
          >
            <AppText
              variant="bodyStrong"
              tone={row.rank <= 3 ? 'primary' : 'muted'}
              style={styles.rank}
            >
              #{row.rank}
            </AppText>
            <AppText style={styles.flex}>{row.name}</AppText>
            <AppText variant="caption" tone="muted">
              {t('referral.boardCount', { count: row.count })}
            </AppText>
          </View>
        ))}
        <AppText variant="caption" tone={board.my_rank ? 'primary' : 'muted'}>
          {board.my_rank
            ? t('referral.myRank', { rank: board.my_rank })
            : t('referral.notRanked')}
        </AppText>
      </Card>
    </>
  );
}

const styles = StyleSheet.create({
  content: { gap: space.lg },
  header: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  center: { alignSelf: 'center' },
  gap: { gap: space.md },
  gapSm: { gap: space.sm },
  codeCard: { gap: space.md, paddingVertical: space.xl },
  whatsapp: {
    minHeight: 56,
    borderRadius: radius.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.sm,
  },
  white: { color: '#FFFFFF' },
  totals: { flexDirection: 'row', alignItems: 'center' },
  total: { flex: 1, alignItems: 'center', gap: 2 },
  rule: { width: 1, height: 32 },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  step: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  flex: { flex: 1 },
  track: { height: 8, borderRadius: radius.pill, overflow: 'hidden' },
  bar: { height: 8 },
  marker: { position: 'absolute', top: 0, bottom: 0, width: 2 },
  stepRow: { flexDirection: 'row', flexWrap: 'wrap', gap: space.md },
  stepChip: { flexDirection: 'row', alignItems: 'center', gap: space.xs },
  boardRow: {
    paddingVertical: space.xs,
    paddingHorizontal: space.sm,
    borderRadius: radius.md,
  },
  rank: { width: 36 },
  faqRow: { gap: space.xs, paddingVertical: space.xs },
});
