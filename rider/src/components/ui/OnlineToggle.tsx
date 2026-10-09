import React, { useEffect } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  interpolate,
  interpolateColor,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSpring,
  withTiming,
} from 'react-native-reanimated';

import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space, touch } from '@theme/tokens';
import { haptic } from '@utils/haptics';
import { AppText } from './AppText';
import { Icon } from './Icon';

export type OnlineToggleProps = {
  online: boolean;
  onChange: (next: boolean) => void;
  busy?: boolean;
  disabledReason?: string | null;
  /** The status strip's size: still a full touch target, half the width. */
  compact?: boolean;
  /** Off when the caller already shows `disabledReason` itself. */
  showReason?: boolean;
};

const SIZES = {
  hero: { width: 220, height: touch.hero },
  compact: { width: 148, height: touch.large },
} as const;

/**
 * The one control a rider touches at the start and end of every shift.
 *
 * Big, coloured and pulsing while online, because "am I getting orders right
 * now?" must be answerable from arm's length at a glance. It is a tap, not a
 * slide: going online or offline costs nothing if it is wrong, unlike
 * confirming a pickup. The server decides; `online` is what it said, so a
 * refused request springs the knob back on its own.
 */
export function OnlineToggle({
  online,
  onChange,
  busy = false,
  disabledReason,
  compact = false,
  showReason = true,
}: OnlineToggleProps) {
  const { width: WIDTH, height: HEIGHT } = SIZES[compact ? 'compact' : 'hero'];
  const KNOB = HEIGHT - 8;
  const dims = { width: WIDTH, height: HEIGHT };
  const { colors } = useTheme();
  const progress = useSharedValue(online ? 1 : 0);
  const pulse = useSharedValue(0);

  useEffect(() => {
    progress.value = withSpring(online ? 1 : 0, motion.spring);
    if (online) {
      pulse.value = 0;
      pulse.value = withRepeat(
        withTiming(1, { duration: 1600, easing: Easing.out(Easing.quad) }),
        -1,
        false,
      );
    } else {
      cancelAnimation(pulse);
      pulse.value = withTiming(0, { duration: motion.fast });
    }
  }, [online, progress, pulse]);

  const offTrack = colors.surfaceAlt;
  const onTrack = colors.success;
  const offBorder = colors.border;
  const track = useAnimatedStyle(() => ({
    backgroundColor: interpolateColor(
      progress.value,
      [0, 1],
      [offTrack, onTrack],
    ),
    borderColor: interpolateColor(progress.value, [0, 1], [offBorder, onTrack]),
  }));
  const knob = useAnimatedStyle(() => ({
    transform: [
      {
        translateX: interpolate(progress.value, [0, 1], [0, WIDTH - KNOB - 8]),
      },
    ],
  }));
  const halo = useAnimatedStyle(() => ({
    opacity: interpolate(pulse.value, [0, 1], [0.45, 0]) * progress.value,
    transform: [
      { scaleX: interpolate(pulse.value, [0, 1], [1, 1.12]) },
      { scaleY: interpolate(pulse.value, [0, 1], [1, 1.4]) },
    ],
  }));
  const offLabel = useAnimatedStyle(() => ({ opacity: 1 - progress.value }));
  const onLabel = useAnimatedStyle(() => ({ opacity: progress.value }));

  const disabled = Boolean(disabledReason) || busy;

  return (
    <View style={styles.wrap}>
      <Pressable
        accessibilityRole="switch"
        accessibilityState={{ checked: online, disabled, busy }}
        accessibilityLabel={online ? 'You are online' : 'You are offline'}
        accessibilityHint={
          disabledReason ??
          (online ? 'Double tap to go offline' : 'Double tap to go online')
        }
        disabled={disabled}
        hitSlop={8}
        onPress={() => {
          haptic(online ? 'medium' : 'success');
          onChange(!online);
        }}
      >
        <View>
          <Animated.View
            pointerEvents="none"
            style={[
              styles.halo,
              dims,
              { backgroundColor: colors.success },
              halo,
            ]}
          />
          <Animated.View
            style={[
              styles.track,
              dims,
              track,
              disabled && !busy ? styles.disabled : null,
            ]}
          >
            <Animated.View
              style={[
                styles.label,
                compact ? styles.labelRightCompact : styles.labelRight,
                offLabel,
              ]}
            >
              <AppText
                variant="bodyStrong"
                tone="muted"
                numberOfLines={1}
                adjustsFontSizeToFit
                minimumFontScale={0.7}
              >
                Go online
              </AppText>
            </Animated.View>
            <Animated.View
              style={[
                styles.label,
                compact ? styles.labelLeftCompact : styles.labelLeft,
                onLabel,
              ]}
            >
              <AppText
                variant="bodyStrong"
                style={{ color: colors.onSuccess }}
                numberOfLines={1}
                adjustsFontSizeToFit
                minimumFontScale={0.7}
              >
                Online
              </AppText>
            </Animated.View>
            <Animated.View
              style={[
                styles.knob,
                { width: KNOB, height: KNOB, backgroundColor: colors.elevated },
                knob,
              ]}
            >
              {busy ? (
                <ActivityIndicator color={colors.success} />
              ) : (
                <Icon
                  name={online ? 'flash' : 'power'}
                  size={compact ? 20 : 24}
                  color={online ? colors.success : colors.textMuted}
                />
              )}
            </Animated.View>
          </Animated.View>
        </View>
      </Pressable>
      {disabledReason && showReason ? (
        <AppText
          variant="caption"
          tone="muted"
          align="center"
          style={[styles.reason, { maxWidth: WIDTH + 40 }]}
        >
          {disabledReason}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center' },
  track: {
    borderRadius: radius.pill,
    borderWidth: 1,
    justifyContent: 'center',
    paddingHorizontal: 3,
  },
  halo: { position: 'absolute', borderRadius: radius.pill },
  knob: {
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    elevation: 3,
  },
  label: { position: 'absolute', top: 0, bottom: 0, justifyContent: 'center' },
  labelRight: { right: space.xl },
  labelLeft: { left: space.xl },
  labelRightCompact: { right: space.md },
  labelLeftCompact: { left: space.md },
  disabled: { opacity: 0.5 },
  reason: { marginTop: space.sm },
});
