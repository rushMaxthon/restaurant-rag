/**
 * The fifth realtime client, kept identical in behaviour to the other four.
 *
 * `CLAUDE.md`: one `realtime.ts` per app — kitchen, admin, customer, mobile —
 * "kept identical in behaviour". This is that, for the agent, and it holds
 * the same two rules:
 *
 * **A push is a hint, never data.** `order:updated` carries an order id and a
 * status and nothing else. This client does not read either: it calls
 * `pokeNow()` and the runner asks the server what it owes over REST. So the
 * socket cannot hand the agent a ticket the REST scope would not, and REST
 * stays the only source of truth.
 *
 * **Refusal reasons are a contract.** `auth` means stop; `realtime_disabled`
 * and `forbidden` mean stop retrying; anything else retries. Getting this
 * wrong is how a client hammers a server that will never let it in.
 *
 * And one rule specific to being an accelerator rather than a transport: a
 * socket that never connects costs nothing. Tickets still arrive on the
 * poll — fifteen seconds rather than one — so every failure here is logged
 * and otherwise ignored. `enable_realtime` defaults off in this platform, so
 * "never connects" is the expected state in most deployments.
 */

import { io, type Socket } from "socket.io-client";

import type { AgentConfig } from "./config";
import type { Logger } from "./runner";

export interface RealtimeHandle {
  close(): void;
}

/** The refusals that mean "stop trying", per the platform's contract. */
const TERMINAL = new Set(["auth", "realtime_disabled", "forbidden"]);

export function connectRealtime(
  config: AgentConfig,
  log: Logger,
  onChange: () => void,
): RealtimeHandle {
  // Mounted inside the API at `/api/socket.io`, so the path is derived from
  // the same base URL the REST calls use rather than configured separately —
  // one fewer thing to get wrong on an install.
  const base = config.serverUrl.replace(/\/+$/, "");
  const origin = base.replace(/\/api$/, "");
  const path = `${base.endsWith("/api") ? "/api" : ""}/socket.io`;

  let socket: Socket | null = null;
  try {
    socket = io(origin, {
      path,
      // WebSocket only, on both ends. Long-polling needs sticky sessions and
      // gunicorn has none between workers.
      transports: ["websocket"],
      auth: { token: config.agentToken, agent: true },
      reconnection: true,
      reconnectionDelay: 2_000,
      reconnectionDelayMax: 60_000,
      timeout: 10_000,
    });
  } catch (error) {
    log.warn(`Realtime unavailable, falling back to polling: ${(error as Error).message}`);
    return { close: () => undefined };
  }

  socket.on("connect", () => {
    log.info("Realtime connected; tickets will arrive within about a second.");
    // A reconnect means anything may have changed, because Redis pub/sub
    // keeps nothing for a disconnected client. So the first thing a fresh
    // connection does is ask.
    onChange();
  });

  socket.on("order:updated", () => onChange());

  socket.on("disconnect", (reason) => {
    log.warn(`Realtime disconnected (${reason}); polling continues.`);
  });

  socket.on("connect_error", (error: Error & { data?: { reason?: string } }) => {
    const reason = error.data?.reason ?? error.message;
    if (TERMINAL.has(reason)) {
      // Not a problem to report loudly: `enable_realtime` is off by default
      // on this platform, and polling is the documented fallback.
      log.info(`Realtime refused (${reason}); using the poll interval instead.`);
      socket?.close();
      return;
    }
    log.warn(`Realtime could not connect (${reason}); will retry.`);
  });

  return {
    close: () => {
      socket?.removeAllListeners();
      socket?.close();
    },
  };
}
