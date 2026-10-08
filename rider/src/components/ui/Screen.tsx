import React from 'react';
import { RefreshControl, ScrollView, StyleSheet, View, type ViewStyle } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';

/**
 * Every screen's outer frame: the theme background, safe-area padding and a
 * consistent 16 dp gutter. `scroll` adds pull-to-refresh when given `onRefresh`.
 * `tabbed` leaves room for the floating tab bar.
 */
export function Screen({
  children,
  scroll = false,
  refreshing = false,
  onRefresh,
  tabbed = false,
  style,
  contentStyle,
}: {
  children: React.ReactNode;
  scroll?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  tabbed?: boolean;
  style?: ViewStyle;
  contentStyle?: ViewStyle;
}) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const padding = {
    paddingTop: insets.top + space.md,
    paddingBottom: (tabbed ? 96 : insets.bottom) + space.xl,
  };
  if (!scroll) {
    return <View style={[styles.root, { backgroundColor: colors.bg }, padding, styles.gutter, style]}>{children}</View>;
  }
  return (
    <ScrollView
      style={[styles.root, { backgroundColor: colors.bg }, style]}
      contentContainerStyle={[padding, styles.gutter, contentStyle]}
      showsVerticalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
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
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  gutter: { paddingHorizontal: space.lg },
});
