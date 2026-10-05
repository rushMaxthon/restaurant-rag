import { createNavigationContainerRef } from '@react-navigation/native';
import type { RootStackParamList } from '@navigation/hooks/useNavigation';

// Lets code outside the React tree — a tapped notification above all — move
// the app. A request is held until BOTH the navigator is ready AND someone is
// signed in: the order screen is only registered for a signed-in stack, so a
// tap that arrives during launch, or on a signed-out tablet, waits and is
// replayed the moment it can land (after sign-in, straight onto the order).
export const navigationRef = createNavigationContainerRef<RootStackParamList>();

type PendingRoute = {
  [K in keyof RootStackParamList]: { name: K; params: RootStackParamList[K] };
}[keyof RootStackParamList];

let pending: PendingRoute | null = null;
let signedIn = false;

const go = (route: PendingRoute) =>
  // The union is spread back into navigate's overloads one member at a time.
  (navigationRef.navigate as (name: string, params?: object) => void)(route.name, route.params);

export const navigateFromOutside = (route: PendingRoute): void => {
  if (navigationRef.isReady() && signedIn) {
    go(route);
  } else {
    pending = route;
  }
};

export const flushPendingNavigation = (): void => {
  if (pending && navigationRef.isReady() && signedIn) {
    const route = pending;
    pending = null;
    go(route);
  }
};

// Called once the signed-in (or signed-out) stack has rendered.
export const setNavigationSignedIn = (value: boolean): void => {
  signedIn = value;
  flushPendingNavigation();
};

// Test seam: forget a held request between tests.
export const resetNavigationServiceForTests = (): void => {
  pending = null;
  signedIn = false;
};
