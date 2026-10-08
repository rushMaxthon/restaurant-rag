import React, { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, { Easing, useAnimatedStyle, useSharedValue, withDelay, withRepeat, withTiming } from 'react-native-reanimated';

import { Icon } from '@components/ui/Icon';
import { useTheme } from '@theme/ThemeProvider';

function Ring({ delay, size, color }: { delay: number; size: number; color: string }) {
  const t = useSharedValue(0);
  useEffect(() => {
    t.value = withDelay(delay, withRepeat(withTiming(1, { duration: 2400, easing: Easing.out(Easing.quad) }), -1, false));
  }, [delay, t]);
  const style = useAnimatedStyle(() => ({
    opacity: 0.5 * (1 - t.value),
    transform: [{ scale: 0.35 + t.value * 0.65 }],
  }));
  return <Animated.View style={[styles.ring, { width: size, height: size, borderRadius: size / 2, borderColor: color }, style]} />;
}

/** "Looking for orders near you": three rings rippling out from the rider. */
export function Radar({ size = 160 }: { size?: number }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.wrap, { width: size, height: size }]} accessibilityLabel="Looking for orders near you">
      {[0, 800, 1600].map(d => (
        <Ring key={d} delay={d} size={size} color={colors.success} />
      ))}
      <View style={[styles.core, { backgroundColor: colors.success }]}>
        <Icon name="bicycle" size={26} color={colors.onSuccess} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', justifyContent: 'center' },
  ring: { position: 'absolute', borderWidth: 2 },
  core: { width: 56, height: 56, borderRadius: 28, alignItems: 'center', justifyContent: 'center' },
});
