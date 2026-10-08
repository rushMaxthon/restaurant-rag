import React from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { Screen } from '@components/ui/Screen';
import { usePermissions, type PermissionKey } from '@hooks/usePermissions';
import { useNav } from '@navigation/types';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, motion } from '@theme/tokens';

const ITEMS: {
  key: PermissionKey;
  icon: IconName;
  title: string;
  why: string;
}[] = [
  {
    key: 'location',
    icon: 'location',
    title: 'Location',
    why: 'We send you orders from restaurants near you, and customers see you arriving.',
  },
  {
    key: 'notifications',
    icon: 'notifications',
    title: 'Notifications',
    why: 'A new order rings even when your screen is off, so you never miss one.',
  },
];

/** Each permission with one sentence on why - a rider who understands taps Allow. */
export function PermissionsScreen() {
  const { colors } = useTheme();
  const nav = useNav();
  const { state, ready, request } = usePermissions();

  return (
    <Screen scroll contentStyle={styles.content}>
      <Animated.View entering={FadeInDown.duration(350)}>
        <View style={[styles.badge, { backgroundColor: colors.primarySoft }]}>
          <Icon name="shield-checkmark" size={34} color={colors.primary} />
        </View>
        <AppText variant="title">Two quick things</AppText>
        <AppText tone="muted" style={styles.gapXs}>
          The app needs these to send you orders.
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
                <AppText variant="bodyStrong">{item.title}</AppText>
                <AppText variant="caption" tone="muted">
                  {item.why}
                </AppText>
              </View>
              {granted ? null : (
                <Button
                  size="md"
                  label="Allow"
                  onPress={() => request(item.key)}
                />
              )}
            </Card>
          </Animated.View>
        );
      })}

      <Button
        label={ready ? 'All set' : 'Continue'}
        icon="arrow-forward"
        disabledReason={ready ? null : 'Allow both to start getting orders'}
        onPress={() => (nav.canGoBack() ? nav.goBack() : nav.navigate('Main'))}
      />
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
