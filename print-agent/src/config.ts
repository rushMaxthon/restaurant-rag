/**
 * Where this agent keeps what it was told.
 *
 * `%ProgramData%` rather than the user's profile, because the agent runs at
 * boot with no user signed in — a config under `%APPDATA%` would be invisible
 * to it. The same reason it is not beside the executable: Program Files is
 * not writable by a service account, and a config that cannot be written is a
 * pairing that cannot be saved.
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

export interface AgentConfig {
  /** Where this server is. No trailing slash. */
  serverUrl: string;
  /** Issued once, at pairing. The only credential this agent has. */
  agentToken: string;
  agentId: string;
  restaurantName?: string;
  branchName?: string;
  /**
   * The host header to send, for a deployment serving several tenants on one
   * address. Normally unset: in production each restaurant has its own
   * subdomain and the URL carries it.
   */
  storefrontHost?: string;
}

export function configDir(): string {
  const base =
    process.env["QUICKBITE_PRINT_HOME"] ??
    join(process.env["ProgramData"] ?? process.env["HOME"] ?? ".", "QuickBitePrint");
  return base;
}

export function configPath(): string {
  return join(configDir(), "config.json");
}

export function readConfig(): AgentConfig | null {
  try {
    return JSON.parse(readFileSync(configPath(), "utf8")) as AgentConfig;
  } catch {
    // Absent, unreadable, or corrupt. All three mean "not paired yet", which
    // the caller handles by asking for a code rather than crashing.
    return null;
  }
}

export function writeConfig(config: AgentConfig): void {
  mkdirSync(dirname(configPath()), { recursive: true });
  writeFileSync(configPath(), `${JSON.stringify(config, null, 2)}\n`, "utf8");
}
