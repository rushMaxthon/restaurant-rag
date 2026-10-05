import { io, type Socket } from 'socket.io-client';
import type { RealtimeStatus } from '@/types/app';
import { coalesce, refusalAction, socketEndpoint } from '@utils/realtime';

// Socket.IO pushes from the API. A push is a HINT, never data: it says "order
// X changed" and the board refetches over REST, so the socket can never show
// a ticket the REST scope would not. WebSocket transport only — the API runs
// several processes with no sticky routing, which long-polling requires.
//
// Polling never stops; it slows while the socket is live. Every (re)connect
// refetches everything, because a push sent while disconnected is gone.

// After a transient refusal, how long before asking again.
const REFUSED_RETRY_MS = 15000;
const COALESCE_MS = 300;

export interface RealtimeOptions {
  apiBaseUrl: string;
  token: string;
  // Something changed; refetch.
  onChange: () => void;
  // The session is over on the server's say-so.
  onSignOut: () => void;
  connect?: typeof io;
}

export class RealtimeClient {
  private status: RealtimeStatus = 'connecting';
  private readonly listeners = new Set<() => void>();
  private socket: Socket | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private scope: Record<string, unknown> = {};
  private readonly change: ReturnType<typeof coalesce>;

  constructor(private readonly options: RealtimeOptions) {
    this.change = coalesce(options.onChange, COALESCE_MS);
  }

  getStatus = (): RealtimeStatus => this.status;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  start(): void {
    if (this.socket) {
      return;
    }
    const { url, path } = socketEndpoint(this.options.apiBaseUrl);
    const connect = this.options.connect ?? io;
    const socket = connect(url, {
      path,
      transports: ['websocket'],
      // Read at every (re)connect, so a reconnect after a Wi-Fi drop asks for
      // the branch on screen now, not the one chosen when it first opened.
      auth: callback => callback({ ...this.scope, token: this.options.token }),
      reconnectionDelay: 1000,
      reconnectionDelayMax: 30000,
      randomizationFactor: 0.5,
    });
    this.socket = socket;
    this.setStatus('connecting');

    socket.on('connect', () => {
      this.setStatus('live');
      this.change.call();
    });
    socket.on('disconnect', reason => {
      if (this.status !== 'disabled') {
        this.setStatus('offline');
      }
      // The server ended this socket on purpose (revoked, expired, moved out
      // of scope). Socket.IO will not reconnect by itself after that; one
      // attempt settles it — a dead session is then refused with `auth`.
      if (reason === 'io server disconnect') {
        socket.connect();
      }
    });
    socket.on('connect_error', (error: Error) => {
      if (socket.active) {
        // Network-level: Socket.IO is already backing off and retrying.
        this.setStatus('offline');
        return;
      }
      const action = refusalAction(error.message);
      if (action === 'sign-out') {
        this.stop();
        this.options.onSignOut();
      } else if (action === 'give-up') {
        this.setStatus('disabled');
      } else {
        this.setStatus('offline');
        this.retryTimer = setTimeout(() => socket.connect(), REFUSED_RETRY_MS);
      }
    });
    socket.on('order:updated', () => this.change.call());
    socket.on('session:revoked', () => {
      this.stop();
      this.options.onSignOut();
    });
  }

  // Move the open socket to another restaurant or branch. The server checks
  // it with the same scope rule as GET /orders; on refusal the socket
  // reconnects, re-authenticating with the scope above, and its answer stands.
  resubscribe(scope: Record<string, unknown>): void {
    this.scope = scope;
    const socket = this.socket;
    if (!socket?.connected) {
      return;
    }
    socket.emit('subscribe', scope, (ack: { ok?: boolean } | undefined) => {
      if (!ack?.ok) {
        socket.disconnect().connect();
      }
    });
  }

  stop(): void {
    this.change.cancel();
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
    }
    this.retryTimer = null;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.removeAllListeners();
      socket.close();
    }
  }

  private setStatus(next: RealtimeStatus): void {
    if (next === this.status) {
      return;
    }
    this.status = next;
    this.listeners.forEach(listener => listener());
  }
}
