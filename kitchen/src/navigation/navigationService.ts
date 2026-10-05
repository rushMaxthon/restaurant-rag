import { createNavigationContainerRef } from '@react-navigation/native';
import type { RootStackParamList } from '@navigation/hooks/useNavigation';

// Lets code outside the React tree (an alert for a new ticket, a revoked
// session) move the board. Anything asked before the container is ready is
// held and replayed, so an early request is not lost.
export const navigationRef = createNavigationContainerRef<RootStackParamList>();

type PendingRoute = {
  [K in keyof RootStackParamList]: { name: K; params: RootStackParamList[K] };
}[keyof RootStackParamList];

let pending: PendingRoute | null = null;

export const navigateFromOutside = (route: PendingRoute): void => {
  if (navigationRef.isReady()) {
    // The union is spread back into navigate's overloads one member at a time.
    (navigationRef.navigate as (name: string, params?: object) => void)(
      route.name,
      route.params,
    );
  } else {
    pending = route;
  }
};

export const flushPendingNavigation = (): void => {
  if (pending) {
    const route = pending;
    pending = null;
    navigateFromOutside(route);
  }
};
