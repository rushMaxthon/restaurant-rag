import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, Switch, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { LanguageSheet } from '@components/LanguageSwitch';
import { Card } from '@components/ui/Card';
import { ConfirmDialog } from '@components/ui/ConfirmDialog';
import { Icon, type IconName } from '@components/ui/Icon';
import { Group, GroupRow } from '@components/ui/Group';
import { Screen } from '@components/ui/Screen';
import { Sheet } from '@components/ui/Sheet';
import { useGuide } from '@/guide/GuideProvider';
import { LANGUAGE_NAMES, useI18n, type Key } from '@/i18n';
import { testOfferAlert } from '@/services/push';
import { THEME_OPTIONS } from '@theme/preference';
import { useNav } from '@navigation/types';
import { APP_NAME, APP_VERSION, SUPPORT_PHONE } from '@/config/api';
import { useRider } from '@/store/RiderProvider';
import { useApi, useSession, useSignedInUser } from '@/store/SessionProvider';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, motion } from '@theme/tokens';
import { initials, prettyPhone } from '@utils/format';
import { call } from '@utils/links';

const VEHICLE: Record<string, { labelKey: Key; icon: IconName }> = {
  BIKE: { labelKey: 'account.profile.vehicleBike', icon: 'bicycle' },
  SCOOTER: { labelKey: 'account.profile.vehicleScooter', icon: 'bicycle' },
  EV_SCOOTER: {
    labelKey: 'onboarding.vehicle.EV_SCOOTER',
    icon: 'flash-outline',
  },
  CYCLE: { labelKey: 'account.profile.vehicleCycle', icon: 'bicycle-outline' },
};

