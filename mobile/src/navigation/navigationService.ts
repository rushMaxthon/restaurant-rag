import {
  CommonActions,
  createNavigationContainerRef,
} from '@react-navigation/native';
import type {
  AuthRedirectTarget,
  RootStackParamList,
} from '@/navigation/navigationTypes';

type NotificationNavigationTarget =
  {
      screen: 'OrderDetail';
      params: {
        orderId: string;
      };
    };

export const navigationRef =
  createNavigationContainerRef<RootStackParamList>();

let pendingTarget: NotificationNavigationTarget | null = null;
let currentAuthToken: string | null = null;
let authStateResolved = false;

function toAuthRedirectTarget(
  target: NotificationNavigationTarget,
): AuthRedirectTarget {
  return {
    screen: 'OrderDetail',
    params: target.params,
  };
}

function resetToTarget(target: NotificationNavigationTarget) {
  navigationRef.dispatch(
    CommonActions.reset({
      index: 1,
      routes: [
        { name: 'MainTabs' },
        { name: 'OrderDetail', params: target.params },
      ],
    }),
  );
}

function flushPendingNavigation() {
  if (!pendingTarget || !navigationRef.isReady() || !authStateResolved) {
    return;
  }

  const nextTarget = pendingTarget;
  pendingTarget = null;

  if (!currentAuthToken) {
    navigationRef.navigate('Login', {
      redirectTo: toAuthRedirectTarget(nextTarget),
    });
    return;
  }

  resetToTarget(nextTarget);
}

export function setNotificationNavigationAuthToken(token: string | null) {
  authStateResolved = true;
  currentAuthToken = token;
  flushPendingNavigation();
}

export function queueNotificationNavigation(
  target: NotificationNavigationTarget,
) {
  pendingTarget = target;
  flushPendingNavigation();
}

export function markNotificationNavigationReady() {
  flushPendingNavigation();
}
