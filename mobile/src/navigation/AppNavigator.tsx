import React, { useCallback, useState } from 'react';
import { StatusBar, StyleSheet, Text, View } from 'react-native';
import {
  NavigationContainer,
  DefaultTheme,
  DarkTheme,
} from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import Icon from 'react-native-vector-icons/Ionicons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { usePreferences, useSession } from '@hooks/useAppStore';
import { AppOverlays } from '@components/AppOverlays';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import { AppSplashScreen } from '@components/AppSplashScreen';
import { HomeScreen } from '@screens/home/HomeScreen';
import { SearchScreen } from '@screens/search/SearchScreen';
import { OrderListScreen } from '@screens/orders/orderList/OrderListScreen';
import { OrderDetailScreen } from '@screens/orders/orderDetail/OrderDetailScreen';
import { OrderSuccessScreen } from '@screens/orders/orderSuccess/OrderSuccessScreen';
import { ChatScreen } from '@screens/chat/ChatScreen';
import { ProfileScreen } from '@screens/profile/ProfileScreen';
import { RestaurantScreen } from '@screens/restaurant/RestaurantScreen';
import { RestaurantsScreen } from '@screens/restaurant/RestaurantsScreen';
import { MenuItemDetailScreen } from '@screens/menuItem/MenuItemScreen';
import { CartScreen } from '@screens/cart/CartScreen';
import { PaymentScreen } from '@screens/payment/PaymentScreen';
import { FavoritesScreen } from '@screens/favorites/FavoritesScreen';
import { LoginScreen } from '@screens/auth/login/LoginScreen';
import { RegisterScreen } from '@screens/auth/register/RegisterScreen';
import { OtpVerificationScreen } from '@screens/auth/otpVerification/OtpVerificationScreen';
import { ProfileDetailsScreen } from '@screens/profile/details/ProfileDetailsScreen';
import { PreferencesOnboardingScreen } from '@screens/profile/preferences/PreferencesOnboardingScreen';
import { PreferencesScreen } from '@screens/profile/preferences/PreferencesScreen';
import {
  SavedAddressEditorScreen,
  SavedAddressesScreen,
} from '@screens/profile/savedAddresses';
import { LocationSelectScreen } from '@screens/location/locationSelect/LocationSelectScreen';
import { NotificationSettingsScreen } from '@screens/profile/notificationSettings/NotificationSettingsScreen';
import { PrivacyScreen } from '@screens/profile/privacy/PrivacyScreen';
import { AppearanceScreen } from '@screens/profile/appearance/AppearanceScreen';
import { HelpSupportScreen } from '@screens/profile/helpSupport/HelpSupportScreen';
import { PersonalizedPicksScreen } from '@screens/personalizedPicks/PersonalizedPicksScreen';
import { AppHeader } from '@components/AppHeader';
import {
  markNotificationNavigationReady,
  navigationRef,
} from '@/navigation/navigationService';
import type {
  MainTabParamList,
  RootStackParamList,
} from '@/navigation/navigationTypes';
export type {
  AuthRedirectTarget,
  MainTabParamList,
  RootStackParamList,
} from '@/navigation/navigationTypes';

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tab = createBottomTabNavigator<MainTabParamList>();

