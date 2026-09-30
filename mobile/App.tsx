import React from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { AppStoreProvider } from './src/store/AppStore';
import { AppNavigator } from './src/navigation/AppNavigator';
import { AppThemeProvider } from './src/theme';
import { PushNotificationBootstrap } from './src/components/notifications/PushNotificationBootstrap';
import { RealtimeBootstrap } from './src/components/realtime/RealtimeBootstrap';
import { StripeBootstrap } from './src/components/payments/StripeBootstrap';

function App(): React.JSX.Element {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <AppStoreProvider>
          <AppThemeProvider>
            <StripeBootstrap>
              <PushNotificationBootstrap />
              <RealtimeBootstrap />
              <AppNavigator />
            </StripeBootstrap>
          </AppThemeProvider>
        </AppStoreProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

export default App;
