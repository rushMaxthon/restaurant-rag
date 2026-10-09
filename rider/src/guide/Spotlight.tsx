import React, { useEffect, useState } from 'react';
import {
  BackHandler,
  Pressable,
  StyleSheet,
  View,
  useWindowDimensions,
} from 'react-native';
import Animated, {
  FadeIn,
  FadeInDown,
  FadeOut,
  useAnimatedProps,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';
import Svg, { Defs, Mask, Rect } from 'react-native-svg';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { useI18n } from '@/i18n';
import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space } from '@theme/tokens';
import { useGuide } from './GuideProvider';
import { placeTooltip, RING_PAD, type Rect as Box } from './placement';

const AnimatedRect = Animated.createAnimatedComponent(Rect);

/**
 * The spotlight: everything dark except the one control the tip is about,
 * and a card beside it. Rendered once, above the whole navigator.
 *
 * The dark area swallows taps and does nothing with them - a rider holding
 * the phone one-handed on a bike stand should not be able to dismiss a tip
 * by brushing the screen. Only Next, Done, Skip and the back button move it
 * on. The overlay fades in once per tour; between steps the hole springs to
 * the next control and the card is re-placed, so nothing flashes.
 */
export function Spotlight() {
  const { active, next, skip } = useGuide();
  const { colors } = useTheme();
  const { t } = useI18n();
  const window = useWindowDimensions();

  // The phone's back button means "not now": it skips the tour rather than
  // popping the screen out from under it.
  const up = active !== null;
  useEffect(() => {
    if (!up) return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      skip();
      return true;
    });
    return () => sub.remove();
  }, [up, skip]);

  if (!active) return null;
  const current = active.steps[active.index];
  if (!current) return null;
  const hole: Box = {
    x: current.rect.x - RING_PAD,
    y: current.rect.y - RING_PAD,
    width: current.rect.width + RING_PAD * 2,
    height: current.rect.height + RING_PAD * 2,
  };

  return (
    <Animated.View
      key={active.id}
      entering={FadeIn.duration(220)}
      exiting={FadeOut.duration(160)}
      style={StyleSheet.absoluteFill}
      accessibilityViewIsModal
    >
      <Pressable
        style={StyleSheet.absoluteFill}
        accessible={false}
        importantForAccessibility="no"
      />
      <Hole
        hole={hole}
        width={window.width}
        height={window.height}
        overlay={colors.overlay}
        ring={colors.primary}
      />
      <Tip
        key={active.index}
        hole={hole}
        title={t(current.step.titleKey)}
        body={t(current.step.bodyKey)}
        index={active.index}
        count={active.steps.length}
        onNext={next}
        onSkip={skip}
      />
    </Animated.View>
  );
}

/** The mask and the ring: four shared values that spring to each new control. */
function Hole({
  hole,
  width,
  height,
  overlay,
  ring,
}: {
  hole: Box;
  width: number;
  height: number;
  overlay: string;
  ring: string;
}) {
  const x = useSharedValue(hole.x);
  const y = useSharedValue(hole.y);
  const w = useSharedValue(hole.width);
  const h = useSharedValue(hole.height);

  useEffect(() => {
    x.value = withSpring(hole.x, motion.springSoft);
    y.value = withSpring(hole.y, motion.springSoft);
    w.value = withSpring(hole.width, motion.springSoft);
    h.value = withSpring(hole.height, motion.springSoft);
  }, [hole.x, hole.y, hole.width, hole.height, x, y, w, h]);

  const box = useAnimatedProps(() => ({
    x: x.value,
    y: y.value,
    width: w.value,
    height: h.value,
  }));

  return (
    <Svg
      pointerEvents="none"
      width={width}
      height={height}
      style={StyleSheet.absoluteFill}
    >
      <Defs>
        <Mask id="hole">
          <Rect x={0} y={0} width={width} height={height} fill="#fff" />
          <AnimatedRect animatedProps={box} rx={radius.lg} fill="#000" />
        </Mask>
      </Defs>
      <Rect
        x={0}
        y={0}
        width={width}
        height={height}
        fill={overlay}
        mask="url(#hole)"
      />
      <AnimatedRect
        animatedProps={box}
        rx={radius.lg}
        fill="none"
        stroke={ring}
        strokeWidth={2}
      />
    </Svg>
  );
}

/** One step's card. Keyed per step by the caller, so its height is measured fresh each time. */
function Tip({
  hole,
  title,
  body,
  index,
  count,
  onNext,
  onSkip,
}: {
  hole: Box;
  title: string;
  body: string;
  index: number;
  count: number;
  onNext: () => void;
  onSkip: () => void;
}) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const window = useWindowDimensions();
  const [cardHeight, setCardHeight] = useState(0);
  const place = placeTooltip(hole, window, { height: cardHeight || 150 });
  const last = index + 1 >= count;

  return (
    <Animated.View
      entering={FadeInDown.duration(200)}
      onLayout={e => setCardHeight(e.nativeEvent.layout.height)}
      style={[
        styles.card,
        {
          top: place.top,
          left: place.left,
          width: place.width,
          backgroundColor: colors.elevated,
          borderColor: colors.border,
        },
        cardHeight ? null : styles.unmeasured,
      ]}
    >
      <View
        style={[
          styles.arrow,
          place.side === 'below' ? styles.arrowUp : styles.arrowDown,
          {
            left: place.arrowLeft - 8,
            backgroundColor: colors.elevated,
            borderColor: colors.border,
          },
        ]}
      />
      <View style={styles.head}>
        <AppText variant="heading" style={styles.flex}>
          {title}
        </AppText>
        <AppText variant="micro" tone="muted">
          {t('account.guide.stepOf', { n: index + 1, count })}
        </AppText>
      </View>
      <AppText tone="muted">{body}</AppText>
      <View style={styles.actions}>
        <Button
          kind="ghost"
          size="md"
          label={t('common.skip')}
          onPress={onSkip}
        />
        <Button
          size="md"
          label={last ? t('common.done') : t('common.next')}
          icon={last ? 'checkmark' : 'arrow-forward'}
          onPress={onNext}
          style={styles.next}
          testID="tip-next"
        />
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  card: {
    position: 'absolute',
    padding: space.lg,
    gap: space.sm,
    borderRadius: radius.xl,
    borderWidth: 1,
    elevation: 16,
  },
  // Drawn once at a guessed height to be measured; shown where it really fits.
  unmeasured: { opacity: 0 },
  arrow: {
    position: 'absolute',
    width: 16,
    height: 16,
    transform: [{ rotate: '45deg' }],
    borderWidth: 1,
  },
  // Pointing up at a control above the card: only the top-left edges show.
  arrowUp: { top: -8, borderRightWidth: 0, borderBottomWidth: 0 },
  arrowDown: { bottom: -8, borderLeftWidth: 0, borderTopWidth: 0 },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: space.sm },
  actions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: space.sm,
    marginTop: space.xs,
  },
  next: { minWidth: 120 },
});
