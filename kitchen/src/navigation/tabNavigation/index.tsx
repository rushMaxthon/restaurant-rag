import React from 'react';
import { StyleSheet } from 'react-native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';

import BoardScreen from '@screens/board';
import MenuScreen from '@screens/menu';
import SettingsScreen from '@screens/settings';
import { MainTabParamList } from '@navigation/hooks/useNavigation';
import { Icon, type IconName } from '@components/Icon';
import { useTheme } from '@/theme';

const Tab = createBottomTabNavigator<MainTabParamList>();

const TAB_ICONS: Record<
  keyof MainTabParamList,
  { active: IconName; idle: IconName }
> = {
  BoardScreen: { active: 'home', idle: 'home-outline' },
  MenuScreen: { active: 'fast-food', idle: 'fast-food-outline' },
  SettingsScreen: { active: 'settings', idle: 'settings-outline' },
};

// Built once per tab at module level, not inside screenOptions, so React
// never sees a new icon component type on a re-render.
const tabIcon =
  (name: keyof MainTabParamList) =>
  ({ focused, color }: { focused: boolean; color: string }) =>
    (
      <Icon
        name={focused ? TAB_ICONS[name].active : TAB_ICONS[name].idle}
        size={26}
        color={color}
      />
    );

const ICONS: Record<keyof MainTabParamList, ReturnType<typeof tabIcon>> = {
  BoardScreen: tabIcon('BoardScreen'),
  MenuScreen: tabIcon('MenuScreen'),
  SettingsScreen: tabIcon('SettingsScreen'),
};

// Home (the board), Menu (stock) and Settings. Tabs keep each other mounted, so switching
// to Settings never stops the board polling or announcing the next order —
// the same reason Completed orders is pushed over the board, not swapped in.
const TabNavigation = () => {
  const { colors } = useTheme();

  return (
    <Tab.Navigator
      initialRouteName="BoardScreen"
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarStyle: [
          styles.bar,
          { backgroundColor: colors.surface, borderTopColor: colors.border },
        ],
        tabBarLabelStyle: styles.label,
        tabBarItemStyle: styles.item,
        tabBarButtonTestID: `tab-${route.name}`,
        tabBarIcon: ICONS[route.name],
      })}
    >
      <Tab.Screen
        name="BoardScreen"
        component={BoardScreen}
        options={{ title: 'Home' }}
      />
      <Tab.Screen
        name="MenuScreen"
        component={MenuScreen}
        options={{ title: 'Menu' }}
      />
      <Tab.Screen
        name="SettingsScreen"
        component={SettingsScreen}
        options={{ title: 'Settings' }}
      />
    </Tab.Navigator>
  );
};

const styles = StyleSheet.create({
  // Taller than the platform default: tapped with wet or gloved hands.
  bar: { borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 6 },
  item: { minHeight: 52 },
  label: { fontSize: 13, fontWeight: '700' },
});

export default TabNavigation;
