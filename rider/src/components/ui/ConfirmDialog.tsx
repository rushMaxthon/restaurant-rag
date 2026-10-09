import React from 'react';
import { Modal, Pressable, StyleSheet, View } from 'react-native';
import Animated, { FadeIn, FadeOut, ZoomIn } from 'react-native-reanimated';

import { translate } from '@/i18n/translate';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';
import { AppText } from './AppText';
import { Button } from './Button';
import { Icon, type IconName } from './Icon';

/**
 * "Are you sure?" in the app's own look, for every action a rider should not
 * take by a slip of the thumb: declining an order, marking a customer
 * unavailable, submitting an application, signing out. Replaces Android's
 * grey system alert, which looked like a different app and put the
 * dangerous button where the safe one usually is.
 *
 * Cancel is always the left, quiet button and is what back and a tap outside
 * do; the action is the right one, red when it cannot be undone. With no
 * `confirmLabel` it is a one-button notice ("Finish your delivery first").
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel,
  tone = 'default',
  icon,
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message?: string;
  /** Omit for a notice with a single OK. */
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'default' | 'danger';
  icon?: IconName;
  busy?: boolean;
  onConfirm?: () => void;
  onCancel: () => void;
}) {
  const { colors } = useTheme();
  const danger = tone === 'danger';
  const accent = danger ? colors.danger : colors.primary;
  const soft = danger ? colors.dangerSoft : colors.primarySoft;

  return (
    <Modal
      visible={open}
      transparent
      statusBarTranslucent
      navigationBarTranslucent
      animationType="none"
      onRequestClose={busy ? () => {} : onCancel}
    >
      <View style={styles.root}>
        <Animated.View
          entering={FadeIn.duration(160)}
          exiting={FadeOut.duration(140)}
          style={StyleSheet.absoluteFill}
        >
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={cancelLabel ?? translate('confirm.cancel')}
            onPress={busy ? undefined : onCancel}
            style={[
              StyleSheet.absoluteFill,
              { backgroundColor: colors.overlay },
            ]}
          />
        </Animated.View>
        <Animated.View
          entering={ZoomIn.duration(180)}
          accessibilityViewIsModal
          style={[
            styles.card,
            { backgroundColor: colors.elevated, borderColor: colors.border },
          ]}
        >
          <View style={[styles.badge, { backgroundColor: soft }]}>
            <Icon
              name={icon ?? (danger ? 'alert-circle' : 'help-circle')}
              size={28}
              color={accent}
            />
          </View>
          <AppText variant="heading" align="center" accessibilityRole="header">
            {title}
          </AppText>
          {message ? (
            <AppText tone="muted" align="center" style={styles.message}>
              {message}
            </AppText>
          ) : null}
          <View style={styles.row}>
            {confirmLabel ? (
              <>
                <Button
                  kind="secondary"
                  size="md"
                  label={cancelLabel ?? translate('confirm.cancel')}
                  onPress={busy ? () => {} : onCancel}
                  style={styles.flex}
                />
                <Button
                  kind={danger ? 'danger' : 'primary'}
                  size="md"
                  label={confirmLabel}
                  loading={busy}
                  onPress={() => onConfirm?.()}
                  style={styles.flex}
                />
              </>
            ) : (
              <Button
                size="md"
                label={cancelLabel ?? translate('confirm.ok')}
                onPress={onCancel}
                style={styles.flex}
              />
            )}
          </View>
        </Animated.View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.xl,
  },
  card: {
    width: '100%',
    maxWidth: 420,
    borderRadius: radius.xxl,
    borderWidth: StyleSheet.hairlineWidth * 2,
    padding: space.xl,
    alignItems: 'center',
    gap: space.sm,
  },
  badge: {
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.xs,
  },
  message: { marginTop: space.xxs },
  row: {
    flexDirection: 'row',
    gap: space.md,
    alignSelf: 'stretch',
    marginTop: space.lg,
  },
  flex: { flex: 1 },
});
