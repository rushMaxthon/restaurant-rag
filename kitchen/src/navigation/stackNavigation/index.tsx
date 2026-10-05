import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import LoginScreen from '@screens/auth/login';
import OrderDetailScreen from '@screens/orders/orderDetail';
import OrderHistoryScreen from '@screens/orders/orderHistory';
import TabNavigation from '@navigation/tabNavigation';
import { RootStackParamList } from '@navigation/hooks/useNavigation';
import { useSessionState } from '@hooks/useAppStore';
import { AppSplashScreen } from '@components/AppSplashScreen';

const Stack = createNativeStackNavigator<RootStackParamList>();

// The signed-out and signed-in screens are never registered together, so
// signing out drops the whole board stack and the back gesture cannot lead a
// signed-out tablet back onto an order.
//
// Signed in, the tabs (Home, Settings) are the base of the stack, and Order
// details and Completed orders are pushed full-screen over them. The tabs
// stay mounted underneath, so the board keeps polling and still announces
// the next ticket while somebody looks something up.
const StackNavigation = () => {
  const { hydrated, session } = useSessionState();

  if (!hydrated) {
    return <AppSplashScreen />;
  }

  return (
    <Stack.Navigator
      initialRouteName={session ? 'MainTabs' : 'LoginScreen'}
      screenOptions={{ headerShown: false }}>
      {session ? (
        <>
          <Stack.Screen name="MainTabs" component={TabNavigation} />
          <Stack.Screen name="OrderDetailScreen" component={OrderDetailScreen} />
          <Stack.Screen name="OrderHistoryScreen" component={OrderHistoryScreen} />
        </>
      ) : (
        <Stack.Screen name="LoginScreen" component={LoginScreen} />
      )}
    </Stack.Navigator>
  );
};

export default StackNavigation;
