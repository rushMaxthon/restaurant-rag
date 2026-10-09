import React, { useCallback, useRef, useState } from 'react';
import {
  Pressable,
  StyleSheet,
  View,
  type TextInputInstance,
} from 'react-native';
import { useRoute, type RouteProp } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Animated, { FadeIn } from 'react-native-reanimated';

import { DateInput } from '@components/onboarding/DateInput';
import { PhotoSlot } from '@components/onboarding/PhotoSlot';
import { StepProgressBar } from '@components/onboarding/StepProgressBar';
import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { Screen } from '@components/ui/Screen';
import { Segmented } from '@components/ui/Segmented';
import { Skeleton } from '@components/ui/Skeleton';
import { TextField } from '@components/ui/TextField';
import { useKeyboardHeight } from '@hooks/useKeyboardHeight';
import { useI18n } from '@/i18n';
import { useNav, type RootStackParamList } from '@navigation/types';
import { ApiError } from '@/services/http';
import { useApplication } from '@/store/ApplicationProvider';
import { useApi } from '@/store/SessionProvider';
import type {
  ApplicationView,
  ItemKind,
  PhotoKind,
  SectionKey,
  VehicleType,
} from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, touch } from '@theme/tokens';
import { haptic } from '@utils/haptics';
import {
  errorKey,
  fieldErrorsFrom,
  isoToDmy,
  needsLicence,
  needsRc,
  STEPS,
  todayIso,
  validateBank,
  validateDocuments,
  validatePersonal,
  validateVehicle,
  type FieldErrors,
} from '@utils/onboarding';

/**
 * One step of the application, one screen each: About you, Vehicle,
 * Documents, Bank. Checked on the phone with the server's own rules, saved
 * on Next (each step its own PUT, so a rider who stops halfway loses
 * nothing), photos sent the moment they are taken.
 *
 * What the rider may change comes from the server (`item.editable`): in a
 * draft everything, after a send-back only what was flagged. The rest is
 * shown read-only with why, never just greyed out.
 */
export function ApplicationStepScreen() {
  const { params } =
    useRoute<RouteProp<RootStackParamList, 'ApplicationStep'>>();
  const { view } = useApplication();
  if (!view) {
    return (
      <Screen>
        <View style={styles.gap}>
          <Skeleton height={40} />
          <Skeleton height={56} round={radius.lg} />
          <Skeleton height={56} round={radius.lg} />
          <Skeleton height={200} round={radius.xl} />
        </View>
      </Screen>
    );
  }
  const Step = FORMS[params.step];
  return (
    <Step view={view} step={params.step} single={Boolean(params.single)} />
  );
}

type StepProps = { view: ApplicationView; step: SectionKey; single: boolean };

const FORMS: Record<SectionKey, (props: StepProps) => React.JSX.Element> = {
  personal: PersonalStep,
  vehicle: VehicleStep,
  documents: DocumentsStep,
  bank: BankStep,
};

// --- shared machinery ---------------------------------------------------------------

function itemOf(view: ApplicationView, kind: ItemKind) {
  return view.items.find(i => i.kind === kind);
}

function editable(view: ApplicationView, kind: ItemKind): boolean {
  return itemOf(view, kind)?.editable ?? false;
}

/**
 * What every step does the same way: track photos still uploading (Next
 * waits for them), say which required photo is missing, save the section,
 * put a 422 under its field, then move on.
 */
