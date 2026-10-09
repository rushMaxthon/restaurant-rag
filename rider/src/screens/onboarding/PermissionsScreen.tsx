import React from 'react';
import notifee from '@notifee/react-native';
import { StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { Screen } from '@components/ui/Screen';
import { usePermissions, type PermissionKey } from '@hooks/usePermissions';
import { useI18n, type Key } from '@/i18n';
import { gateReason } from '@utils/permissions';
import { useNav } from '@navigation/types';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, motion } from '@theme/tokens';

const ITEMS: {
  key: PermissionKey;
  icon: IconName;
  titleKey: Key;
  whyKey: Key;
}[] = [
  {
    key: 'location',
    icon: 'location',
    titleKey: 'account.perm.location',
    whyKey: 'account.perm.locationWhy',
  },
  {
    key: 'notifications',
    icon: 'notifications',
    titleKey: 'account.perm.notifications',
    whyKey: 'account.perm.notificationsWhy',
  },
  {
    key: 'battery',
    icon: 'battery-charging',
    titleKey: 'account.perm.battery',
    whyKey: 'account.perm.batteryWhy',
  },
];

/** Each permission with one sentence on why - a rider who understands taps Allow. */
export function PermissionsScreen() {
  const { colors } = useTheme();
  const { t } = useI18n();
  const nav = useNav();
  const { state, ready, request, openAutoStart } = usePermissions();
  const leave = () =>
    nav.canGoBack()
      ? nav.goBack()
      : nav.reset({ index: 0, routes: [{ name: 'Main' }] });
  // Only on brands that ship their own auto-start screen (Xiaomi, Oppo...).
  const [autoStart, setAutoStart] = React.useState(false);
  React.useEffect(() => {
    let alive = true;
    notifee
      .getPowerManagerInfo()
      .then(info => alive && setAutoStart(Boolean(info.activity)))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  return (
    <Screen scroll contentStyle={styles.content}>
      <Animated.View entering={FadeInDown.duration(350)}>
        <View style={[styles.badge, { backgroundColor: colors.primarySoft }]}>
          <Icon name="shield-checkmark" size={34} color={colors.primary} />
        </View>
        <AppText variant="title">{t('account.perm.title')}</AppText>
        <AppText tone="muted" style={styles.gapXs}>
          {t('account.perm.lead')}
        </AppText>
      </Animated.View>

      {ITEMS.map((item, i) => {
        const granted = state?.[item.key] ?? false;
        return (
          <Animated.View
            key={item.key}
            entering={FadeInDown.delay(80 * (i + 1)).duration(motion.base)}
          >
            <Card tone={granted ? 'success' : 'surface'} style={styles.item}>
              <View
                style={[
                  styles.icon,
                  {
                    backgroundColor: granted
                      ? colors.success
                      : colors.surfaceAlt,
                  },
                ]}
              >
                <Icon
                  name={granted ? 'checkmark' : item.icon}
                  size={22}
                  color={granted ? colors.onSuccess : colors.text}
                />
              </View>
              <View style={styles.flex}>
                <AppText variant="bodyStrong">{t(item.titleKey)}</AppText>
                <AppText variant="caption" tone="muted">
                  {t(item.whyKey)}
                </AppText>
              </View>
              {granted ? null : (
                <Button
                  size="md"
                  label={t('account.perm.allow')}
                  onPress={() => request(item.key)}
                />
              )}
            </Card>
          </Animated.View>
        );
      })}

      {autoStart ? (
        <Card style={styles.item}>
          <View style={styles.flex}>
            <AppText variant="bodyStrong">
              {t('account.perm.autoStartTitle')}
            </AppText>
            <AppText variant="caption" tone="muted">
              {t('account.perm.autoStartBody')}
            </AppText>
          </View>
          <Button
            size="md"
            kind="secondary"
            label={t('account.perm.open')}
            onPress={async () => setAutoStart(await openAutoStart())}
          />
        </Card>
      ) : null}

      <Button
        label={ready ? t('account.perm.allSet') : t('common.continue')}
        icon="arrow-forward"
        disabledReason={gateReason(state)}
        onPress={leave}
      />
      {ready ? null : (
        // Going online is what these gate (Home says so); the app itself is not.
        <Button
          kind="ghost"
          size="md"
          label={t('account.perm.notNow')}
          onPress={leave}
        />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { gap: space.lg },
  flex: { flex: 1 },
  badge: {
    width: 64,
    height: 64,
    borderRadius: radius.xl,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.lg,
  },
  item: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  icon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  gapXs: { marginTop: space.xs },
});
