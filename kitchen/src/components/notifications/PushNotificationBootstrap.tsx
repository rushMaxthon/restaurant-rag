import { useEffect, useRef } from 'react';
import { useSessionState } from '@hooks/useAppStore';
import { setNavigationSignedIn } from '@navigation/navigationService';
import {
  initializePushNotifications,
  registerForPush,
  unregisterForPush,
} from '@services/pushNotifications';

// Push for as long as the app runs, following the session. Renders nothing.
//
// Watching the session rather than hooking the store's actions keeps the
// store free of side effects and covers every way a session changes: a sign-
// in, a session restored at launch (its FCM token may have rotated while the
// app was closed), a sign-out from Settings, and a forced one after a 401.
export const PushNotificationBootstrap = () => {
  const { hydrated, session } = useSessionState();
  const token = session?.token ?? null;
  const previous = useRef<string | null>(null);

  useEffect(() => {
    let teardown: (() => void) | undefined;
    let cancelled = false;
    initializePushNotifications().then(unsubscribe => {
      if (cancelled) {
        unsubscribe();
      } else {
        teardown = unsubscribe;
      }
    });
    return () => {
      cancelled = true;
      teardown?.();
    };
  }, []);

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    const before = previous.current;
    previous.current = token;
    // Runs after the stack for this session has rendered, so a notification
    // tap held during sign-in lands on a route that now exists.
    setNavigationSignedIn(Boolean(token));
    if (before && before !== token) {
      // Signed out (or switched account): silence this device for the old one
      // while its token is still, normally, valid.
      unregisterForPush(before);
    }
    if (token && token !== before) {
      registerForPush(token);
    }
  }, [hydrated, token]);

  return null;
};
