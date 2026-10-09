import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { ConfirmDialog } from '@components/ui/ConfirmDialog';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { IconButton } from '@components/ui/IconButton';
import { Screen } from '@components/ui/Screen';
import { useI18n } from '@/i18n';
import { useNav } from '@navigation/types';
import { ApiError } from '@/services/http';
import { useApplication } from '@/store/ApplicationProvider';
import { useApi } from '@/store/SessionProvider';
import type { ApplicationView, ItemKind, SectionKey } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';
import { prettyPhone } from '@utils/format';
import { haptic } from '@utils/haptics';
import {
  applicationProblem,
  errorKey,
  isoToDmy,
  needsLicence,
  needsRc,
  SECTION_OF,
} from '@utils/onboarding';

const ICON: Record<SectionKey, IconName> = {
  personal: 'person-outline',
  vehicle: 'bicycle-outline',
  documents: 'card-outline',
  bank: 'business-outline',
};

function dmy(iso: string | null): string {
  const d = isoToDmy(iso);
  return d.yyyy ? `${d.dd}/${d.mm}/${d.yyyy}` : '';
}

/**
 * Everything the rider gave, a card per step with Edit, and Submit. Last
 * stop before the reviewers, so it says plainly that nothing can change
 * while they look, and Submit says why when it cannot go yet.
 */
export function ApplicationReviewScreen() {
  const nav = useNav();
  const api = useApi();
  const { t } = useI18n();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { view, setView, refresh } = useApplication();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [askSubmit, setAskSubmit] = useState(false);

  if (!view) return <Screen>{null}</Screen>;

  const problem = applicationProblem(view);
  const reason =
    problem === 'locked'
      ? t('onboarding.step.lockedReview')
      : problem
      ? t(errorKey(problem)!)
      : null;
  const missing = view.missing.map(kind => t(`onboarding.item.${kind}`));
  const resubmit = view.status === 'CHANGES_NEEDED';

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      setView(await api.submitApplication());
      haptic('success');
      nav.popToTop();
    } catch (e) {
      haptic('error');
      setError(e instanceof ApiError ? e.message : String(e));
      // Missing, flagged or decided meanwhile: the screen should show why.
      void refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={[styles.fill, { backgroundColor: colors.bg }]}>
      <Screen scroll style={styles.fill} contentStyle={styles.content}>
        <View style={styles.top}>
          <IconButton
            icon="arrow-back"
            label={t('common.back')}
            onPress={() => nav.goBack()}
          />
        </View>
        <View style={styles.titleBlock}>
          <AppText variant="title" accessibilityRole="header">
            {t('onboarding.review.title')}
          </AppText>
          <AppText tone="muted">{t('onboarding.review.lead')}</AppText>
        </View>

        <Section view={view} step="personal">
          <Row
            label={t('onboarding.review.name')}
            value={view.sections.personal.full_name}
          />
          <Row
            label={t('onboarding.review.dob')}
            value={dmy(view.sections.personal.date_of_birth)}
          />
          <Row
            label={t('onboarding.review.city')}
            value={view.sections.personal.city}
          />
          <Row
            label={t('onboarding.review.address')}
            value={[
              view.sections.personal.address_line,
              view.sections.personal.pincode,
            ]
              .filter(Boolean)
              .join(', ')}
          />
          <Row
            label={t('onboarding.review.emergency')}
            value={[
              view.sections.personal.emergency_name,
              prettyPhone(view.sections.personal.emergency_phone),
            ]
              .filter(Boolean)
              .join(' · ')}
          />
        </Section>

        <Section view={view} step="vehicle">
          <Row
            label={t('onboarding.review.vehicle')}
            value={
              view.sections.vehicle.vehicle_type
                ? t(`onboarding.vehicle.${view.sections.vehicle.vehicle_type}`)
                : ''
            }
          />
          {needsRc(view.sections.vehicle.vehicle_type) ? (
            <Row
              label={t('onboarding.review.number')}
              value={view.sections.vehicle.vehicle_number}
            />
          ) : null}
        </Section>

        <Section view={view} step="documents">
          <Row
            label={t('onboarding.review.aadhaar')}
            value={ending(view.sections.documents.aadhaar_last4)}
          />
          <Row
            label={t('onboarding.review.pan')}
            value={ending(view.sections.documents.pan_last4)}
          />
          {needsLicence(view.sections.vehicle.vehicle_type) ? (
            <>
              <Row
                label={t('onboarding.review.licence')}
                value={ending(view.sections.documents.licence_last4)}
              />
              <Row
                label={t('onboarding.review.validUntil')}
                value={dmy(view.sections.documents.licence_expiry)}
              />
            </>
          ) : null}
        </Section>

        <Section view={view} step="bank">
          <Row
            label={t('onboarding.bank.holder')}
            value={view.sections.bank.bank_holder}
          />
          {view.sections.bank.bank_account_last4 ? (
            <>
              <Row
                label={t('onboarding.review.account')}
                value={ending(view.sections.bank.bank_account_last4)}
              />
              <Row
                label={t('onboarding.review.ifsc')}
                value={view.sections.bank.ifsc}
              />
            </>
          ) : null}
          {view.sections.bank.upi_id ? (
            <Row
              label={t('onboarding.review.upi')}
              value={view.sections.bank.upi_id}
            />
          ) : null}
        </Section>

        {missing.length ? (
          <Card
            tone="alt"
            style={[styles.missing, { borderColor: colors.warning }]}
          >
            <Icon
              name="alert-circle-outline"
              size={20}
              color={colors.warning}
            />
            <AppText variant="label" style={styles.flex}>
              {t('onboarding.review.missingList', {
                items: missing.join(', '),
              })}
            </AppText>
          </Card>
        ) : null}
        {error ? (
          <AppText variant="label" tone="danger">
            {error}
          </AppText>
        ) : null}
      </Screen>
      <View
        style={[
          styles.footer,
          {
            backgroundColor: colors.surface,
            borderTopColor: colors.border,
            paddingBottom: insets.bottom + space.md,
          },
        ]}
      >
        <Button
          icon="paper-plane-outline"
          label={
            resubmit
              ? t('onboarding.review.resubmit')
              : t('onboarding.review.submit')
          }
          loading={busy}
          disabledReason={reason}
          onPress={() => setAskSubmit(true)}
          testID="application-submit"
        />
      </View>
      <ConfirmDialog
        open={askSubmit}
        icon="paper-plane"
        title={t(resubmit ? 'confirm.resubmit.title' : 'confirm.submit.title')}
        message={t(resubmit ? 'confirm.resubmit.body' : 'confirm.submit.body')}
        confirmLabel={t('confirm.submit.yes')}
        cancelLabel={t('confirm.submit.no')}
        busy={busy}
        onCancel={() => setAskSubmit(false)}
        onConfirm={() => {
          setAskSubmit(false);
          void submit();
        }}
      />
    </View>
  );

  function ending(last4: string): string {
    return last4 ? t('onboarding.review.ending', { last4 }) : '';
  }
}