function MainTabs() {
  const insets = useSafeAreaInsets();
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const tabBarBottomPadding =
    insets.bottom > 0 ? Math.max(insets.bottom - 2, 4) : 6;
  const tabBarHeight = 58 + tabBarBottomPadding;

  return (
    <Tab.Navigator
      safeAreaInsets={{ bottom: 0 }}
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarHideOnKeyboard: true,
        tabBarActiveTintColor: theme.colors.primary,
        tabBarInactiveTintColor: theme.colors.hint,
        tabBarStyle: [
          styles.tabBar,
          {
            height: tabBarHeight,
            paddingBottom: tabBarBottomPadding,
          },
        ],
        tabBarItemStyle: styles.tabBarItem,
        tabBarIconStyle: styles.tabBarIcon,
        tabBarIcon: ({ color, focused }) => {
          const iconName =
            route.name === 'Home'
              ? focused
                ? 'home'
                : 'home-outline'
              : route.name === 'Orders'
              ? focused
                ? 'receipt'
                : 'receipt-outline'
              : route.name === 'Chat'
              ? focused
                ? 'chatbubbles'
                : 'chatbubbles-outline'
              : focused
              ? 'person'
              : 'person-outline';
          return <Icon color={color} name={iconName} size={23} />;
        },
        tabBarLabel: ({ color, focused }) => (
          <Text
            style={[
              styles.tabBarLabel,
              { color },
              focused ? styles.tabBarLabelActive : null,
            ]}
          >
            {route.name}
          </Text>
        ),
      })}
    >
      <Tab.Screen name="Home" component={HomeScreen} />
      <Tab.Screen
        name="Orders"
        component={OrderListScreen}
        options={{ title: 'Orders' }}
      />
      <Tab.Screen name="Chat" component={ChatScreen} />
      <Tab.Screen name="Profile" component={ProfileScreen} />
    </Tab.Navigator>
  );
}

