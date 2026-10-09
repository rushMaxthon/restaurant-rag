import React, { useCallback, useState } from 'react';
import { ConfirmDialog } from '@components/ui/ConfirmDialog';
import { StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { ItemRow } from '@components/onboarding/ItemRow';
import { StatusBanner } from '@components/onboarding/StatusBanner';
import { LanguageButton } from '@components/LanguageSwitch';
import { AppText } from '@components/ui/AppText';
import { BrandMark } from '@components/ui/BrandMark';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Group, GroupRow } from '@components/ui/Group';
import { Screen } from '@components/ui/Screen';
import { Skeleton } from '@components/ui/Skeleton';
import { SUPPORT_PHONE } from '@/config/api';
import { useI18n } from '@/i18n';
import { useNav } from '@navigation/types';
import { useApplication } from '@/store/ApplicationProvider';
import { useRider } from '@/store/RiderProvider';
import { useSession, useSignedInUser } from '@/store/SessionProvider';
import type { ApplicationView } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space } from '@theme/tokens';
import { monthName } from '@utils/format';
import { call } from '@utils/links';
import {
  firstIncompleteStep,
  itemState,
  progress,
  SECTION_OF,
  showsChecklist,
} from '@utils/onboarding';

/**
 * What a rider who signed up sees instead of the tabs, until approved: where
 * the application stands, what is still needed, and the one next thing to
 * do. After a send-back the flagged rows are the point - red, with the
 * admin's words and a Fix that opens the right step.
 */
export function OnboardingHomeScreen() {
  const { t } = useI18n();
  const { colors } = useTheme();
  const user = useSignedInUser();
  const { signOut } = useSession();
  const { refreshMe } = useRider();
  const { view, loading, error, refresh } = useApplication();
  const [refreshing, setRefreshing] = useState(false);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([refresh(), refreshMe()]);
    setRefreshing(false);
  }, [refresh, refreshMe]);

  const [askSignOut, setAskSignOut] = useState(false);
  const confirmSignOut = () => setAskSignOut(true);

  const firstName =
    (view?.sections.personal.full_name || user?.full_name || '').split(
      ' ',
    )[0] ?? '';

  return (
    <Screen
      scroll
      refreshing={refreshing}
      onRefresh={onRefresh}
      contentStyle={styles.content}
    >
      <View style={styles.header}>
        <BrandMark size={44} />
        <View style={styles.flex}>
          <AppText variant="label" tone="muted" numberOfLines={1}>
            {t('onboarding.home.hi', { name: firstName })}
          </AppText>
          <AppText variant="title" accessibilityRole="header">
            {t('onboarding.home.title')}
          </AppText>
        </View>
        <LanguageButton />
      </View>

      {view ? (
        <Summary view={view} />
      ) : loading ? (
        <View style={styles.gap}>
          <Skeleton height={96} round={radius.xl} />
          <Skeleton height={64} round={radius.xl} />
          <Skeleton height={280} round={radius.xl} />
        </View>
      ) : (
        <Card style={styles.gap}>
          <AppText variant="bodyStrong">
            {t('onboarding.home.loadFailed')}
          </AppText>
          {error ? (
            <AppText variant="label" tone="muted">
              {error}
            </AppText>
          ) : null}
          <Button
            kind="secondary"
            size="md"
            icon="refresh"
            label={t('onboarding.home.retry')}
            onPress={onRefresh}
          />
        </Card>
      )}

      <Group title={t('onboarding.home.help')}>
        <GroupRow
          icon="headset-outline"
          label={t('onboarding.home.callSupport')}
          onPress={() => void call(SUPPORT_PHONE)}
        />
        <GroupRow
          icon="log-out-outline"
          label={t('onboarding.home.signOut')}
          tone="danger"
          onPress={confirmSignOut}
        />
      </Group>
      <View style={[styles.spacer, { backgroundColor: colors.bg }]} />
      <ConfirmDialog
        open={askSignOut}
        tone="danger"
        icon="log-out-outline"
        title={t('onboarding.home.signOutTitle')}
        message={t('onboarding.home.signOutBody')}
        confirmLabel={t('onboarding.home.signOut')}
        cancelLabel={t('onboarding.home.stay')}
        onCancel={() => setAskSignOut(false)}
        onConfirm={() => {
          setAskSignOut(false);
          void signOut();
        }}
      />
    </Screen>
  );
}

/** "9 Oct", in the rider's language. */
function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getDate()} ${monthName(d.getMonth() + 1)}`;
}

/** The banner, the progress and the next step, and every item with its state. */
function Summary({ view: app }: { view: ApplicationView }) {
  const nav = useNav();
  const { t } = useI18n();
  const { colors } = useTheme();
  const { done, total } = progress(app);
  const open = app.status === 'DRAFT' || app.status === 'CHANGES_NEEDED';
  const next = firstIncompleteStep(app);
  const flaggedEditable = app.items.some(
    i => i.status === 'NEEDS_CHANGE' && i.editable,
  );
  const label =
    app.status === 'CHANGES_NEEDED'
      ? flaggedEditable
        ? t('onboarding.home.fix')
        : t('onboarding.home.resubmit')
      : next === 'review'
      ? t('onboarding.home.review')
      : done === 0
      ? t('onboarding.home.start')
      : t('onboarding.home.continue');
  const go = () =>
    next === 'review'
      ? nav.navigate('ApplicationReview')
      : nav.navigate('ApplicationStep', { step: next });

  return (
    <Animated.View
      entering={FadeInDown.duration(motion.base)}
      style={styles.gap}
    >
      <StatusBanner status={app.status} finalReason={app.final_reason} />

      {open ? (
        <Card style={styles.progress}>
          <View style={styles.row}>
            <AppText variant="bodyStrong" style={styles.flex}>
              {t('onboarding.home.progress', { done, total })}
            </AppText>
            <AppText variant="label" tone="primary">
              {total ? Math.round((done / total) * 100) : 0}%
            </AppText>
          </View>
          <View style={[styles.track, { backgroundColor: colors.border }]}>
            <View
              style={[
                styles.bar,
                {
                  width: `${total ? (done / total) * 100 : 0}%`,
                  backgroundColor: colors.primary,
                },
              ]}
            />
          </View>
          <Button
            label={label}
            icon="arrow-forward"
            onPress={go}
            testID="onboarding-next"
          />
        </Card>
      ) : app.submitted_at && app.status === 'SUBMITTED' ? (
        <AppText variant="caption" tone="muted" align="center">
          {t('onboarding.home.submittedOn', {
            date: shortDate(app.submitted_at),
          })}
        </AppText>
      ) : null}

      {showsChecklist(app.status) ? (
        <Group title={t('onboarding.home.items')}>
          {app.required.map(kind => {
            const item = app.items.find(i => i.kind === kind);
            const state = itemState(app, kind);
            return (
              <ItemRow
                key={kind}
                kind={kind}
                item={item}
                state={state}
                onFix={
                  state === 'fix' && item?.editable
                    ? () =>
                        nav.navigate('ApplicationStep', {
                          step: SECTION_OF[kind],
                          single: true,
                        })
                    : undefined
                }
              />
            );
          })}
        </Group>
      ) : null}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  content: { gap: space.xl },
  header: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  flex: { flex: 1 },
  gap: { gap: space.lg },
  progress: { gap: space.md },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  track: { height: 8, borderRadius: radius.pill, overflow: 'hidden' },
  bar: { height: '100%', borderRadius: radius.pill },
  spacer: { height: space.sm },
});
