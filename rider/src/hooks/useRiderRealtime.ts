import { useEffect, useRef, useState } from 'react';
import { io, type Socket } from 'socket.io-client';

import { API_BASE_URL } from '@/config/api';
import { refusalAction, socketEndpoint } from '@utils/realtime';

export type RealtimeHandlers = {
  onOffer: () => void;
  onTrip: () => void;
  onReconnect: () => void;
  onRevoked: () => void;
};

/**
 * The live connection to the server, while signed in and the app is open.
 *
 * Events are hints, never data (the backend's rule): `rider:offer` means "ask
 * for your current offer now", `rider:trip_updated` "refetch your trip". So
 * the socket can never show a rider something REST would not, and a missed
 * event costs only the polling interval. Returns whether it is live, so
 * polling can slow down to a safety net.
 */
export function useRiderRealtime(
  token: string | null,
  enabled: boolean,
  handlers: RealtimeHandlers,
): boolean {
  const [live, setLive] = useState(false);
  const ref = useRef(handlers);
  ref.current = handlers;

  useEffect(() => {
    if (!token || !enabled) {
      setLive(false);
      return;
    }
    const { url, path } = socketEndpoint(API_BASE_URL);
    let retry: ReturnType<typeof setTimeout> | null = null;
    const socket: Socket = io(url, {
      path,
      transports: ['websocket'],
      auth: { token },
      reconnectionDelay: 1000,
      reconnectionDelayMax: 30_000,
      randomizationFactor: 0.5,
    });
    socket.on('connect', () => {
      setLive(true);
      // Nothing is kept for a disconnected client: anything may have changed.
      ref.current.onReconnect();
    });
    socket.on('disconnect', reason => {
      setLive(false);
      if (reason === 'io server disconnect') socket.connect();
    });
    socket.on('connect_error', (error: Error) => {
      setLive(false);
      if (socket.active) return;
      const action = refusalAction(error.message);
      if (action === 'sign-out') ref.current.onRevoked();
      else if (action === 'retry')
        retry = setTimeout(() => socket.connect(), 15_000);
      // give-up: realtime is off on the server; polling carries on.
    });
    socket.on('rider:offer', () => ref.current.onOffer());
    socket.on('rider:offer_withdrawn', () => ref.current.onOffer());
    socket.on('rider:trip_updated', () => ref.current.onTrip());
    socket.on('rider:trip_cancelled', () => ref.current.onTrip());
    socket.on('session:revoked', () => ref.current.onRevoked());
    return () => {
      if (retry) clearTimeout(retry);
      socket.removeAllListeners();
      socket.disconnect();
      setLive(false);
    };
  }, [token, enabled]);

  return live;
}
