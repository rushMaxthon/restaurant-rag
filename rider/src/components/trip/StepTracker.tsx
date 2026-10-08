import React, { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withSpring } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Icon, type IconName } from '@components/ui/Icon';
import type { TripStep } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { motion, space } from '@theme/tokens';

const STEPS: { key: TripStep; label: string; icon: IconName }[] = [
  { key: 'to_pickup', label: 'Pickup', icon: 'restaurant' },
  { key: 'at_pickup', label: 'Collect', icon: 'bag-handle' },
  { key: 'to_drop', label: 'Drop', icon: 'navigate' },
  { key: 'at_drop', label: 'Deliver', icon: 'home' },
];

export function stepIndex(step: TripStep): number {
  if (step === 'done') return STEPS.length;
  return STEPS.findIndex(s => s.key === step);
}

/** Four stops along one line; the line fills up to where the rider is. */
export function StepTracker({ step }: { step: TripStep }) {
  const { colors } = useTheme();
  const index = stepIndex(step);
  const fill = useSharedValue(0);

  useEffect(() => {
    fill.value = withSpring(Math.min(index, STEPS.length - 1) / (STEPS.length - 1), motion.springSoft);
  }, [index, fill]);

  const bar = useAnimatedStyle(() => ({ width: `${fill.value * 100}%` }));

  return (
    <View accessibilityLabel={`Step ${Math.min(index + 1, 4)} of 4`}>
      <View style={styles.track}>
        <View style={[styles.line, { backgroundColor: colors.border }]}>
          <Animated.View style={[styles.lineFill, { backgroundColor: colors.primary }, bar]} />
        </View>
        {STEPS.map((s, i) => {
          const done = i < index;
          const current = i === index;
          return (
            <View key={s.key} style={styles.node}>
              <View
                style={[
                  styles.dot,
                  {
                    // Opaque, so the progress line never shows through the circle.
                    backgroundColor: done ? colors.primary : current ? colors.elevated : colors.surfaceAlt,
                    borderColor: done || current ? colors.primary : colors.border,
                  },
                ]}
              >
                <Icon name={done ? 'checkmark' : s.icon} size={16} color={done ? colors.onPrimary : current ? colors.primary : colors.textFaint} />
              </View>
              <AppText variant="micro" numberOfLines={1} style={{ color: current ? colors.primary : done ? colors.text : colors.textFaint }}>
                {s.label.toUpperCase()}
              </AppText>
            </View>
          );
        })}
      </View>
    </View>
  );
}

const DOT = 34;

const styles = StyleSheet.create({
  track: { flexDirection: 'row', justifyContent: 'space-between' },
  line: { position: 'absolute', left: DOT / 2 + 8, right: DOT / 2 + 8, top: DOT / 2 - 2, height: 4, borderRadius: 2, overflow: 'hidden' },
  lineFill: { height: '100%', borderRadius: 2 },
  node: { alignItems: 'center', gap: space.xs, width: 72 },
  dot: { width: DOT, height: DOT, borderRadius: DOT / 2, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
});
