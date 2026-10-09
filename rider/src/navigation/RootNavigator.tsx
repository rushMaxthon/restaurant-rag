import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { useNavigation, useNavigationState } from '@react-navigation/native';
import {
  createNativeStackNavigator,
  type NativeStackNavigationProp,
} from '@react-navigation/native-stack';

import { ComponentGalleryScreen } from '@screens/dev/ComponentGalleryScreen';
import { LoginScreen } from '@screens/auth/LoginScreen';
import { EarningsScreen } from '@screens/earnings/EarningsScreen';
import { HistoryScreen } from '@screens/history/HistoryScreen';
import { TripDetailScreen } from '@screens/history/TripDetailScreen';
import { HomeScreen } from '@screens/home/HomeScreen';
import { OfferScreen } from '@screens/offer/OfferScreen';
import { OrdersScreen } from '@screens/orders/OrdersScreen';
import { PushRouter } from '@components/PushRouter';
import { withBoundary } from '@components/ErrorBoundary';
import { ApplicationReviewScreen } from '@screens/onboarding/ApplicationReviewScreen';
import { ApplicationStepScreen } from '@screens/onboarding/ApplicationStepScreen';
import { IntroScreen } from '@screens/onboarding/IntroScreen';
import { OnboardingHomeScreen } from '@screens/onboarding/OnboardingHomeScreen';
import { PermissionsScreen } from '@screens/onboarding/PermissionsScreen';
import { ProfileScreen } from '@screens/profile/ProfileScreen';
import { SignupAccountScreen } from '@screens/signup/SignupAccountScreen';
import { SignupCodeScreen } from '@screens/signup/SignupCodeScreen';
import { SignupPhoneScreen } from '@screens/signup/SignupPhoneScreen';
import { DeliveredScreen } from '@screens/trip/DeliveredScreen';
import { TripScreen } from '@screens/trip/TripScreen';
import { ConnectionBanner } from '@components/ConnectionBanner';
import { ShiftKeeper } from '@components/ShiftKeeper';
import { GuideProvider, useGuide } from '@/guide/GuideProvider';
import { Spotlight } from '@/guide/Spotlight';
import { useTheme } from '@theme/ThemeProvider';
import { loadOnboarding } from '@/services/onboardingMemory';
import { ApplicationProvider } from '@/store/ApplicationProvider';
import { RiderProvider, useRider } from '@/store/RiderProvider';
import { useSession } from '@/store/SessionProvider';
import type { RiderOnboarding } from '@/types/api';
import { gateFor } from '@utils/onboarding';
import { TabBar } from './TabBar';
import type { RootStackParamList, TabParamList } from './types';

const Stack = createNativeStackNavigator<RootStackParamList>();

// Wrapped once, at module level: a new component per render would remount
// every screen.
const Bounded = {
  ComponentGalleryScreen: withBoundary(ComponentGalleryScreen),
  LoginScreen: withBoundary(LoginScreen),
  EarningsScreen: withBoundary(EarningsScreen),
  HistoryScreen: withBoundary(HistoryScreen),
  HomeScreen: withBoundary(HomeScreen),
  IntroScreen: withBoundary(IntroScreen),
  TripDetailScreen: withBoundary(TripDetailScreen),
  OfferScreen: withBoundary(OfferScreen),
  OrdersScreen: withBoundary(OrdersScreen),
  PermissionsScreen: withBoundary(PermissionsScreen),
  ProfileScreen: withBoundary(ProfileScreen),
  DeliveredScreen: withBoundary(DeliveredScreen),
  TripScreen: withBoundary(TripScreen),
  SignupPhoneScreen: withBoundary(SignupPhoneScreen),
  SignupCodeScreen: withBoundary(SignupCodeScreen),
  SignupAccountScreen: withBoundary(SignupAccountScreen),
  OnboardingHomeScreen: withBoundary(OnboardingHomeScreen),
  ApplicationStepScreen: withBoundary(ApplicationStepScreen),
  ApplicationReviewScreen: withBoundary(ApplicationReviewScreen),
};
const Tabs = createBottomTabNavigator<TabParamList>();

function MainTabs() {
  return (
    <Tabs.Navigator
      tabBar={props => <TabBar {...props} />}
      screenOptions={{ headerShown: false, animation: 'shift' }}
    >
      <Tabs.Screen name="Home" component={Bounded.HomeScreen} />
      <Tabs.Screen name="Orders" component={Bounded.OrdersScreen} />
      <Tabs.Screen name="Earnings" component={Bounded.EarningsScreen} />
      <Tabs.Screen name="History" component={Bounded.HistoryScreen} />
      <Tabs.Screen name="Profile" component={Bounded.ProfileScreen} />
    </Tabs.Navigator>
  );
}

/**
 * Opens the full-screen order alert when a NEW offer arrives, from wherever
 * the rider is - except the screens where it would interrupt a delivery.
 */
function OfferWatcher() {
  const nav = useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const { offer } = useRider();
  const shown = useRef<string | null>(null);
  const route = useNavigationState(state => state?.routes[state.index]?.name);

  useEffect(() => {
    if (!offer || shown.current === offer.id) return;
    if (route === 'Offer' || route === 'Trip' || route === 'Delivered') return;
    shown.current = offer.id;
    nav.navigate('Offer');
  }, [offer, route, nav]);

  return null;
}

