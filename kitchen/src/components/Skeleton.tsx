import React, { useEffect, useRef } from 'react';
import { Animated, type DimensionValue, StyleSheet } from 'react-native';
import { useTheme } from '@/theme';

interface SkeletonProps {
  height: number;
  width?: DimensionValue;
  radius?: number;
}

// A placeholder that breathes, only ever shown before the FIRST answer — a
// refetch keeps the last good content on screen instead.
export const Skeleton = ({ height, width = '100%', radius = 16 }: SkeletonProps) => {
  const { colors } = useTheme();
  const opacity = useRef(new Animated.Value(0.5)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 700, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.5, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity]);
  return (
    <Animated.View
      style={[
        styles.block,
        { height, width, borderRadius: radius, backgroundColor: colors.surfaceMuted, opacity },
      ]}
    />
  );
};

const styles = StyleSheet.create({
  block: {},
});
