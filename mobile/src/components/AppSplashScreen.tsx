import React, { useCallback, useEffect, useRef } from 'react';
import {
  ActivityIndicator,
  Animated,
  Image,
  Platform,
  StyleSheet,
  useColorScheme,
  useWindowDimensions,
  View,
  type ImageSourcePropType,
} from 'react-native';
import { lightTheme } from '@/theme';
import { hideSplashScreen } from '@services/splashScreen';

/**
 * The React Native continuation of the native splash screen.
 *
 * This does NOT re-create the splash artwork - it points at the very same
 * image files the native splash uses, by resource name:
 *
 *   Android  `launch_screen`  -> res/drawable-{ldpi..xxxhdpi}/launch_screen.png
 *            (the same drawable res/layout/launch_screen.xml renders)
 *   iOS      `splashScreen`   -> Images.xcassets/splashScreen.imageset
 *            (the same asset LaunchScreen.storyboard renders)
 *
 * Referencing the assets rather than copying them is what guarantees the two
 * splashes are pixel-identical: there is only one set of artwork, and both
 * layers draw it at the same scale mode. `cover` is React Native's equivalent
 * of Android's `centerCrop` and iOS's `scaleAspectFill`, both of which the
 * native layers already use.
 */
const SPLASH_IMAGE: ImageSourcePropType = Platform.select({
  ios: { uri: 'splashScreen' },
  default: { uri: 'launch_screen' },
});

/**
 * Brand orange, taken from the theme's `sharedColors.primary` - the one colour
 * that is identical in both the light and dark palettes.
 *
 * Read from `lightTheme` rather than `useTheme()` on purpose: the native
 * splash this continues is a fixed image with no theme variants, so the
 * spinner must not change with the in-app theme either. Measured against the
 * artwork's lower third (average #C9C5C1, luminance 0.78), so it has contrast
 * where it sits.
 */
const INDICATOR_COLOR = lightTheme.colors.primary;

/** Long enough to read as a fade, short enough not to delay a ready app. */
const FADE_OUT_DURATION_MS = 250;

/**
 * How far up the screen the indicator sits, as a fraction of screen HEIGHT.
 *
 * 0.32 puts it at ~68% of the height: below the logo card, and inside the
 * artwork's flat backdrop rather than on the food photography. Sampled from a
 * real 1080x2400 device, the centre column is a flat grey (RGB ~186-216,
 * channel spread <=12) from 55% to 70%, then becomes photographic detail
 * (spread 128-204) from 75% down. Brand orange reads clearly on the former
 * and disappears into the sauces on the latter.
 *
 * Applied from `useWindowDimensions` rather than as a `'32%'` style value on
 * purpose: React Native resolves percentage margins against the parent's
 * WIDTH (same as CSS), so a percentage string here would track the wrong axis
 * and drift badly across aspect ratios.
 */
const INDICATOR_BOTTOM_FRACTION = 0.32;

interface AppSplashScreenProps {
  /**
   * True once app initialisation has finished. Flips this component from
   * "holding" to fading itself out; it does not unmount on its own.
   */
  done: boolean;
  /** Called after the fade completes, so the parent can unmount this. */
  onHidden: () => void;
}

export function AppSplashScreen({
  done,
  onHidden,
}: AppSplashScreenProps): React.JSX.Element {
  const opacity = useRef(new Animated.Value(1)).current;
  const hasHiddenNativeSplashRef = useRef(false);
  const osColorScheme = useColorScheme();
  const { height: screenHeight } = useWindowDimensions();

  /**
   * Dismisses the NATIVE splash only once this view has been laid out, so the
   * hand-off is invisible: the native splash is removed while an identical
   * image is already on screen underneath it.
   *
   * Doing it the other way round - hiding the native splash on mount, or from
   * bootstrap - is what produces the white flash, because the native layer
   * disappears a frame or more before React Native has drawn anything.
   *
   * `requestAnimationFrame` defers to after this layout pass has actually been
   * painted; `onLayout` alone fires once the layout is computed, which is a
   * frame too early on a slow first render.
   */
  const handleLayout = useCallback(() => {
    if (hasHiddenNativeSplashRef.current) {
      return;
    }
    hasHiddenNativeSplashRef.current = true;
    requestAnimationFrame(() => {
      hideSplashScreen();
    });
  }, []);

  useEffect(() => {
    if (!done) {
      return;
    }
    // One frame of headroom before fading: `done` flipping is what mounts the
    // navigator underneath, and this lets that tree commit its first paint so
    // the fade reveals a finished screen rather than a half-laid-out one.
    const frame = requestAnimationFrame(() => {
      Animated.timing(opacity, {
        toValue: 0,
        duration: FADE_OUT_DURATION_MS,
        useNativeDriver: true,
      }).start(({ finished }) => {
        if (finished) {
          onHidden();
        }
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [done, onHidden, opacity]);

  return (
    <Animated.View
      // `none`: during the fade the real app is already live underneath, so a
      // tap should reach it rather than being swallowed by a dying overlay.
      pointerEvents="none"
      onLayout={handleLayout}
      style={[
        StyleSheet.absoluteFill,
        styles.container,
        // Mirrors each platform's own splash background, which only shows on
        // aspect ratios the artwork cannot cover. Android's
        // res/values/colors.xml pins `splash_background` to #FFFFFF in every
        // configuration; iOS's LaunchScreen.storyboard uses the DYNAMIC
        // `systemBackgroundColor`, which is black in dark mode - so matching it
        // needs the OS appearance, not the in-app theme.
        Platform.OS === 'ios' && osColorScheme === 'dark'
          ? styles.backgroundDark
          : styles.backgroundLight,
        { opacity },
      ]}
    >
      <Image
        source={SPLASH_IMAGE}
        style={StyleSheet.absoluteFill}
        resizeMode="cover"
        // Decorative duplicate of the native splash; announcing it would make
        // a screen reader read the same artwork twice during hand-off.
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
      />

      <View style={{ marginBottom: screenHeight * INDICATOR_BOTTOM_FRACTION }}>
        <ActivityIndicator size="large" color={INDICATOR_COLOR} />
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    // The image is absolutely filled, so this only positions the indicator.
    justifyContent: 'flex-end',
    alignItems: 'center',
  },
  backgroundLight: {
    backgroundColor: '#FFFFFF',
  },
  backgroundDark: {
    backgroundColor: '#000000',
  },
});
