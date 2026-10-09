import React, { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { useI18n } from '@/i18n';
import type { SectionKey } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space } from '@theme/tokens';
import { STEPS } from '@utils/onboarding';

/** "Step 2 of 4 · Vehicle" over four segments; the current one fills as you arrive. */
export function StepProgressBar({ step }: { step: SectionKey }) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const index = STEPS.indexOf(step);
  const fill = useSharedValue(0);
  useEffect(() => {
    fill.value = 0;
    fill.value = withTiming(1, { duration: motion.slow });
  }, [fill, step]);
  const current = useAnimatedStyle(() => ({ width: `${fill.value * 100}%` }));

  return (
    <View
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 1, max: STEPS.length, now: index + 1 }}
      style={styles.wrap}
    >
      <AppText variant="label" tone="muted">
        {t('onboarding.step.progress', {
          n: index + 1,
          total: STEPS.length,
          name: t(`onboarding.step.${step}`),
        })}
      </AppText>
      <View style={styles.row}>
        {STEPS.map((s, i) => (
          <View
            key={s}
            style={[styles.segment, { backgroundColor: colors.border }]}
          >
            {i < index ? (
              <View
                style={[
                  styles.fill,
                  styles.full,
                  { backgroundColor: colors.primary },
                ]}
              />
            ) : i === index ? (
              <Animated.View
                style={[
                  styles.fill,
                  { backgroundColor: colors.primary },
                  current,
                ]}
              />
            ) : null}
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: space.sm },
  row: { flexDirection: 'row', gap: space.xs },
  segment: {
    flex: 1,
    height: 6,
    borderRadius: radius.pill,
    overflow: 'hidden',
  },
  fill: { height: '100%', borderRadius: radius.pill },
  full: { width: '100%' },
});
