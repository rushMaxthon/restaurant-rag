import React, { useEffect, useRef } from 'react';
import {
  AccessibilityInfo,
  Animated,
  Easing,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { formatCurrency } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import { getOfferPalette } from '@/components/offers/offerPalette';
import type { PersonalizedOfferCard } from '@/types/app';

interface OfferBannerCardProps {
  offer: PersonalizedOfferCard;
  onPress: (offer: PersonalizedOfferCard) => void;
}

function formatValidityLabel(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
  }).format(date);
}

function OfferBannerCardComponent({
  offer,
  onPress,
}: OfferBannerCardProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const palette = getOfferPalette(offer, theme.mode);

  // --- Animation values -----------------------------------------------
  const mountProgress = useRef(new Animated.Value(0)).current;
  const pressScale = useRef(new Animated.Value(1)).current;
  const shimmerProgress = useRef(new Animated.Value(0)).current;
  const glowPulse = useRef(new Animated.Value(0)).current;
  const arrowNudge = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    let isMounted = true;
    const loops: Animated.CompositeAnimation[] = [];

    const start = (reduceMotion: boolean) => {
      if (!isMounted) return;

      // Entrance: fade + pop + slight rise. Always runs, but is instant
      // (no perceptible motion) when the system asks for reduced motion.
      Animated.timing(mountProgress, {
        toValue: 1,
        duration: reduceMotion ? 1 : 480,
        easing: Easing.out(Easing.exp),
        useNativeDriver: true,
      }).start();

      if (reduceMotion) {
        return;
      }

      const shimmerLoop = Animated.loop(
        Animated.sequence([
          Animated.delay(1500),
          Animated.timing(shimmerProgress, {
            toValue: 1,
            duration: 1100,
            easing: Easing.inOut(Easing.quad),
            useNativeDriver: true,
          }),
          Animated.timing(shimmerProgress, {
            toValue: 0,
            duration: 0,
            useNativeDriver: true,
          }),
        ]),
      );

      const glowLoop = Animated.loop(
        Animated.sequence([
          Animated.timing(glowPulse, {
            toValue: 1,
            duration: 1600,
            easing: Easing.inOut(Easing.sin),
            useNativeDriver: true,
          }),
          Animated.timing(glowPulse, {
            toValue: 0,
            duration: 1600,
            easing: Easing.inOut(Easing.sin),
            useNativeDriver: true,
          }),
        ]),
      );

      const arrowLoop = Animated.loop(
        Animated.sequence([
          Animated.delay(900),
          Animated.timing(arrowNudge, {
            toValue: 1,
            duration: 600,
            easing: Easing.inOut(Easing.quad),
            useNativeDriver: true,
          }),
          Animated.timing(arrowNudge, {
            toValue: 0,
            duration: 600,
            easing: Easing.inOut(Easing.quad),
            useNativeDriver: true,
          }),
        ]),
      );

      loops.push(shimmerLoop, glowLoop, arrowLoop);
      shimmerLoop.start();
      glowLoop.start();
      arrowLoop.start();
    };

    AccessibilityInfo.isReduceMotionEnabled
      ? AccessibilityInfo.isReduceMotionEnabled().then(start)
      : start(false);

    return () => {
      isMounted = false;
      loops.forEach(loop => loop.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handlePressIn = () => {
    Animated.spring(pressScale, {
      toValue: 0.965,
      speed: 30,
      bounciness: 6,
      useNativeDriver: true,
    }).start();
  };

  const handlePressOut = () => {
    Animated.spring(pressScale, {
      toValue: 1,
      speed: 20,
      bounciness: 8,
      useNativeDriver: true,
    }).start();
  };

  const iconName =
    offer.discount_type === 'FREE_DELIVERY'
      ? 'bicycle'
      : offer.discount_type === 'FLAT'
      ? 'cash'
      : 'pricetag';
  const headline = offer.discount_label ?? offer.badge;
  const validityLabel = formatValidityLabel(offer.expires_at);
  const metaLabel =
    Number(offer.minimum_order_amount) > 0
      ? `Min ${formatCurrency(offer.minimum_order_amount)}`
      : validityLabel
      ? `Valid till ${validityLabel}`
      : offer.restaurant_name;
  const supportingLabel =
    metaLabel === offer.restaurant_name ? offer.subtitle ?? null : metaLabel;

  // --- Derived animated styles ------------------------------------------
  const mountScale = mountProgress.interpolate({
    inputRange: [0, 1],
    outputRange: [0.92, 1],
  });
  const mountTranslateY = mountProgress.interpolate({
    inputRange: [0, 1],
    outputRange: [16, 0],
  });
  const shimmerTranslateX = shimmerProgress.interpolate({
    inputRange: [0, 1],
    outputRange: [0, 420],
  });
  const glowScale = glowPulse.interpolate({
    inputRange: [0, 1],
    outputRange: [1, 1.16],
  });
  const glowOpacity = glowPulse.interpolate({
    inputRange: [0, 1],
    outputRange: [0.55, 1],
  });
  const arrowTranslateX = arrowNudge.interpolate({
    inputRange: [0, 1],
    outputRange: [0, 4],
  });

  return (
    <Animated.View
      style={{
        opacity: mountProgress,
        transform: [
          { scale: Animated.multiply(mountScale, pressScale) },
          { translateY: mountTranslateY },
        ],
      }}
    >
      <Pressable
        onPress={() => onPress(offer)}
        onPressIn={handlePressIn}
        onPressOut={handlePressOut}
        style={[styles.card, { backgroundColor: palette.surface }]}
      >
        <Animated.View
          style={[
            styles.glow,
            {
              backgroundColor: palette.glow,
              opacity: glowOpacity,
              transform: [{ scale: glowScale }],
            },
          ]}
        />
        <View
          style={[
            styles.shape,
            styles.shapeOne,
            { backgroundColor: palette.shapePrimary },
          ]}
        />
        <View
          style={[
            styles.shape,
            styles.shapeTwo,
            { backgroundColor: palette.shapeSecondary },
          ]}
        />
        <Animated.View
          pointerEvents="none"
          style={[
            styles.shimmer,
            {
              transform: [
                { rotate: '18deg' },
                { translateX: shimmerTranslateX },
              ],
            },
          ]}
        />

        <View style={styles.topRow}>
          <View
            style={[styles.badge, { backgroundColor: palette.badgeSurface }]}
          >
            <Text style={[styles.badgeText, { color: palette.accent }]}>
              {headline}
            </Text>
          </View>
          <View
            style={[styles.iconWrap, { backgroundColor: palette.iconSurface }]}
          >
            <Icon color={palette.iconText} name={iconName} size={15} />
          </View>
        </View>

        <View style={styles.copy}>
          <Text numberOfLines={2} style={styles.title}>
            {offer.title}
          </Text>
          <Text numberOfLines={1} style={styles.description}>
            {offer.restaurant_name}
          </Text>

          <View style={styles.footer}>
            <View
              style={[styles.ctaRow, { backgroundColor: palette.ctaSurface }]}
            >
              <Text style={[styles.cta, { color: palette.ctaText }]}>
                {offer.cta_label}
              </Text>
              <Animated.View
                style={{ transform: [{ translateX: arrowTranslateX }] }}
              >
                <Icon color={palette.ctaText} name="arrow-forward" size={13} />
              </Animated.View>
            </View>
            {supportingLabel ? (
              <View style={styles.metaChip}>
                <Text numberOfLines={1} style={styles.metaChipText}>
                  {supportingLabel}
                </Text>
              </View>
            ) : null}
          </View>
        </View>
      </Pressable>
    </Animated.View>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    card: {
      width: 260,
      minHeight: 110,
      borderRadius: 15,
      padding: 10,
      marginRight: 12,
      gap: 7,
      overflow: 'hidden',
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.07,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 18,
      elevation: 3,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark'
          ? theme.colors.border
          : 'rgba(255, 255, 255, 0.56)',
    },
    glow: {
      position: 'absolute',
      width: 86,
      height: 86,
      borderRadius: 43,
      top: -26,
      right: -12,
    },
    shape: {
      position: 'absolute',
      borderRadius: 999,
    },
    shapeOne: {
      width: 76,
      height: 76,
      right: -20,
      top: 12,
    },
    shapeTwo: {
      width: 46,
      height: 46,
      left: -14,
      bottom: -16,
    },
    shimmer: {
      position: 'absolute',
      top: -60,
      bottom: -60,
      left: -90,
      width: 70,
      backgroundColor:
        theme.mode === 'dark'
          ? 'rgba(255, 255, 255, 0.10)'
          : 'rgba(255, 255, 255, 0.32)',
    },
    topRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    badge: {
      minHeight: 21,
      borderRadius: 11,
      paddingHorizontal: 7,
      alignItems: 'center',
      justifyContent: 'center',
    },
    badgeText: {
      fontSize: 10.5,
      fontWeight: '800',
      letterSpacing: -0.1,
    },
    iconWrap: {
      width: 22,
      height: 22,
      borderRadius: 11,
      alignItems: 'center',
      justifyContent: 'center',
    },
    copy: {
      flex: 1,
      gap: 1,
      marginTop: 6,
    },
    title: {
      color: theme.colors.text,
      fontSize: 15.5,
      fontWeight: '800',
      lineHeight: 17.5,
    },
    description: {
      color: theme.colors.secondaryText,
      fontSize: 10.8,
      lineHeight: 13,
      marginTop: 1,
    },
    footer: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8,
      marginTop: 'auto',
      paddingTop: 7,
    },
    ctaRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      minHeight: 25,
      borderRadius: 13,
      paddingHorizontal: 9,
    },
    metaChip: {
      minHeight: 23,
      maxWidth: 88,
      borderRadius: 11.5,
      paddingHorizontal: 8,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : 'rgba(255, 255, 255, 0.44)',
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark'
          ? theme.colors.border
          : 'rgba(255, 255, 255, 0.48)',
      justifyContent: 'center',
    },
    metaChipText: {
      color: theme.colors.hint,
      fontSize: 9.5,
      lineHeight: 11,
      fontWeight: '800',
    },
    cta: {
      fontWeight: '800',
      fontSize: 10.5,
    },
  });


/**
 * Memoized: these cards sit in lists whose parent re-renders on unrelated
 * state changes, and none of them depend on anything but their props.
 */
export const OfferBannerCard = React.memo(OfferBannerCardComponent);
