import React, { useContext } from 'react';
import { StyleSheet, View } from 'react-native';
import { BottomTabBarHeightContext } from '@react-navigation/bottom-tabs';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '@/theme';

export const ScreenContainer = ({ children }: { children: React.ReactNode }) => {
  const insets = useSafeAreaInsets();
  // Inside a tab the tab bar already sits above the home indicator; padding
  // for it again would leave a dead band between the content and the bar.
  const inTab = useContext(BottomTabBarHeightContext) !== undefined;
  const bottomInset = inTab ? 0 : insets.bottom;
  const { colors } = useTheme();
  return (
    <View
      style={[
        styles.container,
        {
          backgroundColor: colors.background,
          paddingTop: insets.top,
          paddingBottom: bottomInset,
        },
      ]}>
      {children}
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1 },
});