function useStep(step: SectionKey, single: boolean) {
  const nav = useNav();
  const api = useApi();
  const { t } = useI18n();
  const { view, setView, refresh } = useApplication();
  const [uploading, setUploading] = useState<Set<PhotoKind>>(new Set());
  const [photoErrors, setPhotoErrors] = useState<
    Partial<Record<PhotoKind, string>>
  >({});
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onBusy = useCallback((kind: PhotoKind, busy: boolean) => {
    setUploading(prev => {
      const next = new Set(prev);
      if (busy) next.add(kind);
      else next.delete(kind);
      return next;
    });
    if (busy) setPhotoErrors(prev => ({ ...prev, [kind]: undefined }));
  }, []);

  const onUploaded = useCallback(
    (next: ApplicationView) => setView(next),
    [setView],
  );

  const fieldError = (field: string): string | null => {
    const code = errors[field];
    return code ? t(errorKey(code) ?? 'onboarding.err.required') : null;
  };

  const clear = (field: string) =>
    setErrors(prev => {
      if (!prev[field]) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });

  /** Required photos the rider may give and has not: "Add this photo" under each. */
  const missingPhotos = (kinds: PhotoKind[]): boolean => {
    const current = view ?? null;
    const missing: Partial<Record<PhotoKind, string>> = {};
    for (const kind of kinds) {
      const item = current ? itemOf(current, kind) : undefined;
      if (item?.editable && !item.has_photo)
        missing[kind] = t('onboarding.err.photoNeeded');
    }
    setPhotoErrors(missing);
    return Object.keys(missing).length > 0;
  };

  const goOn = () => {
    if (single) {
      nav.goBack();
      return;
    }
    const next = STEPS[STEPS.indexOf(step) + 1];
    if (next) nav.push('ApplicationStep', { step: next });
    else nav.push('ApplicationReview');
  };

  /**
   * `body` null: nothing on this step the rider may change (accepted, or
   * the application is with the reviewers) - move on without a request
   * the server would only refuse.
   */
  const save = async (
    local: FieldErrors,
    body: Record<string, unknown> | null,
    photos: PhotoKind[],
  ) => {
    setError(null);
    setErrors(local);
    if (Object.keys(local).length) {
      missingPhotos(photos);
      haptic('warning');
      return;
    }
    if (!body) {
      if (missingPhotos(photos)) {
        haptic('warning');
        return;
      }
      goOn();
      return;
    }
    setSaving(true);
    try {
      // The typed answers are saved even while a photo is still missing:
      // "your progress is saved after every step" has to hold for a rider
      // who closes the app here. Only moving on waits for the photo.
      setView(await api.saveSection(step, body));
      if (missingPhotos(photos)) {
        haptic('warning');
        return;
      }
      haptic('success');
      goOn();
    } catch (e) {
      haptic('error');
      if (e instanceof ApiError) {
        const fields = fieldErrorsFrom(e.detail);
        if (Object.keys(fields).length) setErrors(fields);
        else
          setError(e.isNetwork ? t('onboarding.step.saveFailed') : e.message);
        if (e.code === 'not_editable') void refresh();
      } else {
        setError(t('onboarding.step.saveFailed'));
      }
    } finally {
      setSaving(false);
    }
  };

  return {
    uploading: uploading.size > 0,
    onBusy,
    onUploaded,
    photoErrors,
    fieldError,
    clear,
    saving,
    error,
    save,
  };
}