export function ProfileScreen() {
  const {
    colors,
    mode,
    preference,
    setPreference,
    highContrast,
    setHighContrast,
  } = useTheme();
  const { resetTips } = useGuide();
  const i18n = useI18n();
  const { t } = i18n;
  const [languageOpen, setLanguageOpen] = useState(false);
  const [appearance, setAppearance] = useState(false);
  const [alertNote, setAlertNote] = useState<string | null>(null);
  const alertTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (alertTimer.current) clearTimeout(alertTimer.current);
    },
    [],
  );
  const nav = useNav();
  const api = useApi();
  const user = useSignedInUser();
  const { me, trip } = useRider();
  const { signOut } = useSession();
  const [leaving, setLeaving] = useState(false);
  const vehicle = VEHICLE[me?.vehicle_type ?? 'BIKE'] ?? VEHICLE.BIKE!;

  // Two answers in the app's own dialog (not Android's grey alert): a rider
  // carrying an order is told why they cannot leave; anyone else is asked.
  const [askSignOut, setAskSignOut] = useState<null | 'blocked' | 'ask'>(null);
  const confirmSignOut = () => setAskSignOut(trip ? 'blocked' : 'ask');
  const doSignOut = async () => {
    setLeaving(true);
    try {
      if (me?.status === 'ONLINE') await api.setOnline(false);
    } catch {
      // the server takes a silent rider offline within minutes anyway
    }
    await signOut(null);
  };

  return (
    <Screen scroll tabbed contentStyle={styles.content}>
      <Animated.View entering={FadeInDown.duration(350)}>
        <AppText variant="title">{t('account.profile.title')}</AppText>
      </Animated.View>

      {/* Who and on what: the two things anyone checking a rider asks. */}
      <Animated.View entering={FadeInDown.delay(60).duration(motion.base)}>
        <Card style={styles.idCard}>
          <View style={styles.idRow}>
            <View style={[styles.avatar, { backgroundColor: colors.primary }]}>
              <AppText variant="heading" tone="onPrimary">
                {initials(me?.full_name ?? user?.full_name ?? 'R')}
              </AppText>
            </View>
            <View style={styles.flex}>
              <AppText variant="heading" numberOfLines={1}>
                {me?.full_name ?? user?.full_name}
              </AppText>
              <AppText variant="caption" tone="muted" numberOfLines={1}>
                {prettyPhone(me?.phone_number ?? user?.phone_number)}
                {me?.city ? ` · ${me.city}` : ''}
              </AppText>
            </View>
            <Icon name="shield-checkmark" size={20} color={colors.primary} />
          </View>
          <View style={[styles.vehicle, { borderTopColor: colors.border }]}>
            <Icon name={vehicle.icon} size={20} color={colors.textMuted} />
            <AppText variant="label" tone="muted" style={styles.flex}>
              {t(vehicle.labelKey)}
            </AppText>
            <View style={[styles.plate, { borderColor: colors.text }]}>
              <AppText variant="label">{me?.vehicle_number || '—'}</AppText>
            </View>
          </View>
        </Card>
      </Animated.View>

      <Animated.View
        entering={FadeInDown.delay(120).duration(motion.base)}
        style={styles.list}
      >
        <Group title={t('account.profile.settings')}>
          {/* First: a rider who cannot read the current language must find it. */}
          <GroupRow
            icon="language-outline"
            label={t('account.language.title')}
            value={
              i18n.preference === 'system'
                ? t('account.language.phoneHint', {
                    name: LANGUAGE_NAMES[i18n.lang],
                  })
                : LANGUAGE_NAMES[i18n.lang]
            }
            onPress={() => setLanguageOpen(true)}
          />
          <GroupRow
            icon="shield-half-outline"
            label={t('account.profile.permissions')}
            onPress={() => nav.navigate('Permissions')}
          />
          <GroupRow
            icon={mode === 'dark' ? 'moon' : 'sunny'}
            label={t('account.profile.appearance')}
            value={
              preference === 'system'
                ? t('account.profile.modeFromPhone', {
                    mode: t(
                      mode === 'dark'
                        ? 'account.profile.dark'
                        : 'account.profile.light',
                    ),
                  })
                : t(
                    preference === 'dark'
                      ? 'account.profile.dark'
                      : 'account.profile.light',
                  )
            }
            onPress={() => setAppearance(true)}
          />
          <GroupRow
            icon="contrast"
            label={t('account.profile.highContrast')}
            value={
              highContrast ? undefined : t('account.profile.highContrastHint')
            }
            onPress={() => setHighContrast(!highContrast)}
            trailing={
              <Switch
                value={highContrast}
                onValueChange={setHighContrast}
                trackColor={{ false: colors.border, true: colors.primary }}
                thumbColor={highContrast ? colors.onPrimary : colors.textMuted}
                accessibilityLabel={t('account.profile.highContrast')}
              />
            }
          />
        </Group>
        <Group title={t('account.profile.guide')}>
          <GroupRow
            icon="gift-outline"
            label={t('referral.title')}
            onPress={() => nav.navigate('Referral')}
          />
          <GroupRow
            icon="book-outline"
            label={t('account.profile.howItWorks')}
            onPress={() => nav.navigate('Intro', { replay: true })}
          />
          <GroupRow
            icon="bulb-outline"
            label={t('account.profile.showTips')}
            onPress={() => {
              resetTips();
              nav.navigate('Main', { screen: 'Home' });
            }}
          />
          <GroupRow
            icon="volume-high-outline"
            label={t('account.profile.testAlert')}
            value={alertNote ?? undefined}
            onPress={async () => {
              const ok = await testOfferAlert();
              setAlertNote(
                ok
                  ? t('account.profile.listen')
                  : t('account.profile.notificationsOff'),
              );
              if (alertTimer.current) clearTimeout(alertTimer.current);
              alertTimer.current = setTimeout(() => setAlertNote(null), 6000);
            }}
          />
        </Group>
        <Group title={t('account.profile.help')}>
          <GroupRow
            icon="headset-outline"
            label={t('account.profile.callSupport')}
            onPress={() => call(SUPPORT_PHONE)}
          />
          {__DEV__ ? (
            <GroupRow
              icon="color-palette-outline"
              label="Component preview"
              onPress={() => nav.navigate('Gallery')}
            />
          ) : null}
        </Group>
        <Group>
          <GroupRow
            icon="log-out-outline"
            label={t('account.profile.signOut')}
            tone="danger"
            busy={leaving}
            onPress={confirmSignOut}
          />
        </Group>
      </Animated.View>

      <AppText variant="caption" tone="faint" align="center">
        {APP_NAME} · v{APP_VERSION}
      </AppText>

      <ConfirmDialog
        open={askSignOut === 'blocked'}
        icon="bicycle"
        title={t('account.profile.finishFirstTitle')}
        message={t('account.profile.finishFirstBody')}
        onCancel={() => setAskSignOut(null)}
      />
      <ConfirmDialog
        open={askSignOut === 'ask'}
        tone="danger"
        icon="log-out-outline"
        title={t('account.profile.signOutTitle')}
        message={t('account.profile.signOutBody')}
        confirmLabel={t('account.profile.signOut')}
        cancelLabel={t('account.profile.stay')}
        busy={leaving}
        onCancel={() => setAskSignOut(null)}
        onConfirm={() => void doSignOut()}
      />

      <LanguageSheet
        open={languageOpen}
        onClose={() => setLanguageOpen(false)}
      />

      <Sheet
        open={appearance}
        onClose={() => setAppearance(false)}
        title={t('account.profile.appearance')}
      >
        {THEME_OPTIONS.map(option => {
          const active = option.key === preference;
          return (
            <Card
              key={option.key}
              tone={active ? 'primary' : 'surface'}
              style={styles.row}
              onPress={() => {
                setPreference(option.key);
                setAppearance(false);
              }}
            >
              <View
                style={[
                  styles.rowIcon,
                  {
                    backgroundColor: active
                      ? colors.primary
                      : colors.surfaceAlt,
                  },
                ]}
              >
                <Icon
                  name={
                    option.key === 'system'
                      ? 'phone-portrait-outline'
                      : option.key === 'dark'
                      ? 'moon'
                      : 'sunny'
                  }
                  size={20}
                  color={active ? colors.onPrimary : colors.text}
                />
              </View>
              <View style={styles.flex}>
                <AppText variant="bodyStrong">{t(option.labelKey)}</AppText>
                <AppText variant="caption" tone="muted">
                  {t(option.hintKey)}
                </AppText>
              </View>
              {active ? (
                <Icon
                  name="checkmark-circle"
                  size={22}
                  color={colors.primary}
                />
              ) : null}
            </Card>
          );
        })}
      </Sheet>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { gap: space.lg },
  flex: { flex: 1 },
  idCard: { gap: space.md, borderRadius: radius.xxl },
  idRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  avatar: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
  },
  vehicle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingTop: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  plate: {
    borderWidth: 2,
    borderRadius: radius.sm,
    paddingHorizontal: space.sm,
    paddingVertical: 2,
  },
  list: { gap: space.lg },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingVertical: space.md,
  },
  rowIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
