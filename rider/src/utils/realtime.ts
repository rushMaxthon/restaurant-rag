/**
 * The rider app's Socket.IO rules, kept pure so they can be tested. Ported
 * from the kitchen app (`kitchen/src/utils/realtime.ts`); keep the two in step.
 */

/**
 * Where the socket lives, from the REST base URL. The server is mounted under
 * the API prefix (/api/socket.io), and the prefix belongs in Socket.IO's PATH
 * option: left in the URL it would be read as a namespace. Parsed by hand
 * because React Native's URL implementation does not expose `origin`.
 */
export function socketEndpoint(apiBaseUrl: string): {
  url: string;
  path: string;
} {
  const match = /^(https?:\/\/[^/]+)(\/.*)?$/.exec(apiBaseUrl.trim());
  if (!match) return { url: apiBaseUrl, path: '/socket.io' };
  const prefix = (match[2] ?? '').replace(/\/+$/, '');
  return { url: match[1] ?? apiBaseUrl, path: `${prefix}/socket.io` };
}

export type RefusalAction = 'sign-out' | 'give-up' | 'retry';

/**
 * What to do when the server refuses the handshake, by its stated reason -
 * a contract the backend documents. `auth`: the token is dead for REST too.
 * `realtime_disabled` / `forbidden` / `invalid_*`: asking again changes
 * nothing, so keep polling. Anything else is transient.
 */
export function refusalAction(reason: string): RefusalAction {
  if (reason === 'auth') return 'sign-out';
  if (
    reason === 'realtime_disabled' ||
    reason === 'forbidden' ||
    reason.startsWith('invalid_')
  )
    return 'give-up';
  return 'retry';
}

/** How often to poll for offers: fast without a live socket, a safety net with one. */
export function offerPollMs(live: boolean): number {
  return live ? 20_000 : 3_000;
}
