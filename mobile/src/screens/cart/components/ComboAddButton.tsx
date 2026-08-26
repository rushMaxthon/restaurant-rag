import React, { useEffect, useRef, useState } from 'react';
import {
  AccessibilityInfo,
  Platform,
  Pressable,
  Text,
  Vibration,
  View,
} from 'react-native';
import Reanimated, {
  Easing as ReanimatedEasing,
  cancelAnimation,
  interpolate,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import Icon from 'react-native-vector-icons/Ionicons';
import { useTheme, useThemedStyles } from '@/theme';
import { createStyles } from '../styles';

type ComboAddButtonProps = {
  hasAppeared: boolean;
  interacted: boolean;
  isVisible: boolean;
  label: string;
  onPress: () => void;
};

const ReanimatedPressable = Reanimated.createAnimatedComponent(Pressable);
export const ComboAddButton = React.memo(function ComboAddButton({
  hasAppeared,
  interacted,
  isVisible,
  label,
  onPress,
}: ComboAddButtonProps) {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [showAddedState, setShowAddedState] = useState(false);
  const hasPlayedIntroRef = useRef(false);
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idleProgress = useSharedValue(0);
  const pressScale = useSharedValue(1);
  const introOpacity = useSharedValue(0);
  const introScale = useSharedValue(0.96);

  useEffect(() => {
    let mounted = true;
    const updatePreference = (value: boolean) => {
      if (mounted) {
        setReduceMotion(value);
      }
    };

    AccessibilityInfo.isReduceMotionEnabled?.()
      .then(updatePreference)
      .catch(() => undefined);

    const subscription = AccessibilityInfo.addEventListener?.(
      'reduceMotionChanged',
      updatePreference,
    );

    return () => {
      mounted = false;
      if (successTimerRef.current) {
        clearTimeout(successTimerRef.current);
      }
      subscription?.remove?.();
    };
  }, []);

  useEffect(() => {
    if (!hasAppeared || hasPlayedIntroRef.current) {
      return;
    }
    hasPlayedIntroRef.current = true;
    introOpacity.value = withTiming(1, {
      duration: reduceMotion ? 1 : 240,
      easing: ReanimatedEasing.out(ReanimatedEasing.cubic),
    });
    introScale.value = withTiming(1, {
      duration: reduceMotion ? 1 : 300,
      easing: ReanimatedEasing.out(ReanimatedEasing.cubic),
    });
  }, [hasAppeared, introOpacity, introScale, reduceMotion]);

  useEffect(() => {
    const canAnimateIdle =
      isVisible && !interacted && !reduceMotion && !showAddedState;

    if (!canAnimateIdle) {
      cancelAnimation(idleProgress);
      idleProgress.value = withTiming(0, {
        duration: 160,
        easing: ReanimatedEasing.out(ReanimatedEasing.quad),
      });
      return;
    }

    idleProgress.value = withRepeat(
      withSequence(
        withTiming(1, {
          duration: 900,
          easing: ReanimatedEasing.inOut(ReanimatedEasing.sin),
        }),
        withTiming(0, {
          duration: 900,
          easing: ReanimatedEasing.inOut(ReanimatedEasing.sin),
        }),
      ),
      -1,
      false,
    );

    return () => {
      cancelAnimation(idleProgress);
    };
  }, [idleProgress, interacted, isVisible, reduceMotion, showAddedState]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity:
      introOpacity.value * interpolate(idleProgress.value, [0, 1], [0.8, 1]),
    transform: [
      {
        scale:
          introScale.value *
          pressScale.value *
          interpolate(idleProgress.value, [0, 1], [0.96, 1.05]),
      },
    ],
  }));

  const handlePressIn = () => {
    pressScale.value = withTiming(reduceMotion ? 1 : 0.94, {
      duration: 70,
      easing: ReanimatedEasing.out(ReanimatedEasing.quad),
    });
  };

  const handlePressOut = () => {
    if (showAddedState) {
      return;
    }
    pressScale.value = withTiming(1, {
      duration: reduceMotion ? 1 : 130,
      easing: ReanimatedEasing.out(ReanimatedEasing.quad),
    });
  };

  const handlePress = () => {
    if (successTimerRef.current) {
      clearTimeout(successTimerRef.current);
    }
    if (Platform.OS !== 'web') {
      Vibration.vibrate(10);
    }
    cancelAnimation(idleProgress);
    idleProgress.value = withTiming(0, {
      duration: 120,
      easing: ReanimatedEasing.out(ReanimatedEasing.quad),
    });
    pressScale.value = withSequence(
      withTiming(reduceMotion ? 1 : 0.94, {
        duration: reduceMotion ? 1 : 70,
        easing: ReanimatedEasing.out(ReanimatedEasing.quad),
      }),
      withSpring(reduceMotion ? 1 : 1.02, {
        damping: 12,
        stiffness: 260,
      }),
      withTiming(1, {
        duration: reduceMotion ? 1 : 140,
        easing: ReanimatedEasing.out(ReanimatedEasing.cubic),
      }),
    );
    setShowAddedState(true);
    onPress();
    successTimerRef.current = setTimeout(() => {
      setShowAddedState(false);
    }, 800);
  };

  return (
    <Reanimated.View style={animatedStyle}>
      <ReanimatedPressable
        accessibilityLabel={`${showAddedState ? 'Added' : label} combo`}
        onPress={handlePress}
        onPressIn={handlePressIn}
        onPressOut={handlePressOut}
        style={styles.upsellCarouselButton}
      >
        {showAddedState ? (
          <View style={styles.upsellCarouselButtonSuccessRow}>
            <Icon color={theme.colors.white} name="checkmark" size={14} />
            <Text style={styles.upsellCarouselButtonText}>Added</Text>
          </View>
        ) : (
          <Text style={styles.upsellCarouselButtonText}>{label}</Text>
        )}
      </ReanimatedPressable>
    </Reanimated.View>
  );
});
