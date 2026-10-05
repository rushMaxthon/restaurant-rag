import type { RealtimeStatus } from '@/types/app';

// Full speed without a socket — the board's original, measured cadence.
export const POLL_INTERVAL_MS = 6000;
// With a live socket, polling is only the safety net for a lost push.
export const LIVE_POLL_INTERVAL_MS = 30000;

export const pollIntervalFor = (status: RealtimeStatus | null): number =>
  status === 'live' ? LIVE_POLL_INTERVAL_MS : POLL_INTERVAL_MS;

// Where the socket lives, from the REST base URL. The server is mounted under
// the API prefix (/api/socket.io), and the prefix belongs in Socket.IO's PATH
// option: left in the URL it would be read as a namespace. Parsed by hand
// because React Native's URL implementation does not expose `origin`.
export const socketEndpoint = (apiBaseUrl: string): { url: string; path: string } => {
  const match = /^(https?:\/\/[^/]+)(\/.*)?$/.exec(apiBaseUrl.trim());
  if (!match) {
    return { url: apiBaseUrl, path: '/socket.io' };
  }
  const prefix = (match[2] ?? '').replace(/\/+$/, '');
  return { url: match[1], path: `${prefix}/socket.io` };
};

export type RefusalAction = 'sign-out' | 'give-up' | 'retry';

// What to do when the server refuses the handshake, by its stated reason —
// a contract the backend documents. `auth`: the token is dead for REST too,
// so sign out now rather than run a board that quietly stops refreshing.
// `realtime_disabled` / `forbidden` / `invalid_*`: asking again changes
// nothing, so stop asking and keep polling. Anything else is transient.
export const refusalAction = (reason: string): RefusalAction => {
  if (reason === 'auth') {
    return 'sign-out';
  }
  if (reason === 'realtime_disabled' || reason === 'forbidden' || reason.startsWith('invalid_')) {
    return 'give-up';
  }
  return 'retry';
};

// Collapse a burst into one call: a rush that moves six tickets in a second
// should cost one refetch of the board, not six.
export const coalesce = (
  fn: () => void,
  waitMs: number,
): { call: () => void; cancel: () => void } => {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return {
    call: () => {
      if (timer !== null) {
        return;
      }
      timer = setTimeout(() => {
        timer = null;
        fn();
      }, waitMs);
    },
    cancel: () => {
      if (timer !== null) {
        clearTimeout(timer);
      }
      timer = null;
    },
  };
};
