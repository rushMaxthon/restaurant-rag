import { useEffect, useMemo, useRef } from 'react';
import { AppState } from 'react-native';

import { API_BASE_URL } from '@/config/api';
import { useAppActions, useSession } from '@hooks/useAppStore';
import { getAppIdentityHeaders } from '@services/api';
import {
  RealtimeClient,
  announceOrdersChanged,
  setRealtimeStatus,
} from '@services/realtime';

/**
 * Keeps the signed-in customer's socket open while the app is in front.
 *
 * Mounted beside `PushNotificationBootstrap` because the two are halves of one
 * job: a notification reaches a closed app, this keeps an open screen current.
 * Closed on background (the OS would drop it anyway, and a socket held by an
 * app the user cannot see is battery spent on nothing) and reopened on
 * foreground, where the reconnect refetches whatever is on screen.
 */
export function RealtimeBootstrap(): null {
  const { token } = useSession();
  const { logout } = useAppActions();

  // Read through a ref: the socket is keyed on the token alone, and a new
  // `logout` identity must not tear it down and reconnect.
  const logoutRef = useRef(logout);
  useEffect(() => {
    logoutRef.current = logout;
  }, [logout]);

  const client = useMemo(
    () =>
      token
        ? new RealtimeClient({
            apiBaseUrl: API_BASE_URL,
            auth: () => {
              const { bundleId, platform } = getAppIdentityHeaders();
              return { token, bundle_id: bundleId, platform };
            },
            onChange: announceOrdersChanged,
            onSignOut: () => logoutRef.current(),
          })
        : null,
    [token],
  );

  useEffect(() => {
    if (!client) {
      setRealtimeStatus(null);
      return;
    }
    const unsubscribe = client.subscribe(() =>
      setRealtimeStatus(client.getStatus()),
    );
    if (AppState.currentState === 'active') {
      client.start();
    }
    setRealtimeStatus(client.getStatus());

    const appState = AppState.addEventListener('change', next => {
      if (next === 'active') {
        client.start();
      } else if (next === 'background') {
        client.stop();
        // Not live while away: the screens fall back to polling on return
        // until the reconnect lands.
        setRealtimeStatus('offline');
      }
    });

    return () => {
      appState.remove();
      unsubscribe();
      client.stop();
      setRealtimeStatus(null);
    };
  }, [client]);

  return null;
}