export function AppNavigator(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  // Deliberately narrow: toasts and the cart replacement prompt are rendered
  // by `AppOverlays` so they cannot re-render the navigator tree.
  const { bootstrapped, token } = useSession();
  const { preferencesOnboardingCompleted } = usePreferences();

  // Kept mounted across the whole hand-off and only torn down once the splash
  // has finished fading, so there is never a frame with neither the splash nor
  // the app on screen. `bootstrapped` alone cannot drive this: it flips the
  // instant init finishes, which is when the fade STARTS, not when it ends.
  const [isSplashMounted, setIsSplashMounted] = useState(true);
  const handleSplashHidden = useCallback(() => setIsSplashMounted(false), []);

  return (
    <View style={styles.root}>
      <StatusBar
        barStyle={theme.mode === 'dark' ? 'light-content' : 'dark-content'}
        backgroundColor={theme.colors.background}
      />
      {/* Mounts only once init is done. Rendering the navigator underneath a
          still-opaque splash is deliberate: it gets a frame to lay itself out
          before AppSplashScreen fades and reveals it. */}
      {bootstrapped ? (
        <NavigationContainer
          onReady={markNotificationNavigationReady}
          ref={navigationRef}
          theme={{
            ...(theme.mode === 'dark' ? DarkTheme : DefaultTheme),
            colors: {
              ...(theme.mode === 'dark'
                ? DarkTheme.colors
                : DefaultTheme.colors),
              background: theme.colors.background,
              card: theme.colors.surface,
              border: theme.colors.border,
              text: theme.colors.text,
              primary: theme.colors.primary,
              notification: theme.colors.primary,
            },
          }}
        >
          {preferencesOnboardingCompleted ? (
            <Stack.Navigator
              screenOptions={{
                header: ({ navigation, options, route, back }) => (
                  <AppHeader
                    canGoBack={Boolean(back)}
                    onBack={navigation.goBack}
                    right={options.headerRight?.({ canGoBack: Boolean(back) })}
                    title={
                      typeof options.title === 'string' &&
                      options.title.length > 0
                        ? options.title
                        : route.name
                    }
                  />
                ),
                contentStyle: { backgroundColor: theme.colors.background },
              }}
            >
              <Stack.Screen
                name="MainTabs"
                component={MainTabs}
                options={{ headerShown: false }}
              />
              <Stack.Screen
                name="Restaurant"
                component={RestaurantScreen}
                options={{ headerShown: false }}
              />
              <Stack.Screen
                name="Restaurants"
                component={RestaurantsScreen}
                options={{ title: 'Restaurants' }}
              />
              <Stack.Screen
                name="MenuItemDetail"
                component={MenuItemDetailScreen}
                options={{ title: 'Menu item' }}
              />
              <Stack.Screen
                name="Search"
                component={SearchScreen}
                options={{ headerShown: false }}
              />
              <Stack.Screen
                name="PersonalizedPicks"
                component={PersonalizedPicksScreen}
                options={{ title: 'Personalized Picks' }}
              />
              <Stack.Screen
                name="Favorites"
                component={FavoritesScreen}
                options={{ title: 'Favorites' }}
              />
              <Stack.Screen name="Cart" component={CartScreen} />
              <Stack.Screen
                name="Payment"
                component={PaymentScreen}
                options={{ title: 'Payment' }}
              />
              <Stack.Screen
                name="OrderSuccess"
                component={OrderSuccessScreen}
                options={{ headerShown: false }}
              />
              <Stack.Screen
                name="OrderList"
                component={OrderListScreen}
                options={{ title: 'Order history' }}
              />
              <Stack.Screen
                name="OrderDetail"
                component={OrderDetailScreen}
                options={{ title: 'Order details' }}
              />
              <Stack.Screen
                name="ProfileDetails"
                component={ProfileDetailsScreen}
                options={{ title: 'Profile details' }}
              />
              <Stack.Screen
                name="UserPreferences"
                component={PreferencesScreen}
                options={{ headerShown: false }}
              />
              <Stack.Screen
                name="SavedAddresses"
                component={SavedAddressesScreen}
                options={{ title: 'Saved addresses' }}
              />
              <Stack.Screen
                name="SavedAddressEditor"
                component={SavedAddressEditorScreen}
                options={({ route }) => ({
                  title:
                    route.params.mode === 'edit'
                      ? 'Edit address'
                      : 'Add address',
                })}
              />
              <Stack.Screen
                name="LocationSelect"
                component={LocationSelectScreen}
                options={{
                  headerShown: false,
                  presentation: 'modal',
                }}
              />
              <Stack.Screen
                name="NotificationSettings"
                component={NotificationSettingsScreen}
                options={{ title: 'Notifications' }}
              />
              <Stack.Screen
                name="Privacy"
                component={PrivacyScreen}
                options={{ title: 'Privacy' }}
              />
              <Stack.Screen
                name="Appearance"
                component={AppearanceScreen}
                options={{ title: 'Appearance' }}
              />
              <Stack.Screen
                name="HelpSupport"
                component={HelpSupportScreen}
                options={{ title: 'Help & support' }}
              />
              <Stack.Screen
                name="Login"
                component={LoginScreen}
                options={{
                  title: token ? 'Account Login' : 'Login',
                  presentation: 'modal',
                }}
              />
              <Stack.Screen
                name="Register"
                component={RegisterScreen}
                options={{
                  title: token ? 'Create Account' : 'Register',
                  presentation: 'modal',
                }}
              />
              <Stack.Screen
                name="OtpVerification"
                component={OtpVerificationScreen}
                options={{ title: 'Verify OTP' }}
              />
            </Stack.Navigator>
          ) : (
            <Stack.Navigator
              screenOptions={{
                headerShown: false,
                contentStyle: { backgroundColor: theme.colors.background },
              }}
            >
              <Stack.Screen
                name="PreferencesOnboarding"
                component={PreferencesOnboardingScreen}
              />
            </Stack.Navigator>
          )}
        </NavigationContainer>
      ) : null}
      <AppOverlays />
      {/* Last child so it sits above the navigator, and rendered from the very
          first frame - it is what the native splash hands off to. */}
      {isSplashMounted ? (
        <AppSplashScreen done={bootstrapped} onHidden={handleSplashHidden} />
      ) : null}
    </View>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    root: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    tabBar: {
      backgroundColor: theme.colors.surface,
      borderTopWidth: 1,
      borderTopColor: theme.colors.border,
      paddingTop: 6,
      paddingHorizontal: 0,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.05,
      shadowOffset: { width: 0, height: -3 },
      shadowRadius: 10,
      elevation: 8,
    },
    tabBarItem: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      paddingVertical: 3,
    },
    tabBarLabel: {
      fontSize: 11,
      fontWeight: '600',
      marginTop: 3,
      marginBottom: 0,
      lineHeight: 14,
    },
    tabBarLabelActive: {
      fontWeight: '700',
    },
    tabBarIcon: {
      marginTop: 0,
    },
  });
