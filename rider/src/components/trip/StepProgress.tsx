import React, { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import type { TripStep } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { motion, space } from '@theme/tokens';
import { stepProgress } from '@utils/tripSteps';

/**
 * "Step 2 of 4 · At the restaurant" over a thin bar that fills as the rider
 * goes. It replaced four labelled circles that took a whole card, pushing the
 * address - what the rider actually needs - down the screen.
 */
export function StepProgress({ step }: { step: TripStep }) {
  const { colors } = useTheme();
  const { current, total, label } = stepProgress(step);
  const fill = useSharedValue(0);
  useEffect(() => {
    fill.value = withSpring(current / total, motion.springSoft);
  }, [current, total, fill]);
  const bar = useAnimatedStyle(() => ({ width: `${fill.value * 100}%` }));

  return (
    <View
      style={styles.wrap}
      accessibilityLabel={`Step ${current} of ${total}: ${label}`}
    >
      <View style={styles.row}>
        <AppText variant="bodyStrong" style={styles.flex} numberOfLines={1}>
          {label}
        </AppText>
        <AppText variant="label" tone="muted">
          {current} of {total}
        </AppText>
      </View>
      <View style={[styles.track, { backgroundColor: colors.border }]}>
        <Animated.View
          style={[styles.fill, { backgroundColor: colors.primary }, bar]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: space.sm },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  flex: { flex: 1 },
  track: { height: 6, borderRadius: 3, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: 3 },
});
