import { useEffect } from 'react';
import { AppState } from 'react-native';

import { APP_VERSION } from '@/config/app';
import { navigationRef } from '@navigation/ref';
import {
  listenForPush,
  onPushTap,
  registerDeviceToken,
  takePendingPush,
} from '@/services/push';
import { useRider } from '@/store/RiderProvider';
import { useApi } from '@/store/SessionProvider';
import { screenFor, type RiderPush } from '@utils/push';

/**
 * Where a notification tap takes the rider, from any screen and from a cold
 * start; and the device token, so the server can reach a killed app.
 *
 * An offer tap only fetches the offer: OfferWatcher opens the Offer screen
 * whenever there is one, so a tap and a socket event take the same path and
 * an offer that expired meanwhile simply opens nothing.
 */
export function PushRouter() {
  const api = useApi();
  const { refreshOffer, refreshTrip, refreshMe } = useRider();

  useEffect(() => {
    const act = (push: RiderPush) => {
      if (screenFor(push) === 'Offer') {
        void refreshOffer();
        return;
      }
      void refreshTrip();
      void refreshMe();
      if (navigationRef.isReady())
        navigationRef.navigate('Main', { screen: 'Home' });
    };
    const consume = () => {
      const push = takePendingPush();
      if (push) act(push);
    };
    consume();
    const offTap = onPushTap(act);
    const offPush = listenForPush(() => void refreshOffer());
    const sub = AppState.addEventListener(
      'change',
      next => next === 'active' && consume(),
    );
    return () => {
      offTap();
      offPush();
      sub.remove();
    };
  }, [refreshOffer, refreshTrip, refreshMe]);

  useEffect(
    () => registerDeviceToken(token => api.deviceToken(token, APP_VERSION)),
    [api],
  );

  return null;
}
