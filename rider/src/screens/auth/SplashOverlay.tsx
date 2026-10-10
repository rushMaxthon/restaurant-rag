import React, { useEffect, useState } from 'react';
import { StyleSheet, View, useWindowDimensions } from 'react-native';
import Animated, {
  Easing,
  FadeOut,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';

import { Illustration } from '@components/illustrations/Illustration';
import { AppText } from '@components/ui/AppText';
import { BrandMark } from '@components/ui/BrandMark';
import { useI18n } from '@/i18n';
import { space, motion } from '@theme/tokens';

const MIN_VISIBLE_MS = 1300;

/** The launch screen's orange (`res/values/colors.xml`), in every theme. */
const BRAND = '#FF5200';
const INK = '#11141B';

/**
 * The rider on the splash, redrawn for the orange: a white jacket and box
 * and a dark scooter, where the theme's orange would vanish into the ground.
 */
const ON_ORANGE = {
  P: '#FFFFFF',
  PD: '#FFD9C7',
  SC: INK,
  BE: '#2A3042',
  L: INK,
  B: '#FFFFFF',
  W: '#FFD24D',
  JN: INK,
  G: 'rgba(0, 0, 0, 0.14)',
};

/**
 * Picks up from the launch screen (`res/drawable/launch_screen.xml`): the
 * same orange and the mark in the same place - Android 12+ draws it 288 dp on
 * the 108-unit grid, which is 192 dp of the visible 72 - so the hand-over is
 * invisible. Then the name
 * rises under it and a rider rides in along the bottom while the saved
 * session is read. Held for a minimum so a fast restore does not flash.
 */
export function SplashOverlay({ ready }: { ready: boolean }) {
  const { t } = useI18n();
  const { width } = useWindowDimensions();
  const [minElapsed, setMinElapsed] = useState(false);
  const lift = useSharedValue(16);
  const fade = useSharedValue(0);
  const ride = useSharedValue(-width);
  const bob = useSharedValue(0);

  useEffect(() => {
    lift.value = withDelay(120, withSpring(0, motion.springSoft));
    fade.value = withDelay(120, withTiming(1, { duration: 420 }));
    ride.value = withDelay(
      250,
      withTiming(0, { duration: 900, easing: Easing.out(Easing.cubic) }),
    );
    bob.value = withDelay(
      1150,
      withRepeat(
        withSequence(
          withTiming(1, { duration: 260, easing: Easing.inOut(Easing.quad) }),
          withTiming(0, { duration: 260, easing: Easing.inOut(Easing.quad) }),
        ),
        -1,
      ),
    );
    const timer = setTimeout(() => setMinElapsed(true), MIN_VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [lift, fade, ride, bob]);

  const words = useAnimatedStyle(() => ({
    opacity: fade.value,
    transform: [{ translateY: lift.value }],
  }));
  const rider = useAnimatedStyle(() => ({
    transform: [{ translateX: ride.value }, { translateY: -bob.value * 2 }],
  }));

  if (ready && minElapsed) return null;

  return (
    <Animated.View
      exiting={FadeOut.duration(320)}
      style={[StyleSheet.absoluteFill, styles.root, { backgroundColor: BRAND }]}
    >
      <View style={[StyleSheet.absoluteFill, styles.center]}>
        <BrandMark size={192} bare />
      </View>
      <Animated.View style={[styles.words, words]}>
        <AppText variant="display" align="center" style={styles.white}>
          Rydor
          <AppText variant="display" style={styles.ink}>
            go
          </AppText>
        </AppText>
        <AppText align="center" style={styles.tagline}>
          {t('account.splash.tagline')}
        </AppText>
      </Animated.View>
      <Animated.View style={[styles.ride, rider]}>
        <Illustration name="ride" width={220} palette={ON_ORANGE} />
      </Animated.View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  root: { zIndex: 10 },
  center: { alignItems: 'center', justifyContent: 'center' },
  // Pinned under the mark (192 dp, centred), whatever the text's height.
  words: {
    position: 'absolute',
    top: '50%',
    left: 0,
    right: 0,
    // The R ends well above the mark's box (the grid's margin), so the
    // name tucks back into that space: about 22 dp under the letter.
    marginTop: 192 / 2 - space.lg,
    gap: space.xs,
  },
  white: { color: '#FFFFFF' },
  ink: { color: INK },
  tagline: { color: 'rgba(255, 255, 255, 0.88)' },
  ride: { position: 'absolute', bottom: space.huge, alignSelf: 'center' },
});
