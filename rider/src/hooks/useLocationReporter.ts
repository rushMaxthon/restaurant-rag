import { useEffect, useRef, useState } from 'react';
import Geolocation from '@react-native-community/geolocation';

import { useApi } from '@/store/SessionProvider';
import type { LocationFix, RiderStatus } from '@/types/api';
import { batchToSend } from '@utils/heartbeat';

/** On a trip the customer watches the rider move; idle, we only need "near which branch". */
const SEND_EVERY_MS = { ON_TRIP: 10_000, ONLINE: 30_000 } as const;
const MAX_QUEUE = 20;

export type LocationState = {
  lastFix: LocationFix | null;
  error: string | null;
};

/**
 * Watches the GPS while the rider is online and sends what it saw in batches.
 *
 * Batched, not one request per fix: a phone on a weak cell sends one small
 * request every 10 s instead of several, and fixes taken while offline are
 * kept (up to the server's 20) and sent when the network returns, newest
 * last, so the server keeps the right one.
 */
export function useLocationReporter(
  status: RiderStatus | undefined,
  enabled: boolean,
): LocationState {
  const api = useApi();
  const queue = useRef<LocationFix[]>([]);
  // The first fix after going online is sent AT ONCE: until the server has a
  // position this rider is invisible to the offer loop, and the sweep takes a
  // rider with no position offline again within minutes.
  const sentOnce = useRef(false);
  const flushRef = useRef<() => Promise<void>>(async () => undefined);
  const [state, setState] = useState<LocationState>({
    lastFix: null,
    error: null,
  });
  // Read by the send timer: a still rider resends their last fix (see heartbeat.ts).
  const lastFix = useRef<LocationFix | null>(null);
  const gpsError = useRef<string | null>(null);
  const active = enabled && (status === 'ONLINE' || status === 'ON_TRIP');

  useEffect(() => {
    if (!active) sentOnce.current = false;
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const watchId = Geolocation.watchPosition(
      position => {
        const fix: LocationFix = {
          lat: position.coords.latitude,
          lng: position.coords.longitude,
          accuracy_m: position.coords.accuracy ?? null,
          at: new Date(position.timestamp || Date.now()).toISOString(),
        };
        queue.current = [...queue.current, fix].slice(-MAX_QUEUE);
        lastFix.current = fix;
        gpsError.current = null;
        setState({ lastFix: fix, error: null });
        if (!sentOnce.current) void flushRef.current();
      },
      error => {
        gpsError.current = error.message || 'Location is not available';
        setState(prev => ({ ...prev, error: gpsError.current }));
      },
      {
        enableHighAccuracy: true,
        distanceFilter: 15,
        interval: 5_000,
        fastestInterval: 3_000,
      },
    );
    return () => Geolocation.clearWatch(watchId);
  }, [active]);

  useEffect(() => {
    if (!active || (status !== 'ONLINE' && status !== 'ON_TRIP')) return;
    const flush = async () => {
      const batch = batchToSend(
        queue.current,
        lastFix.current,
        gpsError.current,
      );
      if (batch.length === 0) return;
      queue.current = [];
      try {
        await api.sendLocation(batch);
        sentOnce.current = true;
      } catch {
        // keep them for the next try, newest last, never more than the server takes
        queue.current = [...batch, ...queue.current].slice(-MAX_QUEUE);
      }
    };
    flushRef.current = flush;
    void flush();
    const id = setInterval(flush, SEND_EVERY_MS[status]);
    return () => clearInterval(id);
  }, [active, status, api]);

  return state;
}
