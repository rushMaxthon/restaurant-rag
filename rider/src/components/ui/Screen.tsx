import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef } from 'react';
import {
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
  type HostInstance,
  type ScrollViewInstance,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useKeyboardHeight } from '@hooks/useKeyboardHeight';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';

/** Room kept below a focused field: its error line and a glimpse of what comes next. */
const REVEAL_MARGIN = 96;

type Reveal = (target?: HostInstance | null) => void;
const RevealContext = createContext<Reveal>(() => {});

/**
 * Scrolls the screen so a field sits clear of the keyboard. Fields call it on
 * focus; outside a scrolling Screen it does nothing.
 */
export function useRevealOnFocus(): Reveal {
  return useContext(RevealContext);
}

/**
 * Every screen's outer frame: the theme background, safe-area padding and a
 * consistent 16 dp gutter. `scroll` adds pull-to-refresh when given `onRefresh`.
 * `tabbed` leaves room for the floating tab bar.
 *
 * A scrolling screen also makes room for the keyboard. The app is
 * edge-to-edge, so Android no longer shrinks the window for it
 * (`adjustResize` does nothing): the scroll view is shortened by the
 * keyboard's height instead, and the focused field is scrolled up until it
 * and the line under it are clear - Android's own ScrollView leaves a field
 * that is half-visible exactly where it is. A screen with its own footer that
 * already rises with the keyboard passes `avoidKeyboard={false}`, or the room
 * is made twice (it still scrolls the field into view).
 */
export function Screen({
  children,
  scroll = false,
  refreshing = false,
  onRefresh,
  tabbed = false,
  style,
  contentStyle,
  avoidKeyboard = true,
}: {
  children: React.ReactNode;
  scroll?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  tabbed?: boolean;
  style?: ViewStyle;
  contentStyle?: ViewStyle;
  avoidKeyboard?: boolean;
}) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const keyboard = useKeyboardHeight();
  const scrollRef = useRef<ScrollViewInstance>(null);
  const offset = useRef(0);
  // iOS screens wrap themselves in KeyboardAvoidingView, which works there.
  const lift = scroll && avoidKeyboard && Platform.OS === 'android' ? keyboard : 0;

  const reveal = useCallback<Reveal>(target => {
    const field = target ?? TextInput.State.currentlyFocusedInput();
    const frame = scrollRef.current?.getNativeScrollRef();
    if (!field || !frame) return;
    // A frame later: the lift has to be laid out before anything is measured.
    requestAnimationFrame(() => {
      frame.measureInWindow((_x, top, _w, height) => {
        field.measureInWindow((_fx, fy, _fw, fh) => {
          const bottom = top + height;
          const over = fy + fh + REVEAL_MARGIN - bottom;
          if (over > 0) {
            scrollRef.current?.scrollTo({ y: offset.current + over, animated: true });
          } else if (fy < top + space.md) {
            scrollRef.current?.scrollTo({
              y: Math.max(0, offset.current - (top + space.md - fy)),
              animated: true,
            });
          }
        });
      });
    });
  }, []);

  useEffect(() => {
    if (scroll && keyboard > 0) reveal();
  }, [scroll, keyboard, reveal]);

  const padding = {
    paddingTop: insets.top + space.md,
    paddingBottom: (tabbed ? 96 : insets.bottom) + space.xl,
  };
  const value = useMemo(() => (scroll ? reveal : () => {}), [scroll, reveal]);

  if (!scroll) {
    return <View style={[styles.root, { backgroundColor: colors.bg }, padding, styles.gutter, style]}>{children}</View>;
  }
  return (
    <RevealContext.Provider value={value}>
      <ScrollView
        ref={scrollRef}
        style={[styles.root, { backgroundColor: colors.bg }, style, lift > 0 && { marginBottom: lift }]}
        contentContainerStyle={[padding, styles.gutter, contentStyle]}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        scrollEventThrottle={32}
        onScroll={e => {
          offset.current = e.nativeEvent.contentOffset.y;
        }}
        refreshControl={
          onRefresh ? (
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={colors.primary}
              colors={[colors.primary]}
              progressBackgroundColor={colors.surface}
            />
          ) : undefined
        }
      >
        {children}
      </ScrollView>
      {/* Scrolled content slides under this, not under the clock and battery. */}
      <View
        pointerEvents="none"
        style={[styles.scrim, { height: insets.top, backgroundColor: colors.bg }]}
      />
    </RevealContext.Provider>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  gutter: { paddingHorizontal: space.lg },
  scrim: { position: 'absolute', top: 0, left: 0, right: 0, opacity: 0.94 },
});
