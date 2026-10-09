import React, { useEffect, useState } from 'react';
import {
  BackHandler,
  Pressable,
  StyleSheet,
  View,
  useWindowDimensions,
} from 'react-native';
import Animated, { FadeIn, FadeOut } from 'react-native-reanimated';
import Svg, { Defs, Mask, Rect } from 'react-native-svg';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';
import { useGuide } from './GuideProvider';
import { placeTooltip, RING_PAD } from './placement';

/**
 * The spotlight: everything dark except the one control the tip is about,
 * and a card beside it. Rendered once, above the whole navigator.
 *
 * The dark area swallows taps and does nothing with them - a rider holding
 * the phone one-handed on a bike stand should not be able to dismiss a tip
 * by brushing the screen. Only Next, Done and Skip move it on.
 */
export function Spotlight() {
  const { active, next, skip } = useGuide();
  const { colors } = useTheme();
  const window = useWindowDimensions();
  const [cardHeight, setCardHeight] = useState(0);

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
  const { step, rect } = current;
  const hole = {
    x: rect.x - RING_PAD,
    y: rect.y - RING_PAD,
    width: rect.width + RING_PAD * 2,
    height: rect.height + RING_PAD * 2,
  };
  const place = placeTooltip(hole, window, { height: cardHeight || 150 });
  const last = active.index + 1 >= active.steps.length;

  return (
    <Animated.View
      key={`${active.id}-${active.index}`}
      entering={FadeIn.duration(220)}
      exiting={FadeOut.duration(160)}
      style={StyleSheet.absoluteFill}
      accessibilityViewIsModal
    >
      <Pressable
        style={StyleSheet.absoluteFill}
        accessibilityLabel="Tip overlay"
      />
      <Svg
        pointerEvents="none"
        width={window.width}
        height={window.height}
        style={StyleSheet.absoluteFill}
      >
        <Defs>
          <Mask id="hole">
            <Rect
              x={0}
              y={0}
              width={window.width}
              height={window.height}
              fill="#fff"
            />
            <Rect
              x={hole.x}
              y={hole.y}
              width={hole.width}
              height={hole.height}
              rx={radius.lg}
              fill="#000"
            />
          </Mask>
        </Defs>
        <Rect
          x={0}
          y={0}
          width={window.width}
          height={window.height}
          fill={colors.overlay}
          mask="url(#hole)"
        />
        <Rect
          x={hole.x}
          y={hole.y}
          width={hole.width}
          height={hole.height}
          rx={radius.lg}
          fill="none"
          stroke={colors.primary}
          strokeWidth={2}
        />
      </Svg>

      <View
        onLayout={e => setCardHeight(e.nativeEvent.layout.height)}
        style={[
          styles.card,
          {
            top: place.top,
            left: place.left,
            width: place.width,
            backgroundColor: colors.elevated,
            borderColor: colors.border,
            opacity: cardHeight ? 1 : 0,
          },
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
            {step.title}
          </AppText>
          <AppText variant="micro" tone="muted">
            {active.index + 1} OF {active.steps.length}
          </AppText>
        </View>
        <AppText tone="muted">{step.body}</AppText>
        <View style={styles.actions}>
          <Button kind="ghost" size="md" label="Skip" onPress={skip} />
          <Button
            size="md"
            label={last ? 'Done' : 'Next'}
            icon={last ? 'checkmark' : 'arrow-forward'}
            onPress={next}
            style={styles.next}
            testID="tip-next"
          />
        </View>
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
