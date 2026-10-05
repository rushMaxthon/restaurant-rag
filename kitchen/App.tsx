import React from 'react';
import { StatusBar } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { AppStoreProvider } from './src/store/AppStore';
import { AppThemeProvider, useTheme } from './src/theme';
import { RealtimeProvider } from './src/components/realtime/RealtimeProvider';
import StackNavigation from './src/navigation/stackNavigation';
import {
  flushPendingNavigation,
  navigationRef,
} from './src/navigation/navigationService';

const AppContent = () => {
  const theme = useTheme();
  return (
    <>
      <StatusBar
        barStyle={theme.mode === 'dark' ? 'light-content' : 'dark-content'}
        backgroundColor={theme.colors.background}
      />
      <NavigationContainer ref={navigationRef} onReady={flushPendingNavigation}>
        <StackNavigation />
      </NavigationContainer>
    </>
  );
};

const App = (): React.JSX.Element => {
  return (
    <SafeAreaProvider>
      <AppStoreProvider>
        <AppThemeProvider>
          <RealtimeProvider>
            <AppContent />
          </RealtimeProvider>
        </AppThemeProvider>
      </AppStoreProvider>
    </SafeAreaProvider>
  );
};

export default App;
