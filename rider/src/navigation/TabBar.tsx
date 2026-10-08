import React, { useEffect } from 'react';
import { Pressable, StyleSheet, View, useWindowDimensions } from 'react-native';
import type { BottomTabBarProps } from '@react-navigation/bottom-tabs';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText } from '@components/ui/AppText';
import { Icon, type IconName } from '@components/ui/Icon';
import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space } from '@theme/tokens';
import { haptic } from '@utils/haptics';
import { useRider } from '@/store/RiderProvider';

const ICONS: Record<string, [IconName, IconName]> = {
  Home: ['home-outline', 'home'],
  Orders: ['receipt-outline', 'receipt'],
  Earnings: ['wallet-outline', 'wallet'],
  History: ['time-outline', 'time'],
  Profile: ['person-circle-outline', 'person-circle'],
};

const BAR_MARGIN = space.lg;
const BAR_HEIGHT = 68;

/**
 * A floating bar with a pill that slides under the active tab. Thumb-sized
 * targets (the whole quarter is the button), icon + label always visible:
 * a rider glancing down on a bike should not have to decode an icon.
 */
export function TabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const { colors } = useTheme();
  // Orders waiting on the board: a count on its tab, so a rider sees them from anywhere.
  const waiting = useRider().openOrders.length;
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const count = state.routes.length;
  const slot = (width - BAR_MARGIN * 2 - 8) / count;
  const x = useSharedValue(state.index * slot);

  useEffect(() => {
    x.value = withSpring(state.index * slot, motion.spring);
  }, [state.index, slot, x]);

  const pill = useAnimatedStyle(() => ({
    transform: [{ translateX: x.value }],
  }));

  return (
    <View
      pointerEvents="box-none"
      style={[
        styles.wrap,
        {
          bottom: Math.max(insets.bottom, space.md),
          left: BAR_MARGIN,
          right: BAR_MARGIN,
        },
      ]}
    >
      <View
        style={[
          styles.bar,
          { backgroundColor: colors.elevated, borderColor: colors.border },
        ]}
      >
        <Animated.View
          style={[
            styles.pill,
            { width: slot, backgroundColor: colors.primary },
            pill,
          ]}
        />
        {state.routes.map((route, index) => {
          const focused = state.index === index;
          const label = (descriptors[route.key]?.options.title ??
            route.name) as string;
          const [outline, solid] = ICONS[route.name] ?? [
            'ellipse-outline',
            'ellipse',
          ];
          return (
            <Pressable
              key={route.key}
              accessibilityRole="tab"
              accessibilityState={{ selected: focused }}
              accessibilityLabel={label}
              style={styles.item}
              onPress={() => {
                const event = navigation.emit({
                  type: 'tabPress',
                  target: route.key,
                  canPreventDefault: true,
                });
                if (!focused && !event.defaultPrevented) {
                  haptic('tick');
                  navigation.navigate(route.name);
                }
              }}
            >
              <View>
                <Icon
                  name={focused ? solid : outline}
                  size={22}
                  color={focused ? colors.onPrimary : colors.textMuted}
                />
                {route.name === 'Orders' && waiting > 0 ? (
                  <View
                    style={[
                      styles.badge,
                      {
                        backgroundColor: colors.danger,
                        borderColor: colors.elevated,
                      },
                    ]}
                  >
                    <AppText
                      variant="micro"
                      style={[styles.badgeText, { color: colors.onPrimary }]}
                    >
                      {waiting > 9 ? '9+' : waiting}
                    </AppText>
                  </View>
                ) : null}
              </View>
              <AppText
                variant="micro"
                style={{ color: focused ? colors.onPrimary : colors.textMuted }}
              >
                {label.toUpperCase()}
              </AppText>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: 'absolute' },
  bar: {
    height: BAR_HEIGHT,
    borderRadius: radius.xxl,
    borderWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 4,
    elevation: 12,
    shadowColor: '#000',
    shadowOpacity: 0.18,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
  },
  pill: {
    position: 'absolute',
    left: 4,
    top: 6,
    bottom: 6,
    borderRadius: radius.xl,
  },
  badge: {
    position: 'absolute',
    top: -6,
    right: -10,
    minWidth: 18,
    height: 18,
    paddingHorizontal: 4,
    borderRadius: 9,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: { fontSize: 10, lineHeight: 12 },
  item: {
    flex: 1,
    height: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
  },
});
