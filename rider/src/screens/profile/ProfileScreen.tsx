import React, { useEffect, useRef, useState } from 'react';
import { Alert, StyleSheet, Switch, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { Group, GroupRow } from '@components/ui/Group';
import { Screen } from '@components/ui/Screen';
import { Sheet } from '@components/ui/Sheet';
import { useGuide } from '@/guide/GuideProvider';
import { testOfferAlert } from '@/services/push';
import { THEME_OPTIONS } from '@theme/preference';
import { useNav } from '@navigation/types';
import { APP_VERSION, SUPPORT_PHONE } from '@/config/api';
import { useRider } from '@/store/RiderProvider';
import { useApi, useSession, useSignedInUser } from '@/store/SessionProvider';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, motion } from '@theme/tokens';
import { initials, prettyPhone } from '@utils/format';
import { call } from '@utils/links';

const VEHICLE: Record<string, { label: string; icon: IconName }> = {
  BIKE: { label: 'Motorbike', icon: 'bicycle' },
  SCOOTER: { label: 'Scooter', icon: 'bicycle' },
  CYCLE: { label: 'Bicycle', icon: 'bicycle-outline' },
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

  const confirmSignOut = () => {
    if (trip) {
      Alert.alert(
        'Finish your delivery first',
        'You cannot sign out while carrying an order.',
      );
      return;
    }
    Alert.alert('Sign out?', 'You will stop getting orders on this phone.', [
      { text: 'Stay', style: 'cancel' },
      {
        text: 'Sign out',
        style: 'destructive',
        onPress: async () => {
          setLeaving(true);
          try {
            if (me?.status === 'ONLINE') await api.setOnline(false);
          } catch {
            // the server takes a silent rider offline within minutes anyway
          }
          await signOut(null);
        },
      },
    ]);
  };

  return (
    <Screen scroll tabbed contentStyle={styles.content}>
      <Animated.View entering={FadeInDown.duration(350)}>
        <AppText variant="title">Profile</AppText>
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
              {vehicle.label}
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
        <Group title="SETTINGS">
          <GroupRow
            icon="shield-half-outline"
            label="Permissions"
            onPress={() => nav.navigate('Permissions')}
          />
          <GroupRow
            icon={mode === 'dark' ? 'moon' : 'sunny'}
            label="Appearance"
            value={
              preference === 'system'
                ? `${mode === 'dark' ? 'Dark' : 'Light'} · phone`
                : preference === 'dark'
                ? 'Dark'
                : 'Light'
            }
            onPress={() => setAppearance(true)}
          />
          <GroupRow
            icon="contrast"
            label="High contrast"
            value={highContrast ? undefined : 'For bright sun'}
            onPress={() => setHighContrast(!highContrast)}
            trailing={
              <Switch
                value={highContrast}
                onValueChange={setHighContrast}
                trackColor={{ false: colors.border, true: colors.primary }}
                thumbColor={highContrast ? colors.onPrimary : colors.textMuted}
                accessibilityLabel="High contrast"
              />
            }
          />
        </Group>
        <Group title="GUIDE">
          <GroupRow
            icon="book-outline"
            label="How the app works"
            onPress={() => nav.navigate('Intro', { replay: true })}
          />
          <GroupRow
            icon="bulb-outline"
            label="Show tips again"
            onPress={() => {
              resetTips();
              nav.navigate('Main', { screen: 'Home' });
            }}
          />
          <GroupRow
            icon="volume-high-outline"
            label="Test the order alert"
            value={alertNote ?? undefined}
            onPress={async () => {
              const ok = await testOfferAlert();
              setAlertNote(ok ? 'Listen…' : 'Notifications are off');
              if (alertTimer.current) clearTimeout(alertTimer.current);
              alertTimer.current = setTimeout(() => setAlertNote(null), 6000);
            }}
          />
        </Group>
        <Group title="HELP">
          <GroupRow
            icon="headset-outline"
            label="Call support"
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
            label="Sign out"
            tone="danger"
            busy={leaving}
            onPress={confirmSignOut}
          />
        </Group>
      </Animated.View>

      <AppText variant="caption" tone="faint" align="center">
        Foodie Rider · v{APP_VERSION}
      </AppText>

      <Sheet
        open={appearance}
        onClose={() => setAppearance(false)}
        title="Appearance"
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
                <AppText variant="bodyStrong">{option.label}</AppText>
                <AppText variant="caption" tone="muted">
                  {option.hint}
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