/** The step's frame: progress at the top, Back / Next held at the bottom above the keyboard. */
function StepFrame({
  step,
  title,
  lead,
  saving,
  uploading,
  error,
  single,
  onNext,
  children,
}: {
  step: SectionKey;
  title: string;
  lead: string;
  saving: boolean;
  uploading: boolean;
  error: string | null;
  single: boolean;
  onNext: () => void;
  children: React.ReactNode;
}) {
  const nav = useNav();
  const { colors } = useTheme();
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const keyboard = useKeyboardHeight();
  const last = STEPS.indexOf(step) === STEPS.length - 1;

  return (
    <View style={[styles.fill, { backgroundColor: colors.bg }]}>
      <Screen scroll style={styles.fill} contentStyle={styles.content}>
        <StepProgressBar step={step} />
        <View style={styles.titleBlock}>
          <AppText variant="title" accessibilityRole="header">
            {title}
          </AppText>
          <AppText tone="muted">{lead}</AppText>
        </View>
        {children}
        {error ? (
          <Animated.View entering={FadeIn}>
            <Card
              tone="alt"
              style={[styles.errorCard, { borderColor: colors.danger }]}
            >
              <Icon name="alert-circle" size={20} color={colors.danger} />
              <AppText variant="label" tone="danger" style={styles.flex}>
                {error}
              </AppText>
            </Card>
          </Animated.View>
        ) : null}
      </Screen>
      <View
        style={[
          styles.footer,
          {
            backgroundColor: colors.surface,
            borderTopColor: colors.border,
            paddingBottom: Math.max(insets.bottom, keyboard) + space.md,
          },
        ]}
      >
        <Button
          kind="secondary"
          icon="arrow-back"
          label={t('onboarding.step.back')}
          style={styles.back}
          onPress={() => nav.goBack()}
        />
        <Button
          icon={single ? 'checkmark' : 'arrow-forward'}
          label={
            single
              ? t('common.done')
              : last
              ? t('onboarding.step.toReview')
              : t('onboarding.step.next')
          }
          loading={saving}
          style={styles.next}
          disabledReason={uploading ? t('onboarding.step.waitUploads') : null}
          onPress={onNext}
          testID="step-next"
        />
      </View>
    </View>
  );
}

/** Why a part of the form is read-only: accepted already, or with the reviewers. */
function LockNote({ view, kind }: { view: ApplicationView; kind: ItemKind }) {
  const { colors } = useTheme();
  const { t } = useI18n();
  if (editable(view, kind)) {
    const item = itemOf(view, kind);
    if (item?.status !== 'NEEDS_CHANGE') return null;
    return (
      <View style={[styles.note, { backgroundColor: colors.dangerSoft }]}>
        <Icon name="alert-circle" size={18} color={colors.danger} />
        <AppText variant="label" tone="danger" style={styles.flex}>
          {item.reason
            ? t('onboarding.step.flagged', { reason: item.reason })
            : t('onboarding.step.flaggedNoReason')}
        </AppText>
      </View>
    );
  }
  const accepted = itemOf(view, kind)?.status === 'ACCEPTED';
  return (
    <View
      style={[
        styles.note,
        { backgroundColor: accepted ? colors.successSoft : colors.surfaceAlt },
      ]}
    >
      <Icon
        name={accepted ? 'checkmark-circle' : 'lock-closed-outline'}
        size={18}
        color={accepted ? colors.success : colors.textMuted}
      />
      <AppText
        variant="label"
        tone={accepted ? 'success' : 'muted'}
        style={styles.flex}
      >
        {accepted
          ? t('onboarding.step.locked')
          : t('onboarding.step.lockedReview')}
      </AppText>
    </View>
  );
}

function SectionTitle({ children }: { children: string }) {
  return (
    <AppText variant="micro" tone="muted" style={styles.sectionTitle}>
      {children}
    </AppText>
  );
}

// --- step 1: about you ------------------------------------------------------------

