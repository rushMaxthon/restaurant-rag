import React, { useEffect } from 'react';
import { Animated, type DimensionValue, StyleSheet } from 'react-native';
import { useTheme } from '@/theme';

// ONE pulse for every skeleton on screen. A board loading four columns would
// otherwise run eight independent loops; here they share a single native-
// driven value, started by the first skeleton and stopped by the last.
const pulse = new Animated.Value(0.55);
let users = 0;
let loop: Animated.CompositeAnimation | null = null;

const retain = () => {
  users += 1;
  if (!loop) {
    loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 750, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0.55, duration: 750, useNativeDriver: true }),
      ]),
    );
    loop.start();
  }
};

const release = () => {
  users -= 1;
  if (users === 0 && loop) {
    loop.stop();
    loop = null;
  }
};

interface SkeletonProps {
  height: number;
  width?: DimensionValue;
  radius?: number;
}

// Only ever shown before the FIRST answer — a refetch keeps the last good
// content on screen instead of flashing back to placeholders.
export const Skeleton = ({ height, width = '100%', radius = 12 }: SkeletonProps) => {
  const { colors } = useTheme();
  useEffect(() => {
    retain();
    return release;
  }, []);
  return (
    <Animated.View
      style={[
        styles.block,
        { height, width, borderRadius: radius, backgroundColor: colors.surfaceMuted, opacity: pulse },
      ]}
    />
  );
};

const styles = StyleSheet.create({
  block: {},
});
