import React, { useEffect } from 'react';
import {
  Pressable,
  StyleSheet,
  View,
  type LayoutChangeEvent,
} from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';

import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space, touch } from '@theme/tokens';
import { haptic } from '@utils/haptics';
import { AppText } from './AppText';

/**
 * A few choices side by side, one active, a pill sliding under it. Each
 * segment is the full touch height: this is tapped between deliveries, with
 * gloves on, not studied.
 */
export function Segmented<K extends string>({
  options,
  value,
  onChange,
}: {
  options: readonly { key: K; label: string }[];
  value: K;
  onChange: (key: K) => void;
}) {
  const { colors } = useTheme();
  const index = Math.max(
    0,
    options.findIndex(o => o.key === value),
  );
  const width = useSharedValue(0);
  const x = useSharedValue(0);

  useEffect(() => {
    x.value = withSpring(index * width.value, motion.spring);
  }, [index, x, width]);

  const onLayout = (e: LayoutChangeEvent) => {
    width.value = (e.nativeEvent.layout.width - PAD * 2) / options.length;
    x.value = index * width.value;
  };

  const pill = useAnimatedStyle(() => ({
    width: width.value,
    transform: [{ translateX: x.value }],
  }));

  return (
    <View
      accessibilityRole="tablist"
      onLayout={onLayout}
      style={[
        styles.track,
        { backgroundColor: colors.surfaceAlt, borderColor: colors.border },
      ]}
    >
      <Animated.View
        style={[
          styles.pill,
          { backgroundColor: colors.elevated, borderColor: colors.border },
          pill,
        ]}
      />
      {options.map(o => {
        const active = o.key === value;
        return (
          <Pressable
            key={o.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            style={styles.item}
            onPress={() => {
              if (active) return;
              haptic('tick');
              onChange(o.key);
            }}
          >
            <AppText variant="label" tone={active ? 'default' : 'muted'}>
              {o.label}
            </AppText>
          </Pressable>
        );
      })}
    </View>
  );
}

const PAD = 4;

const styles = StyleSheet.create({
  track: {
    flexDirection: 'row',
    // Each segment is a full touch target inside the padding.
    height: touch.min + PAD * 2,
    borderRadius: radius.pill,
    borderWidth: 1,
    padding: PAD,
  },
  pill: {
    position: 'absolute',
    top: PAD,
    bottom: PAD,
    left: PAD,
    borderRadius: radius.pill,
    borderWidth: 1,
    elevation: 2,
  },
  item: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.sm,
  },
});
