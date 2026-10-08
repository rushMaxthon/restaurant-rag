import React, { useEffect, useRef } from 'react';
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
import { HomeScreen } from '@screens/home/HomeScreen';
import { OfferScreen } from '@screens/offer/OfferScreen';
import { OrdersScreen } from '@screens/orders/OrdersScreen';
import { PushRouter } from '@components/PushRouter';
import { PermissionsScreen } from '@screens/onboarding/PermissionsScreen';
import { ProfileScreen } from '@screens/profile/ProfileScreen';
import { DeliveredScreen } from '@screens/trip/DeliveredScreen';
import { TripScreen } from '@screens/trip/TripScreen';
import { ShiftKeeper } from '@components/ShiftKeeper';
import { RiderProvider, useRider } from '@/store/RiderProvider';
import { useSession } from '@/store/SessionProvider';
import { TabBar } from './TabBar';
import type { RootStackParamList, TabParamList } from './types';

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tabs = createBottomTabNavigator<TabParamList>();

function MainTabs() {
  return (
    <Tabs.Navigator
      tabBar={props => <TabBar {...props} />}
      screenOptions={{ headerShown: false, animation: 'shift' }}
    >
      <Tabs.Screen name="Home" component={HomeScreen} />
      <Tabs.Screen name="Orders" component={OrdersScreen} />
      <Tabs.Screen name="Earnings" component={EarningsScreen} />
      <Tabs.Screen name="History" component={HistoryScreen} />
      <Tabs.Screen name="Profile" component={ProfileScreen} />
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
      <ShiftKeeper>
        <PushRouter />
        <Stack.Navigator
          screenOptions={{ headerShown: false, animation: 'slide_from_right' }}
        >
          <Stack.Screen name="Main" component={MainTabsWithWatcher} />
          <Stack.Screen name="Trip" component={TripScreen} />
          <Stack.Screen
            name="Permissions"
            component={PermissionsScreen}
            options={{ animation: 'slide_from_bottom' }}
          />
          <Stack.Screen
            name="Offer"
            component={OfferScreen}
            options={{
              presentation: 'fullScreenModal',
              animation: 'slide_from_bottom',
              gestureEnabled: false,
            }}
          />
          <Stack.Screen
            name="Delivered"
            component={DeliveredScreen}
            options={{ animation: 'fade', gestureEnabled: false }}
          />
          <Stack.Screen name="Gallery" component={ComponentGalleryScreen} />
        </Stack.Navigator>
      </ShiftKeeper>
    </RiderProvider>
  );
}

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
      <Stack.Screen name="Login" component={LoginScreen} />
    </Stack.Navigator>
  );
}