function PersonalStep({ view, step, single }: StepProps) {
  const { t } = useI18n();
  const s = useStep(step, single);
  const saved = view.sections.personal;
  const may = editable(view, 'PERSONAL');
  const [form, setForm] = useState(() => ({
    full_name: saved.full_name,
    dob: isoToDmy(saved.date_of_birth),
    city: saved.city,
    address_line: saved.address_line,
    pincode: saved.pincode,
    emergency_name: saved.emergency_name,
    emergency_phone: saved.emergency_phone.replace(/^\+91/, ''),
  }));
  const set = (field: keyof typeof form) => (value: string) => {
    s.clear(field);
    setForm(prev => ({ ...prev, [field]: value }));
  };

  const next = () => {
    if (!may) return void s.save({}, null, ['SELFIE']);
    const checked = validatePersonal(form, todayIso());
    void s.save(checked.errors, checked.body, ['SELFIE']);
  };

  return (
    <StepFrame
      step={step}
      single={single}
      title={t('onboarding.step.personal')}
      lead={t('onboarding.personal.lead')}
      saving={s.saving}
      uploading={s.uploading}
      error={s.error}
      onNext={next}
    >
      <LockNote view={view} kind="PERSONAL" />
      <TextField
        label={t('onboarding.personal.name')}
        icon="person-outline"
        value={form.full_name}
        onChangeText={set('full_name')}
        error={s.fieldError('full_name')}
        editable={may}
        autoCapitalize="words"
        autoComplete="name"
      />
      <DateInput
        label={t('onboarding.personal.dob')}
        value={form.dob}
        onChange={dob => {
          s.clear('date_of_birth');
          setForm(prev => ({ ...prev, dob }));
        }}
        error={s.fieldError('date_of_birth')}
        editable={may}
      />
      <TextField
        label={t('onboarding.personal.city')}
        icon="business-outline"
        value={form.city}
        onChangeText={set('city')}
        error={s.fieldError('city')}
        editable={may}
        autoCapitalize="words"
        placeholder={t('onboarding.personal.cityPlaceholder')}
      />
      <TextField
        label={t('onboarding.personal.address')}
        icon="home-outline"
        value={form.address_line}
        onChangeText={set('address_line')}
        error={s.fieldError('address_line')}
        editable={may}
        autoComplete="street-address"
        placeholder={t('onboarding.personal.addressPlaceholder')}
        multiline
      />
      <TextField
        label={t('onboarding.personal.pincode')}
        icon="location-outline"
        value={form.pincode}
        onChangeText={v => set('pincode')(v.replace(/\D/g, ''))}
        error={s.fieldError('pincode')}
        editable={may}
        keyboardType="number-pad"
        autoComplete="postal-code"
        maxLength={6}
        placeholder="395009"
      />

      <SectionTitle>{t('onboarding.personal.emergency')}</SectionTitle>
      <TextField
        label={t('onboarding.personal.emergencyName')}
        icon="people-outline"
        value={form.emergency_name}
        onChangeText={set('emergency_name')}
        error={s.fieldError('emergency_name')}
        editable={may}
        autoCapitalize="words"
        placeholder={t('onboarding.personal.emergencyNamePlaceholder')}
      />
      <TextField
        label={t('onboarding.personal.emergencyPhone')}
        icon="call-outline"
        prefix="+91"
        value={form.emergency_phone}
        onChangeText={v =>
          set('emergency_phone')(v.replace(/\D/g, '').slice(-10))
        }
        error={s.fieldError('emergency_phone')}
        editable={may}
        keyboardType="phone-pad"
        maxLength={10}
        placeholder="98765 43210"
      />

      <PhotoSlot
        kind="SELFIE"
        face
        title={t('onboarding.personal.selfie')}
        hint={t('onboarding.personal.selfieHint')}
        view={view}
        onBusy={s.onBusy}
        onUploaded={s.onUploaded}
        error={s.photoErrors.SELFIE}
      />
    </StepFrame>
  );
}

// --- step 2: vehicle -------------------------------------------------------------------

const VEHICLES: { type: VehicleType; icon: IconName }[] = [
  { type: 'BIKE', icon: 'speedometer-outline' },
  { type: 'SCOOTER', icon: 'bicycle' },
  { type: 'EV_SCOOTER', icon: 'flash-outline' },
  { type: 'CYCLE', icon: 'bicycle-outline' },
];

