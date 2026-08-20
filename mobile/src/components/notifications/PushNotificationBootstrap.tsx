import React, { useEffect } from 'react';
import { initializePushNotifications } from '@services/pushNotifications';

export function PushNotificationBootstrap(): null {
  useEffect(() => {
    let teardown: (() => void) | undefined;

    void initializePushNotifications().then(unsubscribe => {
      teardown = unsubscribe;
    });

    return () => {
      teardown?.();
    };
  }, []);

  return null;
}