/** One step as a card: its answers, its photos counted, and Edit when the rider may. */
function Section({
  view,
  step,
  children,
}: {
  view: ApplicationView;
  step: SectionKey;
  children: React.ReactNode;
}) {
  const nav = useNav();
  const { t } = useI18n();
  const { colors } = useTheme();
  const kinds = view.required.filter(kind => SECTION_OF[kind] === step);
  const items = view.items.filter(
    i => SECTION_OF[i.kind] === step && kinds.includes(i.kind),
  );
  const photos = items.filter(i => isPhoto(i.kind));
  const given = photos.filter(i => i.has_photo).length;
  const missing = view.missing.some(kind => SECTION_OF[kind] === step);
  const flagged = items.some(i => i.status === 'NEEDS_CHANGE');
  const canEdit = view.items.some(
    i => SECTION_OF[i.kind] === step && i.editable,
  );
  const accent = flagged
    ? colors.danger
    : missing
    ? colors.warning
    : colors.border;

  return (
    <Animated.View entering={FadeInDown.duration(300)}>
      <Card style={[styles.section, { borderColor: accent }]}>
        <View style={styles.head}>
          <View style={[styles.icon, { backgroundColor: colors.primarySoft }]}>
            <Icon name={ICON[step]} size={18} color={colors.primary} />
          </View>
          <AppText variant="heading" style={styles.flex}>
            {t(`onboarding.step.${step}`)}
          </AppText>
          {canEdit ? (
            <Button
              kind="ghost"
              size="md"
              icon="create-outline"
              label={t('onboarding.review.edit')}
              onPress={() =>
                nav.navigate('ApplicationStep', { step, single: true })
              }
            />
          ) : null}
        </View>
        {children}
        {photos.length ? (
          <Row
            label={t('onboarding.review.photos')}
            value={t('onboarding.review.photoCount', {
              n: given,
              total: photos.length,
            })}
            warn={given < photos.length}
          />
        ) : null}
      </Card>
    </Animated.View>
  );
}

const PHOTOS = new Set<ItemKind>([
  'SELFIE',
  'RC',
  'AADHAAR_FRONT',
  'AADHAAR_BACK',
  'PAN',
  'LICENCE_FRONT',
  'LICENCE_BACK',
  'BANK_PROOF',
]);

function isPhoto(kind: ItemKind): boolean {
  return PHOTOS.has(kind);
}

function Row({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  const { t } = useI18n();
  return (
    <View style={styles.row}>
      <AppText variant="label" tone="muted" style={styles.label}>
        {label}
      </AppText>
      <AppText
        variant="bodyStrong"
        tone={!value || warn ? 'warning' : 'default'}
        style={styles.value}
      >
        {value || t('onboarding.review.notGiven')}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  flex: { flex: 1 },
  content: { gap: space.lg },
  top: { flexDirection: 'row' },
  titleBlock: { gap: space.xs },
  section: { gap: space.sm, borderWidth: 1 },
  head: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    marginBottom: space.xs,
  },
  icon: {
    width: 36,
    height: 36,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  row: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.sm,
    paddingVertical: space.xxs,
  },
  label: { flexBasis: 110, flexGrow: 0, flexShrink: 0 },
  value: { flex: 1, minWidth: 140 },
  missing: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    borderWidth: 1,
  },
  footer: {
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
});
