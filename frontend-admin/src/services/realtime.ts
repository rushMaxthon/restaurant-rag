/**
 * Realtime pushes from the API, over Socket.IO.
 *
 * `socket.io-client` is the ONE documented exception to this panel's
 * no-runtime-dependencies rule (see CLAUDE.md): the kitchen board, the customer
 * web app and the mobile app all speak Socket.IO to the same server, and a
 * hand-written Engine.IO client here would be a fourth implementation of a
 * protocol with heartbeats, reconnection and packet framing to get wrong.
 *
 * A push is a HINT, never data. It says "order X is now Y" and nothing else;
 * the open screen reacts by refetching over REST, so what an owner or admin
 * sees is still exactly what `GET /orders` decides. An ADMIN's socket sits in
 * `admin:all` and hears every restaurant's orders, which is what the Orders
 * page lists for them; an OWNER's sits in their own restaurant's room.
 *
 * This panel never polled, so there is no poll to slow down: while the socket
 * is down it behaves exactly as it always did (load on navigation, Refresh /
 * Try again), and a reconnect refetches whatever is on screen, because a push
 * sent while disconnected is gone.
 *
 * WebSocket transport only: the API runs several processes with no sticky
 * routing between them, which Socket.IO's long-polling transport requires.
 */

import { io, type Socket } from "socket.io-client";

import { invalidatePageSnapshotsByPrefix } from "./pageCache";

/** What the header shows. `disabled` means the server has realtime off. */
export type RealtimeStatus = "connecting" | "live" | "offline" | "disabled";

/** What `order:updated` carries. Deliberately no order contents. */
export type OrderUpdatedEvent = {
  order_id: string;
  restaurant_id: string;
  restaurant_location_id: string;
  status: string;
  from_status: string | null;
  occurred_at: string;
};

/**
 * Where the socket lives, from the REST base URL.
 *
 * The server is mounted under the API prefix (`/api/socket.io`), so every
 * proxy that already routes `/api` routes it too. The prefix is part of the
 * PATH here, not the URL — Socket.IO would read a path in the URL as a
 * namespace.
 */
export function socketEndpoint(apiBaseUrl: string): {
  url: string;
  path: string;
} {
  const base = new URL(apiBaseUrl);
  const prefix = base.pathname.replace(/\/+$/, "");
  return { url: base.origin, path: `${prefix}/socket.io` };
}

export type RefusalAction = "sign-out" | "give-up" | "retry";

/**
 * What to do when the server refuses the handshake, by its stated reason.
 *
 * `auth` means the token is no longer good for REST either — signing out now
 * beats a board that quietly stops refreshing. `realtime_disabled` and
 * `forbidden` will not change by asking again, so the board stops asking and
 * keeps polling. Anything else is transient.
 */
export function refusalAction(reason: string): RefusalAction {
  if (reason === "auth") return "sign-out";
  if (
    reason === "realtime_disabled" ||
    reason === "forbidden" ||
    reason.startsWith("invalid_")
  ) {
    return "give-up";
  }
  return "retry";
}

/**
 * Coalesce bursts into one call. A rush that advances six tickets in a second
 * should cost one refetch of the board, not six.
 */
export function coalesce(
  fn: () => void,
  waitMs: number,
): { call: () => void; cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return {
    call() {
      if (timer !== null) return;
      timer = setTimeout(() => {
        timer = null;
        fn();
      }, waitMs);
    },
    cancel() {
      if (timer !== null) clearTimeout(timer);
      timer = null;
    },
  };
}

/** How long to wait before asking again after a transient refusal. */
const REFUSED_RETRY_MS = 15000;

export type RealtimeOptions = {
  apiBaseUrl: string;
  /** Credentials, read at every (re)connect. The scope is merged in by `resubscribe`. */
  auth: () => Record<string, unknown>;
  /**
   * Orders changed. Coalesced: `orderIds` is every order pushed in the window,
   * or `null` after a (re)connect — anything could have changed while away.
   */
  onChange: (orderIds: string[] | null) => void;
  /** The session is over; sign out. */
  onSignOut: () => void;
  /**
   * A rider moved or went on/off shift (`fleet:riders_changed`, admin room
   * only). Coalesced like orders. A hint: the live map refetches over REST.
   */
  onRidersChanged?: () => void;
  /** Injected by tests. */
  connect?: (url: string, options: Parameters<typeof io>[1]) => Socket;
  coalesceMs?: number;
};

export class RealtimeClient {
  private status: RealtimeStatus = "connecting";
  private listeners = new Set<() => void>();
  private socket: Socket | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private scope: Record<string, unknown> = {};
  private readonly options: RealtimeOptions;
  private readonly change: ReturnType<typeof coalesce>;
  private readonly ridersChange: ReturnType<typeof coalesce>;
  private pendingIds: Set<string> | null = new Set();

  constructor(options: RealtimeOptions) {
    this.options = options;
    this.change = coalesce(() => {
      const ids = this.pendingIds;
      this.pendingIds = new Set();
      options.onChange(ids ? [...ids] : null);
    }, options.coalesceMs ?? 300);
    this.ridersChange = coalesce(
      () => options.onRidersChanged?.(),
      options.coalesceMs ?? 300,
    );
  }

