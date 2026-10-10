import { useCallback, useEffect, useRef, useState } from 'react';
import NetInfo from '@react-native-community/netinfo';

import { translate } from '@/i18n/translate';
import { ApiError } from '@/services/http';
import {
  clearPending,
  loadPending,
  savePending,
} from '@/services/pendingAction';
import { useApi } from '@/store/SessionProvider';
import type { Trip, TripAction } from '@/types/api';
import { actionId } from '@utils/format';

const RETRY_MS = 3_000;
const RETRY_MAX_MS = 30_000;

/** 3 s, 6 s, 12 s, 24 s, then every 30 s: a basement does not need 20 requests a minute. */
export function retryDelay(failures: number): number {
  return Math.min(RETRY_MS * 2 ** Math.max(failures - 1, 0), RETRY_MAX_MS);
}

type Pending = { action: TripAction; id: string; otp?: string };

/**
 * Runs a trip step. On a dropped connection it keeps retrying with the SAME
 * action id until the server answers - the server applies an action id once,
 * so a step taken in a basement with no signal lands exactly once when the
 * rider comes back up. A real refusal (wrong code, out of order) stops and
 * is shown.
 *
 * The step is saved before the first attempt, so it also survives the app
 * being killed: the next time this trip opens, it is sent again. The moment
 * the phone gets a connection back it is retried at once, not on the timer.
 */
export function useTripAction(
  tripId: string | undefined,
  onDone: (trip: Trip) => void,
) {
  const api = useApi();
  const [pending, setPending] = useState<Pending | null>(null);
  const [waitingForNetwork, setWaitingForNetwork] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // One request at a time: the timer, a reconnect and a resume can all fire,
  // and two answers would run onDone twice (two Delivered screens).
  const inFlight = useRef(false);
  const failures = useRef(0);
  // The screen can close while a request is out. Its answer must then neither
  // re-arm a retry (nothing would ever clear it) nor call back into a screen
  // that is gone; the saved step is sent again when the trip reopens.
  const alive = useRef(true);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  const attempt = useCallback(
    async (p: Pending) => {
      if (!tripId) return;
      if (inFlight.current) return;
      inFlight.current = true;
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
      try {
        const trip = await api.act(tripId, p.action, p.id, p.otp);
        failures.current = 0;
        void clearPending();
        if (!alive.current) return;
        setPending(null);
        setWaitingForNetwork(false);
        doneRef.current(trip);
      } catch (e) {
        if (e instanceof ApiError && (e.isNetwork || e.status >= 500)) {
          if (!alive.current) return;
          failures.current += 1;
          setWaitingForNetwork(true);
          timer.current = setTimeout(
            () => void attempt(p),
            retryDelay(failures.current),
          );
          return;
        }
        void clearPending();
        if (!alive.current) return;
        setPending(null);
        setWaitingForNetwork(false);
        setError(
          e instanceof ApiError
            ? e
            : new ApiError(0, translate('trip.somethingWrong')),
        );
      } finally {
        inFlight.current = false;
      }
    },
    [api, tripId],
  );

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
    };
  }, []);

  // A step saved before the app was killed goes out again, same id.
  useEffect(() => {
    if (!tripId) return;
    let alive = true;
    loadPending(tripId).then(saved => {
      if (!alive || !saved) return;
      const p = { action: saved.action, id: saved.id, otp: saved.otp };
      setPending(current => current ?? p);
      void attempt(p);
    });
    return () => {
      alive = false;
    };
  }, [tripId, attempt]);

  // Signal is back: send now rather than waiting out the retry timer.
  useEffect(() => {
    if (!pending || !waitingForNetwork) return;
    return NetInfo.addEventListener(state => {
      if (state.isConnected && state.isInternetReachable !== false)
        void attempt(pending);
    });
  }, [pending, waitingForNetwork, attempt]);

  const run = useCallback(
    (action: TripAction, otp?: string) => {
      // Logging a call is advice to the server, not a step: it is sent once,
      // never saved or retried, so it can never sit in front of "delivered".
      if (action === 'call-logged') {
        if (tripId)
          api
            .act(tripId, action, actionId())
            .then(trip => doneRef.current(trip))
            .catch(() => undefined);
        return;
      }
      if (pending) return;
      setError(null);
      const p = { action, id: actionId(), otp };
      setPending(p);
      if (tripId) {
        void savePending({
          tripId,
          ...p,
          savedAt: new Date().toISOString(),
        }).then(() => attempt(p));
      }
    },
    [api, attempt, pending, tripId],
  );

  return {
    run,
    busy: pending?.action ?? null,
    waitingForNetwork,
    error,
    clearError: () => setError(null),
  };
}
