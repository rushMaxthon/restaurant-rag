import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '@/services/http';
import { useApi } from '@/store/SessionProvider';
import type { Trip, TripAction } from '@/types/api';
import { actionId } from '@utils/format';

const RETRY_MS = 3_000;

type Pending = { action: TripAction; id: string; otp?: string };

/**
 * Runs a trip step. On a dropped connection it keeps retrying with the SAME
 * action id until the server answers - the server applies an action id once,
 * so a step taken in a basement with no signal lands exactly once when the
 * rider comes back up. A real refusal (wrong code, out of order) stops and
 * is shown.
 */
export function useTripAction(tripId: string | undefined, onDone: (trip: Trip) => void) {
  const api = useApi();
  const [pending, setPending] = useState<Pending | null>(null);
  const [waitingForNetwork, setWaitingForNetwork] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  const attempt = useCallback(
    async (p: Pending) => {
      if (!tripId) return;
      try {
        const trip = await api.act(tripId, p.action, p.id, p.otp);
        setPending(null);
        setWaitingForNetwork(false);
        doneRef.current(trip);
      } catch (e) {
        if (e instanceof ApiError && (e.isNetwork || e.status >= 500)) {
          setWaitingForNetwork(true);
          timer.current = setTimeout(() => void attempt(p), RETRY_MS);
          return;
        }
        setPending(null);
        setWaitingForNetwork(false);
        setError(e instanceof ApiError ? e : new ApiError(0, 'Something went wrong. Try again.'));
      }
    },
    [api, tripId],
  );

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const run = useCallback(
    (action: TripAction, otp?: string) => {
      if (pending) return;
      setError(null);
      const p = { action, id: actionId(), otp };
      setPending(p);
      void attempt(p);
    },
    [attempt, pending],
  );

  return { run, busy: pending?.action ?? null, waitingForNetwork, error, clearError: () => setError(null) };
}
