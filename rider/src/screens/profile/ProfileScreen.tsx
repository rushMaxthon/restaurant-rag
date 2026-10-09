import React, { useEffect, useRef, useState } from 'react';
import { Alert, StyleSheet, Switch, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { Pill } from '@components/ui/Pill';
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

function Row({
  icon,
  label,
  value,
  onPress,
  trailing,
}: {
  icon: IconName;
  label: string;
  value?: string;
  onPress?: () => void;
  trailing?: React.ReactNode;
}) {
  const { colors } = useTheme();
  return (
    <Card onPress={onPress} style={styles.row}>
      <View style={[styles.rowIcon, { backgroundColor: colors.surfaceAlt }]}>
        <Icon name={icon} size={20} color={colors.text} />
      </View>
      <AppText variant="bodyStrong" style={styles.flex}>
        {label}
      </AppText>
      {value ? (
        <AppText variant="label" tone="muted">
          {value}
        </AppText>
      ) : null}
      {trailing}
      {onPress && !trailing ? (
        <Icon name="chevron-forward" size={18} color={colors.textFaint} />
      ) : null}
    </Card>
  );
}

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
      <Animated.View entering={FadeInDown.duration(350)} style={styles.hero}>
        <View style={[styles.avatar, { backgroundColor: colors.primary }]}>
          <AppText variant="display" tone="onPrimary">
            {initials(me?.full_name ?? user?.full_name ?? 'R')}
          </AppText>
        </View>
        <AppText variant="title" align="center">
          {me?.full_name ?? user?.full_name}
        </AppText>
        <AppText tone="muted" align="center">
          {prettyPhone(me?.phone_number ?? user?.phone_number)}
        </AppText>
        <View style={styles.pills}>
          <Pill label="Foodie rider" tone="primary" icon="shield-checkmark" />
          {me?.city ? <Pill label={me.city} icon="location" /> : null}
        </View>
      </Animated.View>

      <Animated.View entering={FadeInDown.delay(80).duration(motion.base)}>
        <Card style={styles.vehicle}>
          <View
            style={[
              styles.vehicleIcon,
              { backgroundColor: colors.primarySoft },
            ]}
          >
            <Icon name={vehicle.icon} size={28} color={colors.primary} />
          </View>
          <View style={styles.flex}>
            <AppText variant="caption" tone="muted">
              Your vehicle
            </AppText>
            <AppText variant="heading">{vehicle.label}</AppText>
          </View>
          <View style={[styles.plate, { borderColor: colors.text }]}>
            <AppText variant="label">{me?.vehicle_number || '—'}</AppText>
          </View>
        </Card>
      </Animated.View>

      <Animated.View
        entering={FadeInDown.delay(140).duration(motion.base)}
        style={styles.list}
      >
        <AppText variant="micro" tone="muted" style={styles.section}>
          SETTINGS
        </AppText>
        <Row
          icon="shield-half-outline"
          label="Permissions"
          onPress={() => nav.navigate('Permissions')}
        />
        <Row
          icon={mode === 'dark' ? 'moon' : 'sunny'}
          label="Appearance"
          value={
            preference === 'system'
              ? `${mode === 'dark' ? 'Dark' : 'Light'} · follows phone`
              : preference === 'dark'
              ? 'Dark'
              : 'Light'
          }
          onPress={() => setAppearance(true)}
        />
        <Row
          icon="contrast"
          label="High contrast"
          value={highContrast ? 'On' : 'For bright sun'}
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
        <AppText variant="micro" tone="muted" style={styles.section}>
          GUIDE
        </AppText>
        <Row
          icon="book-outline"
          label="How the app works"
          onPress={() => nav.navigate('Intro', { replay: true })}
        />
        <Row
          icon="bulb-outline"
          label="Show tips again"
          value="On every screen"
          onPress={() => {
            resetTips();
            nav.navigate('Main', { screen: 'Home' });
          }}
        />
        <Row
          icon="volume-high-outline"
          label="Test the order alert"
          value={alertNote ?? 'Hear the ring'}
          onPress={async () => {
            const ok = await testOfferAlert();
            setAlertNote(ok ? 'Listen…' : 'Notifications are off');
            if (alertTimer.current) clearTimeout(alertTimer.current);
            alertTimer.current = setTimeout(() => setAlertNote(null), 6000);
          }}
        />
        <AppText variant="micro" tone="muted" style={styles.section}>
          HELP
        </AppText>
        <Row
          icon="headset-outline"
          label="Call support"
          onPress={() => call(SUPPORT_PHONE)}
        />
        {__DEV__ ? (
          <Row
            icon="color-palette-outline"
            label="Component preview"
            onPress={() => nav.navigate('Gallery')}
          />
        ) : null}
      </Animated.View>

      <Button
        kind="danger"
        label="Sign out"
        icon="log-out-outline"
        loading={leaving}
        onPress={confirmSignOut}
      />
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
  hero: { alignItems: 'center', gap: space.xs, paddingTop: space.md },
  avatar: {
    width: 92,
    height: 92,
    borderRadius: 46,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.md,
  },
  pills: { flexDirection: 'row', gap: space.sm, marginTop: space.sm },
  vehicle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    borderRadius: radius.xxl,
  },
  vehicleIcon: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
  },
  plate: {
    borderWidth: 2,
    borderRadius: radius.sm,
    paddingHorizontal: space.sm,
    paddingVertical: 2,
  },
  list: { gap: space.sm },
  section: { marginTop: space.sm, marginLeft: space.xs },
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
