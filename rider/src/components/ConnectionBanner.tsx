import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import NetInfo from '@react-native-community/netinfo';
import Animated, { FadeInUp, FadeOutUp } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText } from '@components/ui/AppText';
import { Icon } from '@components/ui/Icon';
import { useI18n } from '@/i18n';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';

/** A dropout shorter than this is a tunnel, not an outage: no banner for it. */
const PATIENCE_MS = 1500;

/**
 * "No connection", once, at the top of whatever screen is open. Mounted a
 * single time above the navigator; the Trip screen keeps its own, more
 * specific line ("your step is saved") on top of this.
 */
export function ConnectionBanner() {
  const { colors } = useTheme();
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = NetInfo.addEventListener(state => {
      const down = state.isConnected === false;
      if (timer) clearTimeout(timer);
      timer = null;
      if (down) timer = setTimeout(() => setOffline(true), PATIENCE_MS);
      else setOffline(false);
    });
    return () => {
      unsubscribe();
      if (timer) clearTimeout(timer);
    };
  }, []);

  if (!offline) return null;
  return (
    <Animated.View
      entering={FadeInUp.duration(240)}
      exiting={FadeOutUp.duration(200)}
      pointerEvents="none"
      style={[styles.wrap, { top: insets.top + space.xs }]}
    >
      <View
        style={[
          styles.pill,
          { backgroundColor: colors.elevated, borderColor: colors.warning },
        ]}
      >
        <Icon name="cloud-offline" size={16} color={colors.warning} />
        <AppText variant="label" tone="warning">
          {t('account.offline')}
        </AppText>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    position: 'absolute',
    left: 0,
    right: 0,
    alignItems: 'center',
    zIndex: 20,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
    borderRadius: 999,
    borderWidth: 1,
    elevation: 6,
  },
});