function SignedIn() {
  return (
    <RiderProvider>
      <SignedInGate />
    </RiderProvider>
  );
}

/**
 * Tabs, or the application. A rider who signed up themselves is PENDING
 * until an admin approves them, and sees only their application: no shift
 * keeper, no location, no offers or Orders board - the server would refuse
 * all of it, and a "Go online" that can only fail is worse than none. The
 * moment /rider/me says APPROVED (a push, the socket, a pull to refresh)
 * this swaps to the tabs, and SignedInStack opens on the first-time intro.
 */
function SignedInGate() {
  const { me, loading } = useRider();
  const { colors } = useTheme();
  // undefined: not read yet. The read is one AsyncStorage get.
  const [remembered, setRemembered] = useState<RiderOnboarding | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    loadOnboarding().then(value => alive && setRemembered(value));
    return () => {
      alive = false;
    };
  }, []);
  const gate = remembered === undefined ? 'wait' : gateFor(me, remembered, loading);

  if (gate === 'wait')
    return <View style={[styles.fill, { backgroundColor: colors.bg }]} />;
  if (gate === 'onboarding') {
    return (
      <ApplicationProvider>
        <PushRouter />
        <OnboardingStack />
        <ConnectionBanner />
      </ApplicationProvider>
    );
  }
  return (
    <ShiftKeeper>
      <GuideProvider>
        <PushRouter />
        <SignedInStack />
        <ConnectionBanner />
        {/* Last, so a tip sits above every screen and the tab bar. */}
        <Spotlight />
      </GuideProvider>
    </ShiftKeeper>
  );
}

function OnboardingStack() {
  return (
    <Stack.Navigator
      initialRouteName="OnboardingHome"
      screenOptions={{ headerShown: false, animation: 'slide_from_right' }}
    >
      <Stack.Screen name="OnboardingHome" component={Bounded.OnboardingHomeScreen} />
      <Stack.Screen name="ApplicationStep" component={Bounded.ApplicationStepScreen} />
      <Stack.Screen name="ApplicationReview" component={Bounded.ApplicationReviewScreen} />
    </Stack.Navigator>
  );
}

/**
 * The first screen after sign-in is the intro, once: the seen-flags must be
 * read before the navigator mounts, because its initial route cannot change
 * afterwards. The wait is one storage read, drawn as the background colour.
 */
function SignedInStack() {
  const { loaded, seen } = useGuide();
  const { loading, me, trip } = useRider();
  const { colors } = useTheme();
  // First run only: wait for /me as well, so a rider who is on shift or
  // carrying an order (an app update, a reinstall) goes straight to it and
  // keeps hearing offers, instead of being walked through the intro.
  if (!loaded || (!seen.intro && loading))
    return <View style={[styles.fill, { backgroundColor: colors.bg }]} />;
  const intro =
    !seen.intro && !trip && (me === null || me.status === 'OFFLINE');
  return (
    <Stack.Navigator
      initialRouteName={intro ? 'Intro' : 'Main'}
      screenOptions={{ headerShown: false, animation: 'slide_from_right' }}
    >
      <Stack.Screen name="Main" component={MainTabsWithWatcher} />
      <Stack.Screen
        name="Intro"
        component={Bounded.IntroScreen}
        options={{ animation: 'fade' }}
      />
      <Stack.Screen name="Trip" component={Bounded.TripScreen} />
      <Stack.Screen name="TripDetail" component={Bounded.TripDetailScreen} />
      <Stack.Screen
        name="Permissions"
        component={Bounded.PermissionsScreen}
        options={{ animation: 'slide_from_bottom' }}
      />
      <Stack.Screen
        name="Offer"
        component={Bounded.OfferScreen}
        options={{
          presentation: 'fullScreenModal',
          animation: 'slide_from_bottom',
          gestureEnabled: false,
        }}
      />
      <Stack.Screen
        name="Delivered"
        component={Bounded.DeliveredScreen}
        options={{ animation: 'fade', gestureEnabled: false }}
      />
      <Stack.Screen name="Gallery" component={Bounded.ComponentGalleryScreen} />
    </Stack.Navigator>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });

function MainTabsWithWatcher() {
  return (
    <>
      <MainTabs />
      <OfferWatcher />
    </>
  );
}

export function RootNavigator() {
  const { state } = useSession();
  if (state.status === 'signedIn') return <SignedIn />;
  return (
    <Stack.Navigator screenOptions={{ headerShown: false, animation: 'fade' }}>
      <Stack.Screen name="Login" component={Bounded.LoginScreen} />
      <Stack.Screen
        name="SignupPhone"
        component={Bounded.SignupPhoneScreen}
        options={{ animation: 'slide_from_right' }}
      />
      <Stack.Screen
        name="SignupCode"
        component={Bounded.SignupCodeScreen}
        options={{ animation: 'slide_from_right' }}
      />
      <Stack.Screen
        name="SignupAccount"
        component={Bounded.SignupAccountScreen}
        options={{ animation: 'slide_from_right' }}
      />
    </Stack.Navigator>
  );
}
