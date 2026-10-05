import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import LoginScreen from '@screens/auth/login';
import BoardScreen from '@screens/board';
import OrderDetailScreen from '@screens/orders/orderDetail';
import OrderHistoryScreen from '@screens/orders/orderHistory';
import SettingsScreen from '@screens/settings';
import { RootStackParamList } from '@navigation/hooks/useNavigation';
import { useSessionState } from '@hooks/useAppStore';
import { AppSplashScreen } from '@components/AppSplashScreen';

const Stack = createNativeStackNavigator<RootStackParamList>();

// The signed-out and signed-in screens are never registered together, so
// signing out drops the whole board stack and the back gesture cannot lead a
// signed-out tablet back onto an order.
//
// Completed orders is pushed ON TOP of the board rather than replacing it:
// a native stack keeps the board mounted underneath, so it keeps polling and
// still announces the next ticket while somebody looks something up.
const StackNavigation = () => {
  const { hydrated, session } = useSessionState();

  if (!hydrated) {
    return <AppSplashScreen />;
  }

  return (
    <Stack.Navigator
      initialRouteName={session ? 'BoardScreen' : 'LoginScreen'}
      screenOptions={{ headerShown: false }}>
      {session ? (
        <>
          <Stack.Screen name="BoardScreen" component={BoardScreen} />
          <Stack.Screen name="OrderDetailScreen" component={OrderDetailScreen} />
          <Stack.Screen name="OrderHistoryScreen" component={OrderHistoryScreen} />
          <Stack.Screen name="SettingsScreen" component={SettingsScreen} />
        </>
      ) : (
        <Stack.Screen name="LoginScreen" component={LoginScreen} />
      )}
    </Stack.Navigator>
  );
};

export default StackNavigation;
