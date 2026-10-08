import React from 'react';
import { StatusBar, StyleSheet } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { DarkTheme, DefaultTheme, NavigationContainer } from '@react-navigation/native';

import { ErrorBoundary } from '@components/ErrorBoundary';
import { RootNavigator } from '@navigation/RootNavigator';
import { SplashOverlay } from '@screens/auth/SplashOverlay';
import { SessionProvider, useSession } from '@/store/SessionProvider';
import { ThemeProvider, useTheme } from '@theme/ThemeProvider';

/**
 * GestureHandlerRootView wraps EVERYTHING, including navigation: a gesture
 * (the slide-to-confirm) outside it is silently dead on Android, which looks
 * exactly like a frozen screen.
 */
export default function App() {
  return (
    <GestureHandlerRootView style={styles.root}>
      <SafeAreaProvider>
        <ThemeProvider>
          <SessionProvider>
            <Navigation />
          </SessionProvider>
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

function Navigation() {
  const { mode, colors } = useTheme();
  const { state } = useSession();
  const base = mode === 'dark' ? DarkTheme : DefaultTheme;
  const navTheme = {
    ...base,
    colors: { ...base.colors, background: colors.bg, card: colors.surface, text: colors.text, border: colors.border, primary: colors.primary },
  };
  return (
    <>
      <NavigationContainer theme={navTheme}>
        <StatusBar barStyle={mode === 'dark' ? 'light-content' : 'dark-content'} />
        <ErrorBoundary>{state.status === 'loading' ? null : <RootNavigator />}</ErrorBoundary>
      </NavigationContainer>
      <SplashOverlay ready={state.status !== 'loading'} />
    </>
  );
}

const styles = StyleSheet.create({ root: { flex: 1 } });