function VehicleStep({ view, step, single }: StepProps) {
  const { t } = useI18n();
  const { colors } = useTheme();
  const s = useStep(step, single);
  const saved = view.sections.vehicle;
  const may = editable(view, 'VEHICLE_DETAILS');
  const [type, setType] = useState<VehicleType | null>(saved.vehicle_type);
  const [plate, setPlate] = useState(saved.vehicle_number);
  const registered = needsRc(type);

  const next = () => {
    const rc: PhotoKind[] = registered ? ['RC'] : [];
    if (!may) return void s.save({}, null, rc);
    const checked = validateVehicle({
      vehicle_type: type,
      vehicle_number: plate,
    });
    void s.save(checked.errors, checked.body, rc);
  };

  return (
    <StepFrame
      step={step}
      single={single}
      title={t('onboarding.step.vehicle')}
      lead={t('onboarding.vehicle.lead')}
      saving={s.saving}
      uploading={s.uploading}
      error={s.error}
      onNext={next}
    >
      <LockNote view={view} kind="VEHICLE_DETAILS" />
      <View accessibilityRole="radiogroup" style={styles.choices}>
        {VEHICLES.map(v => {
          const active = v.type === type;
          const papers = needsRc(v.type);
          return (
            <Pressable
              key={v.type}
              accessibilityRole="radio"
              accessibilityState={{ selected: active, disabled: !may }}
              disabled={!may}
              android_ripple={{ color: colors.border }}
              onPress={() => {
                haptic('tick');
                s.clear('vehicle_type');
                setType(v.type);
              }}
              style={[
                styles.choice,
                {
                  backgroundColor: active ? colors.primarySoft : colors.surface,
                  borderColor: active ? colors.primary : colors.border,
                },
                !may && !active && styles.dimmed,
              ]}
            >
              <View
                style={[
                  styles.choiceIcon,
                  {
                    backgroundColor: active
                      ? colors.primary
                      : colors.surfaceAlt,
                  },
                ]}
              >
                <Icon
                  name={v.icon}
                  size={24}
                  color={active ? colors.onPrimary : colors.text}
                />
              </View>
              <View style={styles.flex}>
                <AppText variant="bodyStrong">
                  {t(`onboarding.vehicle.${v.type}`)}
                </AppText>
                <AppText variant="caption" tone={papers ? 'muted' : 'success'}>
                  {papers
                    ? t('onboarding.vehicle.needsPapers')
                    : t('onboarding.vehicle.noPapers')}
                </AppText>
              </View>
              <Icon
                name={active ? 'radio-button-on' : 'radio-button-off'}
                size={22}
                color={active ? colors.primary : colors.textFaint}
              />
            </Pressable>
          );
        })}
      </View>
      {s.fieldError('vehicle_type') ? (
        <AppText variant="caption" tone="danger">
          {s.fieldError('vehicle_type')}
        </AppText>
      ) : null}
      {type === 'EV_SCOOTER' ? (
        <AppText variant="caption" tone="muted">
          {t('onboarding.vehicle.evNote')}
        </AppText>
      ) : null}

      {registered ? (
        <Animated.View entering={FadeIn} style={styles.gap}>
          <TextField
            label={t('onboarding.vehicle.number')}
            icon="reader-outline"
            value={plate}
            onChangeText={v => {
              s.clear('vehicle_number');
              setPlate(v.toUpperCase());
            }}
            error={s.fieldError('vehicle_number')}
            editable={may}
            autoCapitalize="characters"
            autoCorrect={false}
            maxLength={16}
            placeholder={t('onboarding.vehicle.numberPlaceholder')}
          />
          <PhotoSlot
            kind="RC"
            title={t('onboarding.vehicle.rc')}
            hint={t('onboarding.vehicle.rcHint')}
            view={view}
            onBusy={s.onBusy}
            onUploaded={s.onUploaded}
            error={s.photoErrors.RC}
          />
        </Animated.View>
      ) : null}
    </StepFrame>
  );
}

// --- step 3: documents -----------------------------------------------------------------

