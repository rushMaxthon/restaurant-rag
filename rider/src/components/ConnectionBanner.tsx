import React, { useEffect, useState } from 'react';
import { Linking, Platform, StyleSheet, View } from 'react-native';
import NetInfo from '@react-native-community/netinfo';
import Animated, { FadeInUp, FadeOutUp } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText } from '@components/ui/AppText';
import { ConfirmDialog } from '@components/ui/ConfirmDialog';
import { Icon } from '@components/ui/Icon';
import { useI18n } from '@/i18n';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';

/** A dropout shorter than this is a tunnel, not an outage: nothing for it. */
const PATIENCE_MS = 1500;

/**
 * No internet, said twice over: a popup the moment it is lost (once per
 * outage, with a way straight to the phone's network settings), then a small
 * pill at the top for as long as it lasts. Both go away by themselves when
 * the connection is back. Mounted ONCE above every navigator, so sign-in,
 * sign-up, the application and the working app all get it.
 *
 * The Trip screen keeps its own, more specific line ("your step is saved").
 */
export function ConnectionBanner() {
  const { colors } = useTheme();
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const [offline, setOffline] = useState(false);
  // Per outage: dismissing the popup keeps the pill, and the next outage
  // asks again.
  const [popup, setPopup] = useState(false);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = NetInfo.addEventListener(state => {
      // `isInternetReachable` null means "not checked yet" - not a failure.
      const down =
        state.isConnected === false || state.isInternetReachable === false;
      if (timer) clearTimeout(timer);
      timer = null;
      if (down) {
        timer = setTimeout(() => {
          setOffline(true);
          setPopup(true);
        }, PATIENCE_MS);
      } else {
        setOffline(false);
        setPopup(false);
      }
    });
    return () => {
      unsubscribe();
      if (timer) clearTimeout(timer);
    };
  }, []);

  const openSettings = async () => {
    setPopup(false);
    try {
      if (Platform.OS === 'android') {
        await Linking.sendIntent('android.settings.WIRELESS_SETTINGS');
      } else {
        await Linking.openSettings();
      }
    } catch {
      // Some phones hide that page: the app's own settings are the fallback.
      Linking.openSettings().catch(() => {});
    }
  };

  return (
    <>
      {offline ? (
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
      ) : null}
      <ConfirmDialog
        open={popup}
        icon="cloud-offline"
        title={t('net.title')}
        message={t('net.body')}
        confirmLabel={t('net.settings')}
        cancelLabel={t('confirm.ok')}
        onCancel={() => setPopup(false)}
        onConfirm={() => void openSettings()}
      />
    </>
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
