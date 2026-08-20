import React, { useEffect, useRef } from 'react';
import { Animated, StyleSheet, View } from 'react-native';
import { theme, useThemedStyles, type AppTheme } from '@/theme';

interface SkeletonBlockProps {
  height: number;
  borderRadius?: number;
  width?: number | `${number}%`;
}

export function SkeletonBlock({
  height,
  borderRadius = 12,
  width = '100%',
}: SkeletonBlockProps): React.JSX.Element {
  const styles = useThemedStyles(createStyles);
  const shimmer = useRef(new Animated.Value(-1)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.timing(shimmer, {
        toValue: 1,
        duration: 1200,
        useNativeDriver: true,
      }),
    );
    animation.start();
    return () => animation.stop();
  }, [shimmer]);

  const translateX = shimmer.interpolate({
    inputRange: [-1, 1],
    outputRange: [-220, 220],
  });

  return (
    <View style={[styles.base, { height, borderRadius, width }]}>
      <Animated.View
        style={[
          styles.shimmer,
          {
            transform: [{ translateX }],
          },
        ]}
      />
    </View>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    base: {
      overflow: 'hidden',
      backgroundColor: theme.colors.skeletonBase,
    },
    shimmer: {
      ...StyleSheet.absoluteFill,
      backgroundColor: theme.colors.skeletonHighlight,
      opacity: theme.mode === 'dark' ? 0.42 : 0.6,
    },
  });

const styles = createStyles(theme);