function DocumentsStep({ view, step, single }: StepProps) {
  const { t } = useI18n();
  const s = useStep(step, single);
  const saved = view.sections.documents;
  const vehicle = view.sections.vehicle.vehicle_type;
  const licence = needsLicence(vehicle);
  const may = {
    aadhaar: editable(view, 'AADHAAR_FRONT'),
    pan: editable(view, 'PAN'),
    licence: licence && editable(view, 'LICENCE_FRONT'),
  };
  // PAN and licence come back as their last 4 only (they are stored
  // encrypted), so the boxes start empty; left empty with a number on file,
  // the saved one stands and is not sent.
  const [form, setForm] = useState(() => ({
    aadhaar_last4: saved.aadhaar_last4,
    pan: '',
    licence_number: '',
    licence_expiry: isoToDmy(saved.licence_expiry),
  }));
  const set =
    (field: 'aadhaar_last4' | 'pan' | 'licence_number') => (value: string) => {
      s.clear(field);
      setForm(prev => ({ ...prev, [field]: value }));
    };

  const next = () => {
    const keepPan = !form.pan.trim() && Boolean(saved.pan_last4);
    const keepLicence =
      !form.licence_number.trim() && Boolean(saved.licence_last4);
    const sending = {
      aadhaar: may.aadhaar,
      pan: may.pan && !keepPan,
      licence: may.licence && !keepLicence,
    };
    const photos: PhotoKind[] = ['AADHAAR_FRONT', 'AADHAAR_BACK', 'PAN'];
    if (licence) photos.push('LICENCE_FRONT', 'LICENCE_BACK');
    const checked = validateDocuments(form, vehicle, sending, todayIso());
    const body =
      checked.body && Object.keys(checked.body).length ? checked.body : null;
    void s.save(checked.errors, body, photos);
  };

  const slot = (kind: PhotoKind, title: string) => (
    <PhotoSlot
      kind={kind}
      title={title}
      view={view}
      onBusy={s.onBusy}
      onUploaded={s.onUploaded}
      error={s.photoErrors[kind]}
    />
  );

  return (
    <StepFrame
      step={step}
      single={single}
      title={t('onboarding.step.documents')}
      lead={t('onboarding.docs.lead')}
      saving={s.saving}
      uploading={s.uploading}
      error={s.error}
      onNext={next}
    >
      <SectionTitle>{t('onboarding.docs.aadhaar')}</SectionTitle>
      <LockNote view={view} kind="AADHAAR_FRONT" />
      <TextField
        label={t('onboarding.docs.aadhaarLast4')}
        icon="keypad-outline"
        value={form.aadhaar_last4}
        onChangeText={v => set('aadhaar_last4')(v.replace(/\D/g, ''))}
        error={s.fieldError('aadhaar_last4')}
        editable={may.aadhaar}
        keyboardType="number-pad"
        maxLength={4}
        placeholder="1234"
      />
      <AppText variant="caption" tone="muted">
        {t('onboarding.docs.aadhaarHint')}
      </AppText>
      {slot(
        'AADHAAR_FRONT',
        `${t('onboarding.docs.aadhaar')} · ${t('onboarding.docs.front')}`,
      )}
      {slot(
        'AADHAAR_BACK',
        `${t('onboarding.docs.aadhaar')} · ${t('onboarding.docs.back')}`,
      )}

      <SectionTitle>{t('onboarding.docs.pan')}</SectionTitle>
      <LockNote view={view} kind="PAN" />
      <TextField
        label={t('onboarding.docs.panNumber')}
        icon="card-outline"
        value={form.pan}
        onChangeText={v => set('pan')(v.toUpperCase())}
        error={s.fieldError('pan')}
        editable={may.pan}
        autoCapitalize="characters"
        autoCorrect={false}
        maxLength={10}
        placeholder={
          saved.pan_last4 ? `••••••${saved.pan_last4}` : 'ABCDE1234F'
        }
      />
      {saved.pan_last4 ? (
        <AppText variant="caption" tone="muted">
          {t('onboarding.docs.panSaved', { last4: saved.pan_last4 })}
          {may.pan ? ` · ${t('onboarding.docs.retype')}` : ''}
        </AppText>
      ) : null}
      {slot('PAN', t('onboarding.docs.panPhoto'))}

      {licence ? (
        <>
          <SectionTitle>{t('onboarding.docs.licence')}</SectionTitle>
          <LockNote view={view} kind="LICENCE_FRONT" />
          <TextField
            label={t('onboarding.docs.licenceNumber')}
            icon="id-card-outline"
            value={form.licence_number}
            onChangeText={v => set('licence_number')(v.toUpperCase())}
            error={s.fieldError('licence_number')}
            editable={may.licence}
            autoCapitalize="characters"
            autoCorrect={false}
            maxLength={24}
            placeholder={
              saved.licence_last4
                ? `••••${saved.licence_last4}`
                : 'GJ05 20190001234'
            }
          />
          {saved.licence_last4 ? (
            <AppText variant="caption" tone="muted">
              {t('onboarding.docs.licenceSaved', {
                last4: saved.licence_last4,
              })}
              {may.licence ? ` · ${t('onboarding.docs.retype')}` : ''}
            </AppText>
          ) : null}
          <DateInput
            label={t('onboarding.docs.licenceExpiry')}
            value={form.licence_expiry}
            onChange={licence_expiry => {
              s.clear('licence_expiry');
              setForm(prev => ({ ...prev, licence_expiry }));
            }}
            error={s.fieldError('licence_expiry')}
            editable={may.licence}
          />
          {slot(
            'LICENCE_FRONT',
            `${t('onboarding.docs.licence')} · ${t('onboarding.docs.front')}`,
          )}
          {slot(
            'LICENCE_BACK',
            `${t('onboarding.docs.licence')} · ${t('onboarding.docs.back')}`,
          )}
        </>
      ) : null}
    </StepFrame>
  );
}

