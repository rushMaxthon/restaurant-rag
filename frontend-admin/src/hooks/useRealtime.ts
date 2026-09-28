import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";

import { API_BASE_URL } from "../services/api";
import {
  RealtimeClient,
  announceOrdersChanged,
  onOrdersChanged,
  type RealtimeStatus,
} from "../services/realtime";

const noSubscription = () => () => {};

/**
 * The panel's one socket, open while a staff session is.
 *
 * Mounted once, in `App`, not per page: an owner moving between screens
 * should not reconnect on every navigation. Status is read with
 * `useSyncExternalStore` because it changes in socket callbacks, outside React.
 *
 * A burst is coalesced over a longer window than the kitchen board's: an
 * ADMIN hears every restaurant on the platform, and each coalesced push costs
 * the open screen a refetch.
 */
export function useRealtimeConnection(
  token: string | null,
  onSignOut: () => void,
): RealtimeStatus | null {
  const client = useMemo(
    () =>
      token
        ? new RealtimeClient({
            apiBaseUrl: API_BASE_URL,
            auth: () => ({ token }),
            onChange: announceOrdersChanged,
            onSignOut,
            coalesceMs: 1000,
          })
        : null,
    [token, onSignOut],
  );

  useEffect(() => {
    if (!client) return;
    client.start();
    return () => client.stop();
  }, [client]);

  return useSyncExternalStore(
    client?.subscribe ?? noSubscription,
    client?.getStatus ?? (() => null),
  );
}

/**
 * Run `listener` whenever orders change, from a push or a reconnect.
 *
 * `orderIds` is null after a reconnect, meaning "anything may have changed".
 * The latest listener is always the one called, so a page can pass an inline
 * function without re-subscribing on every render.
 */
export function useOrdersChanged(
  listener: (orderIds: string[] | null) => void,
): void {
  const latest = useRef(listener);
  useEffect(() => {
    latest.current = listener;
  }, [listener]);
  useEffect(() => onOrdersChanged((orderIds) => latest.current(orderIds)), []);
}