  private changed(orderId: string | null): void {
    if (orderId === null) this.pendingIds = null;
    else this.pendingIds?.add(orderId);
    this.change.call();
  }

  getStatus = (): RealtimeStatus => this.status;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  start(): void {
    if (this.socket) return;
    const { url, path } = socketEndpoint(this.options.apiBaseUrl);
    const connect = this.options.connect ?? io;
    const socket = connect(url, {
      path,
      transports: ["websocket"],
      // Read at every (re)connect, so a reconnect after a wifi drop asks for
      // the branch on screen now, not the one selected when it first opened.
      auth: (callback: (data: object) => void) =>
        callback({ ...this.scope, ...this.options.auth() }),
      reconnectionDelay: 1000,
      reconnectionDelayMax: 30000,
      randomizationFactor: 0.5,
    });
    this.socket = socket;
    this.setStatus("connecting");

    socket.on("connect", () => {
      this.setStatus("live");
      // Anything pushed while disconnected is lost for good, so a (re)connect
      // always refetches rather than trusting the board it already has.
      this.changed(null);
    });
    socket.on("disconnect", (reason) => {
      if (this.status !== "disabled") this.setStatus("offline");
      // The server ended this socket on purpose: revoked, expired, or moved
      // out of scope. Socket.IO does not reconnect after that by itself; one
      // attempt settles it — a still-valid session reconnects, a dead one is
      // refused with `auth` and signs out below.
      if (reason === "io server disconnect") socket.connect();
    });
    socket.on("connect_error", (error: Error) => {
      if (socket.active) {
        // Network-level: Socket.IO is already backing off and retrying.
        this.setStatus("offline");
        return;
      }
      const action = refusalAction(error.message);
      if (action === "sign-out") {
        this.stop();
        this.options.onSignOut();
      } else if (action === "give-up") {
        this.setStatus("disabled");
      } else {
        this.setStatus("offline");
        this.retryTimer = setTimeout(() => socket.connect(), REFUSED_RETRY_MS);
      }
    });
    socket.on(
      "order:updated",
      (event: Partial<OrderUpdatedEvent> | undefined) =>
        this.changed(
          typeof event?.order_id === "string" ? event.order_id : null,
        ),
    );
    socket.on("fleet:riders_changed", () => this.ridersChange.call());
    socket.on("session:revoked", () => {
      this.stop();
      this.options.onSignOut();
    });
  }

  /**
   * Ask the server to move this socket to another restaurant or branch.
   *
   * Validated server-side by the same scope rule as `GET /orders`. On refusal
   * the socket is reconnected, which re-authenticates with the current scope
   * from `auth()` — the server's answer then stands either way.
   */
  resubscribe(scope: Record<string, unknown>): void {
    this.scope = scope;
    const socket = this.socket;
    if (!socket?.connected) return; // the next connect carries it via auth()
    socket.emit("subscribe", scope, (ack: { ok?: boolean } | undefined) => {
      if (!ack?.ok) socket.disconnect().connect();
    });
  }

  stop(): void {
    this.change.cancel();
    this.ridersChange.cancel();
    if (this.retryTimer !== null) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.removeAllListeners();
      socket.close();
    }
  }

  private setStatus(next: RealtimeStatus): void {
    if (next === this.status) return;
    this.status = next;
    for (const listener of this.listeners) listener();
  }
}

/**
 * The panel's "orders changed" bus.
 *
 * Pages register a callback rather than reading a version in an effect: a
 * callback runs like an event handler, so a page can bump its own reload
 * nonce from it without tripping `react-hooks/set-state-in-effect` — which
 * this panel enforces and its older pages already trip.
 *
 * The page cache is invalidated BEFORE listeners run, so the refetch a
 * listener triggers misses the cache instead of re-serving the stale snapshot.
 * Every order-bearing snapshot is keyed under one of these prefixes; a page
 * that is not mounted simply fetches fresh on its next visit.
 */
const ORDER_SNAPSHOT_PREFIXES = [
  "orders:",
  "order-detail:",
  "dashboard:",
  "restaurant-detail:",
  "location-detail:",
];

type OrdersListener = (orderIds: string[] | null) => void;
const ordersListeners = new Set<OrdersListener>();

export function onOrdersChanged(listener: OrdersListener): () => void {
  ordersListeners.add(listener);
  return () => {
    ordersListeners.delete(listener);
  };
}

type RidersListener = () => void;
const ridersListeners = new Set<RidersListener>();

/** The live map listens here; the panel's one socket announces. */
export function onRidersChanged(listener: RidersListener): () => void {
  ridersListeners.add(listener);
  return () => {
    ridersListeners.delete(listener);
  };
}

export function announceRidersChanged(): void {
  for (const listener of Array.from(ridersListeners)) listener();
}

export function announceOrdersChanged(orderIds: string[] | null): void {
  for (const prefix of ORDER_SNAPSHOT_PREFIXES) {
    invalidatePageSnapshotsByPrefix(prefix);
  }
  for (const listener of Array.from(ordersListeners)) {
    listener(orderIds);
  }
}