// --- step 4: bank ---------------------------------------------------------------------------

function BankStep({ view, step, single }: StepProps) {
  const { t } = useI18n();
  const s = useStep(step, single);
  const saved = view.sections.bank;
  const may = editable(view, 'BANK_DETAILS');
  const [mode, setMode] = useState<'account' | 'upi'>(
    saved.upi_id && !saved.bank_account_last4 ? 'upi' : 'account',
  );
  const [form, setForm] = useState(() => ({
    bank_holder: saved.bank_holder,
    account_number: '',
    account_number_again: '',
    ifsc: saved.ifsc,
    upi_id: saved.upi_id,
  }));
  const againRef = useRef<TextInputInstance>(null);
  const set = (field: keyof typeof form) => (value: string) => {
    s.clear(field);
    setForm(prev => ({ ...prev, [field]: value }));
  };
  const accountOnFile = Boolean(saved.bank_account_last4);

  const next = () => {
    const proof: PhotoKind[] = mode === 'account' ? ['BANK_PROOF'] : [];
    if (!may) return void s.save({}, null, proof);
    const typedAccount = Boolean(form.account_number.trim());
    // The account number is stored encrypted and never comes back: with one
    // on file and nothing changed, there is nothing to send. A changed name
    // or IFSC needs the number again, because the server saves all of it.
    if (mode === 'account' && !typedAccount && accountOnFile) {
      const unchanged =
        form.bank_holder.trim() === saved.bank_holder &&
        form.ifsc.trim().toUpperCase() === saved.ifsc;
      if (unchanged) return void s.save({}, null, proof);
      return void s.save({ account_number: 'required' }, null, proof);
    }
    const checked = validateBank({
      ...form,
      ...(mode === 'account'
        ? { upi_id: '' }
        : { account_number: '', account_number_again: '', ifsc: '' }),
    });
    void s.save(checked.errors, checked.body, proof);
  };

  return (
    <StepFrame
      step={step}
      single={single}
      title={t('onboarding.step.bank')}
      lead={t('onboarding.bank.lead')}
      saving={s.saving}
      uploading={s.uploading}
      error={s.error}
      onNext={next}
    >
      <LockNote view={view} kind="BANK_DETAILS" />
      <TextField
        label={t('onboarding.bank.holder')}
        icon="person-outline"
        value={form.bank_holder}
        onChangeText={set('bank_holder')}
        error={s.fieldError('bank_holder')}
        editable={may}
        autoCapitalize="words"
      />
      {may ? (
        <Segmented
          options={[
            { key: 'account', label: t('onboarding.bank.useAccount') },
            { key: 'upi', label: t('onboarding.bank.useUpi') },
          ]}
          value={mode}
          onChange={choice => {
            s.clear('account_number');
            setMode(choice);
          }}
        />
      ) : null}

      {mode === 'account' ? (
        <Animated.View key="account" entering={FadeIn} style={styles.gap}>
          <TextField
            label={t('onboarding.bank.account')}
            icon="keypad-outline"
            value={form.account_number}
            onChangeText={v => set('account_number')(v.replace(/\D/g, ''))}
            error={s.fieldError('account_number')}
            editable={may}
            keyboardType="number-pad"
            maxLength={18}
            secure
            placeholder={
              accountOnFile ? `••••${saved.bank_account_last4}` : '123456789012'
            }
            onSubmitEditing={() => againRef.current?.focus()}
          />
          {accountOnFile ? (
            <AppText variant="caption" tone="muted">
              {t('onboarding.bank.accountSaved', {
                last4: saved.bank_account_last4,
              })}
              {may ? ` · ${t('onboarding.docs.retype')}` : ''}
            </AppText>
          ) : null}
          <TextField
            ref={againRef}
            label={t('onboarding.bank.accountAgain')}
            icon="keypad-outline"
            value={form.account_number_again}
            onChangeText={v =>
              set('account_number_again')(v.replace(/\D/g, ''))
            }
            error={s.fieldError('account_number_again')}
            editable={may}
            keyboardType="number-pad"
            maxLength={18}
            contextMenuHidden
          />
          <TextField
            label={t('onboarding.bank.ifsc')}
            icon="business-outline"
            value={form.ifsc}
            onChangeText={v => set('ifsc')(v.toUpperCase().replace(/\s/g, ''))}
            error={s.fieldError('ifsc')}
            editable={may}
            autoCapitalize="characters"
            autoCorrect={false}
            maxLength={11}
            placeholder="SBIN0001234"
          />
          <AppText variant="caption" tone="muted">
            {t('onboarding.bank.ifscHint')}
          </AppText>
          <LockNote view={view} kind="BANK_PROOF" />
          <PhotoSlot
            kind="BANK_PROOF"
            title={t('onboarding.bank.proof')}
            hint={t('onboarding.bank.proofHint')}
            view={view}
            onBusy={s.onBusy}
            onUploaded={s.onUploaded}
            error={s.photoErrors.BANK_PROOF}
          />
        </Animated.View>
      ) : (
        <Animated.View key="upi" entering={FadeIn} style={styles.gap}>
          <TextField
            label={t('onboarding.bank.upi')}
            icon="at-outline"
            value={form.upi_id}
            onChangeText={v => set('upi_id')(v.trim())}
            error={s.fieldError('upi_id') ?? s.fieldError('account_number')}
            editable={may}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            placeholder={t('onboarding.bank.upiPlaceholder')}
          />
        </Animated.View>
      )}
    </StepFrame>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  flex: { flex: 1 },
  gap: { gap: space.lg },
  content: { gap: space.lg },
  titleBlock: { gap: space.xs, marginTop: space.sm },
  sectionTitle: { marginTop: space.md, marginLeft: space.xs },
  note: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: space.sm,
    padding: space.md,
    borderRadius: radius.lg,
  },
  errorCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingVertical: space.md,
  },
  choices: { gap: space.sm },
  choice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    minHeight: touch.hero + space.sm,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    borderRadius: radius.xl,
    borderWidth: 1.5,
    overflow: 'hidden',
  },
  dimmed: { opacity: 0.5 },
  choiceIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  footer: {
    flexDirection: 'row',
    gap: space.sm,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  back: { flex: 1 },
  next: { flex: 2 },
});
