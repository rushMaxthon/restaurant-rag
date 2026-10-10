import { useEffect } from 'react';
import { AppState } from 'react-native';

import { APP_VERSION } from '@/config/app';
import { navigationRef } from '@navigation/ref';
import {
  listenForPush,
  onPushTap,
  registerDeviceToken,
  showReferral,
  takePendingPush,
} from '@/services/push';
import { useRider } from '@/store/RiderProvider';
import { useApi } from '@/store/SessionProvider';
import { foregroundAction, type RiderPush, screenFor } from '@utils/push';

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
  const { refreshOffer, refreshTrip, refreshMe, applicationChanged } =
    useRider();

  useEffect(() => {
    const act = (push: RiderPush) => {
      // A decision on the application: refetch it and /me. If it was an
      // approval, RootNavigator swaps the application for the tabs itself.
      if (push.kind === 'application') {
        applicationChanged();
        return;
      }
      // Refer & earn lives in the approved rider's stack only.
      if (push.kind === 'referral') {
        if (
          navigationRef.isReady() &&
          navigationRef.getRootState()?.routeNames?.includes('Referral')
        )
          navigationRef.navigate('Referral');
        return;
      }
      if (screenFor(push) === 'Offer') {
        void refreshOffer();
        return;
      }
      void refreshTrip();
      void refreshMe();
      // Mounted over the application stack too, which has no Main.
      if (
        navigationRef.isReady() &&
        navigationRef.getRootState()?.routeNames?.includes('Main')
      )
        navigationRef.navigate('Main', { screen: 'Home' });
    };
    const consume = () => {
      const push = takePendingPush();
      if (push) act(push);
    };
    consume();
    const offTap = onPushTap(act);
    const offPush = listenForPush(push => {
      const action = foregroundAction(push);
      if (action === 'show_referral' && push?.kind === 'referral')
        void showReferral(push);
      else if (action === 'application') applicationChanged();
      else void refreshOffer();
    });
    const sub = AppState.addEventListener(
      'change',
      next => next === 'active' && consume(),
    );
    return () => {
      offTap();
      offPush();
      sub.remove();
    };
  }, [refreshOffer, refreshTrip, refreshMe, applicationChanged]);

  useEffect(
    () => registerDeviceToken(token => api.deviceToken(token, APP_VERSION)),
    [api],
  );

  return null;
}
