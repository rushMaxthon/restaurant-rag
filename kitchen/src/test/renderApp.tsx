import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import { Text } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { NavigationContainer } from '@react-navigation/native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import StackNavigation from '@navigation/stackNavigation';
import { navigationRef } from '@navigation/navigationService';
import { AppStoreProvider } from '@store/AppStore';
import { AppThemeProvider } from '@/theme';
import { RealtimeProvider } from '@components/realtime/RealtimeProvider';
import { PushNotificationBootstrap } from '@components/notifications/PushNotificationBootstrap';
import { flushPendingNavigation } from '@navigation/navigationService';
import type { KitchenSession } from '@/types/app';

// Test harness only: the real provider tree, with a session already saved
// the way a tablet that was signed in before a restart would have it.
const SAFE_AREA = {
  frame: { x: 0, y: 0, width: 390, height: 844 },
  insets: { top: 0, left: 0, right: 0, bottom: 0 },
};

export type Tree = ReactTestRenderer.ReactTestRenderer;

// Lets pending promises and the effects they trigger run to completion.
export const settle = async (rounds = 6) => {
  for (let i = 0; i < rounds; i += 1) {
    await ReactTestRenderer.act(async () => {
      await new Promise<void>(resolve => setImmediate(() => resolve()));
    });
  }
};

export const renderApp = async (
  session: KitchenSession | null,
  // A stored value as some earlier build might have left it.
  rawSession?: string,
  // Mount the push bootstrap too, as App.tsx does. Off by default so screen
  // tests do not register devices they never asked about.
  options: { push?: boolean } = {},
): Promise<Tree> => {
  await AsyncStorage.clear();
  if (session) {
    await AsyncStorage.setItem('kitchen.session', JSON.stringify(session));
  } else if (rawSession !== undefined) {
    await AsyncStorage.setItem('kitchen.session', rawSession);
  }
  let tree!: Tree;
  await ReactTestRenderer.act(async () => {
    tree = ReactTestRenderer.create(
      <SafeAreaProvider initialMetrics={SAFE_AREA}>
        <AppStoreProvider>
          <AppThemeProvider>
            <RealtimeProvider>
              {options.push ? <PushNotificationBootstrap /> : null}
              <NavigationContainer ref={navigationRef} onReady={flushPendingNavigation}>
                <StackNavigation />
              </NavigationContainer>
            </RealtimeProvider>
          </AppThemeProvider>
        </AppStoreProvider>
      </SafeAreaProvider>,
    );
  });
  await settle();
  return tree;
};

export const byTestId = (tree: Tree, id: string) =>
  tree.root.findAll(node => node.props.testID === id)[0];

export const hasTestId = (tree: Tree, id: string) =>
  tree.root.findAll(node => node.props.testID === id).length > 0;

export const press = async (tree: Tree, id: string) => {
  await ReactTestRenderer.act(async () => {
    byTestId(tree, id).props.onPress();
  });
  await settle();
};

export const typeInto = async (tree: Tree, id: string, value: string) => {
  await ReactTestRenderer.act(async () => {
    byTestId(tree, id).props.onChangeText(value);
  });
};

export const allText = (tree: Tree) =>
  tree.root
    .findAllByType(Text)
    .map(node => [node.props.children].flat(Infinity).filter(part => typeof part !== 'object').join(''))
    .join('\n');

export const currentRoute = () => navigationRef.getCurrentRoute();

export const unmount = async (tree: Tree) => {
  await ReactTestRenderer.act(async () => {
    tree.unmount();
  });
};
