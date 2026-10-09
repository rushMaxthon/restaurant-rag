import React, { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import Animated, {
  Easing,
  FadeInDown,
  useAnimatedProps,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Circle, Path } from 'react-native-svg';

import { AnimatedAmount } from '@components/ui/AnimatedAmount';
import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Screen } from '@components/ui/Screen';
import type { RootStackParamList } from '@navigation/types';
import { useRider } from '@/store/RiderProvider';
import { waitingLabel } from '@utils/delivered';
import { useTheme } from '@theme/ThemeProvider';
import { space, motion } from '@theme/tokens';
import { haptic } from '@utils/haptics';

const AnimatedPath = Animated.createAnimatedComponent(Path);
const AnimatedCircle = Animated.createAnimatedComponent(Circle);

const SIZE = 132;
const TICK_LENGTH = 70;
const RING_LENGTH = 2 * Math.PI * 58;

function Burst({ angle, color }: { angle: number; color: string }) {
  const t = useSharedValue(0);
  useEffect(() => {
    t.value = withDelay(
      350,
      withTiming(1, { duration: 650, easing: Easing.out(Easing.cubic) }),
    );
  }, [t]);
  const style = useAnimatedStyle(() => ({
    opacity: 1 - t.value,
    transform: [
      { translateX: Math.cos(angle) * (60 + t.value * 50) },
      { translateY: Math.sin(angle) * (60 + t.value * 50) },
      { scale: 1 - t.value * 0.5 },
    ],
  }));
  return (
    <Animated.View style={[styles.spark, { backgroundColor: color }, style]} />
  );
}

/** The moment a delivery is done: the ring closes, the tick draws, the money lands. */
export function DeliveredScreen({
  navigation,
  route,
}: NativeStackScreenProps<RootStackParamList, 'Delivered'>) {
  const { colors } = useTheme();
  const { me, openOrders } = useRider();
  // Only when they could actually take one: the board needs them online.
  const waiting = waitingLabel(me?.status === 'ONLINE' ? openOrders.length : 0);
  const ring = useSharedValue(0);
  const tick = useSharedValue(0);
  const pop = useSharedValue(0.6);

  useEffect(() => {
    haptic('success');
    pop.value = withSpring(1, motion.spring);
    ring.value = withTiming(1, {
      duration: 500,
      easing: Easing.out(Easing.cubic),
    });
    tick.value = withDelay(
      350,
      withTiming(1, { duration: 380, easing: Easing.out(Easing.quad) }),
    );
  }, [ring, tick, pop]);

  const ringProps = useAnimatedProps(() => ({
    strokeDashoffset: RING_LENGTH * (1 - ring.value),
  }));
  const tickProps = useAnimatedProps(() => ({
    strokeDashoffset: TICK_LENGTH * (1 - tick.value),
  }));
  const badge = useAnimatedStyle(() => ({ transform: [{ scale: pop.value }] }));
  const sparks = [colors.primary, colors.success, colors.warning];

  return (
    <Screen style={styles.root}>
      <View style={styles.center}>
        <View style={styles.badgeWrap}>
          {Array.from({ length: 10 }, (_, i) => (
            <Burst
              key={i}
              angle={(i / 10) * Math.PI * 2}
              color={sparks[i % 3] ?? colors.primary}
            />
          ))}
          <Animated.View style={badge}>
            <Svg width={SIZE} height={SIZE}>
              <Circle
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={58}
                fill={colors.successSoft}
              />
              <AnimatedCircle
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={58}
                stroke={colors.success}
                strokeWidth={6}
                fill="none"
                strokeLinecap="round"
                strokeDasharray={`${RING_LENGTH} ${RING_LENGTH}`}
                animatedProps={ringProps}
                rotation={-90}
                origin={`${SIZE / 2}, ${SIZE / 2}`}
              />
              <AnimatedPath
                d="M42 68 L58 84 L92 50"
                stroke={colors.success}
                strokeWidth={8}
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray={`${TICK_LENGTH} ${TICK_LENGTH}`}
                animatedProps={tickProps}
              />
            </Svg>
          </Animated.View>
        </View>

        <Animated.View
          entering={FadeInDown.delay(500).duration(motion.base)}
          style={styles.text}
        >
          <AppText variant="title" align="center">
            Delivered!
          </AppText>
          <AppText tone="muted" align="center">
            Order {route.params.orderCode} is with the customer.
          </AppText>
        </Animated.View>

        <Animated.View
          entering={FadeInDown.delay(700).duration(motion.base)}
          style={[
            styles.earned,
            { backgroundColor: colors.surfaceAlt, borderColor: colors.border },
          ]}
        >
          <AppText variant="micro" tone="muted" align="center">
            YOU EARNED
          </AppText>
          <AnimatedAmount
            value={Number(route.params.amount)}
            duration={900}
            align="center"
            tone="success"
          />
        </Animated.View>
      </View>

      <Animated.View entering={FadeInDown.delay(900)} style={styles.actions}>
        {waiting ? (
          <Button
            kind="secondary"
            label={waiting}
            icon="receipt"
            onPress={() =>
              navigation.reset({
                index: 0,
                routes: [{ name: 'Main', params: { screen: 'Orders' } }],
              })
            }
          />
        ) : null}
        <Button
          label="Done"
          icon="checkmark"
          onPress={() =>
            navigation.reset({ index: 0, routes: [{ name: 'Main' }] })
          }
        />
      </Animated.View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  root: { justifyContent: 'space-between' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  badgeWrap: {
    width: SIZE,
    height: SIZE,
    alignItems: 'center',
    justifyContent: 'center',
  },
  spark: { position: 'absolute', width: 10, height: 10, borderRadius: 5 },
  text: { marginTop: space.xxl, gap: space.xs },
  actions: { gap: space.sm },
  earned: {
    marginTop: space.xxl,
    paddingVertical: space.lg,
    paddingHorizontal: space.xxxl,
    borderRadius: 20,
    borderWidth: 1,
  },
});
