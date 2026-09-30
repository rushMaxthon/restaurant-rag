import { useEffect, useRef, useSyncExternalStore } from 'react';

import {
  getRealtimeStatus,
  onOrdersChanged,
  subscribeRealtimeStatus,
  type RealtimeStatus,
} from '@services/realtime';

/** Whether a push can currently reach this app. `null` while signed out. */
export function useRealtimeStatus(): RealtimeStatus | null {
  return useSyncExternalStore(subscribeRealtimeStatus, getRealtimeStatus);
}

/**
 * Run `listener` whenever orders change, from a push or a reconnect.
 *
 * `orderIds` is null after a reconnect, meaning "anything may have changed".
 * The latest listener is always the one called, so a screen can pass an
 * inline function without re-subscribing on every render.
 */
export function useOrdersChanged(
  listener: (orderIds: string[] | null) => void,
): void {
  const latest = useRef(listener);
  useEffect(() => {
    latest.current = listener;
  }, [listener]);
  useEffect(() => onOrdersChanged(orderIds => latest.current(orderIds)), []);
}
